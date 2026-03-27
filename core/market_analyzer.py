"""Market environment analyzer using Tavily search and AI."""
import logging
import json
from typing import Dict, Optional
from datetime import datetime

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """Analyze market sentiment using news search and AI."""

    def __init__(self):
        """Initialize with API keys from settings."""
        self.tavily_api_key = settings.get_secret('tavily.api_key')
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')
        self.dashscope_base = settings.get_secret('dashscope.api_base') or settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get_secret('dashscope.model') or settings.get('ai', {}).get('model', 'qwen-max')

    def tavily_search(self, query: str, max_results: int = 5) -> list:
        """
        Search for market news using Tavily API.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of search results
        """
        if not self.tavily_api_key:
            logger.warning("Tavily API key not configured")
            return []

        try:
            url = "https://api.tavily.com/search"
            headers = {
                "Content-Type": "application/json"
            }
            payload = {
                "api_key": self.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": True
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            results = data.get('results', [])

            logger.info(f"Tavily search returned {len(results)} results for: {query}")
            return results

        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return []

    def analyze_sentiment(self) -> Dict:
        """
        Analyze overall market sentiment.

        Returns:
            Dict with sentiment analysis results
        """
        # Search for market news
        search_queries = [
            "US stock market today sentiment analysis",
            "S&P 500 market outlook news",
            "Federal Reserve interest rates impact stocks"
        ]

        all_results = []
        for query in search_queries:
            results = self.tavily_search(query, max_results=3)
            all_results.extend(results)

        # Compile news summary
        news_summary = "\n".join([
            f"- {r.get('title', '')}: {r.get('content', '')[:200]}..."
            for r in all_results[:10]
        ])

        # Call AI for sentiment analysis
        sentiment = self._call_ai_for_sentiment(news_summary)

        return {
            'sentiment': sentiment.get('sentiment', 'neutral'),
            'confidence': sentiment.get('confidence', 50),
            'reasoning': sentiment.get('reasoning', ''),
            'key_factors': sentiment.get('key_factors', []),
            'timestamp': datetime.now().isoformat(),
            'news_count': len(all_results)
        }

    def _call_ai_for_sentiment(self, news_summary: str) -> Dict:
        """
        Call DashScope AI to analyze market sentiment.

        Args:
            news_summary: Compiled news summary

        Returns:
            Dict with sentiment analysis
        """
        if not self.dashscope_api_key:
            logger.warning("DashScope API key not configured, using neutral sentiment")
            return {
                'sentiment': 'neutral',
                'confidence': 50,
                'reasoning': 'API not configured',
                'key_factors': []
            }

        try:
            url = f"{self.dashscope_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json"
            }

            prompt = f"""Analyze the current US stock market sentiment based on the following news summary.

News Summary:
{news_summary}

Provide your analysis in the following JSON format:
{{
    "sentiment": "bullish" | "bearish" | "neutral" | "watch",
    "confidence": 0-100,
    "reasoning": "brief explanation",
    "key_factors": ["factor1", "factor2", "factor3"]
}}

Sentiment definitions:
- bullish: Strong positive outlook, good for long positions
- bearish: Negative outlook, consider shorts or staying in cash
- neutral: Mixed signals, be selective
- watch: Uncertain conditions, wait for clarity"""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a market analyst specializing in sentiment analysis."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content']

            # Parse JSON response
            result = json.loads(content)
            logger.info(f"AI sentiment analysis: {result.get('sentiment')} (confidence: {result.get('confidence')})")
            return result

        except Exception as e:
            logger.error(f"AI sentiment analysis failed: {e}")
            return {
                'sentiment': 'neutral',
                'confidence': 50,
                'reasoning': f'Error: {str(e)}',
                'key_factors': []
            }

    def get_market_summary(self) -> str:
        """Get human-readable market summary."""
        analysis = self.analyze_sentiment()

        sentiment_emoji = {
            'bullish': '🟢',
            'bearish': '🔴',
            'neutral': '🟡',
            'watch': '⚪'
        }

        emoji = sentiment_emoji.get(analysis['sentiment'], '⚪')

        summary = f"""{emoji} Market Sentiment: {analysis['sentiment'].upper()}
Confidence: {analysis['confidence']}/100

Key Factors:
"""
        for factor in analysis.get('key_factors', []):
            summary += f"• {factor}\n"

        summary += f"\nReasoning: {analysis.get('reasoning', 'N/A')[:200]}"

        return summary
