"""Centralised configuration — reads .env locally, SSM Parameter Store in AWS."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import boto3
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    # ── Environment ──────────────────────────────────────────────────────────
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "local")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCOUNT_ID: str = os.getenv("AWS_ACCOUNT_ID", "")
    AWS_ENDPOINT_URL: Optional[str] = os.getenv("AWS_ENDPOINT_URL")  # LocalStack

    # ── LLM ──────────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")   # groq | ollama | bedrock
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
    BEDROCK_MODEL: str = os.getenv("BEDROCK_MODEL", "meta.llama3-8b-instruct-v1:0")

    # Groq keys — comma-separated in .env; in AWS injected from SSM via Lambda env var
    _groq_api_keys: Optional[list[str]] = None

    # ── AWS Resource Names ────────────────────────────────────────────────────
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "")
    DYNAMODB_PREFIX: str = os.getenv("DYNAMODB_PREFIX", "dev")
    SQS_INGESTION_URL: str = os.getenv("SQS_INGESTION_URL", "")
    SQS_AGENT_TRIGGER_URL: str = os.getenv("SQS_AGENT_TRIGGER_URL", "")
    SNS_SIGNALS_ARN: str = os.getenv("SNS_SIGNALS_ARN", "")

    # DynamoDB table names (derived from prefix)
    @classmethod
    def dynamo_table(cls, name: str) -> str:
        return f"{cls.DYNAMODB_PREFIX}-{name}"

    DYNAMO_MARKET_SNAPSHOTS = property(lambda self: self.dynamo_table("MarketSnapshots"))
    DYNAMO_AGENT_SIGNALS = property(lambda self: self.dynamo_table("AgentSignals"))
    DYNAMO_LLM_BENCHMARKS = property(lambda self: self.dynamo_table("LLMBenchmarks"))
    DYNAMO_PORTFOLIO = property(lambda self: self.dynamo_table("Portfolio"))

    # ── Data Sources ──────────────────────────────────────────────────────────
    EIA_API_KEY: str = os.getenv("EIA_API_KEY", "")
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
    ENTSO_TOKEN: str = os.getenv("ENTSO_TOKEN", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "EnergyTradingBot/1.0")

    # ── Groq Key Management ───────────────────────────────────────────────────
    def get_groq_keys(self) -> list[str]:
        """Return Groq API keys.
        Local: reads GROQ_API_KEYS env var (comma-separated).
        AWS Lambda: keys are injected as env var from SSM at deploy time (free tier).
        """
        if self._groq_api_keys:
            return self._groq_api_keys

        # Env var works in both local and Lambda (CDK injects SSM value as env var)
        env_keys = os.getenv("GROQ_API_KEYS", "")
        if env_keys:
            self._groq_api_keys = [k.strip() for k in env_keys.split(",") if k.strip()]
            return self._groq_api_keys

        # Fallback: read from SSM directly (avoids Secrets Manager cost)
        if self.ENVIRONMENT != "local":
            try:
                client = self._boto_client("ssm")
                response = client.get_parameter(
                    Name="/energy-trading/groq-api-keys",
                    WithDecryption=True,
                )
                raw = response["Parameter"]["Value"]
                self._groq_api_keys = [k.strip() for k in raw.split(",") if k.strip()]
                return self._groq_api_keys
            except Exception as e:
                logger.warning("Could not fetch Groq keys from SSM: %s", e)

        return []

    def _boto_client(self, service: str):
        kwargs: dict = {"region_name": self.AWS_REGION}
        if self.AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = self.AWS_ENDPOINT_URL
        return boto3.client(service, **kwargs)

    def _boto_resource(self, service: str):
        kwargs: dict = {"region_name": self.AWS_REGION}
        if self.AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = self.AWS_ENDPOINT_URL
        return boto3.resource(service, **kwargs)


@lru_cache(maxsize=1)
def get_config() -> Config:
    cfg = Config()
    logging.basicConfig(level=getattr(logging, cfg.LOG_LEVEL, logging.INFO))
    return cfg
