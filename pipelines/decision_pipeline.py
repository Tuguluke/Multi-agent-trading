"""Decision pipeline — risk assessment + portfolio manager final call."""

from __future__ import annotations

import logging

from data.schemas import TradingRecommendation

logger = logging.getLogger(__name__)


class DecisionPipeline:
    def __init__(self, llm_router, db_client=None, cw_client=None, sns_client=None):
        from agents.risk_manager import RiskManagerAgent
        from agents.portfolio_manager import PortfolioManagerAgent
        self._risk = RiskManagerAgent(llm_router, db_client, cw_client)
        self._pm = PortfolioManagerAgent(llm_router, db_client, cw_client)
        self._sns = sns_client
        self._cfg = None
        try:
            from config import get_config
            self._cfg = get_config()
        except Exception:
            pass

    def run(self, context: dict) -> TradingRecommendation | None:
        # Risk assessment
        try:
            risk_signal = self._risk.timed_run(context)
            context["agent_signals"].append(risk_signal)
        except Exception as e:
            logger.error("RiskManager failed: %s", e, exc_info=True)

        # Portfolio manager final call
        recommendation = None
        try:
            self._pm.timed_run(context)
            recommendation = context.get("recommendation")
        except Exception as e:
            logger.error("PortfolioManager failed: %s", e, exc_info=True)

        # SNS notification for strong signals
        if recommendation and self._sns and self._cfg:
            from data.schemas import SignalStrength
            if recommendation.strength == SignalStrength.STRONG:
                self._notify(recommendation)

        return recommendation

    def _notify(self, rec: TradingRecommendation) -> None:
        if not self._cfg or not self._cfg.SNS_SIGNALS_ARN:
            return
        try:
            import boto3, json
            sns = boto3.client("sns", region_name=self._cfg.AWS_REGION)
            sns.publish(
                TopicArn=self._cfg.SNS_SIGNALS_ARN,
                Subject=f"STRONG {rec.direction.value} signal: {rec.asset}",
                Message=json.dumps(rec.model_dump(mode="json"), indent=2),
            )
            logger.info("SNS notification sent for %s %s", rec.direction.value, rec.asset)
        except Exception as e:
            logger.warning("SNS publish failed: %s", e)
