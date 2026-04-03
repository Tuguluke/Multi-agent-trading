"""Data ingestion pipeline — fetches all sources, normalises, writes to S3 + DynamoDB."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import get_config
from data.schemas import MarketSnapshot

logger = logging.getLogger(__name__)


class IngestPipeline:
    def __init__(self, s3_client=None, db_client=None, cw_client=None):
        self._s3 = s3_client
        self._db = db_client
        self._cw = cw_client

        from data.eia_client import EIAClient
        from data.yfinance_client import YFinanceClient
        from data.fred_client import FREDClient
        from data.entso_client import ENTSOClient
        from data.news_client import NewsClient
        self._eia = EIAClient()
        self._yf = YFinanceClient()
        self._fred = FREDClient()
        self._entso = ENTSOClient()
        self._news = NewsClient()

    def run(self) -> MarketSnapshot:
        """Fetch all data sources and return a normalised MarketSnapshot."""
        logger.info("IngestPipeline: starting data fetch")
        prices: dict[str, float] = {}
        macro: dict[str, float] = {}
        news_count = 0

        # 1. Energy equities (yfinance)
        try:
            snap = self._yf.get_snapshot()
            prices.update(snap)
            logger.info("yfinance: %d prices", len(snap))
        except Exception as e:
            logger.warning("yfinance failed: %s", e)
            if self._cw:
                self._cw.ingestion_failure("yfinance")

        # 2. FRED macro
        try:
            fred_snap = self._fred.get_macro_snapshot()
            macro.update(fred_snap)
            logger.info("FRED: %d series", len(fred_snap))
        except Exception as e:
            logger.warning("FRED failed: %s", e)
            if self._cw:
                self._cw.ingestion_failure("fred")

        # 3. EIA prices (WTI)
        try:
            wti_prices = self._eia.get_wti_price(days=5)
            if wti_prices:
                prices["WTI_EIA"] = wti_prices[0].price
        except Exception as e:
            logger.warning("EIA WTI failed: %s", e)
            if self._cw:
                self._cw.ingestion_failure("eia_wti")

        # 4. ENTSO-E EU power prices
        try:
            entso_snap = self._entso.get_latest_price_snapshot()
            prices.update(entso_snap)
        except Exception as e:
            logger.warning("ENTSO-E failed: %s", e)

        # 5. News count
        try:
            articles = self._news.get_energy_headlines(days=1, page_size=10)
            news_count = len(articles)
        except Exception as e:
            logger.warning("NewsAPI failed: %s", e)

        snapshot = MarketSnapshot(
            date=datetime.now(timezone.utc).date().isoformat(),
            source="combined",
            timestamp=datetime.now(timezone.utc),
            prices=prices,
            macro=macro,
            news_count=news_count,
        )

        # Persist raw data to S3
        if self._s3:
            try:
                from aws.s3_client import S3Client
                key = S3Client.raw_key("combined")
                uri = self._s3.upload_json(key, snapshot.model_dump(mode="json"))
                snapshot.s3_raw_key = key
                logger.info("Raw snapshot uploaded: %s", uri)
            except Exception as e:
                logger.warning("S3 upload failed: %s", e)

        # Persist to DynamoDB
        if self._db:
            try:
                self._db.save_market_snapshot(snapshot.model_dump(mode="json"))
                logger.info("Snapshot saved to DynamoDB")
            except Exception as e:
                logger.warning("DynamoDB save failed: %s", e)

        logger.info(
            "IngestPipeline complete: %d prices, %d macro, %d news articles",
            len(prices), len(macro), news_count,
        )
        return snapshot
