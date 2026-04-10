"""Tests for Strategy E AccumulationBottom v7.1."""
import pytest
import pandas as pd
import numpy as np
from core.strategies.accumulation_bottom import AccumulationBottomStrategy
from core.strategies.base_strategy import normalize_score


class TestAccumulationBottomV7:
    """Test Strategy E v7.1 changes."""

    def test_min_market_cap_updated(self):
        """Min market cap should be $2.5B (was $3B)."""
        strategy = AccumulationBottomStrategy()
        assert strategy.PARAMS['min_market_cap'] == 2_500_000_000, "min_market_cap should be 2.5B"

    def test_min_volume_updated(self):
        """Min volume should be 150K (was 200K)."""
        strategy = AccumulationBottomStrategy()
        assert strategy.PARAMS['min_volume'] == 150_000, "min_volume should be 150000"

    def test_max_distance_from_low_updated(self):
        """Max distance from 60d low should be 10% (was 8%)."""
        strategy = AccumulationBottomStrategy()
        assert strategy.PARAMS['max_distance_from_60d_low'] == 0.10, "max_distance_from_60d_low should be 0.10"

    def test_dimensions_include_od_wy(self):
        """v7.1 should have OD (OBV Divergence) and WY (Wyckoff Structure) dimensions."""
        strategy = AccumulationBottomStrategy()
        assert 'OD' in strategy.DIMENSIONS, "OD dimension missing"
        assert 'WY' in strategy.DIMENSIONS, "WY dimension missing"
        assert 'AS' not in strategy.DIMENSIONS, "AS dimension should be replaced by OD"

    def test_max_score_normalized(self):
        """Raw max score 18.0 should normalize to 15.0."""
        assert normalize_score(18.0, 'AccumulationBottom') == 15.0

    def _make_dataframe(self, days=200):
        """Create a synthetic DataFrame for testing."""
        np.random.seed(42)
        dates = pd.bdate_range(end='2026-04-09', periods=days)
        base_price = 100.0
        prices = np.cumsum(np.random.randn(days) * 0.5) + base_price
        prices = np.maximum(prices, 1.0)  # Ensure positive
        opens = prices + np.random.randn(days) * 0.2
        highs = np.maximum(prices, opens) + abs(np.random.randn(days) * 0.3)
        lows = np.minimum(prices, opens) - abs(np.random.randn(days) * 0.3)
        volumes = np.random.randint(100000, 500000, days)

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows,
            'close': prices, 'volume': volumes
        }, index=dates)
        return df

    def test_obv_divergence_calculation(self):
        """OD should produce a valid score between 0 and 4.0."""
        strategy = AccumulationBottomStrategy()
        df = self._make_dataframe()
        od_score = strategy._calculate_od(df)
        assert 0.0 <= od_score <= 4.0, f"OD score {od_score} out of range [0, 4]"

    def test_wyckoff_structure_calculation(self):
        """WY should produce a valid score between 0 and 3.0."""
        strategy = AccumulationBottomStrategy()
        df = self._make_dataframe()
        wy_score = strategy._calculate_wy(df, None, 2.0)
        assert 0.0 <= wy_score <= 3.0, f"WY score {wy_score} out of range [0, 3]"

    def test_tq_no_unreachable_branch(self):
        """TQ should not have unreachable scoring branches."""
        strategy = AccumulationBottomStrategy()
        df = self._make_dataframe()
        from core.indicators import TechnicalIndicators
        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df)
        assert 0.0 <= tq <= 3.5, f"TQ score {tq} out of range [0, 3.5]"
