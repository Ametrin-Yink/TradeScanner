"""Tests for indicator formula correctness per Strategy Description v7.0.

This module tests that indicator formulas match the documented specifications:
- CLV: (close - low) / (high - low), returns 0-1
- Accumulation Ratio: sum(vol up-days) / sum(vol down-days)
- ATR14: SMA(TR, 14), not EMA
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.indicators import TechnicalIndicators
from core.premarket_prep import PreMarketPrep


class TestCLVFormula:
    """Test Close Location Value formula.

    Per Strategy Description v7.0:
    CLV = (close - low) / (high - low)
    Ranges from 0 (close at low) to 1 (close at high)
    """

    def test_clv_close_at_high(self):
        """CLV should be 1.0 when close equals high."""
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        df = pd.DataFrame({
            'open': [100, 100, 100, 100, 100],
            'high': [110, 110, 110, 110, 110],
            'low': [90, 90, 90, 90, 90],
            'close': [110, 110, 110, 110, 110],  # Close at high
            'volume': [1000000] * 5
        }, index=dates)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert clv == 1.0, f"CLV should be 1.0 when close=high, got {clv}"

    def test_clv_close_at_low(self):
        """CLV should be 0.0 when close equals low."""
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        df = pd.DataFrame({
            'open': [100, 100, 100, 100, 100],
            'high': [110, 110, 110, 110, 110],
            'low': [90, 90, 90, 90, 90],
            'close': [90, 90, 90, 90, 90],  # Close at low
            'volume': [1000000] * 5
        }, index=dates)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert clv == 0.0, f"CLV should be 0.0 when close=low, got {clv}"

    def test_clv_close_at_midpoint(self):
        """CLV should be 0.5 when close is exactly in the middle."""
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        df = pd.DataFrame({
            'open': [100, 100, 100, 100, 100],
            'high': [110, 110, 110, 110, 110],
            'low': [90, 90, 90, 90, 90],
            'close': [100, 100, 100, 100, 100],  # Close at midpoint
            'volume': [1000000] * 5
        }, index=dates)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert clv == 0.5, f"CLV should be 0.5 when close is midpoint, got {clv}"

    def test_clv_close_at_quarter(self):
        """CLV should be 0.25 when close is at 25% of range."""
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        # Range is 90 to 110 = 20
        # 25% of range = 90 + (20 * 0.25) = 95
        df = pd.DataFrame({
            'open': [100, 100, 100, 100, 100],
            'high': [110, 110, 110, 110, 110],
            'low': [90, 90, 90, 90, 90],
            'close': [95, 95, 95, 95, 95],  # 25% of range (90 + 5)
            'volume': [1000000] * 5
        }, index=dates)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert clv == pytest.approx(0.25, rel=1e-5), f"CLV should be 0.25, got {clv}"

    def test_clv_close_at_three_quarters(self):
        """CLV should be 0.75 when close is at 75% of range."""
        dates = pd.date_range('2024-01-01', periods=5, freq='D')
        # Range is 90 to 110 = 20
        # 75% of range = 90 + (20 * 0.75) = 105
        df = pd.DataFrame({
            'open': [100, 100, 100, 100, 100],
            'high': [110, 110, 110, 110, 110],
            'low': [90, 90, 90, 90, 90],
            'close': [105, 105, 105, 105, 105],  # 75% of range (90 + 15)
            'volume': [1000000] * 5
        }, index=dates)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert clv == pytest.approx(0.75, rel=1e-5), f"CLV should be 0.75, got {clv}"

    def test_clv_range_is_0_to_1(self):
        """CLV should always be in range [0, 1], not [-1, 1]."""
        dates = pd.date_range('2024-01-01', periods=20, freq='D')
        np.random.seed(42)
        df = pd.DataFrame({
            'open': np.random.uniform(95, 105, 20),
            'high': np.random.uniform(105, 110, 20),
            'low': np.random.uniform(90, 95, 20),
            'close': np.random.uniform(90, 110, 20),
            'volume': np.random.randint(1000000, 5000000, 20)
        }, index=dates)

        # Ensure high >= close and low <= close
        df['high'] = df[['high', 'close']].max(axis=1)
        df['low'] = df[['low', 'close']].min(axis=1)

        calc = TechnicalIndicators(df)
        clv = calc.calculate_clv()

        assert 0 <= clv <= 1, f"CLV should be in [0, 1], got {clv}"


class TestAccumulationRatioFormula:
    """Test accumulation ratio formula.

    Per Strategy Description v7.0:
    accum_ratio = sum(vol on up-days, 15d) / sum(vol on down-days, 15d)
    NOT avg(vol up-days) / avg(vol down-days)
    """

    def test_accum_ratio_uses_sum_not_avg(self):
        """Accumulation ratio should use sum, not average.

        This test creates a scenario where sum and avg produce different results.
        """
        # Create data with different number of up vs down days
        # First day has no price change (diff = NaN), so we need 21 days
        # to get 15 up days + 5 down days = 20 days with changes
        dates = pd.date_range('2024-01-01', periods=21, freq='D')

        # Day 0: flat (no change), Days 1-15: up (15 up days), Days 16-20: down (5 down days)
        # Up days: volume = 1M each, Down days: volume = 3M each
        # SUM ratio = (15 * 1M) / (5 * 3M) = 15/15 = 1.0
        # AVG ratio = (1M) / (3M) = 0.333...

        prices = []
        volumes = []
        base_price = 100

        for i in range(21):
            if i == 0:  # First day - flat
                prices.append(base_price)
                volumes.append(1000000)
            elif i <= 15:  # Up days (15 days)
                prices.append(base_price + i)
                volumes.append(1000000)  # 1M volume
            else:  # Down days (5 days)
                prices.append(base_price + 15 - (i - 15))
                volumes.append(3000000)  # 3M volume

        df = pd.DataFrame({
            'open': prices,
            'high': [p + 1 for p in prices],
            'low': [p - 1 for p in prices],
            'close': prices,
            'volume': volumes
        }, index=dates)

        prep = PreMarketPrep()
        accum_ratio = prep._calculate_accum_ratio(df, days=21)

        # Expected: sum(up_vols) / sum(down_vols) = (15 * 1M) / (5 * 3M) = 15/15 = 1.0
        expected_sum_ratio = 15 * 1000000 / (5 * 3000000)  # 1.0
        expected_avg_ratio = 1000000 / 3000000  # 0.333...

        # The ratio should match SUM calculation, not AVG
        assert accum_ratio == pytest.approx(expected_sum_ratio, rel=0.01), (
            f"Accum ratio should use SUM ({expected_sum_ratio}), got {accum_ratio}. "
            f"If using AVG, would be {expected_avg_ratio}"
        )

    def test_accum_ratio_equal_up_down_days(self):
        """Test with equal up/down days and equal volumes."""
        dates = pd.date_range('2024-01-01', periods=20, freq='D')

        prices = []
        volumes = []
        base_price = 100

        for i in range(20):
            if i % 2 == 0:  # Up day
                prices.append(base_price + i)
            else:  # Down day
                prices.append(base_price + i - 2)
            volumes.append(1000000)

        df = pd.DataFrame({
            'open': prices,
            'high': [p + 1 for p in prices],
            'low': [p - 1 for p in prices],
            'close': prices,
            'volume': volumes
        }, index=dates)

        prep = PreMarketPrep()
        accum_ratio = prep._calculate_accum_ratio(df, days=15)

        # With equal volumes, ratio should be close to 1.0
        assert accum_ratio == pytest.approx(1.0, rel=0.1), f"Expected ~1.0, got {accum_ratio}"


class TestATRFormula:
    """Test ATR14 formula.

    Per Strategy Description v7.0:
    ATR14 = SMA(TR, 14) - Simple Moving Average
    NOT EMA(TR, 14) - Exponential Moving Average
    """

    def test_atr_uses_sma_not_ema(self):
        """ATR should use SMA, not EMA.

        SMA gives equal weight to all 14 days.
        EMA gives more weight to recent days.

        This test creates data where SMA and EMA produce measurably different results.
        """
        dates = pd.date_range('2024-01-01', periods=30, freq='D')

        # Create constant true range for first 14 days, then different for last 14
        # SMA will average all 14 equally
        # EMA will weight recent days more heavily

        true_ranges = [10] * 14 + [2] * 16  # High TR early, low TR recently

        prices = []
        highs = []
        lows = []
        base_price = 100

        prev_close = base_price
        for i, tr in enumerate(true_ranges):
            if i == 0:
                low = base_price - tr / 2
                high = base_price + tr / 2
                close = base_price
            else:
                # Create price action that generates the desired true range
                low = prev_close - tr / 3
                high = prev_close + tr / 3
                close = (high + low) / 2

            prices.append(close)
            highs.append(high)
            lows.append(low)
            prev_close = close

        df = pd.DataFrame({
            'open': prices,
            'high': highs,
            'low': lows,
            'close': prices,
            'volume': [1000000] * 30
        }, index=dates)

        calc = TechnicalIndicators(df)
        atr_data = calc._calculate_atr(period=14)

        # Calculate expected SMA manually
        tr_values = []
        for i in range(1, len(df)):
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]
            prev_close = df['close'].iloc[i-1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)

        # Last 14 TR values
        last_14_tr = tr_values[-14:]
        expected_sma = sum(last_14_tr) / 14

        # The ATR should match SMA (simple average), not EMA (weighted)
        # EMA would give lower value because recent TR values are lower (2 vs 10)
        actual_atr = atr_data['atr']

        assert actual_atr == pytest.approx(expected_sma, rel=0.1), (
            f"ATR should use SMA ({expected_sma:.4f}), got {actual_atr:.4f}. "
            f"If using EMA, would be significantly lower due to recent low TR values"
        )

    def test_atr_simple_verification(self):
        """Basic ATR verification with known true ranges."""
        dates = pd.date_range('2024-01-01', periods=20, freq='D')

        # Simple case: constant high-low range
        df = pd.DataFrame({
            'open': [100] * 20,
            'high': [110] * 20,  # Range of 10
            'low': [90] * 20,   # Range of 10
            'close': [100] * 20,
            'volume': [1000000] * 20
        }, index=dates)

        calc = TechnicalIndicators(df)
        atr_data = calc._calculate_atr(period=14)

        # True range each day = max(20, |110-100|, |90-100|) = max(20, 10, 10) = 20
        # SMA of 14 values of 20 = 20
        expected_atr = 20.0

        assert atr_data['atr'] == pytest.approx(expected_atr, rel=0.01), (
            f"ATR should be {expected_atr}, got {atr_data['atr']}"
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
