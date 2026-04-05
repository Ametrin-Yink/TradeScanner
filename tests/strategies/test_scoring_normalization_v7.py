"""Tests for scoring normalization v7.0."""
import pytest
from core.strategies.base_strategy import normalize_score, STRATEGY_MAX_SCORES


class TestScoringNormalization:
    """Test score normalization."""

    def test_normalize_strategy_h(self):
        """Strategy H raw score 12 should normalize to ~13.85 (easier to reach S-tier)."""
        raw_score = 12.0
        normalized = normalize_score(raw_score, 'RelativeStrengthLong')

        # 12/13 * 15 = 13.85
        expected = 13.85

        assert abs(normalized - expected) < 0.1, f"Expected ~{expected}, got {normalized}"

    def test_normalize_strategy_a(self):
        """Strategy A raw score 12 should normalize to ~9.73."""
        raw_score = 12.0
        normalized = normalize_score(raw_score, 'MomentumBreakout')

        # 12/18.5 * 15 = 9.73
        expected = 9.73

        assert abs(normalized - expected) < 0.1

    def test_all_strategies_use_same_tier_thresholds(self):
        """All strategies should reach S-tier at ~80% quality after normalization."""
        # After normalization, all strategies use 0-15 scale
        # S-tier = 12/15 = 80% for all strategies

        for strategy_name, max_score in STRATEGY_MAX_SCORES.items():
            # Raw score needed for S-tier (before normalization)
            raw_for_s = (12.0 / 15.0) * max_score

            # Normalize back
            normalized = normalize_score(raw_for_s, strategy_name)

            # Should be exactly 12 (S-tier threshold)
            assert abs(normalized - 12.0) < 0.01, f"{strategy_name}: expected 12.0, got {normalized}"
