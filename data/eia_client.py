"""EIA (US Energy Information Administration) API client.

Free API key: https://www.eia.gov/opendata/
Docs: https://www.eia.gov/opendata/documentation.php
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import requests

from config import get_config
from data.schemas import EnergyPrice

logger = logging.getLogger(__name__)

EIA_BASE = "https://api.eia.gov/v2"

# Series IDs for key energy commodities
EIA_SERIES = {
    "WTI":    "petroleum/pri/spt/data/",       # WTI crude spot price
    "BRENT":  "petroleum/pri/spt/data/",        # Brent crude spot
    "NATGAS": "natural-gas/pri/sum/data/",       # Henry Hub natural gas
    "ELEC_RETAIL": "electricity/retail-sales/data/",  # US retail electricity
}


class EIAClient:
    def __init__(self):
        self._api_key = get_config().EIA_API_KEY
        self._session = requests.Session()

    def _get(self, path: str, params: dict) -> dict:
        params["api_key"] = self._api_key
        url = f"{EIA_BASE}/{path.lstrip('/')}"
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_wti_price(self, days: int = 30) -> list[EnergyPrice]:
        """WTI crude oil spot prices (USD/bbl)."""
        start = (date.today() - timedelta(days=days)).isoformat()
        data = self._get(
            "petroleum/pri/spt/data/",
            {
                "frequency": "daily",
                "data[0]": "value",
                "facets[product][]": "EPCWTI",
                "facets[duoarea][]": "RWC",
                "start": start,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": days,
            },
        )
        prices = []
        for row in data.get("response", {}).get("data", []):
            try:
                from datetime import datetime
                prices.append(EnergyPrice(
                    commodity="WTI",
                    price=float(row["value"]),
                    unit="USD/bbl",
                    timestamp=datetime.fromisoformat(row["period"]),
                    source="eia",
                ))
            except (KeyError, ValueError, TypeError):
                continue
        logger.info("EIA WTI: fetched %d prices", len(prices))
        return prices

    def get_natgas_price(self, days: int = 30) -> list[EnergyPrice]:
        """Henry Hub natural gas spot prices (USD/MMBtu)."""
        start = (date.today() - timedelta(days=days)).isoformat()
        data = self._get(
            "natural-gas/pri/sum/data/",
            {
                "frequency": "monthly",
                "data[0]": "value",
                "facets[process][]": "PCS",
                "start": start,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 12,
            },
        )
        prices = []
        for row in data.get("response", {}).get("data", []):
            try:
                from datetime import datetime
                prices.append(EnergyPrice(
                    commodity="NATGAS",
                    price=float(row["value"]),
                    unit="USD/MMBtu",
                    timestamp=datetime.fromisoformat(row["period"] + "-01"),
                    source="eia",
                ))
            except (KeyError, ValueError, TypeError):
                continue
        logger.info("EIA NatGas: fetched %d prices", len(prices))
        return prices

    def get_weekly_inventory(self) -> dict:
        """Latest US crude oil inventory (EIA weekly petroleum status report)."""
        data = self._get(
            "petroleum/stoc/wstk/data/",
            {
                "frequency": "weekly",
                "data[0]": "value",
                "facets[product][]": "EPC0",
                "facets[duoarea][]": "NUS",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 4,
            },
        )
        rows = data.get("response", {}).get("data", [])
        if not rows:
            return {}
        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        result = {
            "date": latest.get("period"),
            "inventory_mmbbl": float(latest.get("value", 0)),
            "change_mmbbl": None,
        }
        if previous:
            result["change_mmbbl"] = round(
                float(latest.get("value", 0)) - float(previous.get("value", 0)), 2
            )
        logger.info("EIA inventory: %s Mmbbl on %s", result["inventory_mmbbl"], result["date"])
        return result
