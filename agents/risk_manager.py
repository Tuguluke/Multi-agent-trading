"""Risk Manager Agent — portfolio exposure, drawdown limits, position sizing."""

from __future__ import annotations

import logging

from agents.base_agent import BaseAgent
from data.schemas import AgentSignal, SignalDirection, SignalStrength

logger = logging.getLogger(__name__)

# Risk parameters
MAX_SINGLE_POSITION_PCT = 20.0   # max % of portfolio in one asset
MAX_SECTOR_EXPOSURE_PCT = 60.0   # max % in energy sector total
MAX_DRAWDOWN_PCT = 15.0          # stop-loss threshold
VOLATILITY_THRESHOLD = 30.0      # high volatility flag (annualized %)


class RiskManagerAgent(BaseAgent):
    def __init__(self, llm_router, db_client=None, cw_client=None):
        super().__init__("RiskManager", llm_router, db_client, cw_client)
        from data.yfinance_client import YFinanceClient
        self._yf = YFinanceClient()

    def run(self, context: dict) -> AgentSignal:
        price_snapshot = context.get("price_snapshot", {})
        ta_indicators = context.get("ta_indicators", {})
        portfolio = context.get("portfolio", {})

        # Compute volatility for key assets
        volatility_data = self._compute_volatility(["XLE", "USO", "UNG"])
        context["volatility"] = volatility_data

        # Build risk summary
        vol_str = "\n".join(
            f"  {sym}: {vol:.1f}% annualized" for sym, vol in volatility_data.items()
        )
        portfolio_str = "\n".join(
            f"  {sym}: {pct:.1f}%" for sym, pct in portfolio.items()
        ) or "  (no open positions — paper trading)"

        # Check for any risk breaches
        risk_flags = []
        for sym, vol in volatility_data.items():
            if vol > VOLATILITY_THRESHOLD:
                risk_flags.append(f"HIGH VOLATILITY: {sym} at {vol:.1f}%")

        for sym, pct in portfolio.items():
            if pct > MAX_SINGLE_POSITION_PCT:
                risk_flags.append(f"OVERWEIGHT: {sym} at {pct:.1f}% (max {MAX_SINGLE_POSITION_PCT}%)")

        total_exposure = sum(portfolio.values())
        if total_exposure > MAX_SECTOR_EXPOSURE_PCT:
            risk_flags.append(f"SECTOR OVEREXPOSURE: {total_exposure:.1f}% in energy (max {MAX_SECTOR_EXPOSURE_PCT}%)")

        flags_str = "\n".join(f"  ⚠ {f}" for f in risk_flags) or "  ✓ No active risk flags"

        prompt = f"""Perform a risk assessment for the energy trading desk:

CURRENT PORTFOLIO:
{portfolio_str}

ASSET VOLATILITY (annualized):
{vol_str}

RISK FLAGS:
{flags_str}

RISK PARAMETERS:
  Max single position: {MAX_SINGLE_POSITION_PCT}%
  Max sector exposure: {MAX_SECTOR_EXPOSURE_PCT}%
  Max drawdown limit: {MAX_DRAWDOWN_PCT}%
  High volatility threshold: {VOLATILITY_THRESHOLD}%

Assess:
1. Overall risk posture (BULLISH=ok to increase exposure / BEARISH=reduce risk / NEUTRAL=maintain)
2. Risk signal strength (STRONG=urgent action / MODERATE=monitor / WEAK=no action needed)
3. Confidence in risk assessment (0-100%)
4. Recommended position sizing adjustments
5. Key risks to monitor

Format:
DIRECTION: [BULLISH/BEARISH/NEUTRAL — from risk perspective]
STRENGTH: [strength]
CONFIDENCE: [X]%
ASSET: XLE
REASONING: [risk assessment and recommendations]"""

        response = self.call_llm(prompt)

        # If there are active risk flags, lean towards BEARISH (risk-off)
        if len(risk_flags) >= 2:
            direction = SignalDirection.BEARISH
            strength = SignalStrength.STRONG
        elif len(risk_flags) == 1:
            direction = SignalDirection.BEARISH
            strength = SignalStrength.MODERATE
        else:
            direction = self._parse_direction(response)
            strength = self._parse_strength(response)

        confidence = self._parse_confidence(response)
        context["risk_flags"] = risk_flags
        context["risk_direction"] = direction.value

        signal = AgentSignal(
            agent_name=self.name,
            asset="XLE",
            direction=direction,
            strength=strength,
            confidence=confidence,
            reasoning=response,
            raw_data={"volatility": volatility_data, "risk_flags": risk_flags},
        )
        self.log_signal(signal)
        return signal

    def _compute_volatility(self, symbols: list[str]) -> dict[str, float]:
        """Annualized volatility (std of log returns × sqrt(252))."""
        import numpy as np
        vol_data = {}
        for sym in symbols:
            try:
                df = self._yf.get_ohlcv(sym, days=60)
                if df.empty or len(df) < 10:
                    continue
                log_returns = np.log(df["Close"] / df["Close"].shift(1)).dropna()
                annualized_vol = float(log_returns.std() * (252 ** 0.5) * 100)
                vol_data[sym] = round(annualized_vol, 2)
            except Exception as e:
                logger.warning("Volatility calc failed for %s: %s", sym, e)
        return vol_data
