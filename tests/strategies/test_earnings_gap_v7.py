"""Tests for Strategy G v7.0 time window by gap size."""
import pytest
import pandas as pd
from core.strategies.earnings_gap import EarningsGapStrategy


class TestEarningsGapV7:
    """Test Strategy G time window by gap size."""

    def _create_test_df(self, prices, gap_volume_multiplier=1.0):
        """Helper to create test dataframe with sufficient data."""
        dates = pd.date_range('2024-01-01', periods=10, freq='D')

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [int(2_000_000 * gap_volume_multiplier) if i == 5 else 1_500_000 for i in range(10)]
        }, index=dates)
        return df

    def test_large_gap_eligible_day_3(self):
        """Gap >=10% should be eligible for days 1-5 (test day 3)."""
        strategy = EarningsGapStrategy()

        # 12% gap up
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        # Mock phase0_data with all required fields
        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.12,  # 12% gap
                'days_to_earnings': -3,  # 3 days post-earnings
                'gap_direction': 'up',
                'rs_percentile': 75,  # Above min_rs_percentile (50)
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 3 post-earnings with 12% gap should pass
        result = strategy.filter('TEST', df)
        assert result is True, "12% gap should be eligible on day 3"

    def test_large_gap_eligible_day_5(self):
        """Gap >=10% should be eligible on day 5 (boundary)."""
        strategy = EarningsGapStrategy()

        # 12% gap up
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.12,  # 12% gap
                'days_to_earnings': -5,  # 5 days post-earnings (boundary)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 5 post-earnings with 12% gap should pass (boundary)
        result = strategy.filter('TEST', df)
        assert result is True, "12% gap should be eligible on day 5 (boundary)"

    def test_large_gap_rejected_day_6(self):
        """Gap >=10% should be rejected after day 5."""
        strategy = EarningsGapStrategy()

        # 12% gap up
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.12,  # 12% gap
                'days_to_earnings': -6,  # 6 days post-earnings (should be rejected)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 6 post-earnings with 12% gap should be rejected
        result = strategy.filter('TEST', df)
        assert result is False, "12% gap should be rejected on day 6"

    def test_medium_gap_eligible_day_2(self):
        """Gap 7-10% should be eligible on day 2."""
        strategy = EarningsGapStrategy()

        # 8% gap up
        prices = [100, 102, 104, 106, 108, 108, 107, 106, 105, 104]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.08,  # 8% gap
                'days_to_earnings': -2,  # 2 days post-earnings
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 2 post-earnings with 8% gap should pass
        result = strategy.filter('TEST', df)
        assert result is True, "8% gap should be eligible on day 2"

    def test_medium_gap_eligible_day_3(self):
        """Gap 7-10% should be eligible on day 3 (boundary)."""
        strategy = EarningsGapStrategy()

        # 8% gap up
        prices = [100, 102, 104, 106, 108, 108, 107, 106, 105, 104]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.08,  # 8% gap
                'days_to_earnings': -3,  # 3 days post-earnings (boundary)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 3 post-earnings with 8% gap should pass (boundary)
        result = strategy.filter('TEST', df)
        assert result is True, "8% gap should be eligible on day 3 (boundary)"

    def test_medium_gap_rejected_day_4(self):
        """Gap 7-10% should be rejected after day 3."""
        strategy = EarningsGapStrategy()

        # 8% gap up
        prices = [100, 102, 104, 106, 108, 108, 107, 106, 105, 104]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.08,  # 8% gap
                'days_to_earnings': -4,  # 4 days post-earnings (should be rejected)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 4 post-earnings with 8% gap should be rejected
        result = strategy.filter('TEST', df)
        assert result is False, "8% gap should be rejected on day 4"

    def test_small_gap_eligible_day_1(self):
        """Gap 5-7% should be eligible on day 1."""
        strategy = EarningsGapStrategy()

        # 6% gap up
        prices = [100, 102, 104, 106, 106, 105, 104, 103, 102, 101]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.06,  # 6% gap
                'days_to_earnings': -1,  # 1 day post-earnings
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 1 post-earnings with 6% gap should pass
        result = strategy.filter('TEST', df)
        assert result is True, "6% gap should be eligible on day 1"

    def test_small_gap_eligible_day_2(self):
        """Gap 5-7% should be eligible on day 2 (boundary)."""
        strategy = EarningsGapStrategy()

        # 6% gap up
        prices = [100, 102, 104, 106, 106, 105, 104, 103, 102, 101]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.06,  # 6% gap
                'days_to_earnings': -2,  # 2 days post-earnings (boundary)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 2 post-earnings with 6% gap should pass (boundary)
        result = strategy.filter('TEST', df)
        assert result is True, "6% gap should be eligible on day 2 (boundary)"

    def test_small_gap_rejected_day_3(self):
        """Gap 5-7% should be rejected after day 2."""
        strategy = EarningsGapStrategy()

        # 6% gap up
        prices = [100, 102, 104, 106, 106, 105, 104, 103, 102, 101]
        df = self._create_test_df(prices, gap_volume_multiplier=3.0)

        strategy.phase0_data = {
            'TEST': {
                'gap_1d_pct': 0.06,  # 6% gap
                'days_to_earnings': -3,  # 3 days post-earnings (should be rejected)
                'gap_direction': 'up',
                'rs_percentile': 75,
                'gap_volume_ratio': 3.0,
            }
        }
        strategy._get_data = lambda x: df

        # Day 3 post-earnings with 6% gap should be rejected
        result = strategy.filter('TEST', df)
        assert result is False, "6% gap should be rejected on day 3"
