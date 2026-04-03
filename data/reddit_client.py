"""Reddit client for energy market social sentiment.

Create app: https://www.reddit.com/prefs/apps (script type)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import get_config
from data.schemas import NewsArticle

logger = logging.getLogger(__name__)

ENERGY_SUBREDDITS = ["energy", "oil", "RenewableEnergy", "investing", "StockMarket"]
ENERGY_KEYWORDS = {"oil", "gas", "energy", "crude", "opec", "lng", "wti", "brent", "refinery", "natgas", "solar", "wind"}


class RedditClient:
    def __init__(self):
        cfg = get_config()
        self._client = None
        if cfg.REDDIT_CLIENT_ID and cfg.REDDIT_CLIENT_SECRET:
            try:
                import praw
                self._client = praw.Reddit(
                    client_id=cfg.REDDIT_CLIENT_ID,
                    client_secret=cfg.REDDIT_CLIENT_SECRET,
                    user_agent=cfg.REDDIT_USER_AGENT,
                )
            except ImportError:
                logger.warning("praw not installed")
        else:
            logger.warning("Reddit credentials not set — Reddit data unavailable")

    def get_energy_posts(
        self,
        subreddits: list[str] | None = None,
        limit: int = 25,
        time_filter: str = "day",
    ) -> list[NewsArticle]:
        if not self._client:
            return []
        subreddits = subreddits or ENERGY_SUBREDDITS
        articles = []
        for sub_name in subreddits:
            try:
                sub = self._client.subreddit(sub_name)
                for post in sub.top(time_filter=time_filter, limit=limit):
                    title_lower = post.title.lower()
                    if any(kw in title_lower for kw in ENERGY_KEYWORDS):
                        articles.append(NewsArticle(
                            title=post.title,
                            description=post.selftext[:200] if post.selftext else None,
                            url=f"https://reddit.com{post.permalink}",
                            published_at=datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                            source=f"reddit/r/{sub_name}",
                        ))
            except Exception as e:
                logger.warning("Reddit error for r/%s: %s", sub_name, e)
        logger.info("Reddit: %d energy-related posts", len(articles))
        return articles

    def get_sentiment_summary(self, limit: int = 50) -> dict:
        """Return {bullish_count, bearish_count, neutral_count, top_tickers}."""
        posts = self.get_energy_posts(limit=limit)
        bullish_words = {"bullish", "buy", "long", "up", "rise", "surge", "rally", "breakout"}
        bearish_words = {"bearish", "sell", "short", "down", "drop", "crash", "fall", "dump"}
        bullish = bearish = neutral = 0
        tickers: dict[str, int] = {}
        energy_tickers = {"XLE", "XOM", "CVX", "COP", "USO", "UNG", "OXY", "SLB", "HAL", "PSX"}
        for post in posts:
            text = (post.title + " " + (post.description or "")).lower()
            words = set(text.split())
            if words & bullish_words:
                bullish += 1
            elif words & bearish_words:
                bearish += 1
            else:
                neutral += 1
            for ticker in energy_tickers:
                if ticker.lower() in text:
                    tickers[ticker] = tickers.get(ticker, 0) + 1
        total = len(posts) or 1
        return {
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "bullish_pct": round(bullish / total * 100, 1),
            "bearish_pct": round(bearish / total * 100, 1),
            "top_tickers": sorted(tickers.items(), key=lambda x: -x[1])[:5],
            "total_posts": len(posts),
        }
