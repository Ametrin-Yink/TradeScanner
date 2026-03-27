"""AI-powered confidence scoring system for trade opportunities."""
import logging
import json
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

import requests

from core.screener import StrategyMatch
from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ScoredCandidate:
    """Candidate with AI-calculated confidence."""
    symbol: str
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: int
    reasoning: str
    key_factors: List[str]
    risk_factors: List[str]
    match_reasons: List[str]
    technical_snapshot: Dict


class AIConfidenceScorer:
    """Calculate confidence scores using AI analysis."""

    # Strategy descriptions for AI context
    STRATEGY_DESCRIPTIONS = {
        'EP': 'Earnings Play - Trade around earnings announcement, high volatility expected',
        'Momentum': 'Momentum Breakout - Price breaking above resistance with volume expansion',
        'Shoryuken': 'Pullback to EMA - Price declining toward EMA8/21 support for bounce entry',
        'Pullbacks': 'Buying Pullbacks - 1-5 days pullback from 20-day high, above EMA50',
        'U&R': 'Upthrust & Rebound - Price within 1% of support with volume contraction',
        'RangeSupport': 'Range Bottom Support - Uptrend + consolidation range bottom',
        'DTSS': 'Distribution Top Sell - Within 3% of 60-day high showing weakness',
        'Parabolic': 'Parabolic Short - Extended price action, RSI>80, potential reversal'
    }

    # Market sentiment guidance for AI
    SENTIMENT_GUIDANCE = {
        'bullish': {
            'favorable': ['Momentum', 'Shoryuken', 'Pullbacks', 'EP', 'RangeSupport'],
            'unfavorable': ['DTSS', 'Parabolic'],
            'guidance': 'In bullish markets, favor long strategies. Short strategies (DTSS, Parabolic) should have exceptional setups to score high.'
        },
        'bearish': {
            'favorable': ['DTSS', 'Parabolic', 'Shoryuken', 'U&R'],
            'unfavorable': ['Momentum', 'EP'],
            'guidance': 'In bearish markets, favor short strategies (DTSS, Parabolic) and defensive long setups. Momentum breakouts are riskier.'
        },
        'neutral': {
            'favorable': ['RangeSupport', 'U&R', 'Shoryuken', 'Pullbacks'],
            'unfavorable': [],
            'guidance': 'In neutral markets, favor range-bound and mean-reversion strategies. Require stronger confirmation for directional trades.'
        },
        'watch': {
            'favorable': ['U&R', 'RangeSupport'],
            'unfavorable': ['EP', 'Momentum'],
            'guidance': 'In uncertain markets, prioritize capital preservation. Only highest quality setups should score above 70.'
        }
    }

    def __init__(self):
        """Initialize with API configuration."""
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')
        self.dashscope_base = settings.get_secret('dashscope.api_base') or settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get_secret('dashscope.model') or settings.get('ai', {}).get('model', 'qwen-max')

    def score_candidates(
        self,
        candidates: List[StrategyMatch],
        market_sentiment: str = 'neutral'
    ) -> List[ScoredCandidate]:
        """
        Score all candidates using AI analysis.

        Args:
            candidates: List of strategy matches from screener
            market_sentiment: 'bullish', 'bearish', 'neutral', or 'watch'

        Returns:
            List of ScoredCandidate with AI-calculated confidence
        """
        if not candidates:
            return []

        # Process in batches of 20 to manage context length
        batch_size = 20
        all_scored = []

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]
            scored_batch = self._score_batch(batch, market_sentiment)
            all_scored.extend(scored_batch)

        # Sort by confidence descending
        all_scored.sort(key=lambda x: x.confidence, reverse=True)

        return all_scored

    def _score_batch(
        self,
        candidates: List[StrategyMatch],
        market_sentiment: str
    ) -> List[ScoredCandidate]:
        """Score a batch of candidates."""

        # Prepare candidate data
        candidates_data = []
        for c in candidates:
            r_r_ratio = self._calculate_rr_ratio(c.entry_price, c.stop_loss, c.take_profit)
            candidates_data.append({
                "symbol": c.symbol,
                "strategy": c.strategy,
                "strategy_description": self.STRATEGY_DESCRIPTIONS.get(c.strategy, ""),
                "entry_price": c.entry_price,
                "stop_loss": c.stop_loss,
                "take_profit": c.take_profit,
                "r_r_ratio": r_r_ratio,
                "match_reasons": c.match_reasons,
                "technical_snapshot": c.technical_snapshot
            })

        # Get market guidance
        guidance = self.SENTIMENT_GUIDANCE.get(market_sentiment, self.SENTIMENT_GUIDANCE['neutral'])

        # Build prompt
        prompt = self._build_prompt(candidates_data, market_sentiment, guidance)

        try:
            # Call AI API
            response = self._call_ai_api(prompt)

            # Parse response
            scored_data = self._parse_ai_response(response)

            # Map back to ScoredCandidate objects
            return self._map_scored_data(candidates, scored_data)

        except Exception as e:
            logger.error(f"AI scoring failed: {e}")
            # Fallback: return candidates with neutral confidence
            return self._fallback_scoring(candidates)

    def _build_prompt(
        self,
        candidates_data: List[Dict],
        market_sentiment: str,
        guidance: Dict
    ) -> str:
        """Build the AI scoring prompt."""

        prompt = f"""You are an expert swing trade analyst with 20+ years of experience. Your task is to analyze trading opportunities and assign confidence scores (0-100).

## MARKET CONTEXT
- Current Sentiment: {market_sentiment.upper()}
- Guidance: {guidance['guidance']}
- Favorable Strategies: {', '.join(guidance['favorable']) if guidance['favorable'] else 'None specific'}
- Unfavorable Strategies: {', '.join(guidance['unfavorable']) if guidance['unfavorable'] else 'None specific'}

## CONFIDENCE SCORING CRITERIA
Score each opportunity 0-100 based on:

1. **Setup Quality (30%)**: How well does it match the strategy criteria?
   - All conditions met = 25-30 points
   - Most conditions met = 18-24 points
   - Some conditions met = 10-17 points
   - Weak match = 0-9 points

2. **Technical Confluence (25%)**: Do indicators align?
   - EMA alignment (EMA8>EMA21>EMA50 for longs)
   - RSI in favorable range for strategy
   - Volume confirmation (1.2x+ average)
   - Support/Resistance quality

3. **Risk/Reward Quality (20%)**: Is the trade mathematically favorable?
   - R/R ≥ 2.5: 18-20 points
   - R/R 2.0-2.5: 14-17 points
   - R/R 1.5-2.0: 10-13 points
   - R/R < 1.5: 0-9 points

4. **Market Context Alignment (15%)**: Does it fit current market conditions?
   - Favorable strategy + strong setup = 12-15 points
   - Neutral fit = 6-11 points
   - Contrarian strategy needs exceptional setup = 0-8 points

5. **Volatility Regime (10%)**: Is there enough movement potential?
   - ADR ≥ 3% = 8-10 points
   - ADR 2-3% = 5-7 points
   - ADR < 2% = 0-4 points

## CONFIDENCE SCALE
- 90-100: Exceptional setup, rare opportunity, strong confluence across all factors
- 80-89: Excellent setup, high probability trade, most factors align
- 70-79: Good setup, favorable conditions, worth considering
- 60-69: Decent setup, some concerns but viable
- 50-59: Moderate setup, marginal, higher risk
- 40-49: Weak setup, significant concerns
- 0-39: Poor setup, avoid trading

## CANDIDATES TO ANALYZE
```json
{json.dumps(candidates_data, indent=2)}
```

## OUTPUT FORMAT
Return ONLY a JSON array with NO markdown formatting:
[
  {{
    "symbol": "AAPL",
    "confidence": 78,
    "reasoning": "Strong RangeSupport setup with price bouncing off EMA50. EMA alignment is perfect (8>21>50). R/R of 2.3x is solid. Volume 1.4x confirms interest. Bearish market caps score at 78 vs 85+ in bull market.",
    "key_factors": ["EMA50 support bounce", "Strong EMA alignment", "Good R/R ratio", "Volume confirmation"],
    "risk_factors": ["Bearish market headwind"]
  }},
  ...
]

IMPORTANT:
- Be objective and consistent
- Consider market sentiment when scoring
- Higher confidence requires stronger evidence
- Provide specific reasoning, not generic comments"""

        return prompt

    def _call_ai_api(self, prompt: str) -> str:
        """Call the AI API with the prompt."""
        headers = {
            'Authorization': f'Bearer {self.dashscope_api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': 'You are an expert quantitative swing trade analyst. Provide objective, data-driven confidence scores.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,  # Lower for more consistent scoring
            'max_tokens': 4000
        }

        response = requests.post(
            f'{self.dashscope_base}/chat/completions',
            headers=headers,
            json=data,
            timeout=120
        )

        response.raise_for_status()
        result = response.json()

        return result['choices'][0]['message']['content']

    def _parse_ai_response(self, content: str) -> List[Dict]:
        """Parse AI response to extract scored data."""
        if not content:
            logger.warning("Empty AI response")
            return []

        try:
            # Clean the content
            content = content.strip()

            # Remove markdown code blocks if present
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()

            # Try to find JSON array
            if content.startswith('[') and content.endswith(']'):
                return json.loads(content)

            # Try to find array within text
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                return json.loads(match.group())

            # If no array found, try parsing entire content
            result = json.loads(content)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and 'candidates' in result:
                return result['candidates']
            else:
                logger.warning(f"Unexpected response format: {type(result)}")
                return []

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            # Try to extract individual objects as fallback
            return self._extract_fallback(content)

    def _extract_fallback(self, content: str) -> List[Dict]:
        """Fallback extraction when JSON parsing fails."""
        results = []

        # Look for symbol-confidence pairs
        symbol_matches = re.findall(
            r'["\']symbol["\']\s*:\s*["\']([A-Z]+)["\']',
            content
        )

        for symbol in symbol_matches:
            # Try to find confidence for this symbol
            confidence_match = re.search(
                rf'["\']symbol["\']\s*:\s*["\']{symbol}["\'][^}}]*["\']confidence["\']\s*:\s*(\d+)',
                content,
                re.DOTALL
            )

            confidence = int(confidence_match.group(1)) if confidence_match else 50

            results.append({
                'symbol': symbol,
                'confidence': min(100, max(0, confidence)),
                'reasoning': 'Parsed from partial AI response',
                'key_factors': [],
                'risk_factors': []
            })

        return results

    def _map_scored_data(
        self,
        original: List[StrategyMatch],
        scored_data: List[Dict]
    ) -> List[ScoredCandidate]:
        """Map scored data back to ScoredCandidate objects."""
        scored_candidates = []
        original_map = {c.symbol: c for c in original}

        for scored in scored_data:
            symbol = scored.get('symbol')
            if symbol not in original_map:
                continue

            orig = original_map[symbol]
            scored_candidates.append(ScoredCandidate(
                symbol=symbol,
                strategy=orig.strategy,
                entry_price=orig.entry_price,
                stop_loss=orig.stop_loss,
                take_profit=orig.take_profit,
                confidence=min(100, max(0, scored.get('confidence', 50))),
                reasoning=scored.get('reasoning', ''),
                key_factors=scored.get('key_factors', []),
                risk_factors=scored.get('risk_factors', []),
                match_reasons=orig.match_reasons,
                technical_snapshot=orig.technical_snapshot
            ))

        # Add any missing candidates with fallback scoring
        scored_symbols = {c.symbol for c in scored_candidates}
        for orig in original:
            if orig.symbol not in scored_symbols:
                scored_candidates.append(self._fallback_single(orig))

        return scored_candidates

    def _fallback_scoring(self, candidates: List[StrategyMatch]) -> List[ScoredCandidate]:
        """Fallback scoring when AI fails."""
        return [self._fallback_single(c) for c in candidates]

    def _fallback_single(self, candidate: StrategyMatch) -> ScoredCandidate:
        """Create a fallback ScoredCandidate."""
        r_r = self._calculate_rr_ratio(
            candidate.entry_price,
            candidate.stop_loss,
            candidate.take_profit
        )

        # Simple rule-based fallback
        base_score = 50
        if r_r >= 2.0:
            base_score += 15
        elif r_r >= 1.5:
            base_score += 10

        return ScoredCandidate(
            symbol=candidate.symbol,
            strategy=candidate.strategy,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            confidence=min(100, base_score),
            reasoning=f"Fallback scoring. R/R ratio: {r_r:.2f}x.",
            key_factors=["R/R ratio acceptable"],
            risk_factors=["AI scoring failed"],
            match_reasons=candidate.match_reasons,
            technical_snapshot=candidate.technical_snapshot
        )

    @staticmethod
    def _calculate_rr_ratio(entry: float, stop: float, target: float) -> float:
        """Calculate risk/reward ratio."""
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk == 0:
            return 1.0
        return round(reward / risk, 2)


def calculate_confidence_with_ai(
    candidates: List[StrategyMatch],
    market_sentiment: str = 'neutral'
) -> List[ScoredCandidate]:
    """
    Convenience function to score candidates with AI.

    Args:
        candidates: List of strategy matches
        market_sentiment: Market sentiment for context

    Returns:
        List of ScoredCandidate sorted by confidence
    """
    scorer = AIConfidenceScorer()
    return scorer.score_candidates(candidates, market_sentiment)
