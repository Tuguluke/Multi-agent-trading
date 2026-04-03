"""Analysis pipeline — runs technical + sentiment agents after ingestion."""

from __future__ import annotations

import logging

from data.schemas import AgentSignal

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(self, llm_router, db_client=None, cw_client=None):
        from agents.technical_analyst import TechnicalAnalystAgent
        from agents.sentiment_agent import SentimentAgent
        self._agents = [
            TechnicalAnalystAgent(llm_router, db_client, cw_client),
            SentimentAgent(llm_router, db_client, cw_client),
        ]

    def run(self, context: dict) -> list[AgentSignal]:
        signals = []
        for agent in self._agents:
            try:
                signal = agent.timed_run(context)
                signals.append(signal)
            except Exception as e:
                logger.error("Analysis agent %s failed: %s", agent.name, e, exc_info=True)
        return signals
