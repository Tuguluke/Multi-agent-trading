"""CDK Stack: Lambda functions + EventBridge rules."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_sqs as sqs,
)
from constructs import Construct


class ComputeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        ingestion_queue: sqs.Queue,
        agent_trigger_queue: sqs.Queue,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── IAM Role ─────────────────────────────────────────────────────────
        lambda_role = iam.Role(
            self, "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "s3:GetObject", "s3:PutObject", "s3:ListBucket",
                "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                "sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                "secretsmanager:GetSecretValue",
                "cloudwatch:PutMetricData",
                "sns:Publish",
                "ssm:GetParameter",
            ],
            resources=["*"],
        ))

        common_env = {
            "LOG_LEVEL": "INFO",
            "ENVIRONMENT": "prod",
            "AWS_REGION": self.region,
        }

        # ── Data Ingestion Lambda ─────────────────────────────────────────────
        self.ingestion_fn = lambda_.Function(
            self, "DataIngestionFunction",
            function_name="energy-trading-data-ingestion",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("../lambdas/data_ingestion"),
            handler="handler.handler",
            timeout=cdk.Duration.minutes(5),
            memory_size=512,
            role=lambda_role,
            environment=common_env,
        )

        # ── Agent Trigger Lambda ──────────────────────────────────────────────
        self.agent_fn = lambda_.Function(
            self, "AgentTriggerFunction",
            function_name="energy-trading-agent-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("../lambdas/agent_trigger"),
            handler="handler.handler",
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            role=lambda_role,
            environment=common_env,
        )
        # Wire SQS → AgentTrigger Lambda
        self.agent_fn.add_event_source(
            lambda_events.SqsEventSource(agent_trigger_queue, batch_size=1)
        )

        # ── EventBridge Rules ─────────────────────────────────────────────────
        # Every 15 min Mon-Fri during US market hours (9:30-16:30 ET = 14:30-21:30 UTC)
        market_hours_rule = events.Rule(
            self, "MarketHoursRule",
            rule_name="energy-trading-market-hours",
            schedule=events.Schedule.cron(
                minute="0,15,30,45",
                hour="14-21",
                week_day="MON-FRI",
            ),
            description="Trigger energy data ingestion during US market hours",
        )
        market_hours_rule.add_target(targets.LambdaFunction(self.ingestion_fn))

        # Energy futures run almost 24/5 — additional overnight run at 6am UTC
        overnight_rule = events.Rule(
            self, "OvernightRule",
            rule_name="energy-trading-overnight",
            schedule=events.Schedule.cron(minute="0", hour="6", week_day="MON-FRI"),
            description="Morning pre-market energy data snapshot",
        )
        overnight_rule.add_target(targets.LambdaFunction(self.ingestion_fn))

        cdk.CfnOutput(self, "IngestionFnArn", value=self.ingestion_fn.function_arn)
        cdk.CfnOutput(self, "AgentFnArn", value=self.agent_fn.function_arn)
