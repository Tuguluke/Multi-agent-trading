"""Technical Analyst Agent — RSI, MACD, Bollinger Bands on energy prices."""

from __future__ import annotations

import logging

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands

from agents.base_agent import BaseAgent
from data.schemas import AgentSignal, SignalDirection, SignalStrength

logger = logging.getLogger(__name__)


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute TA indicators on a price DataFrame (must have 'Close' column)."""
    close = df["Close"].dropna()
    if len(close) < 26:
        return {"error": "insufficient data"}

    rsi = RSIIndicator(close=close, window=14)
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    bb = BollingerBands(close=close, window=20, window_dev=2)

    latest_close = float(close.iloc[-1])
    latest_rsi = float(rsi.rsi().iloc[-1])
    macd_line = float(macd.macd().iloc[-1])
    macd_signal = float(macd.macd_signal().iloc[-1])
    macd_hist = float(macd.macd_diff().iloc[-1])
    bb_high = float(bb.bollinger_hband().iloc[-1])
    bb_low = float(bb.bollinger_lband().iloc[-1])
    bb_mid = float(bb.bollinger_mavg().iloc[-1])

    # Simple TA scoring
    score = 0
    signals = []
    if latest_rsi < 30:
        score += 2
        signals.append(f"RSI oversold ({latest_rsi:.1f})")
    elif latest_rsi > 70:
        score -= 2
        signals.append(f"RSI overbought ({latest_rsi:.1f})")
    else:
        signals.append(f"RSI neutral ({latest_rsi:.1f})")

    if macd_hist > 0 and macd_line > macd_signal:
        score += 1
        signals.append("MACD bullish crossover")
    elif macd_hist < 0:
        score -= 1
        signals.append("MACD bearish")

    if latest_close < bb_low:
        score += 1
        signals.append("Price below lower Bollinger Band (oversold)")
    elif latest_close > bb_high:
        score -= 1
        signals.append("Price above upper Bollinger Band (overbought)")

    return {
        "close": round(latest_close, 2),
        "rsi": round(latest_rsi, 2),
        "macd": round(macd_line, 4),
        "macd_signal": round(macd_signal, 4),
        "macd_hist": round(macd_hist, 4),
        "bb_high": round(bb_high, 2),
        "bb_mid": round(bb_mid, 2),
        "bb_low": round(bb_low, 2),
        "ta_score": score,
        "ta_signals": signals,
    }


class TechnicalAnalystAgent(BaseAgent):
    PRIMARY_ASSETS = ["XLE", "XOM", "CVX", "USO", "UNG"]

    def __init__(self, llm_router, db_client=None, cw_client=None):
        super().__init__("TechnicalAnalyst", llm_router, db_client, cw_client)
        from data.yfinance_client import YFinanceClient
        self._yf = YFinanceClient()

    def run(self, context: dict) -> AgentSignal:
        ta_results = {}
        for symbol in self.PRIMARY_ASSETS:
            df = self._yf.get_ohlcv(symbol, days=90)
            if not df.empty:
                ta_results[symbol] = compute_indicators(df)

        context["ta_indicators"] = ta_results

        # Summarise for LLM
        ta_summary = []
        for sym, ind in ta_results.items():
            if "error" not in ind:
                ta_summary.append(
                    f"{sym}: close=${ind['close']}, RSI={ind['rsi']}, "
                    f"MACD_hist={ind['macd_hist']:.4f}, BB=[{ind['bb_low']}-{ind['bb_high']}] | "
                    f"Signals: {', '.join(ind['ta_signals'])}"
                )

        prompt = f"""Analyze the following technical indicators for key energy assets:

{chr(10).join(ta_summary)}

Provide a unified technical analysis:
1. Overall TA direction for energy sector (BULLISH/BEARISH/NEUTRAL)
2. Signal strength (STRONG/MODERATE/WEAK)
3. Confidence (0-100%)
4. Best technical setup among these assets
5. Key risk levels to watch

Format:
DIRECTION: [direction]
STRENGTH: [strength]
CONFIDENCE: [X]%
ASSET: [best setup asset]
REASONING: [your technical analysis]"""

        response = self.call_llm(prompt)

        # Aggregate TA score to aid parsing
        total_score = sum(r.get("ta_score", 0) for r in ta_results.values() if "error" not in r)
        direction = SignalDirection.BULLISH if total_score > 1 else (
            SignalDirection.BEARISH if total_score < -1 else SignalDirection.NEUTRAL
        )
        direction = self._parse_direction(response) or direction
        strength = self._parse_strength(response)
        confidence = self._parse_confidence(response)

        # Best-scoring asset
        best_asset = max(
            ((s, r.get("ta_score", 0)) for s, r in ta_results.items() if "error" not in r),
            key=lambda x: abs(x[1]),
            default=("XLE", 0),
        )[0]

        signal = AgentSignal(
            agent_name=self.name,
            asset=best_asset,
            direction=direction,
            strength=strength,
            confidence=confidence,
            reasoning=response,
            raw_data=ta_results,
        )
        self.log_signal(signal)
        return signal
