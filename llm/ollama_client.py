"""Ollama LLM client — same interface as GroqClient for drop-in v2 swap."""

from __future__ import annotations

import logging
import time
from typing import Iterator

import requests

from config import get_config

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama client using the /api/chat endpoint."""

    def __init__(self):
        cfg = get_config()
        self._base_url = cfg.OLLAMA_BASE_URL.rstrip("/")
        self._model = cfg.OLLAMA_MODEL
        logger.info("OllamaClient ready: %s, model=%s", self._base_url, self._model)

    def complete(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> tuple[str, dict]:
        model = model or self._model
        t0 = time.perf_counter()
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        response = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        total_ms = (time.perf_counter() - t0) * 1000

        text = data["message"]["content"]
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        eval_duration_s = data.get("eval_duration", 0) / 1e9  # nanoseconds → seconds

        meta = {
            "key_index": -1,
            "model": model,
            "provider": "ollama",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "total_ms": round(total_ms, 2),
            "tokens_per_sec": round(completion_tokens / eval_duration_s if eval_duration_s > 0 else 0, 2),
        }
        return text, meta

    def stream(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        model = model or self._model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": True,
        }
        with requests.post(f"{self._base_url}/api/chat", json=payload, stream=True, timeout=120) as r:
            r.raise_for_status()
            import json
            for line in r.iter_lines():
                if line:
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
