"""NewsAPI client for energy-sector financial headlines.

Free key (100 req/day): https://newsapi.org/
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from newsapi import NewsApiClient

from config import get_config
from data.schemas import NewsArticle

logger = logging.getLogger(__name__)

ENERGY_QUERIES = [
    "crude oil price",
    "natural gas price",
    "OPEC oil production",
    "energy market outlook",
    "oil inventory EIA",
    "LNG prices",
    "renewable energy investment",
]


class NewsClient:
    def __init__(self):
        api_key = get_config().NEWSAPI_KEY
        self._client = NewsApiClient(api_key=api_key) if api_key else None
        if not api_key:
            logger.warning("NEWSAPI_KEY not set — news data unavailable")

    def get_energy_headlines(
        self,
        query: str = "energy oil natural gas",
        days: int = 3,
        page_size: int = 20,
        language: str = "en",
    ) -> list[NewsArticle]:
        if not self._client:
            return []
        from_date = (date.today() - timedelta(days=days)).isoformat()
        try:
            response = self._client.get_everything(
                q=query,
                from_param=from_date,
                language=language,
                sort_by="publishedAt",
                page_size=page_size,
            )
            articles = []
            for art in response.get("articles", []):
                try:
                    from datetime import datetime
                    articles.append(NewsArticle(
                        title=art["title"] or "",
                        description=art.get("description"),
                        url=art["url"],
                        published_at=datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00")),
                        source=art["source"]["name"],
                    ))
                except (KeyError, ValueError):
                    continue
            logger.info("NewsAPI: fetched %d articles for '%s'", len(articles), query)
            return articles
        except Exception as e:
            logger.warning("NewsAPI error: %s", e)
            return []

    def get_multi_query_headlines(self, days: int = 2) -> list[NewsArticle]:
        """Fetch headlines across all energy-focused queries, deduplicated by URL."""
        seen_urls: set[str] = set()
        all_articles: list[NewsArticle] = []
        for query in ENERGY_QUERIES[:3]:  # respect free tier limits
            for art in self.get_energy_headlines(query=query, days=days, page_size=10):
                if art.url not in seen_urls:
                    seen_urls.add(art.url)
                    all_articles.append(art)
        logger.info("NewsAPI total unique articles: %d", len(all_articles))
        return all_articles
