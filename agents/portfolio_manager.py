"""Portfolio Manager Agent — aggregates all signals into a final recommendation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agents.base_agent import BaseAgent
from data.schemas import (
    AgentSignal, SignalDirection, SignalStrength, TradingRecommendation
)

logger = logging.getLogger(__name__)

AGENT_WEIGHTS = {
    "MarketDataAgent":  0.20,
    "TechnicalAnalyst": 0.35,
    "SentimentAgent":   0.25,
    "RiskManager":      0.20,
}


class PortfolioManagerAgent(BaseAgent):
    def __init__(self, llm_router, db_client=None, cw_client=None):
        super().__init__("PortfolioManager", llm_router, db_client, cw_client)

    def run(self, context: dict) -> AgentSignal:
        signals: list[AgentSignal] = context.get("agent_signals", [])
        if not signals:
            logger.warning("[PortfolioManager] No upstream signals in context")

        # Weighted signal aggregation
        score = self._aggregate_score(signals)
        risk_flags = context.get("risk_flags", [])
        if risk_flags:
            score *= 0.5  # dampen in high-risk environment

        # Determine position size (Kelly-lite: scale with |score|)
        raw_position_pct = min(abs(score) * 10, 20.0)

        # Build LLM prompt with all signals
        signals_str = "\n".join(
            f"  {s.agent_name}: {s.direction.value} ({s.strength.value}) "
            f"confidence={s.confidence:.0%} asset={s.asset}"
            for s in signals
        )
        risk_str = "\n".join(f"  ⚠ {f}" for f in risk_flags) or "  ✓ None"

        prompt = f"""You are the Portfolio Manager for an energy trading desk.
Synthesize the following agent signals into a final trading recommendation.

AGENT SIGNALS:
{signals_str}

RISK FLAGS:
{risk_str}

AGGREGATED SIGNAL SCORE: {score:+.2f} (positive = bullish, negative = bearish)
SUGGESTED POSITION SIZE: {raw_position_pct:.1f}% of portfolio

Provide the final trading recommendation:
1. Final direction (BULLISH/BEARISH/NEUTRAL)
2. Signal strength (STRONG/MODERATE/WEAK)
3. Final confidence (0-100%)
4. Best asset to trade
5. Position size % (0-20%)
6. Entry rationale (2-3 sentences)
7. Risk management notes

Format:
DIRECTION: [direction]
STRENGTH: [strength]
CONFIDENCE: [X]%
ASSET: [asset]
POSITION_SIZE: [X]%
REASONING: [entry rationale and risk notes]"""

        response = self.call_llm(prompt, max_tokens=1500)

        direction = self._parse_direction(response)
        strength = self._parse_strength(response)
        confidence = self._parse_confidence(response)
        asset = self._extract_recommended_asset(signals, response)
        position_size = self._parse_position_size(response, default=raw_position_pct)

        # Build recommendation
        recommendation = TradingRecommendation(
            asset=asset,
            direction=direction,
            strength=strength,
            confidence=confidence,
            position_size_pct=position_size,
            entry_rationale=response,
            risk_notes=", ".join(risk_flags) if risk_flags else "No active risk flags",
            contributing_agents=[s.agent_name for s in signals],
        )
        context["recommendation"] = recommendation

        # Also save to DynamoDB
        if self._db:
            try:
                rec = recommendation.model_dump()
                rec["timestamp"] = recommendation.timestamp.isoformat()
                rec["date"] = recommendation.timestamp.date().isoformat()
                rec["agent_name"] = "PortfolioManager"
                self._db.save_agent_signal(rec)
            except Exception as e:
                logger.warning("Failed to save recommendation: %s", e)

        signal = AgentSignal(
            agent_name=self.name,
            asset=asset,
            direction=direction,
            strength=strength,
            confidence=confidence,
            reasoning=response,
            raw_data={"score": score, "position_size_pct": position_size},
        )
        self.log_signal(signal)
        return signal

    def _aggregate_score(self, signals: list[AgentSignal]) -> float:
        score = 0.0
        for sig in signals:
            weight = AGENT_WEIGHTS.get(sig.agent_name, 0.25)
            direction_val = (
                1.0 if sig.direction == SignalDirection.BULLISH else
                -1.0 if sig.direction == SignalDirection.BEARISH else 0.0
            )
            strength_mult = (
                1.0 if sig.strength == SignalStrength.STRONG else
                0.6 if sig.strength == SignalStrength.MODERATE else 0.3
            )
            score += weight * direction_val * strength_mult * sig.confidence
        return round(score, 4)

    @staticmethod
    def _extract_recommended_asset(signals: list[AgentSignal], llm_text: str) -> str:
        energy_assets = ["WTI", "BRENT", "NATGAS", "XLE", "USO", "UNG", "XOM", "CVX", "COP"]
        for line in llm_text.split("\n"):
            if "ASSET:" in line.upper():
                for asset in energy_assets:
                    if asset in line.upper():
                        return asset
        # Fall back to most common asset in signals
        if signals:
            from collections import Counter
            return Counter(s.asset for s in signals).most_common(1)[0][0]
        return "XLE"

    @staticmethod
    def _parse_position_size(text: str, default: float = 5.0) -> float:
        import re
        matches = re.findall(r"POSITION_SIZE[:\s]+(\d+(?:\.\d+)?)\s*%?", text, re.IGNORECASE)
        if matches:
            return min(float(matches[0]), 20.0)
        return round(default, 1)
