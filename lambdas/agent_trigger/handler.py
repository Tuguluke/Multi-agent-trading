"""Lambda: SQS consumer → runs the full agent pipeline."""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, "/var/task")

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def handler(event, context):
    """SQS trigger → run orchestrator → return recommendation."""
    logger.info("AgentTrigger Lambda: %d message(s)", len(event.get("Records", [])))

    from aws.dynamodb_client import DynamoDBClient
    from aws.s3_client import S3Client
    from aws.cloudwatch_client import CloudWatchClient
    from llm.llm_router import LLMRouter
    from agents.orchestrator import Orchestrator

    db = DynamoDBClient()
    s3 = S3Client()
    cw = CloudWatchClient()
    router = LLMRouter(dynamodb_client=db)
    orchestrator = Orchestrator(llm_router=router, db_client=db, cw_client=cw, s3_client=s3)

    results = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            logger.info("Processing message: %s", body)
            recommendation = orchestrator.run(context={})
            if recommendation:
                results.append(recommendation.model_dump(mode="json"))
        except Exception as e:
            logger.error("Failed to process message: %s", e, exc_info=True)

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(results)}),
    }
