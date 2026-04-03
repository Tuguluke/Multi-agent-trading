"""FRED (Federal Reserve Economic Data) client for macro energy indicators.

Free API key: https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from fredapi import Fred

from config import get_config
from data.schemas import MacroIndicator

logger = logging.getLogger(__name__)

# FRED series relevant to energy markets
ENERGY_SERIES = {
    "DCOILWTICO":   "WTI Crude Oil Price (USD/bbl)",
    "DCOILBRENTEU": "Brent Crude Oil Price (USD/bbl)",
    "DHHNGSP":      "Henry Hub Natural Gas Spot Price (USD/MMBtu)",
    "GASREGCOVW":   "US Regular Gasoline Price (USD/gallon)",
    "MHHNGSP":      "Henry Hub NatGas Price Monthly (USD/MMBtu)",
    "WTISPLC":      "WTI-Brent Spread",
    "CPIUFDNS":     "CPI Food & Energy",
    "T10YIE":       "10-Year Breakeven Inflation Rate",
}


class FREDClient:
    def __init__(self):
        api_key = get_config().FRED_API_KEY
        self._fred = Fred(api_key=api_key) if api_key else None
        if not api_key:
            logger.warning("FRED_API_KEY not set — FRED data unavailable")

    def get_series(self, series_id: str, days: int = 90) -> pd.Series:
        if not self._fred:
            return pd.Series(dtype=float)
        start = (date.today() - timedelta(days=days)).isoformat()
        try:
            data = self._fred.get_series(series_id, observation_start=start)
            logger.info("FRED %s: %d observations", series_id, len(data))
            return data.dropna()
        except Exception as e:
            logger.warning("FRED error for %s: %s", series_id, e)
            return pd.Series(dtype=float)

    def get_latest(self, series_id: str) -> MacroIndicator | None:
        series = self.get_series(series_id, days=30)
        if series.empty:
            return None
        return MacroIndicator(
            series_id=series_id,
            name=ENERGY_SERIES.get(series_id, series_id),
            value=float(series.iloc[-1]),
            timestamp=series.index[-1].to_pydatetime(),
        )

    def get_macro_snapshot(self) -> dict[str, float]:
        """Return latest value for all tracked energy macro series."""
        snapshot = {}
        for series_id in ENERGY_SERIES:
            indicator = self.get_latest(series_id)
            if indicator:
                snapshot[series_id] = indicator.value
        logger.info("FRED macro snapshot: %d series", len(snapshot))
        return snapshot

    def get_wti_trend(self, weeks: int = 12) -> list[dict]:
        """WTI crude price trend — leading indicator for energy market direction."""
        series = self.get_series("DCOILWTICO", days=weeks * 7)
        return [
            {"date": str(ts.date()), "wti_price": round(float(val), 2)}
            for ts, val in series.items()
        ]
