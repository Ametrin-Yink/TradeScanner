"""Tests for Strategy E v7.0 gate changes."""
import pytest
from core.strategies.accumulation_bottom import AccumulationBottomStrategy


class TestAccumulationBottomV7:
    """Test Strategy E gate loosening."""

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
