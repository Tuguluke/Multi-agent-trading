"""AWS CloudWatch client — emit custom metrics and structured logs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import get_config

logger = logging.getLogger(__name__)

NAMESPACE = "EnergyTradingDesk"


class CloudWatchClient:
    def __init__(self):
        cfg = get_config()
        self._cw = cfg._boto_client("cloudwatch")
        self._logs = cfg._boto_client("logs")
        self._env = cfg.ENVIRONMENT

    def put_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "None",
        dimensions: dict | None = None,
    ) -> None:
        dim_list = [{"Name": "Environment", "Value": self._env}]
        if dimensions:
            dim_list += [{"Name": k, "Value": str(v)} for k, v in dimensions.items()]
        try:
            self._cw.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=[{
                    "MetricName": metric_name,
                    "Value": value,
                    "Unit": unit,
                    "Timestamp": datetime.now(timezone.utc),
                    "Dimensions": dim_list,
                }],
            )
        except Exception as e:
            logger.warning("CloudWatch metric failed (%s): %s", metric_name, e)

    # ── Convenience emitters ──────────────────────────────────────────────────

    def agent_latency(self, agent_name: str, latency_ms: float) -> None:
        self.put_metric("AgentLatencyMs", latency_ms, "Milliseconds", {"Agent": agent_name})

    def llm_call_latency(self, model: str, latency_ms: float) -> None:
        self.put_metric("LLMCallLatencyMs", latency_ms, "Milliseconds", {"Model": model})

    def groq_key_throttle(self, key_index: int) -> None:
        self.put_metric("GroqKeyThrottles", 1, "Count", {"KeyIndex": str(key_index)})

    def signal_emitted(self, agent: str, direction: str) -> None:
        self.put_metric("SignalsEmitted", 1, "Count", {"Agent": agent, "Direction": direction})

    def ingestion_failure(self, source: str) -> None:
        self.put_metric("IngestionFailures", 1, "Count", {"Source": source})
