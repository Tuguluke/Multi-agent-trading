"""CDK Stack: SQS queues + SNS topics for inter-agent messaging."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct


class MessagingStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Dead Letter Queues ────────────────────────────────────────────────
        ingestion_dlq = sqs.Queue(
            self, "DataIngestionDLQ",
            queue_name="energy-trading-ingestion-dlq",
            retention_period=cdk.Duration.days(14),
        )
        agent_dlq = sqs.Queue(
            self, "AgentTriggerDLQ",
            queue_name="energy-trading-agent-dlq",
            retention_period=cdk.Duration.days(14),
        )

        # ── Main Queues ───────────────────────────────────────────────────────
        self.ingestion_queue = sqs.Queue(
            self, "DataIngestionQueue",
            queue_name="energy-trading-ingestion",
            visibility_timeout=cdk.Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=ingestion_dlq,
            ),
        )

        self.agent_trigger_queue = sqs.Queue(
            self, "AgentTriggerQueue",
            queue_name="energy-trading-agent-trigger",
            visibility_timeout=cdk.Duration.minutes(15),  # agents can be slow
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=2,
                queue=agent_dlq,
            ),
        )

        self.signal_notify_queue = sqs.Queue(
            self, "SignalNotifyQueue",
            queue_name="energy-trading-signal-notify",
            visibility_timeout=cdk.Duration.seconds(30),
        )

        # ── SNS Topic ─────────────────────────────────────────────────────────
        self.signals_topic = sns.Topic(
            self, "TradingSignalsTopic",
            topic_name="energy-trading-signals",
            display_name="Energy Trading Signals",
        )

        # Outputs
        cdk.CfnOutput(self, "IngestionQueueUrl", value=self.ingestion_queue.queue_url)
        cdk.CfnOutput(self, "AgentTriggerQueueUrl", value=self.agent_trigger_queue.queue_url)
        cdk.CfnOutput(self, "SignalsTopicArn", value=self.signals_topic.topic_arn)
