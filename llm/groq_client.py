"""Groq LLM client with round-robin key rotation and automatic retry on 429."""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

from groq import Groq, RateLimitError

from config import get_config

logger = logging.getLogger(__name__)


class GroqClient:
    """Thread-safe Groq client that rotates across multiple API keys."""

    def __init__(self):
        cfg = get_config()
        self._keys = cfg.get_groq_keys()
        self._model = cfg.GROQ_MODEL
        self._lock = threading.Lock()
        self._counter = 0
        if not self._keys:
            raise ValueError("No Groq API keys configured. Set GROQ_API_KEYS in .env")
        logger.info("GroqClient ready with %d key(s), model=%s", len(self._keys), self._model)

    def _next_key(self) -> tuple[int, str]:
        with self._lock:
            idx = self._counter % len(self._keys)
            self._counter += 1
        return idx, self._keys[idx]

    def _client_for(self, key: str) -> Groq:
        return Groq(api_key=key)

    def complete(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> tuple[str, dict]:
        """
        Returns (response_text, metadata).
        metadata includes: key_index, model, prompt_tokens, completion_tokens, ttft_ms, total_ms.
        """
        model = model or self._model
        max_retries = len(self._keys)

        for attempt in range(max_retries):
            idx, key = self._next_key()
            client = self._client_for(key)
            t0 = time.perf_counter()
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                total_ms = (time.perf_counter() - t0) * 1000
                text = response.choices[0].message.content or ""
                usage = response.usage
                meta = {
                    "key_index": idx,
                    "model": model,
                    "provider": "groq",
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                    "total_ms": round(total_ms, 2),
                    "tokens_per_sec": round((usage.completion_tokens / (total_ms / 1000)) if usage and total_ms > 0 else 0, 2),
                }
                return text, meta

            except RateLimitError:
                logger.warning("Key %d rate-limited on attempt %d/%d", idx, attempt + 1, max_retries)
                from aws.cloudwatch_client import CloudWatchClient
                try:
                    CloudWatchClient().groq_key_throttle(idx)
                except Exception:
                    pass
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.5)

        raise RuntimeError("All Groq keys exhausted")

    def stream(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        """Streaming completion — yields text chunks."""
        model = model or self._model
        idx, key = self._next_key()
        client = self._client_for(key)
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
