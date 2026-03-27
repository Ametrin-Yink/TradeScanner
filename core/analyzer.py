"""AI opportunity analyzer - deep analysis for top 10."""
import logging
import json
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


class OpportunityAnalyzer:
    """Deep analysis of opportunities using AI and market data."""

    def __init__(self, fetcher: Optional[DataFetcher] = None):
        """Initialize analyzer."""
        self.fetcher = fetcher or DataFetcher()
        self.dashscope_api_key = settings.get_secret('dashscope_api_key')
        self.tavily_api_key = settings.get_secret('tavily_api_key')
        self.dashscope_base = settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get('ai', {}).get('model', 'qwen-max')

    def analyze_opportunity(
        self,
        match: StrategyMatch,
        market_sentiment: str = 'neutral'
    ) -> AnalyzedOpportunity:
        """
        Deep analysis of a single opportunity.

        Args:
            match: Strategy match from screener
            market_sentiment: Current market sentiment

        Returns:
            AnalyzedOpportunity with AI insights
        """
        # Fetch additional market data
        symbol = match.symbol
        df = self.fetcher.fetch_stock_data(symbol, period="3mo", interval="1d")

        # Tavily search for symbol news
        news = self._search_symbol_news(symbol)

        # AI analysis
        ai_analysis = self._call_ai_analysis(match, df, news, market_sentiment)

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
            risk_factors=ai_analysis.get('risk_factors', []),
            position_size=ai_analysis.get('position_size', 'normal'),
            time_frame=ai_analysis.get('time_frame', 'short-term'),
            alternative_scenario=ai_analysis.get('alternative_scenario', '')
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
                    {"role": "system", "content": "You are an expert technical analyst. Provide concise, actionable trading analysis."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content']
            result = json.loads(content)

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
