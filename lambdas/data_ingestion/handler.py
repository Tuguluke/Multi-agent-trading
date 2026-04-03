"""Lambda: triggered by EventBridge cron → fetches all energy market data."""

from __future__ import annotations

import json
import logging
import os
import sys

# Add project root to path (Lambda layer or bundled deployment)
sys.path.insert(0, "/var/task")

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def handler(event, context):
    """EventBridge → fetch market data → write to S3 + DynamoDB → send SQS trigger."""
    logger.info("DataIngestion Lambda triggered: %s", json.dumps(event))

    from aws.s3_client import S3Client
    from aws.dynamodb_client import DynamoDBClient
    from aws.sqs_client import SQSClient
    from aws.cloudwatch_client import CloudWatchClient
    from pipelines.ingest_pipeline import IngestPipeline

    s3 = S3Client()
    db = DynamoDBClient()
    sqs = SQSClient()
    cw = CloudWatchClient()

    pipeline = IngestPipeline(s3_client=s3, db_client=db, cw_client=cw)
    snapshot = pipeline.run()

    # Trigger the agent pipeline via SQS
    from config import get_config
    cfg = get_config()
    if cfg.SQS_AGENT_TRIGGER_URL:
        sqs.send(cfg.SQS_AGENT_TRIGGER_URL, {
            "event_type": "new_snapshot",
            "date": snapshot.date,
            "s3_key": snapshot.s3_raw_key,
        })
        logger.info("SQS agent trigger sent")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "date": snapshot.date,
            "prices_count": len(snapshot.prices),
            "macro_count": len(snapshot.macro),
        }),
    }
