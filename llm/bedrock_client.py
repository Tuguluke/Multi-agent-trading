"""Amazon Bedrock LLM client — AWS-native inference for comparison with Groq."""

from __future__ import annotations

import json
import logging
import time

import boto3

from config import get_config

logger = logging.getLogger(__name__)

# Models available on Bedrock that are good for energy market analysis
BEDROCK_MODELS = {
    "amazon.titan-text-express-v1": "Titan Text Express",
    "amazon.titan-text-lite-v1":    "Titan Text Lite",
    "anthropic.claude-instant-v1":  "Claude Instant",
    "anthropic.claude-v2":          "Claude v2",
    "meta.llama3-8b-instruct-v1:0": "Llama 3 8B",
    "meta.llama3-70b-instruct-v1:0":"Llama 3 70B",
    "mistral.mistral-7b-instruct-v0:2": "Mistral 7B",
}

# Approximate cost per 1K tokens (input / output) in USD
BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    "amazon.titan-text-express-v1":      (0.0002, 0.0006),
    "amazon.titan-text-lite-v1":         (0.00015, 0.0002),
    "anthropic.claude-instant-v1":       (0.0008, 0.0024),
    "anthropic.claude-v2":               (0.008,  0.024),
    "meta.llama3-8b-instruct-v1:0":      (0.0003, 0.0006),
    "meta.llama3-70b-instruct-v1:0":     (0.00265, 0.0035),
    "mistral.mistral-7b-instruct-v0:2":  (0.00015, 0.0002),
}


class BedrockClient:
    """
    Bedrock inference client — same interface as GroqClient/OllamaClient
    so LLMRouter can use it as a drop-in.
    """

    def __init__(self, model: str | None = None):
        cfg = get_config()
        self._model = model or cfg.BEDROCK_MODEL
        self._region = cfg.AWS_REGION
        self._client = boto3.client("bedrock-runtime", region_name=self._region)
        logger.info("BedrockClient ready: model=%s region=%s", self._model, self._region)

    def complete(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful energy market analyst.",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> tuple[str, dict]:
        """Returns (response_text, metadata) — same contract as GroqClient."""
        model = model or self._model
        t0 = time.perf_counter()

        body = self._build_body(model, system_prompt, prompt, temperature, max_tokens)

        response = self._client.invoke_model(
            modelId=model,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )

        total_ms = (time.perf_counter() - t0) * 1000
        result = json.loads(response["body"].read())
        text = self._extract_text(model, result)

        # Estimate token counts (Bedrock doesn't always return usage)
        usage = result.get("usage", {})
        prompt_tokens = usage.get("input_tokens", len(prompt.split()) * 4 // 3)
        completion_tokens = usage.get("output_tokens", len(text.split()) * 4 // 3)

        in_price, out_price = BEDROCK_PRICING.get(model, (0.001, 0.002))
        cost_usd = (prompt_tokens / 1000 * in_price) + (completion_tokens / 1000 * out_price)

        meta = {
            "model": model,
            "provider": "bedrock",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "total_ms": round(total_ms, 2),
            "tokens_per_sec": round(completion_tokens / (total_ms / 1000) if total_ms > 0 else 0, 2),
            "cost_usd": round(cost_usd, 6),
        }
        return text, meta

    def _build_body(
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Build request body in the format each model family expects."""
        full_prompt = f"{system_prompt}\n\n{prompt}"

        if model.startswith("anthropic.claude"):
            return {
                "prompt": f"\n\nHuman: {full_prompt}\n\nAssistant:",
                "max_tokens_to_sample": max_tokens,
                "temperature": temperature,
                "stop_sequences": ["\n\nHuman:"],
            }
        if model.startswith("amazon.titan"):
            return {
                "inputText": full_prompt,
                "textGenerationConfig": {
                    "maxTokenCount": max_tokens,
                    "temperature": temperature,
                },
            }
        if model.startswith("meta.llama"):
            return {
                "prompt": f"<|system|>\n{system_prompt}\n<|user|>\n{prompt}\n<|assistant|>",
                "max_gen_len": max_tokens,
                "temperature": temperature,
            }
        if model.startswith("mistral"):
            return {
                "prompt": f"<s>[INST] {system_prompt}\n\n{prompt} [/INST]",
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        # Generic fallback
        return {
            "inputText": full_prompt,
            "textGenerationConfig": {"maxTokenCount": max_tokens, "temperature": temperature},
        }

    def _extract_text(self, model: str, result: dict) -> str:
        """Extract generated text from model-specific response format."""
        if model.startswith("anthropic.claude"):
            return result.get("completion", "").strip()
        if model.startswith("amazon.titan"):
            outputs = result.get("results", [{}])
            return outputs[0].get("outputText", "").strip() if outputs else ""
        if model.startswith("meta.llama"):
            return result.get("generation", "").strip()
        if model.startswith("mistral"):
            outputs = result.get("outputs", [{}])
            return outputs[0].get("text", "").strip() if outputs else ""
        return str(result)
