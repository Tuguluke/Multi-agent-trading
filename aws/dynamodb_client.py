"""AWS DynamoDB client — agent state, trade signals, LLM benchmark logs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from config import get_config

logger = logging.getLogger(__name__)

cfg = get_config()


def _to_decimal(obj: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _from_decimal(obj: Any) -> Any:
    """Recursively convert Decimal back to float."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(v) for v in obj]
    return obj


class DynamoDBClient:
    def __init__(self):
        kwargs: dict = {"region_name": cfg.AWS_REGION}
        if cfg.AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = cfg.AWS_ENDPOINT_URL
        self._resource = boto3.resource("dynamodb", **kwargs)

    def _table(self, name: str):
        return self._resource.Table(name)

    # ── Generic CRUD ──────────────────────────────────────────────────────────

    def put_item(self, table_name: str, item: dict) -> None:
        self._table(table_name).put_item(Item=_to_decimal(item))
        logger.debug("DynamoDB put %s → %s", table_name, list(item.keys())[:3])

    def get_item(self, table_name: str, pk: str, pk_value: str, sk: str | None = None, sk_value: str | None = None) -> dict | None:
        key = {pk: pk_value}
        if sk and sk_value:
            key[sk] = sk_value
        response = self._table(table_name).get_item(Key=key)
        item = response.get("Item")
        return _from_decimal(item) if item else None

    def query(self, table_name: str, pk: str, pk_value: str, limit: int = 100) -> list[dict]:
        response = self._table(table_name).query(
            KeyConditionExpression=Key(pk).eq(pk_value),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_from_decimal(item) for item in response.get("Items", [])]

    def scan(self, table_name: str, limit: int = 100) -> list[dict]:
        response = self._table(table_name).scan(Limit=limit)
        return [_from_decimal(item) for item in response.get("Items", [])]

    # ── Domain helpers ────────────────────────────────────────────────────────

    def save_market_snapshot(self, snapshot: dict) -> None:
        snapshot.setdefault("date", datetime.now(timezone.utc).date().isoformat())
        self.put_item(cfg.dynamo_table("MarketSnapshots"), snapshot)

    def save_agent_signal(self, signal: dict) -> None:
        signal.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.put_item(cfg.dynamo_table("AgentSignals"), signal)

    def save_llm_benchmark(self, record: dict) -> None:
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.put_item(cfg.dynamo_table("LLMBenchmarks"), record)

    def save_portfolio_position(self, position: dict) -> None:
        position.setdefault("date", datetime.now(timezone.utc).date().isoformat())
        self.put_item(cfg.dynamo_table("Portfolio"), position)

    def get_latest_signals(self, limit: int = 20) -> list[dict]:
        return self.scan(cfg.dynamo_table("AgentSignals"), limit=limit)

    def get_llm_benchmarks(self, model_name: str, limit: int = 200) -> list[dict]:
        return self.query(cfg.dynamo_table("LLMBenchmarks"), "model_name", model_name, limit=limit)

    def get_all_llm_benchmarks(self, limit: int = 500) -> list[dict]:
        return self.scan(cfg.dynamo_table("LLMBenchmarks"), limit=limit)
