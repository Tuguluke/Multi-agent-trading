"""CDK Stack: CloudWatch dashboards and alarms."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
)
from constructs import Construct

NAMESPACE = "EnergyTradingDesk"


class MonitoringStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # Alarm notification topic
        alarm_topic = sns.Topic(self, "AlarmTopic", topic_name="energy-trading-alarms")

        def _alarm(metric_name: str, threshold: float, comparison, period_min: int = 5, **dims):
            metric = cw.Metric(
                namespace=NAMESPACE,
                metric_name=metric_name,
                dimensions_map=dims or {},
                period=cdk.Duration.minutes(period_min),
                statistic="Sum",
            )
            alarm = cw.Alarm(
                self, f"Alarm_{metric_name.replace(' ', '_')}",
                alarm_name=f"energy-trading-{metric_name.lower().replace(' ', '-')}",
                metric=metric,
                threshold=threshold,
                evaluation_periods=2,
                comparison_operator=comparison,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
            return alarm

        # Alarms
        _alarm(
            "IngestionFailures", 3,
            cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
        _alarm(
            "GroqKeyThrottles", 10,
            cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
        _alarm(
            "AgentLatencyMs", 30_000,
            cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            statistic="p95",
        )

        # CloudWatch Dashboard
        dashboard = cw.Dashboard(
            self, "TradingDashboard",
            dashboard_name="EnergyTradingDesk",
        )

        def _metric(name: str, stat: str = "Sum", **dims) -> cw.Metric:
            return cw.Metric(
                namespace=NAMESPACE,
                metric_name=name,
                dimensions_map=dims or {},
                period=cdk.Duration.minutes(15),
                statistic=stat,
            )

        # X-Ray service map link (text widget)
        xray_url = (
            f"https://{self.region}.console.aws.amazon.com/xray/home#/service-map"
        )
        sfn_url = (
            f"https://{self.region}.console.aws.amazon.com/states/home"
            f"#/statemachines"
        )

        dashboard.add_widgets(
            cw.GraphWidget(
                title="Agent Latency (p50 / p95)",
                left=[
                    _metric("AgentLatencyMs", "p50"),
                    _metric("AgentLatencyMs", "p95"),
                ],
                width=12,
            ),
            cw.GraphWidget(
                title="Signals Emitted by Direction",
                left=[
                    _metric("SignalsEmitted", "Sum", Direction="BULLISH"),
                    _metric("SignalsEmitted", "Sum", Direction="BEARISH"),
                    _metric("SignalsEmitted", "Sum", Direction="NEUTRAL"),
                ],
                width=12,
            ),
            cw.GraphWidget(
                title="LLM Call Latency by Provider",
                left=[
                    _metric("LLMCallLatencyMs", "p50"),
                    _metric("LLMCallLatencyMs", "p95"),
                ],
                width=12,
            ),
            cw.GraphWidget(
                title="Groq Key Throttles & Ingestion Failures",
                left=[
                    _metric("GroqKeyThrottles", "Sum"),
                    _metric("IngestionFailures", "Sum"),
                ],
                width=12,
            ),
            # Step Functions execution metrics (built-in namespace)
            cw.GraphWidget(
                title="Step Functions: Executions",
                left=[
                    cw.Metric(
                        namespace="AWS/States",
                        metric_name="ExecutionsStarted",
                        dimensions_map={"StateMachineArn": "*"},
                        period=cdk.Duration.minutes(15),
                        statistic="Sum",
                    ),
                    cw.Metric(
                        namespace="AWS/States",
                        metric_name="ExecutionsFailed",
                        dimensions_map={"StateMachineArn": "*"},
                        period=cdk.Duration.minutes(15),
                        statistic="Sum",
                    ),
                ],
                width=12,
            ),
            # Lambda concurrency + errors
            cw.GraphWidget(
                title="Lambda Errors",
                left=[
                    cw.Metric(
                        namespace="AWS/Lambda",
                        metric_name="Errors",
                        period=cdk.Duration.minutes(15),
                        statistic="Sum",
                    ),
                ],
                width=12,
            ),
            cw.TextWidget(
                markdown=(
                    "## Quick Links\n"
                    f"- [X-Ray Service Map]({xray_url}) — distributed trace view\n"
                    f"- [Step Functions]({sfn_url}) — pipeline execution graph\n"
                ),
                width=24,
                height=3,
            ),
        )

        cdk.CfnOutput(self, "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=EnergyTradingDesk")
