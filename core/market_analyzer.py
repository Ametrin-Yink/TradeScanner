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

    def analyze_for_regime(self, spy_df, vix_df) -> Dict:
        """
        Analyze market using Tavily + AI to determine regime.

        Args:
            spy_df: SPY price DataFrame with 'close' column
            vix_df: VIX price DataFrame with 'close' column

        Returns:
            Dict with:
            - sentiment: one of 6 regimes
            - confidence: 0-100
            - reasoning: explanation
            - tavily_results: raw search data
        """
        import pandas as pd

        # Get VIX level for context
        vix_current = vix_df['close'].iloc[-1] if vix_df is not None and not vix_df.empty else 20.0

        # Get SPY technical context
        if spy_df is not None and len(spy_df) >= 200:
            close = spy_df['close']
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            spy_above_ema200 = current_price > ema200
            ema50_above_200 = ema50 > ema200
        else:
            spy_above_ema200 = True
            ema50_above_200 = True
            current_price = 0
            ema50 = 0
            ema200 = 0

        # Search Tavily for market news
        search_queries = [
            "US stock market today sentiment analysis trend",
            "S&P 500 SPY technical outlook support resistance",
            "VIX volatility fear index market stress"
        ]

        all_results = []
        for query in search_queries:
            results = self.tavily_search(query, max_results=3)
            all_results.extend(results)

        # Compile news summary
        news_summary = "\n".join([
            f"- {r.get('title', '')}: {r.get('content', '')[:150]}..."
            for r in all_results[:8]
        ])

        # Call AI for regime classification
        regime = self._call_ai_for_regime(news_summary, vix_current, spy_above_ema200, ema50_above_200)

        return {
            'sentiment': regime.get('regime', 'neutral'),
            'confidence': regime.get('confidence', 50),
            'reasoning': regime.get('reasoning', ''),
            'tavily_results': all_results
        }

    def _call_ai_for_regime(self, news_summary: str, vix: float,
                            spy_above_ema200: bool, ema50_above_200: bool) -> Dict:
        """Call AI to classify regime from technical + news data."""

        if not self.dashscope_api_key:
            logger.warning("DashScope API key not configured")
            return {'regime': 'neutral', 'confidence': 50, 'reasoning': 'API not configured'}

        try:
            url = f"{self.dashscope_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json"
            }

            technical_context = f"""
VIX Level: {vix:.1f} ({'Extreme fear' if vix > 30 else 'Elevated' if vix > 20 else 'Normal'})
SPY above EMA200: {spy_above_ema200}
EMA50 above EMA200: {ema50_above_200}
"""

            prompt = f"""Analyze the current US stock market regime based on technical indicators and news.

TECHNICAL CONTEXT:
{technical_context}

MARKET NEWS SUMMARY:
{news_summary}

Select ONE regime from these 6 options:
1. bull_strong: Strong uptrend, VIX low (<20), SPY above EMA50>EMA200
2. bull_moderate: Moderate uptrend, VIX normal (20-25), positive momentum
3. neutral: Mixed signals, consolidation, no clear trend
4. bear_moderate: Moderate downtrend, VIX elevated (25-30), SPY below EMA50
5. bear_strong: Strong downtrend, SPY below EMA200, distribution patterns
6. extreme_vix: Fear/volatility spike, VIX >30, panic selling (OVERRIDES others)

Return ONLY JSON:
{{
    "regime": "one_of_six_above",
    "confidence": 0-100,
    "reasoning": "brief explanation combining technical and news"
}}"""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a market regime classifier. Return valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }

            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content']

            # Extract JSON - try multiple strategies for robustness
            import re
            result = None

            # Strategy 1: Look for JSON between braces (non-greedy, handle nested braces)
            # Match { followed by any content (non-greedy) followed by }
            json_match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', content, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            # Strategy 2: If strategy 1 failed, try to find JSON with balanced braces
            if result is None:
                # Find all potential JSON objects by counting braces
                start_idx = content.find('{')
                if start_idx >= 0:
                    brace_count = 0
                    for i, char in enumerate(content[start_idx:], start_idx):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                try:
                                    result = json.loads(content[start_idx:i+1])
                                    break
                                except json.JSONDecodeError:
                                    pass

            # Strategy 3: Try to parse entire content as JSON
            if result is None:
                try:
                    result = json.loads(content.strip())
                except json.JSONDecodeError:
                    pass

            # Strategy 4: Extract JSON from code blocks
            if result is None:
                code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if code_block_match:
                    try:
                        result = json.loads(code_block_match.group(1))
                    except json.JSONDecodeError:
                        pass

            # Fallback: return default regime
            if result is None:
                logger.warning(f"Failed to extract JSON from AI response: {content[:200]}...")
                return {'regime': 'neutral', 'confidence': 50, 'reasoning': 'Failed to parse AI response'}

            # Validate regime
            valid = ['bull_strong', 'bull_moderate', 'neutral',
                    'bear_moderate', 'bear_strong', 'extreme_vix']
            if result.get('regime') not in valid:
                result['regime'] = 'neutral'

            return result

        except Exception as e:
            logger.error(f"AI regime analysis failed: {e}")
            return {'regime': 'neutral', 'confidence': 50, 'reasoning': f'Error: {e}'}

    def analyze_sentiment(self) -> Dict:
        """
        Analyze overall market sentiment.
        DEPRECATED: Use analyze_for_regime instead.

        Returns:
            Dict with sentiment analysis results
        """
        logger.warning("analyze_sentiment is deprecated, use analyze_for_regime")
        return self.analyze_for_regime(None, None)

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

    def get_regime_allocation(self, regime: str) -> Dict[str, int]:
        """
        Get allocation from regime table (replaces AI allocation).

        Args:
            regime: Market regime from MarketRegimeDetector

        Returns:
            Dict mapping strategy names to slot counts
        """
        from core.market_regime import MarketRegimeDetector
        detector = MarketRegimeDetector()
        return detector.get_allocation(regime)
