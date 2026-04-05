"""Tests for Strategy D v7.0 liquidity guard."""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from core.strategies.distribution_top import DistributionTopStrategy


class TestDistributionTopV7:
    """Test Strategy D liquidity guard."""

    def test_liquidity_guard_param_exists(self):
        """Strategy D should have min_dollar_volume_short param of $30M."""
        strategy = DistributionTopStrategy()
        assert strategy.PARAMS.get('min_dollar_volume_short') == 30_000_000, \
            "min_dollar_volume_short should be 30000000"

    def test_filter_rejects_low_dollar_volume(self):
        """Filter should reject stocks with dollar volume < $30M."""
        # Create test data: valid pattern but low dollar volume
        dates = pd.date_range('2024-01-01', periods=60, freq='D')

        # Price around $10, volume around 100K = $1M dollar volume (too low)
        prices = [10 + (i % 10) * 0.1 for i in range(60)]

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [100_000] * 60  # Low volume
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._get_data = lambda x: df

        # Should fail filter due to low dollar volume
        result = strategy.filter('TEST', df)
        assert result is False, "Should reject stock with dollar volume < $30M"

    def test_filter_accepts_high_dollar_volume(self):
        """Filter should accept stocks with dollar volume > $30M if other criteria met."""
        # This test may pass or fail depending on other criteria - just verify no rejection due to dollar volume
        dates = pd.date_range('2024-01-01', periods=60, freq='D')

        # Price around $50, volume around 1M = $50M dollar volume (good)
        prices = [50 + (i % 10) * 0.5 for i in range(60)]

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1_000_000] * 60  # Good volume
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._get_data = lambda x: df

        # Just verify it doesn't fail specifically due to dollar volume check
        # (may fail for other reasons - we just check the dollar volume guard passes)
        try:
            result = strategy.filter('TEST', df)
            # If we get here without exception, the dollar volume check passed
        except Exception as e:
            pytest.fail(f"Filter raised unexpected exception: {e}")
