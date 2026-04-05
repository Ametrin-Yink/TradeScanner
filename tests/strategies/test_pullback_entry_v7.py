"""Tests for Strategy B v7.0 BONUS replacement."""
import pytest
import pandas as pd
import numpy as np
from core.strategies.pullback_entry import PullbackEntryStrategy


class TestPullbackEntryV7:
    """Test Strategy B BONUS replacement."""

    def _create_deterministic_data(self, days=60, stock_5d_return=0.05, spy_5d_return=0.02):
        """Create deterministic test data with exact 5d returns."""
        dates = pd.date_range('2024-01-01', periods=days, freq='D')

        # Create stock prices - flat for first days-5, then exact return
        # Use exact calculation: price[-5] = 100, price[-1] = 100 * (1 + return)
        stock_prices = [100.0] * (days - 5)
        base = 100.0
        target = base * (1 + stock_5d_return)
        # Linear interpolation for days -5 to -1
        for i in range(5):
            price = base + (target - base) * (i / 4)  # i=0 -> base, i=4 -> target
            stock_prices.append(price)

        # Create SPY prices
        spy_prices = [400.0] * (days - 5)
        base = 400.0
        target = base * (1 + spy_5d_return)
        for i in range(5):
            price = base + (target - base) * (i / 4)
            spy_prices.append(price)

        df = pd.DataFrame({
            'open': stock_prices,
            'high': [p * 1.02 for p in stock_prices],
            'low': [p * 0.98 for p in stock_prices],
            'close': stock_prices,
            'volume': [1_000_000] * days
        }, index=dates)

        spy_df = pd.DataFrame({
            'close': spy_prices
        }, index=dates)

        return df, spy_df

    def test_momentum_persistence_bonus(self):
        """Stock with >2% outperformance vs SPY over 5d should get +1.0 bonus."""
        strategy = PullbackEntryStrategy()

        # Stock up 5% over 5 days, SPY up 2% (outperformance = 3%)
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.05, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0  # Mock market ATR

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get +1.0 for momentum persistence (stock outperforms SPY by >2%)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 1.0, \
            f"Should get +1.0 for >2% outperformance, got {bonus.details.get('momentum_persistence_score')}"
        assert bonus.score >= 1.0, f"Total bonus should be >= 1.0, got {bonus.score}"

    def test_momentum_persistence_no_bonus(self):
        """Stock with <1% outperformance vs SPY over 5d should get 0 momentum bonus."""
        strategy = PullbackEntryStrategy()

        # Stock up 0.5% over 5 days, SPY up 2% (underperformance = -1.5%)
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.005, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get 0 for momentum persistence (stock underperforms SPY)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 0, \
            f"Should get 0 for momentum persistence when underperforming, got {bonus.details.get('momentum_persistence_score')}"

    def test_momentum_persistence_partial_bonus(self):
        """Stock with 1-2% outperformance vs SPY over 5d should get +0.5 bonus."""
        strategy = PullbackEntryStrategy()

        # Stock up 3.5% over 5 days, SPY up 2% (outperformance = 1.5%)
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.035, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get +0.5 for momentum persistence (stock outperforms SPY by 1-2%)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 0.5, \
            f"Should get +0.5 bonus for 1-2% outperformance, got {bonus.details.get('momentum_persistence_score')}"

    def test_momentum_persistence_insufficient_data(self):
        """Stock with <5 days data should still calculate (edge case handled)."""
        strategy = PullbackEntryStrategy()

        # Create test data with 60 days (minimum for indicators) but test <5 day calculation
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.05, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0

        # Test with full data - should work normally
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        assert bonus is not None, "BONUS dimension should exist"
        # With proper 5d data, should get the expected score
        assert bonus.details.get('momentum_persistence_score', 0) == 1.0, \
            f"Should get +1.0 with sufficient data, got {bonus.details.get('momentum_persistence_score')}"

    def test_momentum_persistence_boundary_2percent(self):
        """Stock with >2% outperformance should get +1.0 bonus."""
        strategy = PullbackEntryStrategy()

        # Stock up 4.1% over 5 days, SPY up 2% (outperformance = 2.1%)
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.041, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get +1.0 for momentum persistence (>2% outperformance)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 1.0, \
            f"Should get +1.0 bonus for >2% outperformance, got {bonus.details.get('momentum_persistence_score')}"

    def test_momentum_persistence_boundary_1percent(self):
        """Stock with >1% outperformance should get +0.5 bonus."""
        strategy = PullbackEntryStrategy()

        # Stock up 3.1% over 5 days, SPY up 2% (outperformance = 1.1%)
        df, spy_df = self._create_deterministic_data(days=60, stock_5d_return=0.031, spy_5d_return=0.02)

        strategy.sector_etf_data['SPY'] = spy_df
        strategy._get_data = lambda x: df if x != 'SPY' else spy_df
        strategy.market_atr_median = 2.0

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get +0.5 for momentum persistence (>1% outperformance)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 0.5, \
            f"Should get +0.5 bonus for >1% outperformance, got {bonus.details.get('momentum_persistence_score')}"

    def test_momentum_persistence_no_spy_data(self):
        """Stock with no SPY data should get 0 momentum persistence bonus."""
        strategy = PullbackEntryStrategy()

        # Create test data but don't add SPY
        df, _ = self._create_deterministic_data(days=60, stock_5d_return=0.05, spy_5d_return=0.02)

        strategy.sector_etf_data = {}  # No SPY data
        strategy._get_data = lambda x: df

        # Calculate dimensions and check BONUS
        dimensions = strategy.calculate_dimensions('TEST', df)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        # Should get 0 for momentum persistence (no SPY data)
        assert bonus is not None, "BONUS dimension should exist"
        assert bonus.details.get('momentum_persistence_score', 0) == 0, \
            f"Should get 0 for momentum persistence with no SPY data, got {bonus.details.get('momentum_persistence_score')}"
