"""AI candidate selector with confidence scoring - selects top 10 from candidates."""
import logging
from typing import List, Optional

from core.screener import StrategyMatch
from core.ai_confidence_scorer import AIConfidenceScorer, ScoredCandidate
from config.settings import settings

logger = logging.getLogger(__name__)


class CandidateSelector:
    """
    Select and score top 30 opportunities from candidates using AI.

    This class combines selection and scoring into one AI-powered step,
    providing confidence scores (0-100) that adapt to market conditions.
    """

    def __init__(self):
        """Initialize with AI scorer."""
        self.scorer = AIConfidenceScorer()
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')

    def select_top_30(
        self,
        candidates: List[StrategyMatch],
        market_sentiment: str = 'neutral',
        regime: str = None
    ) -> List[ScoredCandidate]:
        """Select and score top 30 candidates using AI."""

        if not candidates:
            logger.warning("No candidates provided")
            return []

        # Score all candidates (up to 30)
        logger.info(f"AI scoring {len(candidates)} candidates")
        scored = self.scorer.score_candidates(candidates, market_sentiment, regime=regime)

        if not scored:
            logger.warning("AI scoring returned empty, using fallback")
            return self._fallback_scoring(candidates[:30])

        # Return top 30
        top_30 = scored[:30]
        conf_range = f"{top_30[-1].confidence}-{top_30[0].confidence}" if len(top_30) > 1 else "N/A"
        logger.info(f"Selected top 30 with confidence range: {conf_range}")

        return top_30

    def _fallback_scoring(self, candidates: List[StrategyMatch]) -> List[ScoredCandidate]:
        """Fallback scoring when AI is not available."""
        from core.ai_confidence_scorer import calculate_confidence_with_ai

        # This will use the fallback logic in the scorer
        return calculate_confidence_with_ai(candidates, 'neutral')

    def get_selection_summary(
        self,
        selected: List[ScoredCandidate],
        market_sentiment: str
    ) -> str:
        """Get human-readable selection summary."""
        if not selected:
            return "No candidates selected"

        summary = f"Top {len(selected)} Opportunities ({market_sentiment.upper()} Market)\n"
        summary += "=" * 60 + "\n\n"

        # Strategy distribution
        strategy_counts = {}
        for match in selected:
            strategy_counts[match.strategy] = strategy_counts.get(match.strategy, 0) + 1

        for i, match in enumerate(selected, 1):
            rrr = self._calculate_rrr(match.entry_price, match.stop_loss, match.take_profit)

            summary += f"{i}. {match.symbol} ({match.strategy}) - {match.confidence}% confidence\n"
            summary += f"   Entry: ${match.entry_price:.2f} | Stop: ${match.stop_loss:.2f} | Target: ${match.take_profit:.2f}\n"
            summary += f"   R/R: {rrr:.1f}x\n"
            summary += f"   Key Factors: {', '.join(match.key_factors[:3])}\n"
            if match.risk_factors:
                summary += f"   Risks: {', '.join(match.risk_factors[:2])}\n"
            summary += "\n"

        summary += f"Strategy Distribution: {strategy_counts}\n"
        summary += f"Average Confidence: {sum(m.confidence for m in selected) / len(selected):.1f}%"

        return summary

    @staticmethod
    def _calculate_rrr(entry: float, stop: float, target: float) -> float:
        """Calculate risk/reward ratio."""
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk == 0:
            return 0
        return reward / risk


def select_and_score_candidates(
    candidates: List[StrategyMatch],
    market_sentiment: str = 'neutral',
    regime: str = None
) -> List[ScoredCandidate]:
    """
    Convenience function to select and score candidates.

    Args:
        candidates: List of strategy matches from screener
        market_sentiment: Market sentiment for context
        regime: Market regime for outcome tracking (e.g., 'bull_strong', 'bear_moderate')

    Returns:
        List of top 30 ScoredCandidate sorted by confidence
    """
    selector = CandidateSelector()
    return selector.select_top_30(candidates, market_sentiment, regime=regime)
