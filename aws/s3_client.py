"""AWS S3 client — upload/download raw market data, reports, artifacts."""

from __future__ import annotations

import io
import json
import logging
from datetime import date

import pandas as pd

from config import get_config

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self):
        cfg = get_config()
        self._s3 = cfg._boto_client("s3")
        self._bucket = cfg.S3_BUCKET_NAME

    # ── Raw market data ───────────────────────────────────────────────────────

    def upload_json(self, key: str, data: dict | list) -> str:
        """Upload a JSON object and return its S3 URI."""
        body = json.dumps(data, default=str).encode()
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json")
        uri = f"s3://{self._bucket}/{key}"
        logger.info("Uploaded %s", uri)
        return uri

    def download_json(self, key: str) -> dict | list:
        response = self._s3.get_object(Bucket=self._bucket, Key=key)
        return json.loads(response["Body"].read())

    def upload_dataframe(self, key: str, df: pd.DataFrame) -> str:
        """Upload a DataFrame as Parquet."""
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=True)
        buffer.seek(0)
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=buffer.read(), ContentType="application/octet-stream")
        uri = f"s3://{self._bucket}/{key}"
        logger.info("Uploaded DataFrame %s (%d rows)", uri, len(df))
        return uri

    def download_dataframe(self, key: str) -> pd.DataFrame:
        response = self._s3.get_object(Bucket=self._bucket, Key=key)
        return pd.read_parquet(io.BytesIO(response["Body"].read()))

    # ── Convenience paths ─────────────────────────────────────────────────────

    @staticmethod
    def raw_key(source: str, run_date: date | None = None) -> str:
        d = run_date or date.today()
        return f"raw/{d.isoformat()}/{source}.json"

    @staticmethod
    def signal_key(agent: str, run_date: date | None = None) -> str:
        d = run_date or date.today()
        return f"signals/{d.isoformat()}/{agent}.json"

    @staticmethod
    def price_key(symbol: str, run_date: date | None = None) -> str:
        d = run_date or date.today()
        return f"prices/{d.isoformat()}/{symbol}.parquet"

    def list_keys(self, prefix: str) -> list[str]:
        paginator = self._s3.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
