"""AI opportunity analyzer - deep analysis for top 10."""
import logging
import json
import time
from typing import Dict, Optional
from dataclasses import dataclass, field

import requests
import pandas as pd

from core.screener import StrategyMatch
from core.fetcher import DataFetcher
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class AnalyzedOpportunity:
    """Analyzed opportunity with AI-generated insights."""
    symbol: str
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: int
    match_reasons: list = field(default_factory=list)

    # AI-generated fields
    ai_reasoning: str = ""
    catalyst: str = ""
    risk_factors: list = field(default_factory=list)
    position_size: str = "normal"  # small, normal, large
    time_frame: str = "short-term"  # short-term, swing, long-term
    alternative_scenario: str = ""
    technical_snapshot: dict = field(default_factory=dict)


class OpportunityAnalyzer:
    """Deep analysis of opportunities using AI and market data."""

    def __init__(self, fetcher: Optional[DataFetcher] = None):
        """Initialize analyzer."""
        self.fetcher = fetcher or DataFetcher()
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')
        self.tavily_api_key = settings.get_secret('tavily.api_key')
        self.dashscope_base = settings.get_secret('dashscope.api_base') or settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get_secret('dashscope.model') or settings.get('ai', {}).get('model', 'qwen-max')

    def analyze_opportunity(
        self,
        match: StrategyMatch,
        market_sentiment: str = 'neutral',
        cached_data: Optional[pd.DataFrame] = None
    ) -> AnalyzedOpportunity:
        """
        Deep analysis of a single opportunity.

        Args:
            match: Strategy match from screener
            market_sentiment: Current market sentiment
            cached_data: Optional cached DataFrame to avoid re-fetching

        Returns:
            AnalyzedOpportunity with AI insights
        """
        # Fetch additional market data (use cached if available)
        symbol = match.symbol
        if cached_data is not None and len(cached_data) >= 20:
            df = cached_data
            logger.debug(f"Using cached data for {symbol} analysis")
        else:
            df = self.fetcher.fetch_stock_data(symbol, period="3mo", interval="1d")

        # Tavily search for symbol news
        news = self._search_symbol_news(symbol)

        # AI analysis
        ai_analysis = self._call_ai_analysis(match, df, news, market_sentiment)

        # Ensure ai_analysis is a dict
        if not isinstance(ai_analysis, dict):
            logger.warning(f"AI analysis returned non-dict type for {match.symbol}, using fallback")
            ai_analysis = self._fallback_analysis(match)

        return AnalyzedOpportunity(
            symbol=match.symbol,
            strategy=match.strategy,
            entry_price=match.entry_price,
            stop_loss=match.stop_loss,
            take_profit=match.take_profit,
            confidence=match.confidence,
            match_reasons=match.match_reasons,
            ai_reasoning=ai_analysis.get('reasoning', ''),
            catalyst=ai_analysis.get('catalyst', ''),
            risk_factors=ai_analysis.get('risk_factors', []) if isinstance(ai_analysis.get('risk_factors'), list) else [],
            position_size=ai_analysis.get('position_size', 'normal') if isinstance(ai_analysis.get('position_size'), str) else 'normal',
            time_frame=ai_analysis.get('time_frame', 'short-term') if isinstance(ai_analysis.get('time_frame'), str) else 'short-term',
            alternative_scenario=ai_analysis.get('alternative_scenario', '') if isinstance(ai_analysis.get('alternative_scenario'), str) else '',
            technical_snapshot=match.technical_snapshot if hasattr(match, 'technical_snapshot') else {}
        )

    def analyze_all(
        self,
        candidates: list[StrategyMatch],
        market_sentiment: str = 'neutral'
    ) -> list[AnalyzedOpportunity]:
        """
        Analyze all top candidates.

        Args:
            candidates: List of StrategyMatch
            market_sentiment: Current market sentiment

        Returns:
            List of AnalyzedOpportunity
        """
        analyzed = []

        for i, match in enumerate(candidates):
            try:
                logger.info(f"Analyzing {match.symbol} ({i+1}/{len(candidates)})...")
                analysis = self.analyze_opportunity(match, market_sentiment)
                analyzed.append(analysis)
            except Exception as e:
                logger.error(f"Failed to analyze {match.symbol}: {e}")
                # Create basic analysis without AI
                analyzed.append(AnalyzedOpportunity(
                    symbol=match.symbol,
                    strategy=match.strategy,
                    entry_price=match.entry_price,
                    stop_loss=match.stop_loss,
                    take_profit=match.take_profit,
                    confidence=match.confidence,
                    match_reasons=match.match_reasons
                ))

        return analyzed

    def _search_symbol_news(self, symbol: str) -> list:
        """Search for symbol-specific news."""
        if not self.tavily_api_key:
            return []

        try:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json"}
            payload = {
                "api_key": self.tavily_api_key,
                "query": f"{symbol} stock news analysis today",
                "max_results": 3,
                "search_depth": "basic"
            }

            response = requests.post(url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()

            data = response.json()
            return [r.get('content', '')[:300] for r in data.get('results', [])]

        except Exception as e:
            logger.warning(f"News search failed for {symbol}: {e}")
            return []

    def _call_ai_with_retry(
        self,
        url: str,
        headers: dict,
        payload: dict,
        max_retries: int = 2
    ) -> Optional[dict]:
        """Call AI API with retry logic."""
        for attempt in range(max_retries + 1):
            try:
                timeout = 60 + (attempt * 30)  # Increase timeout on retry
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.Timeout:
                if attempt < max_retries:
                    logger.warning(f"AI call timeout, retrying ({attempt + 1}/{max_retries})...")
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
            except Exception:
                if attempt < max_retries:
                    logger.warning(f"AI call failed, retrying ({attempt + 1}/{max_retries})...")
                    time.sleep(2 ** attempt)
                else:
                    raise
        return None

    def _call_ai_analysis(
        self,
        match: StrategyMatch,
        df: Optional[pd.DataFrame],
        news: list,
        market_sentiment: str
    ) -> dict:
        """Call AI for deep analysis."""
        if not self.dashscope_api_key:
            return self._fallback_analysis(match)

        try:
            # Prepare price data summary
            price_summary = ""
            if df is not None and len(df) > 0:
                recent = df.tail(20)
                price_summary = f"""
Recent Price Data (20 days):
- Current: ${df['close'].iloc[-1]:.2f}
- 20d High: ${recent['high'].max():.2f}
- 20d Low: ${recent['low'].min():.2f}
- 20d Volume Avg: {int(recent['volume'].mean()):,}
"""

            news_text = "\n".join([f"- {n[:200]}" for n in news]) if news else "No recent news available"

            url = f"{self.dashscope_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json"
            }

            prompt = f"""Analyze this trading opportunity:

Symbol: {match.symbol}
Strategy: {match.strategy}
Market Sentiment: {market_sentiment}

Trade Setup:
- Entry: ${match.entry_price:.2f}
- Stop Loss: ${match.stop_loss:.2f}
- Target: ${match.take_profit:.2f}
- Risk/Reward: {(match.take_profit - match.entry_price) / (match.entry_price - match.stop_loss):.1f}x

Technical Reasons:
{chr(10).join(f"- {r}" for r in match.match_reasons)}

{price_summary}

Recent News:
{news_text}

Provide analysis in JSON format:
{{
    "reasoning": "detailed explanation of why this trade works",
    "catalyst": "key catalyst that could drive price movement",
    "risk_factors": ["risk1", "risk2", "risk3"],
    "position_size": "small|normal|large",
    "time_frame": "short-term|swing|long-term",
    "alternative_scenario": "what could invalidate this trade"
}}"""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an expert technical analyst. Provide concise, actionable trading analysis. Return valid JSON only, no markdown."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4
            }

            # Call AI with retry logic
            data = self._call_ai_with_retry(url, headers, payload, max_retries=2)
            if data is None:
                raise Exception("AI call failed after retries")

            content = data['choices'][0]['message']['content']

            # Extract JSON from response
            import re
            try:
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AI response as JSON: {e}")
                result = {}

            logger.info(f"AI analysis complete for {match.symbol}")
            return result

        except Exception as e:
            logger.error(f"AI analysis failed for {match.symbol}: {e}")
            return self._fallback_analysis(match)

    def _fallback_analysis(self, match: StrategyMatch) -> dict:
        """Generate fallback analysis when AI is unavailable."""
        return {
            "reasoning": f"Technical setup shows {match.strategy} pattern with {match.confidence}% confidence.",
            "catalyst": "Technical breakout/pullback pattern",
            "risk_factors": ["Market risk", "Strategy-specific risk", "Volatility risk"],
            "position_size": "normal",
            "time_frame": "swing",
            "alternative_scenario": "Stop loss hit, exit position"
        }

    def analyze_top_10_deep(
        self,
        scored_candidates: list,
        regime: str
    ) -> list:
        """
        Deep analysis for top 10 candidates by AI score.
        Uses Tavily search + AI for detailed technical + news analysis.

        Args:
            scored_candidates: List of ScoredCandidate (top 30)
            regime: Current market regime

        Returns:
            Top 10 with detailed analysis
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4: Deep Analysis (Top 10)")
        logger.info("=" * 60)

        # Take top 10 by AI confidence
        top_10 = sorted(scored_candidates, key=lambda x: x.confidence, reverse=True)[:10]
        logger.info(f"Selected top 10 for deep analysis")

        # Analyze in parallel
        analyzed = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._deep_analyze_single, c, regime): c
                for c in top_10
            }

            for future in as_completed(futures):
                result = future.result()
                if result:
                    analyzed.append(result)

        # Sort by confidence
        analyzed.sort(key=lambda x: x.confidence, reverse=True)

        return analyzed

    def _deep_analyze_single(self, candidate, regime):
        """Deep analysis for single candidate with Tavily + AI."""
        try:
            # Search Tavily for stock news
            news_results = self._tavily_search_stock(candidate.symbol)

            # Perform AI deep analysis
            analysis = self._ai_deep_analysis(candidate, news_results, regime)

            # Update candidate with deep analysis
            candidate.deep_analysis = analysis
            candidate.news_summary = news_results

            return candidate
        except Exception as e:
            logger.error(f"Deep analysis failed for {candidate.symbol}: {e}")
            return candidate

    def _tavily_search_stock(self, symbol: str) -> list:
        """Search Tavily for stock-specific news."""
        try:
            from core.market_analyzer import MarketAnalyzer
            ma = MarketAnalyzer()
            queries = [
                f"{symbol} stock news today analysis",
                f"{symbol} earnings outlook forecast"
            ]
            results = []
            for q in queries:
                results.extend(ma.tavily_search(q, max_results=2))
            return results
        except Exception as e:
            logger.error(f"Tavily search failed for {symbol}: {e}")
            return []

    def _ai_deep_analysis(self, candidate, news_results, regime):
        """Call AI for detailed analysis with Tavily news context."""
        news_summary = "\n".join([
            f"- {r.get('title', '')}: {r.get('content', '')[:200]}"
            for r in news_results[:5]
        ])

        if not self.dashscope_api_key:
            return {
                'technical_outlook': f"Entry: {candidate.entry_price}, Stop: {candidate.stop_loss}",
                'news_sentiment': 'Neutral',
                'key_catalysts': news_results[:2],
                'risk_level': 'Medium'
            }

        try:
            url = f"{self.dashscope_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json"
            }

            prompt = f"""Deep analysis for {candidate.symbol} ({candidate.strategy}):

