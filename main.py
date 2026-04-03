"""CLI entry point — run the full pipeline once or individual stages."""

from __future__ import annotations

import argparse
import logging
import sys

from config import get_config

logger = logging.getLogger(__name__)


def run_ingest():
    from aws.s3_client import S3Client
    from aws.dynamodb_client import DynamoDBClient
    from aws.cloudwatch_client import CloudWatchClient
    from pipelines.ingest_pipeline import IngestPipeline
    snapshot = IngestPipeline(
        s3_client=S3Client(),
        db_client=DynamoDBClient(),
        cw_client=CloudWatchClient(),
    ).run()
    print(f"Snapshot: {snapshot.date} | prices={len(snapshot.prices)} macro={len(snapshot.macro)}")
    return snapshot


def run_pipeline():
    from aws.dynamodb_client import DynamoDBClient
    from aws.s3_client import S3Client
    from aws.cloudwatch_client import CloudWatchClient
    from llm.llm_router import LLMRouter
    from agents.orchestrator import Orchestrator
    db = DynamoDBClient()
    router = LLMRouter(dynamodb_client=db)
    orchestrator = Orchestrator(
        llm_router=router,
        db_client=db,
        cw_client=CloudWatchClient(),
        s3_client=S3Client(),
    )
    rec = orchestrator.run()
    if rec:
        print(f"\n=== RECOMMENDATION ===")
        print(f"Asset:    {rec.asset}")
        print(f"Signal:   {rec.direction.value} ({rec.strength.value})")
        print(f"Size:     {rec.position_size_pct:.1f}%")
        print(f"Confidence: {rec.confidence*100:.0f}%")
        print(f"Rationale: {rec.entry_rationale[:200]}...")
    else:
        print("Pipeline returned no recommendation")
    return rec


def main():
    parser = argparse.ArgumentParser(description="Energy Trading Desk CLI")
    parser.add_argument(
        "command",
        choices=["ingest", "pipeline", "full"],
        help="ingest: fetch data only | pipeline: run agents only | full: ingest + pipeline",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "ingest":
        run_ingest()
    elif args.command == "pipeline":
        run_pipeline()
    elif args.command == "full":
        run_ingest()
        run_pipeline()


if __name__ == "__main__":
    main()
