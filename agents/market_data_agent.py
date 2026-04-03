"""Market Data Agent — fetches and summarizes all energy price data."""

from __future__ import annotations

import logging

from agents.base_agent import BaseAgent
from data.schemas import AgentSignal, SignalDirection, SignalStrength

logger = logging.getLogger(__name__)


class MarketDataAgent(BaseAgent):
    def __init__(self, llm_router, db_client=None, cw_client=None):
        super().__init__("MarketDataAgent", llm_router, db_client, cw_client)
        from data.eia_client import EIAClient
        from data.yfinance_client import YFinanceClient
        from data.fred_client import FREDClient
        self._eia = EIAClient()
        self._yf = YFinanceClient()
        self._fred = FREDClient()

    def run(self, context: dict) -> AgentSignal:
        """Fetch latest energy prices and produce a market overview signal."""
        # Gather data
        price_snapshot = self._yf.get_snapshot()
        macro_snapshot = self._fred.get_macro_snapshot()
        inventory = {}
        try:
            inventory = self._eia.get_weekly_inventory()
        except Exception as e:
            logger.warning("EIA inventory fetch failed: %s", e)

        # Build context for LLM
        prices_str = "\n".join(f"  {k}: ${v:.2f}" for k, v in price_snapshot.items())
        macro_str = "\n".join(f"  {k}: {v:.2f}" for k, v in list(macro_snapshot.items())[:6])
        inv_str = (
            f"  Inventory: {inventory.get('inventory_mmbbl', 'N/A')} Mmbbl "
            f"(change: {inventory.get('change_mmbbl', 'N/A')} Mmbbl)"
            if inventory else "  Inventory data unavailable"
        )

        prompt = f"""Analyze the current energy market based on this data:

ENERGY EQUITY PRICES:
{prices_str}

MACRO INDICATORS:
{macro_str}

US CRUDE INVENTORY:
{inv_str}

Provide:
1. Overall market direction (BULLISH/BEARISH/NEUTRAL) for the energy sector
2. Signal strength (STRONG/MODERATE/WEAK)
3. Confidence level (0-100%)
4. Key observations (2-3 bullet points)
5. Primary asset to focus on (e.g. XLE, WTI, NATGAS)

Format your response as:
DIRECTION: [direction]
STRENGTH: [strength]
CONFIDENCE: [X]%
ASSET: [asset]
REASONING: [your analysis]"""

        response = self.call_llm(prompt)

        # Parse LLM response
        direction = self._parse_direction(response)
        strength = self._parse_strength(response)
        confidence = self._parse_confidence(response)
        asset = self._extract_asset(response, default="XLE")

        # Store snapshot in context for downstream agents
        context["price_snapshot"] = price_snapshot
        context["macro_snapshot"] = macro_snapshot
        context["inventory"] = inventory

        signal = AgentSignal(
            agent_name=self.name,
            asset=asset,
            direction=direction,
            strength=strength,
            confidence=confidence,
            reasoning=response,
            raw_data={"prices": price_snapshot, "macro": macro_snapshot},
        )
        self.log_signal(signal)
        return signal

    @staticmethod
    def _extract_asset(text: str, default: str = "XLE") -> str:
        assets = ["WTI", "BRENT", "NATGAS", "XLE", "USO", "UNG", "XOM", "CVX", "COP"]
        for line in text.split("\n"):
            if "ASSET:" in line.upper():
                for asset in assets:
                    if asset in line.upper():
                        return asset
        return default
