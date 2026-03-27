"""AI candidate selector - select top 10 from 40 candidates."""
import logging
import json
from typing import List, Dict, Optional
from dataclasses import asdict

import requests

from core.screener import StrategyMatch
from config.settings import settings

logger = logging.getLogger(__name__)


class CandidateSelector:
    """Select top 10 opportunities from 40 candidates using AI."""

    # Strategy weights based on market sentiment
    STRATEGY_WEIGHTS = {
        'bullish': {
            'EP': 1.0,
            'Momentum': 1.3,
            'Shoryuken': 1.2,
            'Pullbacks': 1.2,
            'U&R': 1.1,
            'RangeSupport': 1.1,
            'DTSS': 0.5,
            'Parabolic': 0.3
        },
        'bearish': {
            'EP': 0.5,
            'Momentum': 0.5,
            'Shoryuken': 0.8,
            'Pullbacks': 0.6,
            'U&R': 0.8,
            'RangeSupport': 0.7,
            'DTSS': 1.3,
            'Parabolic': 1.3
        },
        'neutral': {
            'EP': 1.0,
            'Momentum': 1.0,
            'Shoryuken': 1.0,
            'Pullbacks': 1.0,
            'U&R': 1.0,
            'RangeSupport': 1.0,
            'DTSS': 0.8,
            'Parabolic': 0.8
        },
        'watch': {
            'EP': 0.8,
            'Momentum': 0.8,
            'Shoryuken': 0.9,
            'Pullbacks': 0.9,
            'U&R': 1.0,
            'RangeSupport': 1.0,
            'DTSS': 0.7,
            'Parabolic': 0.7
        }
    }

    def __init__(self):
        """Initialize with API configuration."""
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')
        self.dashscope_base = settings.get_secret('dashscope.api_base') or settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get_secret('dashscope.model') or settings.get('ai', {}).get('model', 'qwen-max')

    def select_top_10(
        self,
        candidates: List[StrategyMatch],
        market_sentiment: str = 'neutral'
    ) -> List[StrategyMatch]:
        """
        Select top 10 candidates using AI.

        Args:
            candidates: List of 40 candidates from screener
            market_sentiment: 'bullish', 'bearish', 'neutral', or 'watch'

        Returns:
            List of top 10 StrategyMatch
        """
        if len(candidates) <= 10:
            logger.info(f"Only {len(candidates)} candidates, returning all")
            return candidates

        # Apply strategy weights
        weights = self.STRATEGY_WEIGHTS.get(market_sentiment, self.STRATEGY_WEIGHTS['neutral'])

        weighted_candidates = []
        for candidate in candidates:
            weight = weights.get(candidate.strategy, 1.0)
            weighted_candidates.append({
                'candidate': candidate,
                'weighted_score': candidate.confidence * weight
            })

        # Sort by weighted score
        weighted_candidates.sort(key=lambda x: x['weighted_score'], reverse=True)

        # Take top 20 for AI analysis
        top_20 = weighted_candidates[:20]

        # Use AI to select final 10
        ai_selected = self._ai_select(top_20, market_sentiment)

        if ai_selected:
            return ai_selected

        # Fallback to weighted ranking
        return [wc['candidate'] for wc in weighted_candidates[:10]]

    def _ai_select(
        self,
        candidates: List[Dict],
        market_sentiment: str
    ) -> Optional[List[StrategyMatch]]:
        """
        Use AI to select top 10 from top 20 candidates.

        Args:
            candidates: Top 20 weighted candidates
            market_sentiment: Current market sentiment

        Returns:
            List of 10 selected candidates or None if AI fails
        """
        if not self.dashscope_api_key:
            logger.warning("DashScope API key not configured")
            return None

        try:
            # Prepare candidate data for AI
            candidates_data = []
            for i, wc in enumerate(candidates):
                c = wc['candidate']
                candidates_data.append({
                    'rank': i + 1,
                    'symbol': c.symbol,
                    'strategy': c.strategy,
                    'confidence': c.confidence,
                    'entry': c.entry_price,
                    'stop': c.stop_loss,
                    'target': c.take_profit,
                    'reasons': c.match_reasons[:3],
                    'snapshot': {k: v for k, v in c.technical_snapshot.items()
                                if isinstance(v, (str, int, float, bool))}
                })

            url = f"{self.dashscope_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.dashscope_api_key}",
                "Content-Type": "application/json"
            }

            prompt = f"""Given the current market sentiment is "{market_sentiment}", select the TOP 10 trading opportunities from the following 20 candidates.

Selection Criteria:
1. Strategy alignment with {market_sentiment} market conditions
2. Risk/reward ratio (target - entry) / (entry - stop)
3. Technical setup quality
4. Volume confirmation
5. Avoid over-concentration in single strategy (max 3 per strategy)

Candidates (JSON format):
{json.dumps(candidates_data, indent=2)}

Return your selection as JSON:
{{
    "selected": [
        {{"symbol": "AAPL", "strategy": "Momentum", "rank": 1, "reasoning": "strong breakout setup"}},
        ... (10 total)
    ],
    "excluded": [
        {{"symbol": "XYZ", "strategy": "EP", "reason": "earnings risk too high"}},
        ... (10 total)
    ]
}}"""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an expert stock trader. Select the best opportunities based on technical analysis and market conditions."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content']
            result = json.loads(content)

            # Map AI selection back to StrategyMatch objects
            selected_symbols = [s['symbol'] for s in result.get('selected', [])]
            symbol_to_candidate = {wc['candidate'].symbol: wc['candidate'] for wc in candidates}

            selected = []
            for sym in selected_symbols[:10]:
                if sym in symbol_to_candidate:
                    selected.append(symbol_to_candidate[sym])

            if len(selected) >= 5:  # Accept if we got at least 5
                logger.info(f"AI selected {len(selected)} candidates")
                return selected[:10]

        except Exception as e:
            logger.error(f"AI selection failed: {e}")

        return None

    def get_selection_summary(
        self,
        selected: List[StrategyMatch],
        market_sentiment: str
    ) -> str:
        """Get human-readable selection summary."""
        summary = f"Top 10 Opportunities ({market_sentiment.upper()} Market)\n"
        summary += "=" * 50 + "\n\n"

        strategy_counts = {}
        for match in selected:
            strategy_counts[match.strategy] = strategy_counts.get(match.strategy, 0) + 1

        for i, match in enumerate(selected, 1):
            rrr = (match.take_profit - match.entry_price) / (match.entry_price - match.stop_loss) if match.entry_price != match.stop_loss else 0

            summary += f"{i}. {match.symbol} ({match.strategy})\n"
            summary += f"   Entry: ${match.entry_price:.2f} | Stop: ${match.stop_loss:.2f} | Target: ${match.take_profit:.2f}\n"
            summary += f"   R/R: {rrr:.1f}x | Confidence: {match.confidence}%\n"
            summary += f"   Why: {', '.join(match.match_reasons[:2])}\n\n"

        summary += f"\nStrategy Distribution: {strategy_counts}"

        return summary
