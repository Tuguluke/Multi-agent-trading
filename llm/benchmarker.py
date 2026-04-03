"""LLM call benchmarker — records every call to DynamoDB for cross-model comparison."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)

# Groq pricing (USD per 1M tokens) — update as pricing changes
GROQ_PRICING: dict[str, dict[str, float]] = {
    "llama3-70b-8192":       {"input": 0.59,  "output": 0.79},
    "llama3-8b-8192":        {"input": 0.05,  "output": 0.08},
    "mixtral-8x7b-32768":    {"input": 0.24,  "output": 0.24},
    "gemma2-9b-it":          {"input": 0.20,  "output": 0.20},
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = GROQ_PRICING.get(model, {"input": 0.0, "output": 0.0})
    return round(
        (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000,
        8,
    )


class LLMBenchmarker:
    """Wraps any LLM client's complete() call and logs timing + cost to DynamoDB."""

    def __init__(self, dynamodb_client=None):
        self._db = dynamodb_client

    def record(
        self,
        agent_name: str,
        meta: dict,
        ttft_ms: float | None = None,
    ) -> None:
        """Persist a benchmark record from an LLM call metadata dict."""
        model = meta.get("model", "unknown")
        provider = meta.get("provider", "unknown")
        record = {
            "model_name": f"{provider}/{model}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call_id": str(uuid.uuid4()),
            "agent_name": agent_name,
            "provider": provider,
            "model": model,
            "prompt_tokens": meta.get("prompt_tokens", 0),
            "completion_tokens": meta.get("completion_tokens", 0),
            "total_tokens": meta.get("total_tokens", 0),
            "total_ms": meta.get("total_ms", 0),
            "ttft_ms": ttft_ms,
            "tokens_per_sec": meta.get("tokens_per_sec", 0),
            "cost_usd": _estimate_cost(
                model,
                meta.get("prompt_tokens", 0),
                meta.get("completion_tokens", 0),
            ),
            "key_index": meta.get("key_index", -1),
        }
        logger.debug(
            "LLM [%s/%s] agent=%s tokens=%d total_ms=%.0f cost=$%.6f",
            provider, model, agent_name,
            record["total_tokens"], record["total_ms"], record["cost_usd"],
        )
        if self._db:
            try:
                self._db.save_llm_benchmark(record)
            except Exception as e:
                logger.warning("Failed to save benchmark: %s", e)

    def timed_complete(
        self,
        client,
        agent_name: str,
        prompt: str,
        system_prompt: str,
        **kwargs,
    ) -> tuple[str, dict]:
        """
        Wraps client.complete(), measures TTFT (approx), saves benchmark.
        Returns (text, meta).
        """
        t0 = time.perf_counter()
        text, meta = client.complete(prompt, system_prompt, **kwargs)
        # TTFT approximation: first token assumed at total_ms for non-streaming
        ttft_ms = meta.get("total_ms")
        self.record(agent_name, meta, ttft_ms=ttft_ms)
        return text, meta
