"""Streamlit dashboard — Energy Trading Desk."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import get_config

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Energy Trading Desk",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

cfg = get_config()


# ── Cached resource initialisation ───────────────────────────────────────────

@st.cache_resource
def get_db():
    from aws.dynamodb_client import DynamoDBClient
    return DynamoDBClient()


@st.cache_resource
def get_s3():
    from aws.s3_client import S3Client
    return S3Client()


@st.cache_resource
def get_router():
    from llm.llm_router import LLMRouter
    return LLMRouter(dynamodb_client=get_db())


@st.cache_resource
def get_orchestrator():
    from agents.orchestrator import Orchestrator
    from aws.cloudwatch_client import CloudWatchClient
    return Orchestrator(
        llm_router=get_router(),
        db_client=get_db(),
        cw_client=CloudWatchClient(),
        s3_client=get_s3(),
    )


@st.cache_data(ttl=300)
def fetch_price_data(symbol: str, days: int = 60):
    from data.yfinance_client import YFinanceClient
    return YFinanceClient().get_ohlcv(symbol, days=days)


@st.cache_data(ttl=600)
def fetch_all_prices():
    from data.yfinance_client import YFinanceClient
    return YFinanceClient().get_snapshot()


@st.cache_data(ttl=300)
def fetch_latest_signals(limit: int = 20):
    try:
        return get_db().get_latest_signals(limit=limit)
    except Exception:
        return []


@st.cache_data(ttl=600)
def fetch_llm_benchmarks():
    try:
        return get_db().get_all_llm_benchmarks(limit=500)
    except Exception:
        return []


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚡ Energy Trading Desk")
    st.caption(f"Provider: `{cfg.LLM_PROVIDER}` | Model: `{cfg.GROQ_MODEL}`")
    st.divider()

    if st.button("Run Full Pipeline", type="primary", use_container_width=True):
        with st.spinner("Running agents..."):
            rec = get_orchestrator().run()
            if rec:
                st.success(f"{rec.direction.value} {rec.asset} ({rec.strength.value})")
                st.balloons()
            else:
                st.error("Pipeline failed — check logs")
        st.cache_data.clear()

    st.divider()
    st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    if st.button("Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Live Signals", "Market Data", "Sentiment", "Portfolio", "Agent Logs", "LLM Benchmarks"
])


# ── Tab 1: Live Signals ───────────────────────────────────────────────────────

with tab1:
    st.header("Live Trading Signals")
    signals = fetch_latest_signals()

    if not signals:
        st.info("No signals yet — run the pipeline from the sidebar.")
    else:
        # Latest recommendation
        pm_signals = [s for s in signals if s.get("agent_name") == "PortfolioManager"]
        if pm_signals:
            latest = pm_signals[0]
            col1, col2, col3, col4 = st.columns(4)
            direction = latest.get("direction", "—")
            color = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(direction, "⚪")
            col1.metric("Direction", f"{color} {direction}")
            col2.metric("Asset", latest.get("asset", "—"))
            col3.metric("Strength", latest.get("strength", "—"))
            col4.metric("Confidence", f"{float(latest.get('confidence', 0))*100:.0f}%")

            with st.expander("Portfolio Manager Reasoning"):
                st.write(latest.get("reasoning", "—"))

        st.divider()

        # All agent signals table
        st.subheader("All Agent Signals")
        df = pd.DataFrame(signals)
        if not df.empty:
            display_cols = [c for c in ["agent_name", "asset", "direction", "strength", "confidence", "timestamp"] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True, hide_index=True)


# ── Tab 2: Market Data ────────────────────────────────────────────────────────

with tab2:
    st.header("Energy Market Data")

    col_l, col_r = st.columns([1, 3])
    with col_l:
        symbol = st.selectbox("Asset", ["XLE", "XOM", "CVX", "COP", "USO", "UNG", "OXY", "SLB"])
        days = st.slider("History (days)", 30, 180, 60)
        show_rsi = st.checkbox("RSI", value=True)
        show_macd = st.checkbox("MACD", value=True)
        show_bb = st.checkbox("Bollinger Bands", value=True)

    with col_r:
        df = fetch_price_data(symbol, days)
        if df.empty:
            st.warning(f"No data for {symbol}")
        else:
            # Price + Bollinger chart
            fig = go.Figure()
            if show_bb:
                from ta.volatility import BollingerBands
                bb = BollingerBands(df["Close"], window=20, window_dev=2)
                fig.add_trace(go.Scatter(x=df.index, y=bb.bollinger_hband(), name="BB High",
                    line=dict(color="rgba(100,100,255,0.3)"), fill=None))
                fig.add_trace(go.Scatter(x=df.index, y=bb.bollinger_lband(), name="BB Low",
                    line=dict(color="rgba(100,100,255,0.3)"), fill="tonexty",
                    fillcolor="rgba(100,100,255,0.05)"))

            fig.add_trace(go.Candlestick(
                x=df.index, open=df["Open"], high=df["High"],
                low=df["Low"], close=df["Close"], name=symbol,
            ))
            fig.update_layout(title=f"{symbol} Price", xaxis_rangeslider_visible=False, height=400)
            st.plotly_chart(fig, use_container_width=True)

            # RSI
            if show_rsi:
                from ta.momentum import RSIIndicator
                rsi = RSIIndicator(df["Close"], window=14).rsi()
                fig_rsi = px.line(x=df.index, y=rsi, title="RSI (14)", labels={"y": "RSI"})
                fig_rsi.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought")
                fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold")
                fig_rsi.update_layout(height=200)
                st.plotly_chart(fig_rsi, use_container_width=True)

            # MACD
            if show_macd:
                from ta.trend import MACD
                macd = MACD(df["Close"])
                fig_macd = go.Figure()
                fig_macd.add_trace(go.Scatter(x=df.index, y=macd.macd(), name="MACD"))
                fig_macd.add_trace(go.Scatter(x=df.index, y=macd.macd_signal(), name="Signal"))
                fig_macd.add_bar(x=df.index, y=macd.macd_diff(), name="Histogram")
                fig_macd.update_layout(title="MACD", height=200)
                st.plotly_chart(fig_macd, use_container_width=True)

    # Price snapshot table
    st.divider()
    st.subheader("Energy Universe Snapshot")
    prices = fetch_all_prices()
    if prices:
        price_df = pd.DataFrame(list(prices.items()), columns=["Symbol", "Price"])
        st.dataframe(price_df, use_container_width=True, hide_index=True)


# ── Tab 3: Sentiment ──────────────────────────────────────────────────────────

with tab3:
    st.header("Energy Market Sentiment")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Reddit Sentiment")
        if st.button("Fetch Reddit Sentiment"):
            with st.spinner("Fetching Reddit data..."):
                from data.reddit_client import RedditClient
                summary = RedditClient().get_sentiment_summary(limit=30)
                bull = summary.get("bullish_pct", 0)
                bear = summary.get("bearish_pct", 0)
                neut = 100 - bull - bear
                fig = px.pie(
                    values=[bull, bear, neut],
                    names=["Bullish", "Bearish", "Neutral"],
                    color_discrete_sequence=["#2ecc71", "#e74c3c", "#95a5a6"],
                    title=f"Reddit Energy Sentiment ({summary.get('total_posts', 0)} posts)",
                )
                st.plotly_chart(fig, use_container_width=True)
                if summary.get("top_tickers"):
                    st.write("**Most Mentioned Tickers:**")
                    for ticker, count in summary["top_tickers"]:
                        st.write(f"- {ticker}: {count} mentions")

    with col2:
        st.subheader("Recent News Headlines")
        if st.button("Fetch Energy Headlines"):
            with st.spinner("Fetching news..."):
                from data.news_client import NewsClient
                articles = NewsClient().get_multi_query_headlines(days=2)
                for art in articles[:10]:
                    st.markdown(f"**{art.title}**")
                    st.caption(f"{art.source} · {art.published_at.strftime('%Y-%m-%d %H:%M')}")
                    st.divider()


# ── Tab 4: Portfolio ──────────────────────────────────────────────────────────

with tab4:
    st.header("Paper Portfolio")
    st.info("Paper trading mode — no real orders are executed.")

    # Fetch portfolio positions from DynamoDB
    try:
        positions = get_db().scan(cfg.dynamo_table("Portfolio"), limit=50)
    except Exception:
        positions = []

    if not positions:
        st.write("No open positions.")
    else:
        df = pd.DataFrame(positions)
        if not df.empty:
            pnl_cols = [c for c in ["symbol", "direction", "entry_price", "current_price", "size_pct", "pnl_pct", "opened_at"] if c in df.columns]
            st.dataframe(df[pnl_cols] if pnl_cols else df, use_container_width=True)

            if "pnl_pct" in df.columns:
                fig = px.bar(df, x="symbol", y="pnl_pct", color="pnl_pct",
                    color_continuous_scale="RdYlGn", title="P&L by Position (%)")
                st.plotly_chart(fig, use_container_width=True)


# ── Tab 5: Agent Logs ─────────────────────────────────────────────────────────

with tab5:
    st.header("Agent Execution Logs")
    signals = fetch_latest_signals(limit=50)

    agent_names = list({s.get("agent_name", "") for s in signals})
    selected_agent = st.selectbox("Filter by agent", ["All"] + sorted(agent_names))

    filtered = signals if selected_agent == "All" else [
        s for s in signals if s.get("agent_name") == selected_agent
    ]

    for sig in filtered[:10]:
        with st.expander(
            f"{sig.get('agent_name', '?')} | {sig.get('direction', '?')} {sig.get('asset', '?')} "
            f"| {sig.get('timestamp', '')[:16]}"
        ):
            st.write(sig.get("reasoning", "No reasoning stored"))
            if sig.get("raw_data"):
                st.json(sig["raw_data"])


# ── Tab 6: LLM Benchmarks ─────────────────────────────────────────────────────

with tab6:
    st.header("LLM Performance Comparison")
    st.caption("Every agent call is logged here for cross-model comparison.")

    records = fetch_llm_benchmarks()
    if not records:
        st.info("No benchmark data yet — run the pipeline to generate data.")
    else:
        df = pd.DataFrame(records)

        # Summary stats per model
        st.subheader("Summary by Model")
        summary = (
            df.groupby("model_name")
            .agg(
                calls=("call_id", "count"),
                avg_total_ms=("total_ms", "mean"),
                p95_total_ms=("total_ms", lambda x: x.quantile(0.95)),
                avg_tokens_sec=("tokens_per_sec", "mean"),
                total_cost_usd=("cost_usd", "sum"),
            )
            .round(2)
            .reset_index()
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            fig = px.box(df, x="model_name", y="total_ms", color="model_name",
                title="Total Latency Distribution (ms)",
                labels={"total_ms": "Total ms", "model_name": "Model"})
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.box(df, x="model_name", y="tokens_per_sec", color="model_name",
                title="Throughput Distribution (tokens/sec)",
                labels={"tokens_per_sec": "Tokens/sec", "model_name": "Model"})
            st.plotly_chart(fig, use_container_width=True)

        # Cost breakdown
        st.subheader("Cost per Agent × Model")
        if "agent_name" in df.columns:
            pivot = df.groupby(["agent_name", "model_name"])["cost_usd"].sum().reset_index()
            fig = px.bar(pivot, x="agent_name", y="cost_usd", color="model_name",
                barmode="group", title="Total Cost by Agent and Model (USD)")
            st.plotly_chart(fig, use_container_width=True)

        # Latency over time
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            fig = px.scatter(df, x="timestamp", y="total_ms", color="model_name",
                title="Latency Over Time", opacity=0.7)
            st.plotly_chart(fig, use_container_width=True)

        # Raw data
        with st.expander("Raw Benchmark Records"):
            st.dataframe(df, use_container_width=True)
