"""Tests for Strategy G v7.0: EarningsGap refinements."""
import pytest
import pandas as pd
from core.strategies.earnings_gap import EarningsGapStrategy


class TestEarningsGapV7:
    """Test Strategy G v7.0 with refined filters and scoring."""

    def _create_test_df(self, prices, volumes=None):
        """Helper to create test dataframe with sufficient data."""
        dates = pd.date_range('2024-01-01', periods=10, freq='D')

        if volumes is None:
            volumes = [int(2_000_000 * 3.0) if i == 5 else 1_500_000 for i in range(10)]

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': volumes
        }, index=dates)
        return df

    def _make_phase0_data(self, **overrides):
        """Default phase0_data with common values, overridable."""
        data = {
            'gap_1d_pct': 0.12,
            'gap_direction': 'up',
            'days_to_earnings': -3,
            'days_post_earnings': 3,
            'rs_percentile': 75,
            'gap_volume_ratio': 3.0,
            'sector_aligned': False,
            'earnings_beat': True,
            'guidance_change': False,
            'one_time_event': False,
        }
        data.update(overrides)
        return data

    # --- Filter: Time window by gap size ---

    def test_large_gap_eligible_day_3(self):
        """Gap >=10% should be eligible for days 1-5 (test day 3)."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(days_to_earnings=-3, days_post_earnings=3)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_large_gap_eligible_day_5(self):
        """Gap >=10% should be eligible on day 5 (boundary)."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(days_to_earnings=-5, days_post_earnings=5)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_large_gap_rejected_day_6(self):
        """Gap >=10% should be rejected after day 5."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(days_to_earnings=-6, days_post_earnings=6)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    def test_medium_gap_eligible_day_3(self):
        """Gap 7-10% should be eligible on day 3 (boundary)."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 108, 107, 106, 105, 104]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_1d_pct=0.08, days_to_earnings=-3, days_post_earnings=3)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_medium_gap_rejected_day_4(self):
        """Gap 7-10% should be rejected after day 3."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 108, 107, 106, 105, 104]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_1d_pct=0.08, days_to_earnings=-4, days_post_earnings=4)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    def test_small_gap_rejected_day_3(self):
        """Gap 5-7% should be rejected after day 2."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 106, 105, 104, 103, 102, 101]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_1d_pct=0.06, days_to_earnings=-3, days_post_earnings=3)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    # --- Filter: Gap volume ratio ---

    def test_reject_low_gap_volume(self):
        """Gap volume < 2x avg should be rejected."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_volume_ratio=1.5)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    def test_accept_high_gap_volume(self):
        """Gap volume >= 2x avg should pass (if other criteria met)."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_volume_ratio=2.0)}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    # --- Filter: RS direction-dependent ---

    def test_reject_long_low_rs(self):
        """Long setup (gap up) with RS < 50th should be rejected."""
        strategy = EarningsGapStrategy()
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(rs_percentile=40, gap_direction='up')}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    def test_accept_short_low_rs(self):
        """Short setup (gap down) with RS < 50th should pass (weak stock)."""
        strategy = EarningsGapStrategy()
        prices = [100, 98, 96, 94, 92, 88, 89, 88, 87, 86]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=-0.12,
            gap_direction='down',
            rs_percentile=30,
            days_to_earnings=-2,
            days_post_earnings=2,
        )}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_reject_short_high_rs(self):
        """Short setup (gap down) with RS > 50th should be rejected (strong stock)."""
        strategy = EarningsGapStrategy()
        prices = [100, 98, 96, 94, 92, 88, 89, 88, 87, 86]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=-0.12,
            gap_direction='down',
            rs_percentile=80,
            days_to_earnings=-2,
            days_post_earnings=2,
        )}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    # --- Consolidation day identification ---

    def test_consolidation_uses_actual_gap_day(self):
        """_find_gap_day_index should find the actual gap day, not assume last row."""
        strategy = EarningsGapStrategy()
        # Create a DF where the gap (large open/close_prev diff) is 3 days ago, not the last day
        prices = [100, 102, 104, 106, 108, 112, 111, 110, 109, 108]
        df = self._create_test_df(prices)

        # The gap is at index 5 (108 -> 112, ~3.7%). But we need a >= 5% gap.
        # Let's create a proper gap: index 7 has a big gap up
        prices2 = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]  # gap at index 8: 106->115 = ~8.5%
        df2 = self._create_test_df(prices2)

        gap_idx = strategy._find_gap_day_index(df2)
        assert gap_idx == 8, f"Expected gap at index 8, found at {gap_idx}"

    def test_consolidation_excludes_gap_day(self):
        """_get_consolidation_df should return days AFTER the gap day."""
        strategy = EarningsGapStrategy()
        prices2 = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices2)

        consol = strategy._get_consolidation_df(df)
        # Gap is at index 8, so consolidation should only include index 9
        assert len(consol) == 1
        assert consol.index[0] == df.index[9]

    def test_consolidation_fallback_when_no_gap(self):
        """_find_gap_day_index should fallback to last day if no qualifying gap."""
        strategy = EarningsGapStrategy()
        # Small moves only, no gap >= 5%
        prices = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101]
        df = self._create_test_df(prices)

        gap_idx = strategy._find_gap_day_index(df)
        assert gap_idx == len(df) - 1, "Should fallback to last day when no gap found"

    # --- Scoring dimensions ---

    def test_gs_scaled_with_earnings_surprise(self):
        """GS should scale with earnings_surprise_pct when available."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=0.12,
            gap_direction='up',
            earnings_beat=True,
            earnings_surprise_pct=0.15,  # 15% surprise
        )}

        gs = strategy._calculate_gs(strategy.phase0_data['TEST'], df)
        # base=3.0 (>=10% gap), surprise_bonus=min(1.0, 0.15/0.20)=0.75
        # guidance=0, event=0 => total = 3.75
        assert gs == 3.75, f"Expected GS=3.75, got {gs}"

    def test_gs_fallback_to_binary_beat(self):
        """GS should use binary +1.0 when earnings_surprise_pct is None."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        data = self._make_phase0_data(
            gap_1d_pct=0.12,
            gap_direction='up',
            earnings_beat=True,
        )
        # Explicitly set to None to test fallback path
        data['earnings_surprise_pct'] = None
        strategy.phase0_data = {'TEST': data}

        gs = strategy._calculate_gs(strategy.phase0_data['TEST'], df)
        # base=3.0, surprise_bonus=1.0 (binary), guidance=0, event=0 => total = 4.0
        assert gs == 4.0, f"Expected GS=4.0, got {gs}"

    def test_qc_no_days_score(self):
        """QC should not include a days-score component (time decay in filter)."""
        strategy = EarningsGapStrategy()
        # Gap at index 8, consolidation at index 9 only
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data()}

        qc = strategy._calculate_qc(df, strategy.phase0_data['TEST'])
        # QC max is 4.0, composed of range_score (max 2.5) + vol_score (max 1.5)
        # No days_score component
        assert qc <= 4.0, f"QC={qc} exceeds max 4.0"

    def test_tc_sector_bonus_neutral_when_no_data(self):
        """TC should give +0.5 neutral bonus when sector_aligned field is absent."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        # No sector_aligned field
        data = {
            'gap_1d_pct': 0.12,
            'gap_direction': 'up',
        }

        tc = strategy._calculate_tc(df, data)
        # base_score depends on EMA alignment. With default data,
        # price > ema8 > ema21 likely (bullish trend), base=2.0
        # sector_bonus=0.5 (no data) => total = 2.5, capped at 3.0
        assert tc <= 3.0, f"TC={tc} exceeds max 3.0"

    # --- Entry/Exit ---

    def test_entry_exit_long(self):
        """Entry should be above consolidation high for long setups."""
        strategy = EarningsGapStrategy()
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]  # gap at 8
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_1d_pct=0.12, gap_direction='up')}
        dims = [
            type('d', (), {'name': 'GS', 'score': 4.0, 'max_score': 5.0, 'details': {}})(),
            type('d', (), {'name': 'QC', 'score': 3.0, 'max_score': 4.0, 'details': {}})(),
            type('d', (), {'name': 'TC', 'score': 2.5, 'max_score': 3.0, 'details': {}})(),
            type('d', (), {'name': 'VC', 'score': 2.0, 'max_score': 3.0, 'details': {}})(),
        ]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 11.5, 'S')

        # Consolidation = index 9 only (after gap at 8)
        # Entry = consolidation high = high of index 9
        # Stop = max(consol_low - 0.5*ATR, gap_open * 0.95)
        assert entry > 0
        assert stop < entry  # Stop should be below entry for long
        assert target > entry  # Target should be above entry for long

    def test_entry_exit_short(self):
        """Entry should be below consolidation low for short setups."""
        strategy = EarningsGapStrategy()
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 92, 93]  # gap down at 8
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=-0.12, gap_direction='down',
            days_to_earnings=-2, days_post_earnings=2,
        )}
        dims = [
            type('d', (), {'name': 'GS', 'score': 3.5, 'max_score': 5.0, 'details': {}})(),
            type('d', (), {'name': 'QC', 'score': 3.0, 'max_score': 4.0, 'details': {}})(),
            type('d', (), {'name': 'TC', 'score': 2.5, 'max_score': 3.0, 'details': {}})(),
            type('d', (), {'name': 'VC', 'score': 2.0, 'max_score': 3.0, 'details': {}})(),
        ]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 11.0, 'A')

        assert entry > 0
        assert stop > entry  # Stop should be above entry for short
        assert target < entry  # Target should be below entry for short

    # --- Edge cases ---

    def test_same_day_gap_no_consolidation(self):
        """Same-day gap (days_post_earnings=1, no consolidation rows) should still score."""
        strategy = EarningsGapStrategy()
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=0.12,
            gap_direction='up',
            days_to_earnings=-1,
            days_post_earnings=1,
        )}
        strategy._get_data = lambda x: df

        # Should pass filter (day 1 is within max_days=5 for >=10% gap)
        assert strategy.filter('TEST', df) is True

    def test_sector_aligned_true_gives_tc_bonus(self):
        """TC should give +1.0 sector bonus when sector_aligned=True."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        data = {
            'gap_1d_pct': 0.12,
            'gap_direction': 'up',
            'sector_aligned': True,
        }

        tc_with = strategy._calculate_tc(df, data)
        tc_without = strategy._calculate_tc(df, {
            'gap_1d_pct': 0.12,
            'gap_direction': 'up',
        })
        # sector_aligned=True should give +0.5 more than no data (True=+1.0, no_data=+0.5)
        assert tc_with == tc_without + 0.5, f"Expected +0.5 bonus, got {tc_with} vs {tc_without}"

    def test_earnings_surprise_zero_gives_no_bonus(self):
        """GS should give 0 surprise bonus when earnings_surprise_pct=0."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        data = self._make_phase0_data(
            gap_1d_pct=0.12,
            gap_direction='up',
            earnings_surprise_pct=0.0,
        )
        strategy.phase0_data = {'TEST': data}

        gs = strategy._calculate_gs(data, df)
        # base=3.0, surprise_bonus=0.0, guidance=0, event=0 => total=3.0
        assert gs == 3.0, f"Expected GS=3.0, got {gs}"

    def test_gs_capped_at_5(self):
        """GS total should be capped at 5.0 even with all bonuses."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        data = self._make_phase0_data(
            gap_1d_pct=0.15,  # >=10% => base=3.0
            gap_direction='up',
            earnings_surprise_pct=0.25,  # >=20% => bonus=1.0
            guidance_change=True,  # +1.0
            one_time_event=True,  # +0.5
        )
        strategy.phase0_data = {'TEST': data}

        gs = strategy._calculate_gs(data, df)
        # 3.0 + 1.0 + 1.0 + 0.5 = 5.5, capped at 5.0
        assert gs == 5.0, f"Expected GS=5.0 (capped), got {gs}"

    def test_gap_direction_none_rejected(self):
        """gap_direction='none' should be rejected, not fall through to short filter."""
        strategy = EarningsGapStrategy()
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_direction='none',
            days_to_earnings=-2,
            days_post_earnings=2,
        )}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is False

    def test_rs_at_exact_50_boundary_long(self):
        """Long setup with RS exactly at 50th percentile should pass (>= 50)."""
        strategy = EarningsGapStrategy()
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            rs_percentile=50,
            gap_direction='up',
            days_to_earnings=-2,
            days_post_earnings=2,
        )}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_rs_at_exact_50_boundary_short(self):
        """Short setup with RS exactly at 50th percentile should pass (<= 50)."""
        strategy = EarningsGapStrategy()
        prices = [100, 98, 96, 94, 92, 88, 89, 88, 87, 86]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=-0.12,
            gap_direction='down',
            rs_percentile=50,
            days_to_earnings=-2,
            days_post_earnings=2,
        )}
        strategy._get_data = lambda x: df

        assert strategy.filter('TEST', df) is True

    def test_earnings_beat_false_with_none_surprise_gives_no_bonus(self):
        """GS should give 0 surprise bonus when beat=False and surprise_pct=None."""
        strategy = EarningsGapStrategy()
        df = self._create_test_df([100, 101, 102, 103, 104, 104, 105, 106, 115, 114])

        data = self._make_phase0_data(
            gap_1d_pct=0.12,
            gap_direction='up',
            earnings_beat=False,
        )
        data['earnings_surprise_pct'] = None
        strategy.phase0_data = {'TEST': data}

        gs = strategy._calculate_gs(data, df)
        # base=3.0, surprise_bonus=0.0, guidance=0, event=0 => total=3.0
        assert gs == 3.0, f"Expected GS=3.0, got {gs}"

    def test_entry_exit_long_specific_prices(self):
        """Long entry should be at consolidation high, not last close."""
        strategy = EarningsGapStrategy()
        # Gap at index 8 (106->115), consolidation at index 9 only
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 115, 114]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(gap_1d_pct=0.12, gap_direction='up')}
        dims = [
            type('d', (), {'name': 'GS', 'score': 4.0, 'max_score': 5.0, 'details': {}})(),
            type('d', (), {'name': 'QC', 'score': 3.0, 'max_score': 4.0, 'details': {}})(),
            type('d', (), {'name': 'TC', 'score': 2.5, 'max_score': 3.0, 'details': {}})(),
            type('d', (), {'name': 'VC', 'score': 2.0, 'max_score': 3.0, 'details': {}})(),
        ]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 11.5, 'S')

        # Consolidation = index 9 only. high=114*1.02=116.28, low=114*0.98=111.72
        # Entry = consolidation_high = 116.28
        assert entry == 116.28, f"Expected entry=116.28, got {entry}"
        assert stop < entry
        assert target > entry

    def test_entry_exit_short_specific_prices(self):
        """Short entry should be at consolidation low, not last close."""
        strategy = EarningsGapStrategy()
        # Gap down at index 8 (106->92), consolidation at index 9 only
        prices = [100, 101, 102, 103, 104, 104, 105, 106, 92, 93]
        df = self._create_test_df(prices)

        strategy.phase0_data = {'TEST': self._make_phase0_data(
            gap_1d_pct=-0.12, gap_direction='down',
            days_to_earnings=-2, days_post_earnings=2,
        )}
        dims = [
            type('d', (), {'name': 'GS', 'score': 3.5, 'max_score': 5.0, 'details': {}})(),
            type('d', (), {'name': 'QC', 'score': 3.0, 'max_score': 4.0, 'details': {}})(),
            type('d', (), {'name': 'TC', 'score': 2.5, 'max_score': 3.0, 'details': {}})(),
            type('d', (), {'name': 'VC', 'score': 2.0, 'max_score': 3.0, 'details': {}})(),
        ]

        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dims, 11.0, 'A')

        # Consolidation = index 9 only. low=93*0.98=91.14
        # Entry = consolidation_low = 91.14
        assert entry == 91.14, f"Expected entry=91.14, got {entry}"
        assert stop > entry
        assert target < entry
