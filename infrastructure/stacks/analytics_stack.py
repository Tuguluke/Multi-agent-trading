"""CDK Stack: Athena + Glue Data Catalog for SQL analytics over S3 data.

After the pipeline runs, you can query your market snapshots and agent signals
directly with SQL — no ETL code needed.

Example Athena queries (run from AWS console or scripts/query_athena.py):

    -- Latest agent signals
    SELECT date, agent_name, direction, strength, confidence
    FROM energy_trading.agent_signals
    ORDER BY date DESC LIMIT 20;

    -- WTI price trend over last 30 days
    SELECT date, prices['WTI'] as wti_price
    FROM energy_trading.market_snapshots
    WHERE source = 'yfinance'
    ORDER BY date DESC LIMIT 30;

    -- LLM benchmark: avg latency by model
    SELECT model_name, AVG(total_ms) as avg_ms, AVG(cost_usd) as avg_cost
    FROM energy_trading.llm_benchmarks
    GROUP BY model_name ORDER BY avg_ms;
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_athena as athena,
    aws_glue as glue,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class AnalyticsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        data_bucket: s3.Bucket,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── Athena query results bucket ────────────────────────────────────────
        # Keep results separate from raw data; auto-expire after 30 days
        results_bucket = s3.Bucket(
            self, "AthenaResults",
            bucket_name=f"energy-trading-athena-{self.account}",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireQueryResults",
                    expiration=cdk.Duration.days(30),
                )
            ],
        )

        # ── Athena Workgroup ───────────────────────────────────────────────────
        self.workgroup = athena.CfnWorkGroup(
            self, "EnergyTradingWorkgroup",
            name="energy-trading",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{results_bucket.bucket_name}/query-results/",
                ),
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                bytes_scanned_cutoff_per_query=100_000_000,  # 100 MB safety cap
            ),
        )

        # ── Glue IAM Role ──────────────────────────────────────────────────────
        glue_role = iam.Role(
            self, "GlueRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        data_bucket.grant_read(glue_role)

        # ── Glue Database ──────────────────────────────────────────────────────
        database = glue.CfnDatabase(
            self, "GlueDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="energy_trading",
                description="Energy trading desk — market snapshots, signals, benchmarks",
            ),
        )

        # ── Glue Crawlers ──────────────────────────────────────────────────────
        # Crawlers scan S3 and auto-create/update table schemas in the Glue catalog.
        # Run manually when new data arrives: aws glue start-crawler --name <name>

        def _crawler(name: str, s3_prefix: str) -> glue.CfnCrawler:
            return glue.CfnCrawler(
                self, f"Crawler_{name}",
                name=f"energy-trading-{name}",
                role=glue_role.role_arn,
                database_name="energy_trading",
                targets=glue.CfnCrawler.TargetsProperty(
                    s3_targets=[glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{data_bucket.bucket_name}/{s3_prefix}",
                    )],
                ),
                schema_change_policy=glue.CfnCrawler.SchemaChangePolicyProperty(
                    update_behavior="LOG",
                    delete_behavior="LOG",
                ),
                recrawl_policy=glue.CfnCrawler.RecrawlPolicyProperty(
                    recrawl_behavior="CRAWL_NEW_FOLDERS_ONLY",
                ),
            )

        _crawler("market-snapshots", "raw/")
        _crawler("agent-signals",    "signals/")
        _crawler("benchmarks",       "benchmarks/")

        # ── Outputs ────────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "AthenaWorkgroupName", value="energy-trading")
        cdk.CfnOutput(self, "GlueDatabaseName",   value="energy_trading")
        cdk.CfnOutput(
            self, "AthenaConsole",
            value=f"https://{self.region}.console.aws.amazon.com/athena/home#/query-editor",
            description="Run SQL queries over your S3 market data",
        )
        cdk.CfnOutput(
            self, "RunCrawlers",
            value=(
                f"aws glue start-crawler --name energy-trading-market-snapshots --region {self.region} && "
                f"aws glue start-crawler --name energy-trading-agent-signals --region {self.region}"
            ),
            description="Run after pipeline to update Glue table schemas",
        )
