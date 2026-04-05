"""CDK Stack: S3 bucket + DynamoDB tables."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    RemovalPolicy,
)
from constructs import Construct


class StorageStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 Bucket ─────────────────────────────────────────────────────────
        self.data_bucket = s3.Bucket(
            self, "EnergyTradingData",
            bucket_name=f"energy-trading-data-{self.account}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ArchiveRawData",
                    prefix="raw/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=cdk.Duration.days(90),
                        )
                    ],
                ),
                s3.LifecycleRule(
                    id="CleanupOldSignals",
                    prefix="signals/",
                    expiration=cdk.Duration.days(365),
                ),
            ],
        )

        # ── DynamoDB Tables ───────────────────────────────────────────────────
        table_config = {
            "billing_mode": dynamodb.BillingMode.PAY_PER_REQUEST,
            "removal_policy": RemovalPolicy.RETAIN,
            "point_in_time_recovery_specification": dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        }

        self.market_snapshots = dynamodb.Table(
            self, "MarketSnapshots",
            table_name="dev-MarketSnapshots",
            partition_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="source", type=dynamodb.AttributeType.STRING),
            **table_config,
        )

        self.agent_signals = dynamodb.Table(
            self, "AgentSignals",
            table_name="dev-AgentSignals",
            partition_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="agent_name", type=dynamodb.AttributeType.STRING),
            **table_config,
        )
        self.agent_signals.add_global_secondary_index(
            index_name="AgentNameIndex",
            partition_key=dynamodb.Attribute(name="agent_name", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="timestamp", type=dynamodb.AttributeType.STRING),
        )

        self.llm_benchmarks = dynamodb.Table(
            self, "LLMBenchmarks",
            table_name="dev-LLMBenchmarks",
            partition_key=dynamodb.Attribute(name="model_name", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="timestamp", type=dynamodb.AttributeType.STRING),
            **table_config,
        )

        self.portfolio = dynamodb.Table(
            self, "Portfolio",
            table_name="dev-Portfolio",
            partition_key=dynamodb.Attribute(name="symbol", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING),
            **table_config,
        )

        # Outputs
        cdk.CfnOutput(self, "BucketName", value=self.data_bucket.bucket_name)
        cdk.CfnOutput(self, "MarketSnapshotsTable", value=self.market_snapshots.table_name)
        cdk.CfnOutput(self, "AgentSignalsTable", value=self.agent_signals.table_name)
        cdk.CfnOutput(self, "LLMBenchmarksTable", value=self.llm_benchmarks.table_name)
