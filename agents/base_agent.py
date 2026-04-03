"""Abstract base class for all trading agents."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from data.schemas import AgentSignal, SignalDirection, SignalStrength

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(self, name: str, llm_router, db_client=None, cw_client=None):
        self.name = name
        self._llm = llm_router
        self._db = db_client
        self._cw = cw_client

    @abstractmethod
    def run(self, context: dict) -> AgentSignal:
        """Execute the agent's analysis and return a signal."""

    def call_llm(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Call the LLM through the router (auto-benchmarked)."""
        sys = system_prompt or (
            f"You are an expert energy market analyst specializing in {self.name}. "
            "Be concise, data-driven, and specific. Always state your confidence level."
        )
        return self._llm.complete(
            agent_name=self.name,
            prompt=prompt,
            system_prompt=sys,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def log_signal(self, signal: AgentSignal) -> None:
        record = signal.model_dump()
        record["timestamp"] = signal.timestamp.isoformat()
        record["date"] = signal.timestamp.date().isoformat()

        if self._db:
            try:
                self._db.save_agent_signal(record)
            except Exception as e:
                logger.warning("[%s] Failed to save signal to DynamoDB: %s", self.name, e)

        if self._cw:
            try:
                self._cw.signal_emitted(self.name, signal.direction.value)
            except Exception as e:
                logger.warning("[%s] Failed to emit CloudWatch metric: %s", self.name, e)

        logger.info(
            "[%s] Signal: %s %s (%s) confidence=%.2f",
            self.name, signal.direction.value, signal.asset,
            signal.strength.value, signal.confidence,
        )

    def timed_run(self, context: dict) -> AgentSignal:
        """Run the agent and record latency to CloudWatch."""
        t0 = time.perf_counter()
        signal = self.run(context)
        latency_ms = (time.perf_counter() - t0) * 1000
        if self._cw:
            try:
                self._cw.agent_latency(self.name, latency_ms)
            except Exception:
                pass
        return signal

    @staticmethod
    def _parse_direction(text: str) -> SignalDirection:
        t = text.upper()
        if "BULLISH" in t or "BUY" in t or "LONG" in t:
            return SignalDirection.BULLISH
        if "BEARISH" in t or "SELL" in t or "SHORT" in t:
            return SignalDirection.BEARISH
        return SignalDirection.NEUTRAL

    @staticmethod
    def _parse_strength(text: str) -> SignalStrength:
        t = text.upper()
        if "STRONG" in t or "HIGH" in t:
            return SignalStrength.STRONG
        if "MODERATE" in t or "MEDIUM" in t:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    @staticmethod
    def _parse_confidence(text: str) -> float:
        """Extract a confidence float 0-1 from LLM text."""
        import re
        matches = re.findall(r"confidence[:\s]+(\d+(?:\.\d+)?)\s*%?", text, re.IGNORECASE)
        if matches:
            val = float(matches[0])
            return min(val / 100 if val > 1 else val, 1.0)
        # fallback: look for any percentage
        pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%", text)
        if pcts:
            val = float(pcts[0])
            return min(val / 100, 1.0)
        return 0.5
