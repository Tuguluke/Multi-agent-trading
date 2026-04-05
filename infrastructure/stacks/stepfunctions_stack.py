"""CDK Stack: Step Functions state machine for the agent pipeline.

Architecture:
  StartExecution
    → IngestData          (Lambda)
    → RunMarketDataAgent  (Lambda)
    → RunTechnicalAnalyst (Lambda)
    → RunSentimentAgent   (Lambda)
    → RunRiskManager      (Lambda)
    → RunPortfolioManager (Lambda)
    → SaveResults         (DynamoDB PutItem — no Lambda needed)

Each agent step is a separate Lambda invocation with {"agent": "<name>"}.
The shared context dict is passed as the state machine execution input and
threaded through each step via ResultPath.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as sfn_tasks,
)
from constructs import Construct

PROJECT_ROOT = str(Path(__file__).parents[2])

# Identical to ComputeStack — CDK deduplicates by content hash so Docker
# only builds once even though two stacks define this layer.
_LAYER_BUNDLING = cdk.BundlingOptions(
    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
    platform="linux/amd64",
    command=[
        "bash", "-c",
        "pip install -r lambdas/requirements-lambda.txt "
        "-t /asset-output/python --no-cache-dir --quiet",
    ],
)


def _source_bundling(handler_subpath: str) -> cdk.BundlingOptions:
    """Source-only bundle — deps come from this stack's own layer."""
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


class StepFunctionsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        lambda_env: dict,
        lambda_role: iam.Role,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        deps_layer = lambda_.LayerVersion(
            self, "SfnDepsLayer",
            layer_version_name="energy-trading-sfn-deps",
            code=lambda_.Code.from_asset(PROJECT_ROOT, bundling=_LAYER_BUNDLING),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Energy trading deps for Step Functions Lambdas",
        )

        common_kwargs = dict(
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            role=lambda_role,
            environment=lambda_env,
            layers=[deps_layer],
            tracing=lambda_.Tracing.ACTIVE,
        )

        # ── Shared Lambda for all agent steps ─────────────────────────────────
        agent_fn = lambda_.Function(
            self, "AgentStepFunction",
            function_name="energy-trading-agent-step",
            code=lambda_.Code.from_asset(
                PROJECT_ROOT,
                bundling=_source_bundling("lambdas/agent_step/handler.py"),
            ),
            timeout=cdk.Duration.minutes(5),
            memory_size=1024,
            **common_kwargs,
        )

        ingest_fn = lambda_.Function(
            self, "IngestStepFunction",
            function_name="energy-trading-ingest-step",
            code=lambda_.Code.from_asset(
                PROJECT_ROOT,
                bundling=_source_bundling("lambdas/data_ingestion/handler.py"),
            ),
            timeout=cdk.Duration.minutes(5),
            memory_size=512,
            **common_kwargs,
        )

        # ── Step Functions tasks ───────────────────────────────────────────────
        def _agent_task(name: str, agent_key: str) -> sfn_tasks.LambdaInvoke:
            return sfn_tasks.LambdaInvoke(
                self, name,
                lambda_function=agent_fn,
                payload=sfn.TaskInput.from_object({
                    "agent": agent_key,
                    "context.$": "$",          # pass full accumulated state
                }),
                result_path=f"$.{agent_key}_result",
                retry_on_service_exceptions=True,
            )

        ingest_step = sfn_tasks.LambdaInvoke(
            self, "IngestData",
            lambda_function=ingest_fn,
            result_path="$.ingest_result",
            retry_on_service_exceptions=True,
        )

        market_step     = _agent_task("MarketDataAgent",  "market_data")
        technical_step  = _agent_task("TechnicalAnalyst", "technical")
        sentiment_step  = _agent_task("SentimentAgent",   "sentiment")
        risk_step       = _agent_task("RiskManager",      "risk")
        portfolio_step  = _agent_task("PortfolioManager", "portfolio")

        # Run sentiment + technical in parallel (they are independent)
        parallel_analysis = sfn.Parallel(self, "ParallelAnalysis")
        parallel_analysis.branch(technical_step)
        parallel_analysis.branch(sentiment_step)

        # ── State machine definition ───────────────────────────────────────────
        definition = (
            ingest_step
            .next(market_step)
            .next(parallel_analysis)
            .next(risk_step)
            .next(portfolio_step)
        )

        # CloudWatch log group for execution history
        log_group = logs.LogGroup(
            self, "StateMachineLogs",
            log_group_name="/aws/states/energy-trading-pipeline",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.TWO_WEEKS,
        )

        self.state_machine = sfn.StateMachine(
            self, "AgentPipeline",
            state_machine_name="energy-trading-agent-pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            # EXPRESS = much cheaper ($1/million executions vs $0.025/1K for STANDARD)
            state_machine_type=sfn.StateMachineType.EXPRESS,
            timeout=cdk.Duration.minutes(30),
            logs=sfn.LogOptions(
                destination=log_group,
                level=sfn.LogLevel.ALL,
                include_execution_data=True,
            ),
            tracing_enabled=True,  # X-Ray tracing across the full pipeline
        )

        cdk.CfnOutput(
            self, "StateMachineArn",
            value=self.state_machine.state_machine_arn,
        )
        cdk.CfnOutput(
            self, "StartPipeline",
            value=(
                f"aws stepfunctions start-sync-execution "
                f"--state-machine-arn {self.state_machine.state_machine_arn} "
                f"--input '{{}}' --region {self.region}"
            ),
            description="Command to run the full agent pipeline",
        )
        cdk.CfnOutput(
            self, "StepFunctionsConsole",
            value=(
                f"https://{self.region}.console.aws.amazon.com/states/home"
                f"#/statemachines/view/{self.state_machine.state_machine_arn}"
            ),
            description="View pipeline execution graph in AWS console",
        )
