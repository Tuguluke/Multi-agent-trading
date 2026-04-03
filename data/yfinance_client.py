"""Yahoo Finance client for energy equities and ETFs."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from data.schemas import PriceBar

logger = logging.getLogger(__name__)

# Default energy universe
ENERGY_SYMBOLS = ["XLE", "USO", "UNG", "XOM", "CVX", "COP", "SLB", "HAL", "OXY", "PSX"]


class YFinanceClient:
    def get_ohlcv(
        self,
        symbol: str,
        days: int = 60,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Download OHLCV data. Returns DataFrame indexed by datetime."""
        start = (date.today() - timedelta(days=days)).isoformat()
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, interval=interval)
        if df.empty:
            logger.warning("yfinance: no data for %s", symbol)
            return df
        df.index = pd.to_datetime(df.index, utc=True)
        logger.info("yfinance %s: %d bars", symbol, len(df))
        return df

    def get_latest_price(self, symbol: str) -> float | None:
        """Get the most recent closing price."""
        df = self.get_ohlcv(symbol, days=5)
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])

    def get_multi_ohlcv(
        self,
        symbols: list[str] | None = None,
        days: int = 60,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols."""
        symbols = symbols or ENERGY_SYMBOLS
        result = {}
        for sym in symbols:
            try:
                result[sym] = self.get_ohlcv(sym, days=days)
            except Exception as e:
                logger.warning("yfinance error for %s: %s", sym, e)
        return result

    def get_snapshot(self, symbols: list[str] | None = None) -> dict[str, float]:
        """Return {symbol: latest_close} for all symbols."""
        symbols = symbols or ENERGY_SYMBOLS
        snapshot = {}
        data = yf.download(
            symbols,
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            return snapshot
        close = data["Close"] if "Close" in data.columns else data.xs("Close", axis=1, level=0)
        latest = close.iloc[-1]
        for sym in symbols:
            if sym in latest and not pd.isna(latest[sym]):
                snapshot[sym] = round(float(latest[sym]), 4)
        return snapshot

    def get_fundamentals(self, symbol: str) -> dict:
        """Key fundamental metrics for an energy company."""
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "symbol": symbol,
            "sector": info.get("sector"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "dividend_yield": info.get("dividendYield"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
            "beta": info.get("beta"),
        }
