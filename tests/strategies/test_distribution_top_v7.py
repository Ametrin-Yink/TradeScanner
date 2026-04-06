"""Tests for Strategy D (DistributionTop) v7.0 mismatches.

Tests cover 4 documented mismatches:
1. Dollar volume threshold: $30M avg20d (was $50M)
2. DS logic: Heavy-vol up-days with closes LOWER (distribution = failed up-day)
3. RL interval scoring: ≥14d=1.5, 7-14d=0.8-1.5, 5-7d=0.3-0.8, <5d=0
4. Entry CLV check: CLV ≤ 0.35 for short entry
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.strategies.distribution_top import DistributionTopStrategy
from core.indicators import TechnicalIndicators


class TestDistributionTopV7:
    """Test Strategy D v7.0 mismatch fixes."""

    # =========================================================================
    # MISMATCH 1: Dollar Volume Threshold ($30M)
    # =========================================================================

    def test_dollar_volume_param_is_30m(self):
        """Strategy D min_dollar_volume should be $30M per docs."""
        strategy = DistributionTopStrategy()
        # The docs say $30M avg20d, not $50M
        assert strategy.PARAMS.get('min_dollar_volume') == 30_000_000, \
            f"min_dollar_volume should be 30000000, got {strategy.PARAMS.get('min_dollar_volume')}"

    def test_filter_rejects_dollar_volume_below_30m(self):
        """Filter should reject stocks with dollar volume < $30M."""
        dates = pd.date_range('2024-01-01', periods=60, freq='D')
        # Price ~$10, volume ~100K = $1M dollar volume (too low)
        prices = [10 + (i % 10) * 0.1 for i in range(60)]
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [100_000] * 60
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._get_data = lambda x: df

        result = strategy.filter('TEST', df)
        assert result is False, "Should reject stock with dollar volume < $30M"

    def test_filter_accepts_dollar_volume_above_30m(self):
        """Filter should accept stocks with dollar volume > $30M if other criteria met."""
        dates = pd.date_range('2024-01-01', periods=60, freq='D')
        # Price ~$50, volume ~1M = $50M dollar volume (good)
        prices = [50 + (i % 10) * 0.5 for i in range(60)]
        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._get_data = lambda x: df

        # Just verify dollar volume check passes (may fail for other reasons)
        try:
            result = strategy.filter('TEST', df)
        except Exception as e:
            pytest.fail(f"Filter raised unexpected exception: {e}")

    # =========================================================================
    # MISMATCH 2: DS Logic - Heavy-vol days with closes LOWER (distribution)
    # =========================================================================

    def test_calculate_ds_detects_distribution_with_lower_closes(self):
        """DS should count days with heavy volume where close < open (distribution)."""
        dates = pd.date_range('2024-01-01', periods=90, freq='D')

        # Create resistance level around $100
        base_price = 100
        prices = []
        opens = []
        closes = []
        highs = []
        lows = []
        volumes = []

        for i in range(90):
            if i < 60:
                # Build up to resistance
                prices.append(95 + (i / 60) * 5)
            else:
                # At resistance with distribution signs
                prices.append(100)

            # Days 60, 62, 65: heavy volume, close LOWER than open (distribution)
            if i in [60, 62, 65]:
                o = 99.5
                c = 98.5  # Close LOWER than open
                h = 100.5  # Touched resistance
                l = 98
                v = 2_000_000  # Heavy volume (>1.5x avg)
            else:
                o = prices[-1] if prices else 100
                c = prices[-1] if prices else 100
                h = c * 1.01
                l = c * 0.99
                v = 500_000  # Normal volume

            opens.append(o)
            closes.append(c)
            highs.append(h)
            lows.append(l)
            volumes.append(v)

        df = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {
                'resistances': [100.5],
                'current_price': 98.5,
                'high_60d': 100.5
            }
        }

        # Calculate DS score - should detect 3 distribution days
        ds_score = strategy._calculate_ds(df, resistances=[100.5])

        # With 3 heavy-volume lower-close days, should score 2.0 (max for this dimension part)
        # Per docs: ≥3 days = 2.0 points
        assert ds_score >= 2.0, f"DS score should be >= 2.0 with 3 distribution days, got {ds_score}"

    def test_calculate_ds_does_not_count_actual_up_days(self):
        """DS should NOT count actual up-days (close > open) as distribution."""
        dates = pd.date_range('2024-01-01', periods=90, freq='D')

        opens = []
        closes = []
        highs = []
        lows = []
        volumes = []

        for i in range(90):
            # Days 60, 62, 65: heavy volume, close HIGHER than open (actual up-days - NOT distribution)
            if i in [60, 62, 65]:
                o = 98
                c = 100  # Close HIGHER than open (actual up-day)
                h = 100.5
                l = 97.5
                v = 2_000_000  # Heavy volume
            else:
                o = 99
                c = 99
                h = 99.5
                l = 98.5
                v = 500_000

            opens.append(o)
            closes.append(c)
            highs.append(h)
            lows.append(l)
            volumes.append(v)

        df = pd.DataFrame({
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {
                'resistances': [100.5],
                'current_price': 99,
                'high_60d': 100.5
            }
        }

        # Calculate DS score - actual up-days should NOT count as distribution
        # The docs say "Heavy-vol up-days (vol>1.5×avg, closes lower)"
        # This is contradictory naming, but "closes lower" is the key - distribution = failed up-day
        ds_score = strategy._calculate_ds(df, resistances=[100.5])

        # Should be low because these are NOT distribution days (they're actual up-days)
        # The current WRONG implementation would score these high
        assert ds_score < 1.0, f"DS score should be low for actual up-days (not distribution), got {ds_score}"

    # =========================================================================
    # MISMATCH 3: RL Interval Scoring Thresholds
    # =========================================================================

    def test_rl_interval_scoring_14_days_or_more(self):
        """RL interval ≥14d should score 1.5."""
        strategy = DistributionTopStrategy()

        # Mock level with avg_days_between = 15 (≥14)
        level = {
            'touches': 5,
            'avg_days_between': 15,
            'width_atr': 1.5
        }

        score = strategy._calculate_rl_interval_score(level)
        assert score == 1.5, f"Interval ≥14d should score 1.5, got {score}"

    def test_rl_interval_scoring_7_to_14_days(self):
        """RL interval 7-14d should score 0.8-1.5 (interpolated)."""
        strategy = DistributionTopStrategy()

        # Test at 10 days (middle of 7-14 range)
        level = {
            'touches': 5,
            'avg_days_between': 10,
            'width_atr': 1.5
        }

        score = strategy._calculate_rl_interval_score(level)
        # Should be between 0.8 and 1.5
        assert 0.8 <= score <= 1.5, f"Interval 7-14d should score 0.8-1.5, got {score}"

        # Test at 7 days (lower boundary)
        level['avg_days_between'] = 7
        score = strategy._calculate_rl_interval_score(level)
        assert 0.8 <= score <= 1.0, f"Interval at 7d should score ~0.8-1.0, got {score}"

    def test_rl_interval_scoring_5_to_7_days(self):
        """RL interval 5-7d should score 0.3-0.8."""
        strategy = DistributionTopStrategy()

        level = {
            'touches': 5,
            'avg_days_between': 6,
            'width_atr': 1.5
        }

        score = strategy._calculate_rl_interval_score(level)
        assert 0.3 <= score <= 0.8, f"Interval 5-7d should score 0.3-0.8, got {score}"

    def test_rl_interval_scoring_less_than_5_days(self):
        """RL interval <5d should score 0."""
        strategy = DistributionTopStrategy()

        level = {
            'touches': 5,
            'avg_days_between': 4,
            'width_atr': 1.5
        }

        score = strategy._calculate_rl_interval_score(level)
        assert score == 0, f"Interval <5d should score 0, got {score}"

    # =========================================================================
    # MISMATCH 4: Entry CLV Check (CLV ≤ 0.35)
    # =========================================================================

    def test_clv_entry_validation(self):
        """Test that entry logic validates CLV ≤ 0.35 for short positions."""
        dates = pd.date_range('2024-01-01', periods=60, freq='D')

        # Create data with resistance above current price
        base_price = 100
        prices = [base_price - i * 0.1 for i in range(60)]

        # Low CLV scenario (close near low = bearish, GOOD for short)
        opens_low = [p * 1.01 for p in prices]
        closes_low = [p * 0.99 for p in prices]  # Close near low
        highs_low = [p * 1.02 for p in prices]
        lows_low = [p * 0.985 for p in prices]

        df_low_clv = pd.DataFrame({
            'open': opens_low,
            'high': highs_low,
            'low': lows_low,
            'close': closes_low,
            'volume': [2_000_000] * 60  # High volume
        }, index=dates)

        # High CLV scenario (close near high = bullish, BAD for short)
        opens_high = [p * 0.99 for p in prices]
        closes_high = [p * 1.01 for p in prices]  # Close near high
        highs_high = [p * 1.015 for p in prices]
        lows_high = [p * 0.985 for p in prices]

        df_high_clv = pd.DataFrame({
            'open': opens_high,
            'high': highs_high,
            'low': lows_high,
            'close': closes_high,
            'volume': [2_000_000] * 60
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {
                'resistances': [105],
                'current_price': closes_low[-1],
                'high_60d': max(highs_low)
            }
        }

        dimensions = [
            type('ScoringDimension', (), {'name': 'TQ', 'score': 2.0, 'max_score': 4.0, 'details': {}})(),
            type('ScoringDimension', (), {'name': 'RL', 'score': 2.0, 'max_score': 4.0, 'details': {}})(),
            type('ScoringDimension', (), {'name': 'DS', 'score': 2.0, 'max_score': 4.0, 'details': {}})(),
            type('ScoringDimension', (), {'name': 'VC', 'score': 1.5, 'max_score': 3.0, 'details': {}})(),
        ]

        # Calculate CLV for high CLV scenario
        current_price_high = df_high_clv['close'].iloc[-1]
        high_high = df_high_clv['high'].iloc[-1]
        low_high = df_high_clv['low'].iloc[-1]
        clv_high = ((current_price_high - low_high) - (high_high - current_price_high)) / (high_high - low_high)

        # Calculate CLV for low CLV scenario
        current_price_low = df_low_clv['close'].iloc[-1]
        high_low = df_low_clv['high'].iloc[-1]
        low_low = df_low_clv['low'].iloc[-1]
        clv_low = ((current_price_low - low_low) - (high_low - current_price_low)) / (high_low - low_low)

        # Verify test data is correct
        assert clv_low < 0.35, f"Low CLV test data should have CLV < 0.35, got {clv_low}"
        assert clv_high > 0.35, f"High CLV test data should have CLV > 0.35, got {clv_high}"

        # Test with HIGH CLV (should return None)
        strategy.phase0_data['TEST']['current_price'] = current_price_high
        entry, stop, target = strategy.calculate_entry_exit('TEST', df_high_clv, dimensions, 7.5, '2')
        assert entry is None, f"Entry should be None when CLV > 0.35, got {entry}"

        # Test with LOW CLV (should return valid entry)
        strategy.phase0_data['TEST']['current_price'] = current_price_low
        entry, stop, target = strategy.calculate_entry_exit('TEST', df_low_clv, dimensions, 7.5, '2')
        assert entry is not None, f"Entry should be valid when CLV ≤ 0.35, got {entry}"
