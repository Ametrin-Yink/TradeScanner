"""Tests for DoubleTopBottom strategy stricter short entry confirmation."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from core.strategies.double_top_bottom import DoubleTopBottomStrategy


@pytest.fixture
def strategy():
    """Create a DoubleTopBottom strategy instance."""
    return DoubleTopBottomStrategy()


@pytest.fixture
def create_distribution_data():
    """Factory fixture for creating distribution top test data."""
    def _create(
        ema8=98.0,
        ema21=97.0,
        ema50=96.0,
        price=97.5,
        rsi=55.0,
        rsi_divergence=False,
        ema21_slope=-0.001
    ):
        """Create DataFrame with distribution pattern at 60d high."""
        dates = pd.date_range('2024-01-01', periods=100, freq='D')

        # Base price near 60d high
        base = 100
        high_60d = base * 1.05  # 60d high

        # Create data that trends toward the 60d high then flattens
        closes = []
        for i in range(100):
            if i < 60:
                closes.append(base + i * 0.05)  # Uptrend
            else:
                # Distribution near highs
                closes.append(high_60d - 2 + np.sin(i * 0.1) * 2)

        closes = np.array(closes)
        highs = closes + np.random.uniform(0.5, 1.5, 100)
        lows = closes - np.random.uniform(0.5, 1.5, 100)
        opens = closes - np.random.uniform(-0.5, 0.5, 100)

        # Override last values to set test conditions
        closes[-1] = price
        highs[-1] = high_60d
        lows[-1] = price - 1

        df = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)

        return df, {
            'ema8': ema8,
            'ema21': ema21,
            'ema50': ema50,
            'price': price,
            'rsi': rsi,
            'rsi_divergence': rsi_divergence,
            'high_60d': high_60d
        }

    return _create


class TestDoubleTopBottomShortConfirmation:
    """Test stricter short entry confirmation requirements."""

    def test_short_requires_rsi_divergence_for_max_score(self, strategy, create_distribution_data):
        """Test that short signals without RSI divergence are capped at 4 points."""
        df, params = create_distribution_data(
            ema8=98.0,
            ema21=97.0,
            ema50=96.0,
            price=97.5,
            rsi=55.0,
            rsi_divergence=False
        )

        # Mock market direction
        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': -0.003}  # Negative slope

        # Patch check_rsi_divergence to return False (no divergence)
        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=False):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # Without RSI divergence, max score should be limited
        assert ts_score <= 4.0, f"Score {ts_score} should be capped at 4.0 without RSI divergence"
        assert ts_details['rsi_divergence'] is False

    def test_short_with_rsi_divergence_allows_full_score(self, strategy, create_distribution_data):
        """Test that short signals with RSI divergence allow full scoring."""
        df, params = create_distribution_data(
            ema8=94.0,  # Clear death cross: ema8 < ema21 < ema50
            ema21=96.0,
            ema50=98.0,
            price=95.0,
            rsi=55.0,
            rsi_divergence=True
        )

        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': -0.003}

        # Patch check_rsi_divergence to return True (has divergence)
        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=True):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # With RSI divergence and death cross, should allow higher score
        # Base 3.0 + price<ema8 2.0 + slope -0.003 1.5 + RSI 55 1.0 = 7.5 -> capped at 6.0
        assert ts_score > 4.0, f"Score {ts_score} should exceed 4.0 with RSI divergence and death cross"
        assert ts_details['rsi_divergence'] is True

    def test_short_death_cross_required_for_max_score(self, strategy, create_distribution_data):
        """Test that ema8 < ema21 (death cross) is required for max score."""
        df, params = create_distribution_data(
            ema8=99.0,  # ema8 > ema21, no death cross
            ema21=97.0,
            ema50=96.0,
            price=97.5,
            rsi=55.0,
            rsi_divergence=False
        )

        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': -0.001}

        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=False):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # Without death cross AND no divergence, score should be limited
        assert ts_score <= 4.0, f"Score {ts_score} should be capped at 4.0 without death cross and divergence"
        assert ts_details['side'] in ['transition', 'left', 'unknown']

    def test_left_side_early_distribution_capped_at_tier_b(self, strategy, create_distribution_data):
        """Test that left side (early distribution) is capped at 3 points (Tier B max)."""
        df, params = create_distribution_data(
            ema8=102.0,  # Still bullish EMA alignment
            ema21=100.0,
            ema50=98.0,
            price=101.0,
            rsi=58.0,
            rsi_divergence=True  # But has divergence
        )

        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': 0.001}  # Still positive

        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=True):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # Left side should be capped at 3 points per existing logic
        assert ts_score <= 3.0, f"Left side score {ts_score} should be capped at 3.0 (Tier B max)"
        assert ts_details['side'] == 'left'

    def test_short_full_confirmation_requirements(self, strategy, create_distribution_data):
        """Test complete stricter confirmation: death cross + RSI divergence = full points."""
        df, params = create_distribution_data(
            ema8=94.0,   # Clear death cross
            ema21=96.0,
            ema50=98.0,
            price=95.0,
            rsi=52.0,    # Distribution zone
            rsi_divergence=True
        )

        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': -0.003}  # Negative

        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=True):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # Full confirmation should yield higher score
        assert ts_score >= 4.0, f"Full confirmation score {ts_score} should be >= 4.0"
        assert ts_details['side'] == 'right'
        assert ts_details['rsi_divergence'] is True

    def test_short_partial_confirmation_transition_state(self, strategy, create_distribution_data):
        """Test transition state: ema8 < ema21 but ema21 > ema50 (partial bearish)."""
        df, params = create_distribution_data(
            ema8=95.0,   # ema8 < ema21 (death cross partial)
            ema21=97.0,
            ema50=96.0,  # but ema21 > ema50 (not full death cross)
            price=96.0,
            rsi=55.0,
            rsi_divergence=False
        )

        strategy.market_direction = 'short'

        # Create mock indicators
        mock_ind = Mock()
        mock_ind.indicators = {
            'ema': {'ema8': params['ema8'], 'ema21': params['ema21'], 'ema50': params['ema50']},
            'rsi': {'rsi': params['rsi']},
            'price_metrics': {'high_60d': params['high_60d']},
            'atr': {'atr': 2.0}
        }
        mock_ind.calculate_stable_ema_slope.return_value = {'slope': -0.001}

        with patch('core.strategies.double_top_bottom.check_rsi_divergence', return_value=False):
            ts_score, ts_details = strategy._calculate_ts_short(mock_ind, df, params['price'])

        # Transition state should have limited score (ema8 < ema21 but ema21 > ema50)
        assert ts_score <= 4.0, f"Transition state score {ts_score} should be capped at 4.0"
        assert ts_details['side'] == 'transition'
