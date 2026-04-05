"""CDK Stack: Lambda functions (manually invoked — no EventBridge cron).

Size strategy:
  - Lambda Layer: all pip dependencies (~150 MB, fits under 250 MB limit)
                  boto3 excluded — pre-installed in Python 3.12 runtime
  - Function zip: only project source code (~2 MB)
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_events,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct

PROJECT_ROOT = str(Path(__file__).parents[2])

# Bundling options for the deps layer — installs pip packages only
_LAYER_BUNDLING = cdk.BundlingOptions(
    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
    # Force x86_64 — Lambda runs on AMD64; without this, Docker on Apple Silicon
    # (M1/M2/M3) pulls ARM64 images and pip installs ARM wheels that crash on Lambda.
    platform="linux/amd64",
    command=[
        "bash", "-c",
        "pip install -r lambdas/requirements-lambda.txt "
        "-t /asset-output/python --no-cache-dir --quiet",
    ],
)


def _source_bundling(handler_subpath: str) -> cdk.BundlingOptions:
    """Copy project source + specific handler — no pip install (deps are in the layer)."""
    return cdk.BundlingOptions(
        image=lambda_.Runtime.PYTHON_3_12.bundling_image,
        platform="linux/amd64",
        command=[
            "bash", "-c",
            " && ".join([
                "cp -r agents aws data llm pipelines monitoring /asset-output/",
                "cp config.py /asset-output/",
                f"cp {handler_subpath} /asset-output/handler.py",
            ]),
        ],
    )


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

        # ── SSM Parameter references ──────────────────────────────────────────
        def _ssm(name: str) -> str:
            return ssm.StringParameter.value_for_string_parameter(self, name)

        # ── IAM Role ──────────────────────────────────────────────────────────
        lambda_role = iam.Role(
            self, "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "s3:GetObject", "s3:PutObject", "s3:ListBucket",
                "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                "sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                "cloudwatch:PutMetricData",
                "sns:Publish",
                "ssm:GetParameter", "ssm:GetParameters",
                "bedrock:InvokeModel",
                "xray:PutTraceSegments", "xray:PutTelemetryRecords",
                "states:StartExecution", "states:StartSyncExecution",
            ],
            resources=["*"],
        ))
        self.lambda_role = lambda_role  # exposed for StepFunctionsStack

        # ── Shared dependency layer ───────────────────────────────────────────
        # All pip packages in one layer; functions only ship source code.
        deps_layer = lambda_.LayerVersion(
            self, "DepsLayer",
            layer_version_name="energy-trading-deps",
            code=lambda_.Code.from_asset(
                PROJECT_ROOT,
                bundling=_LAYER_BUNDLING,
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Energy trading desk Python dependencies (no boto3)",
        )

        self.deps_layer = deps_layer  # exposed for StepFunctionsStack

        common_env = {
            "LOG_LEVEL": "INFO",
            "ENVIRONMENT": "prod",
            "LLM_PROVIDER": "groq",
            "GROQ_MODEL": "llama-3.3-70b-versatile",
            "BEDROCK_MODEL": "meta.llama3-8b-instruct-v1:0",
            "DYNAMODB_PREFIX": "dev",
            "GROQ_API_KEYS":  _ssm("/energy-trading/groq-api-keys"),
            "EIA_API_KEY":    _ssm("/energy-trading/eia-api-key"),
            "NEWSAPI_KEY":    _ssm("/energy-trading/newsapi-key"),
            "FRED_API_KEY":   _ssm("/energy-trading/fred-api-key"),
            "SQS_INGESTION_URL":     ingestion_queue.queue_url,
            "SQS_AGENT_TRIGGER_URL": agent_trigger_queue.queue_url,
        }
        self.lambda_env = common_env

        common_kwargs = dict(
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            role=lambda_role,
            environment=common_env,
            layers=[deps_layer],
            tracing=lambda_.Tracing.ACTIVE,
        )

        # ── Data Ingestion Lambda ─────────────────────────────────────────────
        self.ingestion_fn = lambda_.Function(
            self, "DataIngestionFunction",
            function_name="energy-trading-data-ingestion",
            code=lambda_.Code.from_asset(
                PROJECT_ROOT,
                bundling=_source_bundling("lambdas/data_ingestion/handler.py"),
            ),
            timeout=cdk.Duration.minutes(5),
            memory_size=512,
            **common_kwargs,
        )

        # ── Agent Trigger Lambda ──────────────────────────────────────────────
        self.agent_fn = lambda_.Function(
            self, "AgentTriggerFunction",
            function_name="energy-trading-agent-trigger",
            code=lambda_.Code.from_asset(
                PROJECT_ROOT,
                bundling=_source_bundling("lambdas/agent_trigger/handler.py"),
            ),
            timeout=cdk.Duration.minutes(10),
            memory_size=1024,
            **common_kwargs,
        )
        self.agent_fn.add_event_source(
            lambda_events.SqsEventSource(agent_trigger_queue, batch_size=1)
        )

        cdk.CfnOutput(self, "IngestionFnArn", value=self.ingestion_fn.function_arn)
        cdk.CfnOutput(self, "AgentFnArn", value=self.agent_fn.function_arn)
        cdk.CfnOutput(
            self, "InvokeIngestion",
            value=(
                f"aws lambda invoke --function-name energy-trading-data-ingestion "
                f"--region {self.region} /tmp/out.json && cat /tmp/out.json"
            ),
        )
        cdk.CfnOutput(
            self, "InvokeAgents",
            value=(
                f"aws lambda invoke --function-name energy-trading-agent-trigger "
                f"--region {self.region} --payload '{{\"Records\":[]}}' /tmp/out.json && cat /tmp/out.json"
            ),
        )
