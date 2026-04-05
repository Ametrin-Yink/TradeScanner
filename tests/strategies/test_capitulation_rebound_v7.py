"""Tests for Strategy F v7.0 pre-filter changes."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.strategies.capitulation_rebound import CapitulationReboundStrategy


class TestCapitulationReboundV7:
    """Test Strategy F pre-filter loosening."""

    def test_rsi_oversold_threshold_updated(self):
        """RSI oversold threshold should be 25 (was 22)."""
        strategy = CapitulationReboundStrategy()
        assert strategy.PARAMS['rsi_oversold'] == 25, "rsi_oversold should be 25"

    def test_ema_atr_multiplier_updated(self):
        """EMA ATR multiplier should be 3.0 (was 4.0)."""
        strategy = CapitulationReboundStrategy()
        assert strategy.PARAMS['ema_atr_multiplier'] == 3.0, "ema_atr_multiplier should be 3.0"

    def test_prefilter_accepts_consecutive_down_days(self):
        """Pre-filter should accept stocks with >=5 consecutive down-days even without gap-downs."""
        # Create test data: 5 consecutive down-days, no gaps, RSI < 25, price < EMA50-3xATR
        dates = pd.date_range('2024-01-01', periods=60, freq='D')

        # Build price data with sharp drop at the end to create RSI < 25 and price < EMA50 - 3xATR
        # First 50 days: stable high prices around 150
        prices = [150 + np.random.uniform(-2, 2) for _ in range(50)]
        # Last 10 days: sharp decline to create capitulation
        prices += [145, 138, 130, 120, 110, 100, 92, 88, 85, 82]  # 10 consecutive down days

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.01 for p in prices],
            'low': [p * 0.99 for p in prices],
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        strategy = CapitulationReboundStrategy()
        # Mock the _get_data method
        strategy._get_data = lambda x: df

        # Should pass pre-filter due to consecutive down-days (and RSI < 25, price < EMA50-3xATR)
        result = strategy._prefilter_symbol('TEST', df)
        assert result is True, "Should accept stock with 5 consecutive down-days"