Entry: {candidate.entry_price}, Stop: {candidate.stop_loss}, Target: {candidate.take_profit}
Market Regime: {regime}
AI Confidence: {candidate.confidence}%

Technical Reasons:
{chr(10).join(f"- {r}" for r in getattr(candidate, 'match_reasons', [])[:5])}

Recent News:
{news_summary or "No recent news available"}

Return JSON:
{{
    "technical_outlook": "Detailed technical outlook",
    "news_sentiment": "Positive|Neutral|Negative",
    "key_catalysts": ["catalyst1", "catalyst2"],
    "risk_level": "Low|Medium|High",
    "detailed_reasoning": "Detailed reasoning for this trade"
}}"""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Expert technical analyst. Return valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            }

            data = self._call_ai_with_retry(url, headers, payload, max_retries=2)
            if data:
                content = data['choices'][0]['message']['content']
                json_match = __import__('re').search(r'\{[^{}]*\}', content, __import__('re').DOTALL)
                if json_match:
                    return json.loads(json_match.group())

            # Fallback
            return {
                'technical_outlook': f"Entry: {candidate.entry_price}, Stop: {candidate.stop_loss}",
                'news_sentiment': 'Neutral',
                'key_catalysts': news_results[:2],
                'risk_level': 'Medium'
            }
        except Exception as e:
            logger.error(f"AI deep analysis failed for {candidate.symbol}: {e}")
            return {
                'technical_outlook': f"Entry: {candidate.entry_price}, Stop: {candidate.stop_loss}",
                'news_sentiment': 'Neutral',
                'key_catalysts': news_results[:2],
                'risk_level': 'Medium'
            }
