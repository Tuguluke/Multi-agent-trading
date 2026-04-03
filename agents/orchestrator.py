"""Orchestrator — runs all agents in sequence and manages the shared context."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from data.schemas import AgentSignal, TradingRecommendation

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, llm_router, db_client=None, cw_client=None, s3_client=None):
        self._db = db_client
        self._cw = cw_client
        self._s3 = s3_client

        from agents.market_data_agent import MarketDataAgent
        from agents.technical_analyst import TechnicalAnalystAgent
        from agents.sentiment_agent import SentimentAgent
        from agents.risk_manager import RiskManagerAgent
        from agents.portfolio_manager import PortfolioManagerAgent

        kwargs = {"llm_router": llm_router, "db_client": db_client, "cw_client": cw_client}
        self._agents = [
            MarketDataAgent(**kwargs),
            TechnicalAnalystAgent(**kwargs),
            SentimentAgent(**kwargs),
            RiskManagerAgent(**kwargs),
        ]
        self._portfolio_manager = PortfolioManagerAgent(**kwargs)

    def run(self, context: dict | None = None) -> TradingRecommendation | None:
        """
        Execute the full pipeline:
        1. Run all specialist agents
        2. Aggregate signals in PortfolioManager
        3. Return final TradingRecommendation
        """
        ctx = context or {}
        ctx["run_timestamp"] = datetime.now(timezone.utc).isoformat()
        ctx["agent_signals"] = []

        logger.info("=== Orchestrator starting pipeline ===")

        # Run specialist agents
        for agent in self._agents:
            try:
                logger.info("Running %s...", agent.name)
                signal = agent.timed_run(ctx)
                ctx["agent_signals"].append(signal)
            except Exception as e:
                logger.error("Agent %s failed: %s", agent.name, e, exc_info=True)

        if not ctx["agent_signals"]:
            logger.error("All agents failed — aborting pipeline")
            return None

        # Portfolio manager synthesizes everything
        logger.info("Running PortfolioManager...")
        try:
            self._portfolio_manager.timed_run(ctx)
        except Exception as e:
            logger.error("PortfolioManager failed: %s", e, exc_info=True)

        recommendation: TradingRecommendation | None = ctx.get("recommendation")

        # Persist run summary to S3
        if self._s3 and recommendation:
            try:
                from aws.s3_client import S3Client
                key = S3Client.signal_key("orchestrator")
                self._s3.upload_json(key, {
                    "run_timestamp": ctx["run_timestamp"],
                    "signals": [s.model_dump(mode="json") for s in ctx["agent_signals"]],
                    "recommendation": recommendation.model_dump(mode="json"),
                })
            except Exception as e:
                logger.warning("Failed to upload run summary to S3: %s", e)

        logger.info(
            "=== Pipeline complete: %s %s confidence=%.0f%% ===",
            recommendation.direction.value if recommendation else "N/A",
            recommendation.asset if recommendation else "",
            (recommendation.confidence * 100) if recommendation else 0,
        )
        return recommendation
