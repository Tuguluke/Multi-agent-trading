"""Sentiment Agent — news and Reddit-based energy market sentiment."""

from __future__ import annotations

import logging

from agents.base_agent import BaseAgent
from data.schemas import AgentSignal, SignalDirection, SignalStrength

logger = logging.getLogger(__name__)


class SentimentAgent(BaseAgent):
    def __init__(self, llm_router, db_client=None, cw_client=None):
        super().__init__("SentimentAgent", llm_router, db_client, cw_client)
        from data.news_client import NewsClient
        from data.reddit_client import RedditClient
        self._news = NewsClient()
        self._reddit = RedditClient()

    def run(self, context: dict) -> AgentSignal:
        # Fetch news headlines
        articles = self._news.get_multi_query_headlines(days=2)
        headlines = [a.title for a in articles[:15]]

        # Reddit sentiment summary
        reddit_summary = self._reddit.get_sentiment_summary(limit=30)
        context["reddit_sentiment"] = reddit_summary

        headlines_str = "\n".join(f"  - {h}" for h in headlines) or "  (no headlines available)"
        top_tickers = ", ".join(f"{t}({c})" for t, c in reddit_summary.get("top_tickers", []))

        prompt = f"""Analyze sentiment for the energy market based on recent news and social media:

RECENT ENERGY NEWS HEADLINES:
{headlines_str}

REDDIT ENERGY SENTIMENT (last 24h):
  Bullish posts: {reddit_summary.get('bullish_count', 0)} ({reddit_summary.get('bullish_pct', 0):.1f}%)
  Bearish posts: {reddit_summary.get('bearish_count', 0)} ({reddit_summary.get('bearish_pct', 0):.1f}%)
  Neutral posts: {reddit_summary.get('neutral_count', 0)}
  Most mentioned tickers: {top_tickers or 'none'}
  Total posts analyzed: {reddit_summary.get('total_posts', 0)}

Based on news headlines and social sentiment:
1. Overall sentiment direction (BULLISH/BEARISH/NEUTRAL)
2. Signal strength (STRONG/MODERATE/WEAK)
3. Confidence (0-100%)
4. Key sentiment themes (supply/demand news, geopolitical, policy)
5. Any extreme sentiment (fear/greed) indicators

Format:
DIRECTION: [direction]
STRENGTH: [strength]
CONFIDENCE: [X]%
ASSET: XLE
REASONING: [your sentiment analysis]"""

        response = self.call_llm(prompt)

        # Supplement LLM with Reddit data for robustness
        bullish_pct = reddit_summary.get("bullish_pct", 50)
        bearish_pct = reddit_summary.get("bearish_pct", 50)
        reddit_direction = (
            SignalDirection.BULLISH if bullish_pct > bearish_pct + 15
            else SignalDirection.BEARISH if bearish_pct > bullish_pct + 15
            else SignalDirection.NEUTRAL
        )

        direction = self._parse_direction(response)
        if direction == SignalDirection.NEUTRAL:
            direction = reddit_direction

        strength = self._parse_strength(response)
        confidence = self._parse_confidence(response)

        context["news_headlines"] = headlines
        context["sentiment_direction"] = direction.value

        signal = AgentSignal(
            agent_name=self.name,
            asset="XLE",
            direction=direction,
            strength=strength,
            confidence=confidence,
            reasoning=response,
            raw_data={"headlines": headlines[:5], "reddit": reddit_summary},
        )
        self.log_signal(signal)
        return signal
