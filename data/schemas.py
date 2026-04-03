"""Pydantic schemas for all domain objects in the trading desk."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class EnergyAsset(str, Enum):
    WTI = "WTI"           # Crude oil (West Texas Intermediate)
    BRENT = "BRENT"       # Crude oil (Brent)
    NATGAS = "NATGAS"     # Natural gas (Henry Hub)
    XLE = "XLE"           # Energy Select Sector ETF
    USO = "USO"           # US Oil Fund
    UNG = "UNG"           # US Natural Gas Fund
    XOM = "XOM"           # ExxonMobil
    CVX = "CVX"           # Chevron
    COP = "COP"           # ConocoPhillips
    POWER_EU = "POWER_EU" # EU electricity spot


# ── Market Data ───────────────────────────────────────────────────────────────

class PriceBar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    source: str = "yfinance"


class EnergyPrice(BaseModel):
    """Spot/futures price from EIA or ENTSO-E."""
    commodity: str          # e.g. "WTI", "NatGas", "electricity_spot_DE"
    price: float
    unit: str               # e.g. "USD/bbl", "USD/MMBtu", "EUR/MWh"
    timestamp: datetime
    source: str


class MacroIndicator(BaseModel):
    series_id: str          # FRED series, e.g. "DCOILWTICO"
    name: str
    value: float
    timestamp: datetime
    source: str = "fred"


class MarketSnapshot(BaseModel):
    """Aggregated market state written to DynamoDB + S3 after each ingestion run."""
    date: str               # ISO date string (PK)
    source: str             # e.g. "combined" (SK)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    prices: dict[str, float] = {}       # symbol → price
    macro: dict[str, float] = {}        # indicator → value
    news_count: int = 0
    sentiment_score: Optional[float] = None
    s3_raw_key: Optional[str] = None


# ── Agent Signals ─────────────────────────────────────────────────────────────

class AgentSignal(BaseModel):
    """Output from any trading agent."""
    agent_name: str
    asset: str
    direction: SignalDirection
    strength: SignalStrength
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: Optional[dict] = None


class TradingRecommendation(BaseModel):
    """Final output from PortfolioManager after aggregating all agent signals."""
    asset: str
    direction: SignalDirection
    strength: SignalStrength
    confidence: float = Field(ge=0.0, le=1.0)
    position_size_pct: float = Field(ge=0.0, le=100.0, description="% of portfolio")
    entry_rationale: str
    risk_notes: str
    contributing_agents: list[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Portfolio ─────────────────────────────────────────────────────────────────

class Position(BaseModel):
    symbol: str
    direction: SignalDirection
    entry_price: float
    current_price: float
    size_pct: float
    pnl_pct: float = 0.0
    opened_at: datetime
    date: str               # ISO date (DynamoDB SK)


# ── News ──────────────────────────────────────────────────────────────────────

class NewsArticle(BaseModel):
    title: str
    description: Optional[str] = None
    url: str
    published_at: datetime
    source: str
    sentiment: Optional[float] = None  # -1.0 (bearish) to +1.0 (bullish)
