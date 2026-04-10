"""Tests for Strategy D (DistributionTop) v7.1.

v7.1 changes tested:
- Removed market_cap, dollar_volume, ADR, 8%-from-high, EMA8/EMA21 filter gates
- Unified resistance detection to phase0 only (no _detect_resistance_level)
- EMA50 slope in TQ scoring replaces EMA8/EMA21 gate
- Prior trend requirement (25% rally from 52w low)
- TQ re-balance: EMA 2.0 + slope 0.5 + sector 1.0 + trend 0.5 = 4.0
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.strategies.distribution_top import DistributionTopStrategy
from core.indicators import TechnicalIndicators


class TestDistributionTopV71:
    """Test Strategy D v7.1 changes."""

    # =========================================================================
    # PARAMS
    # =========================================================================

    def test_params_updated(self):
        """PARAMS should not have removed fields."""
        strategy = DistributionTopStrategy()
        assert 'min_market_cap' not in strategy.PARAMS
        assert 'min_dollar_volume' not in strategy.PARAMS
        assert 'min_atr_pct' not in strategy.PARAMS
        assert 'max_distance_from_60d_high' not in strategy.PARAMS
        assert 'ema_alignment_tolerance' not in strategy.PARAMS
        assert 'prior_trend_rally_pct' in strategy.PARAMS
        assert strategy.PARAMS['prior_trend_rally_pct'] == 0.25

    # =========================================================================
    # FILTER: Prior trend requirement
    # =========================================================================

    def test_filter_prior_trend_accepts_25pct_rally(self):
        """Filter should accept stock with >= 25% rally from 52w low."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        # Create uptrend: low ~80 at day 0, current ~105 = 31% rally
        base = np.linspace(80, 105, 260)
        opens = base * 1.005
        closes = base
        highs = base * 1.015
        lows = base * 0.985
        volumes = [1_000_000] * 260

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {
                'current_price': closes[-1],
                'resistances': [108],
            }
        }

        result = strategy.filter('TEST', df)
        assert result is True, "Should accept stock with >25% rally"

    def test_filter_prior_trend_rejects_weak_stock(self):
        """Filter should reject stock with < 25% rally from 52w low."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        # Flat stock: 98-100 range = minimal rally
        base = 99 + np.sin(np.linspace(0, 10, 260)) * 1
        opens = base * 1.002
        closes = base
        highs = base * 1.01
        lows = base * 0.99
        volumes = [1_000_000] * 260

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {
                'current_price': closes[-1],
                'resistances': [102],
            }
        }

        result = strategy.filter('TEST', df)
        assert result is False, "Should reject stock with <25% rally"

    # =========================================================================
    # FILTER: Regime + volume
    # =========================================================================

    def test_filter_rejects_low_volume(self):
        """Filter should reject stock with avg volume < 100K."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        base = np.linspace(80, 105, 260)
        df = pd.DataFrame({
            'open': base * 1.005, 'high': base * 1.015,
            'low': base * 0.985, 'close': base,
            'volume': [50_000] * 260  # Below 100K
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {'current_price': base[-1], 'resistances': [108]}
        }

        result = strategy.filter('TEST', df)
        assert result is False, "Should reject low volume stock"

    def test_regime_filter_passes_in_neutral(self):
        """Neutral regime should not trigger sector weakness veto."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        base = np.linspace(80, 105, 260)
        df = pd.DataFrame({
            'open': base * 1.005, 'high': base * 1.015,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 260
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {'current_price': base[-1], 'resistances': [108]}
        }

        result = strategy.filter('TEST', df)
        # Passes all gates: listing days, volume, trend, resistance
        assert result is True

    def test_regime_filter_requires_weak_sector_in_bull(self):
        """In bull regime, filter should require sector ETF < EMA50."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        base = np.linspace(80, 105, 260)
        df = pd.DataFrame({
            'open': base * 1.005, 'high': base * 1.015,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 260
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'bull_strong'
        strategy.phase0_data = {
            'TEST': {'current_price': base[-1], 'resistances': [108], 'sector': 'Technology'}
        }

        # Mock db with strong sector ETF (rising, above EMA50)
        strong_dates = pd.date_range('2023-01-01', periods=260, freq='D')
        strong_prices = np.linspace(180, 220, 260)
        strong_etf = pd.DataFrame({'close': strong_prices}, index=strong_dates)
        strategy.db = type('MockDB', (), {'get_etf_cache': lambda s, x: strong_etf})()

        result = strategy.filter('TEST', df)
        assert result is False, "Should reject in bull regime with strong sector"

    # =========================================================================
    # FILTER: No removed gates
    # =========================================================================

    def test_filter_no_longer_checks_adr(self):
        """Filter should not reject based on ADR (moved to VC scoring)."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        base = np.linspace(80, 105, 260)
        # Low volatility stock (would have failed old ADR check)
        df = pd.DataFrame({
            'open': base * 1.001, 'high': base * 1.003,
            'low': base * 0.999, 'close': base,
            'volume': [1_000_000] * 260
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {'current_price': base[-1], 'resistances': [108]}
        }

        result = strategy.filter('TEST', df)
        assert result is True, "Should not reject for low ADR"

    def test_filter_no_longer_checks_ema8_ema21(self):
        """Filter should not reject based on EMA8/EMA21 (replaced by slope)."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        base = np.linspace(80, 105, 260)
        df = pd.DataFrame({
            'open': base * 1.005, 'high': base * 1.015,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 260
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy._current_regime = 'neutral'
        strategy.phase0_data = {
            'TEST': {'current_price': base[-1], 'resistances': [108]}
        }

        # Even if EMA8 > EMA21 (uptrend), filter should not reject
        # because EMA8/EMA21 check was removed
        result = strategy.filter('TEST', df)
        assert result is True

    # =========================================================================
    # TQ SCORING: EMA alignment + EMA50 slope + sector + prior trend
    # =========================================================================

    def test_tq_ema_alignment_strong_bearish(self):
        """TQ EMA alignment: price<EMA50 AND EMA8<EMA21 = 2.0."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        # Clear downtrend: price declining
        base = np.linspace(110, 90, 90)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 90
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {'TEST': {'sector': '', 'ret_6m': 0.05}}

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df, 'TEST')

        # EMA alignment (2.0) + sector unknown (0.3) + trend weak (0.0) = 2.3
        # EMA50 slope: declining = 0.5
        assert tq >= 2.0, f"TQ should have EMA alignment points, got {tq}"

    def test_tq_ema50_slope_declining_scores(self):
        """TQ EMA50 slope: declining = 0.5."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        # Declining trend
        base = np.linspace(110, 85, 90)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 90
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {'TEST': {'sector': '', 'ret_6m': 0.05}}

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df, 'TEST')

        # Should get EMA50 slope points for declining
        assert tq > 0, f"TQ should have some points, got {tq}"

    def test_tq_sector_weakness_scores(self):
        """TQ sector weakness: sector ETF < EMA50 = 1.0."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        base = np.linspace(110, 90, 90)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 90
        }, index=dates)

        strategy = DistributionTopStrategy()
        # Mock db with weak sector ETF (declining, below EMA50)
        weak_dates = pd.date_range('2023-01-01', periods=260, freq='D')
        weak_prices = np.linspace(200, 170, 260)
        weak_etf = pd.DataFrame({'close': weak_prices}, index=weak_dates)
        strategy.db = type('MockDB', (), {'get_etf_cache': lambda s, x: weak_etf})()
        strategy.phase0_data = {'TEST': {'sector': 'Technology', 'ret_6m': 0.05}}

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df, 'TEST')

        # Should get sector weakness points (1.0)
        assert tq >= 1.0, f"TQ should have sector weakness points, got {tq}"

    def test_tq_prior_trend_scores(self):
        """TQ prior trend: ret_6m > 20% = 0.5."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        base = np.linspace(110, 90, 90)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 90
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {'TEST': {'sector': '', 'ret_6m': 0.25}}

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df, 'TEST')

        # Should get prior trend points (0.5) for ret_6m > 20%
        assert tq >= 0.5, f"TQ should have prior trend points, got {tq}"

    def test_tq_max_is_4(self):
        """TQ should not exceed 4.0."""
        dates = pd.date_range('2023-01-01', periods=260, freq='D')
        # Strong prior uptrend now reversing
        base = np.concatenate([np.linspace(80, 120, 180), np.linspace(120, 105, 80)])
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [1_000_000] * 260
        }, index=dates)

        strategy = DistributionTopStrategy()
        weak_dates = pd.date_range('2023-01-01', periods=260, freq='D')
        weak_prices = np.linspace(200, 170, 260)
        weak_etf = pd.DataFrame({'close': weak_prices}, index=weak_dates)
        strategy.db = type('MockDB', (), {'get_etf_cache': lambda s, x: weak_etf})()
        strategy.phase0_data = {'TEST': {'sector': 'Technology', 'ret_6m': 0.30}}

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        tq = strategy._calculate_tq(ind, df, 'TEST')

        assert tq <= 4.0, f"TQ should not exceed 4.0, got {tq}"

    # =========================================================================
    # RL SCORING: Unified to phase0
    # =========================================================================

    def test_rl_interval_scoring_14d_or_more(self):
        """RL interval >= 14d = 1.5."""
        strategy = DistributionTopStrategy()
        level = {'touches': 5, 'avg_days_between': 15, 'width_atr': 1.5}
        score = strategy._calculate_rl_interval_score(level)
        assert score == 1.5

    def test_rl_interval_scoring_7_to_14d(self):
        """RL interval 7-14d = 0.8-1.5 interpolated."""
        strategy = DistributionTopStrategy()
        level = {'avg_days_between': 10, 'width_atr': 1.5}
        score = strategy._calculate_rl_interval_score(level)
        assert 0.8 <= score <= 1.5, f"Got {score}"

    def test_rl_interval_scoring_5_to_7d(self):
        """RL interval 5-7d = 0.3-0.8 interpolated."""
        strategy = DistributionTopStrategy()
        level = {'avg_days_between': 6, 'width_atr': 1.5}
        score = strategy._calculate_rl_interval_score(level)
        assert 0.3 <= score <= 0.8, f"Got {score}"

    def test_rl_interval_scoring_less_than_5d(self):
        """RL interval < 5d = 0."""
        strategy = DistributionTopStrategy()
        level = {'avg_days_between': 4, 'width_atr': 1.5}
        score = strategy._calculate_rl_interval_score(level)
        assert score == 0.0

    def test_rl_from_phase0_resistances(self):
        """RL should score from phase0-built level."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        # Create stock with clear resistance at ~100
        opens, closes, highs, lows = [], [], [], []
        for i in range(90):
            if i in [15, 30, 45, 60, 75]:  # 5 touches at resistance
                opens.append(99.8)
                closes.append(99.2)
                highs.append(100.1)
                lows.append(99.0)
            else:
                p = 95 + (i % 15) * 0.3
                opens.append(p * 1.005)
                closes.append(p)
                highs.append(p * 1.01)
                lows.append(p * 0.99)

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': [1_000_000] * 90
        }, index=dates)

        strategy = DistributionTopStrategy()
        level = strategy._build_level_from_phase0(df, resistances=[100.1])
        assert level is not None, "Should build level from phase0 resistances"
        assert level['touches'] >= 2, f"Should detect touches, got {level['touches']}"

        rl = strategy._calculate_rl(df, level, resistances=[100.1])
        assert rl > 0, f"RL should score > 0, got {rl}"

    # =========================================================================
    # DS SCORING
    # =========================================================================

    def test_ds_detects_distribution(self):
        """DS should count heavy volume failed up-days at resistance."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        opens, closes, highs, lows, volumes = [], [], [], [], []

        for i in range(90):
            if i in [60, 62, 65]:
                opens.append(99.5)
                closes.append(98.5)  # Close lower
                highs.append(100.5)  # Touched resistance
                lows.append(98.0)
                volumes.append(2_000_000)  # Heavy volume
            else:
                p = 95 + (i % 15) * 0.3
                opens.append(p * 1.005)
                closes.append(p)
                highs.append(p * 1.01)
                lows.append(p * 0.99)
                volumes.append(500_000)

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        level = {'high': 100.5, 'touches': 3, 'width_atr': 1.0, 'avg_days_between': 10}
        ds = strategy._calculate_ds(df, level, resistances=[100.5])
        assert ds >= 2.0, f"DS should be >= 2.0 with 3 distribution days, got {ds}"

    def test_ds_no_distribution_on_actual_up_days(self):
        """DS should NOT score actual up-days as distribution."""
        dates = pd.date_range('2023-01-01', periods=90, freq='D')
        opens, closes, highs, lows, volumes = [], [], [], [], []

        for i in range(90):
            if i in [60, 62, 65]:
                opens.append(98.0)
                closes.append(100.0)  # Close HIGHER (actual up-day)
                highs.append(100.5)
                lows.append(97.5)
                volumes.append(2_000_000)
            else:
                opens.append(99.0)
                closes.append(99.0)
                highs.append(99.5)
                lows.append(98.5)
                volumes.append(500_000)

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        level = {'high': 100.5, 'touches': 3, 'width_atr': 1.0, 'avg_days_between': 10}
        ds = strategy._calculate_ds(df, level, resistances=[100.5])
        assert ds < 1.0, f"DS should be low for actual up-days, got {ds}"

    # =========================================================================
    # VC SCORING
    # =========================================================================

    def test_vc_follow_through_two_down_days(self):
        """VC: 2 down-days in last 2 sessions = +1.0 follow-through."""
        dates = pd.date_range('2023-01-01', periods=60, freq='D')
        opens = [100] * 57 + [98, 96, 94]
        closes = [100] * 57 + [97, 95, 92]
        highs = [101] * 57 + [99, 97, 95]
        lows = [99] * 57 + [96, 94, 91]
        volumes = [1_000_000] * 57 + [3_000_000, 1_500_000, 2_000_000]

        df = pd.DataFrame({
            'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': volumes
        }, index=dates)

        strategy = DistributionTopStrategy()
        vc = strategy._calculate_vc(df)
        assert vc > 1.0, f"VC should include follow-through, got {vc}"

    # =========================================================================
    # ENTRY/EXIT
    # =========================================================================

    def test_entry_clv_validation(self):
        """Entry requires CLV <= 0.35 (close near low)."""
        dates = pd.date_range('2023-01-01', periods=60, freq='D')
        base = np.linspace(105, 94, 60)

        # Low CLV: close near low (bearish, good for short)
        df_low = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [2_000_000] * 59 + [4_000_000]
        }, index=dates)

        # High CLV: close near high (bullish, bad for short)
        df_high = pd.DataFrame({
            'open': base * 0.99, 'high': base * 1.015,
            'low': base * 0.985, 'close': base * 1.01,
            'volume': [2_000_000] * 60
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {'resistances': [110], 'current_price': base[-1], 'days_to_earnings': 20}
        }

        dims = [
            type('SD', (), {'name': n, 'score': 2.0, 'max_score': 4.0, 'details': {}})()
            for n in ['TQ', 'RL', 'DS']
        ] + [type('SD', (), {'name': 'VC', 'score': 1.5, 'max_score': 3.0, 'details': {}})()]

        # High CLV should reject
        e, s, t = strategy.calculate_entry_exit('TEST', df_high, dims, 7.5, '2')
        assert e is None, "Should reject high CLV"

        # Low CLV should accept
        e, s, t = strategy.calculate_entry_exit('TEST', df_low, dims, 7.5, '2')
        assert e is not None, "Should accept low CLV"

    def test_entry_stop_uses_105_cap(self):
        """Stop loss uses entry * 1.05 cap."""
        dates = pd.date_range('2023-01-01', periods=60, freq='D')
        base = np.linspace(105, 94, 60)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [2_000_000] * 59 + [4_000_000]
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {'resistances': [110], 'current_price': base[-1], 'days_to_earnings': 20}
        }

        dims = [
            type('SD', (), {'name': n, 'score': 2.0, 'max_score': 4.0, 'details': {}})()
            for n in ['TQ', 'RL', 'DS']
        ] + [type('SD', (), {'name': 'VC', 'score': 1.5, 'max_score': 3.0, 'details': {}})()]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 7.5, 'B')
        assert entry is not None
        assert stop <= round(entry * 1.05, 2), f"Stop {stop} exceeds 5% cap"

    def test_entry_rejects_near_earnings(self):
        """Entry rejected within 5 days of earnings."""
        dates = pd.date_range('2023-01-01', periods=60, freq='D')
        base = np.linspace(105, 94, 60)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [2_000_000] * 59 + [4_000_000]
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {'resistances': [110], 'current_price': base[-1], 'days_to_earnings': 3}
        }

        dims = [
            type('SD', (), {'name': n, 'score': 2.0, 'max_score': 4.0, 'details': {}})()
            for n in ['TQ', 'RL', 'DS']
        ] + [type('SD', (), {'name': 'VC', 'score': 1.5, 'max_score': 3.0, 'details': {}})()]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 7.5, 'B')
        assert entry is None, "Should reject near earnings"

    def test_entry_accepts_far_from_earnings(self):
        """Entry accepted when > 5 days from earnings."""
        dates = pd.date_range('2023-01-01', periods=60, freq='D')
        base = np.linspace(105, 94, 60)
        df = pd.DataFrame({
            'open': base * 1.01, 'high': base * 1.02,
            'low': base * 0.985, 'close': base,
            'volume': [2_000_000] * 59 + [4_000_000]
        }, index=dates)

        strategy = DistributionTopStrategy()
        strategy.phase0_data = {
            'TEST': {'resistances': [110], 'current_price': base[-1], 'days_to_earnings': 15}
        }

        dims = [
            type('SD', (), {'name': n, 'score': 2.0, 'max_score': 4.0, 'details': {}})()
            for n in ['TQ', 'RL', 'DS']
        ] + [type('SD', (), {'name': 'VC', 'score': 1.5, 'max_score': 3.0, 'details': {}})()]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 7.5, 'B')
        assert entry is not None, "Should accept far from earnings"
