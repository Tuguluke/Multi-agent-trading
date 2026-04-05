"""Lambda: single agent step called by Step Functions state machine.

Event shape (from Step Functions task):
    {
        "agent": "market_data" | "technical" | "sentiment" | "risk" | "portfolio",
        "context": { ... accumulated pipeline context ... }
    }
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, "/var/task")

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

AGENT_MAP = {
    "market_data": "agents.market_data_agent.MarketDataAgent",
    "technical":   "agents.technical_analyst.TechnicalAnalystAgent",
    "sentiment":   "agents.sentiment_agent.SentimentAgent",
    "risk":        "agents.risk_manager.RiskManagerAgent",
    "portfolio":   "agents.portfolio_manager.PortfolioManagerAgent",
}


def handler(event, context):
    agent_key = event.get("agent")
    if agent_key not in AGENT_MAP:
        raise ValueError(f"Unknown agent: {agent_key}. Valid: {list(AGENT_MAP)}")

    pipeline_ctx = event.get("context", {})
    if isinstance(pipeline_ctx, str):
        pipeline_ctx = json.loads(pipeline_ctx)

    logger.info("AgentStep: running agent=%s", agent_key)

    from aws.dynamodb_client import DynamoDBClient
    from aws.cloudwatch_client import CloudWatchClient
    from llm.llm_router import LLMRouter

    db = DynamoDBClient()
    cw = CloudWatchClient()
    router = LLMRouter(dynamodb_client=db)

    # Dynamically import + instantiate the requested agent
    module_path, class_name = AGENT_MAP[agent_key].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    AgentClass = getattr(module, class_name)
    agent = AgentClass(llm_router=router, db_client=db, cw_client=cw)

    if "agent_signals" not in pipeline_ctx:
        pipeline_ctx["agent_signals"] = []

    signal = agent.timed_run(pipeline_ctx)
    if signal:
        pipeline_ctx["agent_signals"].append(signal.model_dump(mode="json"))

    logger.info("AgentStep complete: agent=%s direction=%s",
                agent_key, signal.direction.value if signal else "N/A")

    return {
        "agent": agent_key,
        "signal": signal.model_dump(mode="json") if signal else None,
        "context": pipeline_ctx,
    }
