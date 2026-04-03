"""ENTSO-E client for European electricity market data.

Free registration: https://transparency.entsoe.eu/
Token docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import get_config
from data.schemas import EnergyPrice

logger = logging.getLogger(__name__)


class ENTSOClient:
    def __init__(self):
        self._token = get_config().ENTSO_TOKEN
        self._client = None
        if self._token:
            try:
                from entsoe import EntsoePandasClient
                self._client = EntsoePandasClient(api_key=self._token)
            except ImportError:
                logger.warning("entsoe-py not installed")
        else:
            logger.warning("ENTSO_TOKEN not set — EU power data unavailable")

    def get_day_ahead_prices(
        self,
        country_code: str = "DE_LU",
        days: int = 7,
    ) -> list[EnergyPrice]:
        """Day-ahead electricity prices (EUR/MWh) for a bidding zone."""
        if not self._client:
            return []
        import pandas as pd
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        try:
            series = self._client.query_day_ahead_prices(
                country_code,
                start=pd.Timestamp(start),
                end=pd.Timestamp(end),
            )
            prices = []
            for ts, val in series.items():
                prices.append(EnergyPrice(
                    commodity=f"POWER_{country_code}",
                    price=float(val),
                    unit="EUR/MWh",
                    timestamp=ts.to_pydatetime(),
                    source="entsoe",
                ))
            logger.info("ENTSO-E %s: %d hourly prices", country_code, len(prices))
            return prices
        except Exception as e:
            logger.warning("ENTSO-E error for %s: %s", country_code, e)
            return []

    def get_generation_mix(self, country_code: str = "DE_LU") -> dict:
        """Current generation mix by fuel type (% share)."""
        if not self._client:
            return {}
        import pandas as pd
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        try:
            df = self._client.query_generation(
                country_code,
                start=pd.Timestamp(start),
                end=pd.Timestamp(end),
            )
            latest = df.iloc[-1]
            total = latest.sum()
            if total == 0:
                return {}
            mix = {str(k): round(float(v) / total * 100, 2) for k, v in latest.items() if v > 0}
            logger.info("ENTSO-E generation mix %s: %d fuel types", country_code, len(mix))
            return mix
        except Exception as e:
            logger.warning("ENTSO-E generation mix error: %s", e)
            return {}

    def get_latest_price_snapshot(self) -> dict[str, float]:
        """Latest hour day-ahead price for key European zones."""
        zones = {"DE_LU": "Power_DE", "FR": "Power_FR", "GB": "Power_GB"}
        snapshot = {}
        for zone, label in zones.items():
            prices = self.get_day_ahead_prices(zone, days=1)
            if prices:
                snapshot[label] = prices[-1].price
        return snapshot
