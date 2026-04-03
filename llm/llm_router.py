"""LLM Router — routes to Groq or Ollama based on config, wraps with benchmarker."""

from __future__ import annotations

import logging
from functools import lru_cache

from config import get_config

logger = logging.getLogger(__name__)


class LLMRouter:
    """Single entry point for all LLM calls across the trading desk."""

    def __init__(self, dynamodb_client=None):
        cfg = get_config()
        self._provider = cfg.LLM_PROVIDER
        self._client = self._build_client()
        from llm.benchmarker import LLMBenchmarker
        self._benchmarker = LLMBenchmarker(dynamodb_client)
        logger.info("LLMRouter using provider=%s", self._provider)

    def _build_client(self):
        cfg = get_config()
        if cfg.LLM_PROVIDER == "ollama":
            from llm.ollama_client import OllamaClient
            return OllamaClient()
        from llm.groq_client import GroqClient
        return GroqClient()

    def complete(
        self,
        agent_name: str,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Complete a prompt and return text. Benchmarks the call automatically."""
        kwargs = {"temperature": temperature, "max_tokens": max_tokens}
        if model:
            kwargs["model"] = model
        text, _meta = self._benchmarker.timed_complete(
            self._client, agent_name, prompt, system_prompt, **kwargs
        )
        return text

    def complete_with_meta(
        self,
        agent_name: str,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> tuple[str, dict]:
        """Like complete() but also returns metadata dict."""
        kwargs = {"temperature": temperature, "max_tokens": max_tokens}
        if model:
            kwargs["model"] = model
        return self._benchmarker.timed_complete(
            self._client, agent_name, prompt, system_prompt, **kwargs
        )


@lru_cache(maxsize=1)
def get_router(dynamodb_client=None) -> LLMRouter:
    return LLMRouter(dynamodb_client)
