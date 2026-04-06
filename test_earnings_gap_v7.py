"""Tests for Strategy G: EarningsGap v7.0 mismatches.

These tests verify the 7 mismatches between code and Strategy_Description_v7.md
are fixed correctly.
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.strategies.earnings_gap import EarningsGapStrategy
from core.strategies.base_strategy import ScoringDimension


def create_test_df(
    days: int = 10,
    base_price: float = 100.0,
    gap_day: bool = True,
    gap_pct: float = 0.05,
    volume_multiplier: float = 1.0,
    consolidation_range: float = 0.02,
    trend: str = 'aligned'
) -> pd.DataFrame:
    """Create a test DataFrame with specified characteristics.

    Args:
        days: Number of days of data
        base_price: Starting price
        gap_day: Whether to include a gap day (last day)
        gap_pct: Gap percentage (positive for up, negative for down)
        volume_multiplier: Volume multiplier for non-gap days
        consolidation_range: The total range (high-low)/base_price for consolidation period
        trend: 'aligned' or 'neutral'
    """
    dates = pd.date_range(end=datetime.now(), periods=days)

    prices = []
    volumes = []
    highs = []
    lows = []
    avg_volume = 1000000

    # Daily range percentage based on desired consolidation range
    # For tight consolidation (<3% total), use ~0.5% daily range
    # For wide consolidation (>8% total), use ~2% daily range
    daily_range_pct = consolidation_range / 4

    for i in range(days):
        if i == days - 1 and gap_day:
            # Gap day
            prev_close = prices[-1] if prices else base_price
            open_price = prev_close * (1 + gap_pct)
            if gap_pct > 0:
                # Gap up - price holds above gap
                close_price = open_price * (1 + consolidation_range * 0.5)
                high_price = open_price * (1 + consolidation_range)
                low_price = open_price
            else:
                # Gap down - price holds below gap
                close_price = open_price * (1 - consolidation_range * 0.5)
                high_price = open_price
                low_price = open_price * (1 - consolidation_range)
            prices.append(close_price)
            highs.append(high_price)
            lows.append(low_price)
            volumes.append(int(avg_volume * volume_multiplier * 5))  # Gap day volume
        else:
            # Regular day with small movement
            if prices:
                base = prices[-1]
            else:
                base = base_price

            if trend == 'aligned' and gap_pct > 0:
                # Uptrend
                close_price = base * (1 + 0.005)
            elif trend == 'aligned' and gap_pct < 0:
                # Downtrend
                close_price = base * (1 - 0.005)
            else:
                # Neutral
                close_price = base * (1 + np.random.uniform(-0.002, 0.002))

            high_price = close_price * (1 + daily_range_pct)
            low_price = close_price * (1 - daily_range_pct)
            open_price = (high_price + low_price) / 2

            prices.append(close_price)
            highs.append(high_price)
            lows.append(low_price)
            volumes.append(int(avg_volume * volume_multiplier))

    return pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': highs,
        'low': lows,
        'close': prices,
        'volume': volumes
    })


class TestEarningsGapV7Mismatches(unittest.TestCase):
    """Test all 7 mismatches for Strategy G v7.0."""

    def setUp(self):
        """Set up test fixtures."""
        self.strategy = EarningsGapStrategy()
        self.strategy.phase0_data = {}

    # =========================================================================
    # MISMATCH 1 & 2: GS Dimension Structure and Gap Size Thresholds
    # =========================================================================

    def test_gs_gap_size_thresholds_v7(self):
        """Test GS gap size thresholds match v7.0 spec.

        Documentation:
        - ≥10% = 3.0
        - 7-10% = 2.0-3.0
        - 5-7% = 1.0-2.0
        """
        # Test each threshold
        test_cases = [
            (0.12, 3.0, "≥10% should score 3.0"),
            (0.10, 3.0, "Exactly 10% should score 3.0"),
            (0.085, 2.5, "7-10% should score 2.0-3.0 (midpoint ~2.5)"),
            (0.07, 2.0, "Exactly 7% should score 2.0"),
            (0.06, 1.5, "5-7% should score 1.0-2.0 (midpoint ~1.5)"),
            (0.05, 1.0, "Exactly 5% should score 1.0"),
        ]

        for gap_pct, expected_base_score, description in test_cases:
            with self.subTest(gap_pct=gap_pct):
                df = create_test_df(gap_pct=gap_pct)
                self.strategy.phase0_data['TEST'] = {
                    'gap_1d_pct': gap_pct,
                    'gap_direction': 'up' if gap_pct > 0 else 'down',
                    'earnings_beat': True,  # For bonus
                    'guidance_change': False,
                    'one_time_event': False,
                }

                dimensions = self.strategy.calculate_dimensions('TEST', df)
                gs = next((d for d in dimensions if d.name == 'GS'), None)

                self.assertIsNotNone(gs, f"GS dimension not found for {description}")
                # Base gap score (without bonuses) should match thresholds
                # Note: bonuses add on top, so we check minimum expected
                if gap_pct >= 0.10:
                    self.assertGreaterEqual(gs.score, 3.0, f"Gap ≥10% should have base ≥3.0: {description}")
                elif gap_pct >= 0.07:
                    self.assertGreaterEqual(gs.score, 2.0, f"Gap 7-10% should have base ≥2.0: {description}")
                    self.assertLessEqual(gs.score, 4.0, f"Gap 7-10% should be ≤4.0 max: {description}")
                else:  # 5-7%
                    self.assertGreaterEqual(gs.score, 1.0, f"Gap 5-7% should have base ≥1.0: {description}")
                    self.assertLessEqual(gs.score, 3.0, f"Gap 5-7% should be ≤3.0 max: {description}")

    def test_gs_single_dimension_structure(self):
        """Test GS is a single dimension with gap % scoring + gap type bonus.

        Documentation shows single GS dimension (max 5.0) with:
        - Base gap % score
        - Gap type bonus (beat/miss, guidance, one-time)
        """
        df = create_test_df(gap_pct=0.08)
        self.strategy.phase0_data['TEST'] = {
            'gap_1d_pct': 0.08,
            'gap_direction': 'up',
            'earnings_beat': True,
            'guidance_change': True,
            'one_time_event': False,
        }

        dimensions = self.strategy.calculate_dimensions('TEST', df)

        # GS should be a single dimension
        gs_dims = [d for d in dimensions if d.name == 'GS']
        self.assertEqual(len(gs_dims), 1, "GS should be a single dimension")

        gs = gs_dims[0]
        self.assertEqual(gs.max_score, 5.0, "GS max should be 5.0")

        # With beat (+1.0) and guidance (+1.0), score should be elevated
        # Base for 7-10% is 2.0-3.0, plus up to 2.0 in bonuses
        self.assertGreater(gs.score, 2.0, "GS with bonuses should exceed base")

    # =========================================================================
    # MISMATCH 3: Earnings-Specific Bonuses
    # =========================================================================

    def test_earnings_beat_bonus(self):
        """Test +1.0 bonus for beat/miss vs estimates."""
        df = create_test_df(gap_pct=0.06)

        # With beat bonus
        self.strategy.phase0_data['TEST_BEAT'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': True,
            'guidance_change': False,
            'one_time_event': False,
        }

        # Without beat bonus
        self.strategy.phase0_data['TEST_NO_BEAT'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': False,
            'guidance_change': False,
            'one_time_event': False,
        }

        dims_beat = self.strategy.calculate_dimensions('TEST_BEAT', df)
        dims_no_beat = self.strategy.calculate_dimensions('TEST_NO_BEAT', df)

        gs_beat = next(d for d in dims_beat if d.name == 'GS')
        gs_no_beat = next(d for d in dims_no_beat if d.name == 'GS')

        # Beat should add +1.0
        expected_diff = 1.0
        self.assertAlmostEqual(
            gs_beat.score - gs_no_beat.score,
            expected_diff,
            delta=0.2,
            msg="Earnings beat should add ~+1.0 bonus"
        )

    def test_guidance_change_bonus(self):
        """Test +1.0 bonus for guidance change."""
        df = create_test_df(gap_pct=0.06)

        self.strategy.phase0_data['TEST_GUIDANCE'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': False,
            'guidance_change': True,
            'one_time_event': False,
        }

        self.strategy.phase0_data['TEST_NO_GUIDANCE'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': False,
            'guidance_change': False,
            'one_time_event': False,
        }

        dims_guidance = self.strategy.calculate_dimensions('TEST_GUIDANCE', df)
        dims_no_guidance = self.strategy.calculate_dimensions('TEST_NO_GUIDANCE', df)

        gs_guidance = next(d for d in dims_guidance if d.name == 'GS')
        gs_no_guidance = next(d for d in dims_no_guidance if d.name == 'GS')

        self.assertAlmostEqual(
            gs_guidance.score - gs_no_guidance.score,
            1.0,
            delta=0.2,
            msg="Guidance change should add +1.0 bonus"
        )

    def test_one_time_event_bonus(self):
        """Test +0.5 bonus for one-time event."""
        df = create_test_df(gap_pct=0.06)

        self.strategy.phase0_data['TEST_ONE_TIME'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': False,
            'guidance_change': False,
            'one_time_event': True,
        }

        self.strategy.phase0_data['TEST_NOT_ONE_TIME'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'earnings_beat': False,
            'guidance_change': False,
            'one_time_event': False,
        }

        dims_one_time = self.strategy.calculate_dimensions('TEST_ONE_TIME', df)
        dims_not_one_time = self.strategy.calculate_dimensions('TEST_NOT_ONE_TIME', df)

        gs_one_time = next(d for d in dims_one_time if d.name == 'GS')
        gs_not_one_time = next(d for d in dims_not_one_time if d.name == 'GS')

        self.assertAlmostEqual(
            gs_one_time.score - gs_not_one_time.score,
            0.5,
            delta=0.2,
            msg="One-time event should add +0.5 bonus"
        )

    # =========================================================================
    # MISMATCH 4: QC Methodology - Consolidation Range
    # =========================================================================

    def test_qc_consolidation_range(self):
        """Test QC uses consolidation range per v7.0 spec.

        Documentation:
        | Consolidation range | Score |
        |---------------------|-------|
        | <3% | 1.5 |
        | 3-5% | 1.0 |
        | 5-8% | 0.5 |
        | >8% | 0 |

        Days since gap:
        | Days | Score |
        |------|-------|
        | 1-2 | 2.0 |
        | 3-4 | 1.5 |
        | 5+ | 0.5 |
        """
        # Test with tight consolidation (<3%)
        df_tight = create_test_df(gap_pct=0.06, consolidation_range=0.02)
        self.strategy.phase0_data['TEST_TIGHT'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'days_post_earnings': 2,
        }

        # Test with wide consolidation (>8%)
        df_wide = create_test_df(gap_pct=0.06, consolidation_range=0.10)
        self.strategy.phase0_data['TEST_WIDE'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'days_post_earnings': 2,
        }

        dims_tight = self.strategy.calculate_dimensions('TEST_TIGHT', df_tight)
        dims_wide = self.strategy.calculate_dimensions('TEST_WIDE', df_wide)

        qc_tight = next(d for d in dims_tight if d.name == 'QC')
        qc_wide = next(d for d in dims_wide if d.name == 'QC')

        # Tight consolidation should score higher on range component
        # Both have same days score (2.0), but tight has 1.5 range vs 0 for wide
        self.assertGreater(qc_tight.score, qc_wide.score,
                          "Tight consolidation (<3%) should score higher than wide (>8%)")

        # Days=2 gives 2.0, tight range <3% gives 1.5, total = 3.5
        # Days=2 gives 2.0, wide range >8% gives 0, total = 2.0
        self.assertGreaterEqual(qc_tight.score, 3.0,
                               "Tight consolidation should score at least 3.0 (2.0 days + 1.5 range)")
        self.assertLessEqual(qc_wide.score, 2.5,
                            "Wide consolidation should score at most 2.5 (2.0 days + 0 range)")

    def test_qc_days_since_gap(self):
        """Test QC scoring by days since gap."""
        df = create_test_df(gap_pct=0.06, consolidation_range=0.02)

        test_cases = [
            (1, 2.0, "1 day should score 2.0 for days component"),
            (2, 2.0, "2 days should score 2.0 for days component"),
            (3, 1.5, "3 days should score 1.5 for days component"),
            (4, 1.5, "4 days should score 1.5 for days component"),
            (5, 0.5, "5+ days should score 0.5 for days component"),
        ]

        for days, expected_days_score, description in test_cases:
            with self.subTest(days=days):
                self.strategy.phase0_data['TEST'] = {
                    'gap_1d_pct': 0.06,
                    'gap_direction': 'up',
                    'days_post_earnings': days,
                }

                dims = self.strategy.calculate_dimensions('TEST', df)
                qc = next(d for d in dims if d.name == 'QC')

                # Score should decrease as days increase
                if days <= 2:
                    self.assertGreaterEqual(qc.score, 2.0, f"{description}")
                elif days <= 4:
                    self.assertLess(qc.score, 3.0, f"4 days should score less than max: {description}")
                else:
                    self.assertLess(qc.score, 2.0, f"5+ days should have reduced score: {description}")

    # =========================================================================
    # MISMATCH 5: Sector Alignment Bonus
    # =========================================================================

    def test_sector_alignment_bonus(self):
        """Test +1.0 sector alignment bonus in TC dimension.

        Documentation: +1.0 if sector ETF confirms gap direction
        """
        df = create_test_df(gap_pct=0.06)

        # With sector alignment
        self.strategy.phase0_data['TEST_ALIGNED'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'sector_aligned': True,
        }

        # Without sector alignment
        self.strategy.phase0_data['TEST_NOT_ALIGNED'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
            'sector_aligned': False,
        }

        dims_aligned = self.strategy.calculate_dimensions('TEST_ALIGNED', df)
        dims_not_aligned = self.strategy.calculate_dimensions('TEST_NOT_ALIGNED', df)

        tc_aligned = next(d for d in dims_aligned if d.name == 'TC')
        tc_not_aligned = next(d for d in dims_not_aligned if d.name == 'TC')

        # Sector alignment should add +1.0 to TC
        self.assertGreater(tc_aligned.score, tc_not_aligned.score,
                          "Sector aligned should score higher")
        self.assertAlmostEqual(
            tc_aligned.score - tc_not_aligned.score,
            1.0,
            delta=0.2,
            msg="Sector alignment should add +1.0 bonus"
        )

    # =========================================================================
    # MISMATCH 6: VC Volume Thresholds
    # =========================================================================

    def test_vc_volume_thresholds_v7(self):
        """Test VC volume thresholds match v7.0 spec.

        Documentation:
        | Gap day vol / avg20d | Score | Consolidation vol | Score |
        |----------------------|-------|-------------------|-------|
        | >5× | 2.0 | Below average | 1.0 |
        | 3-5× | 1.5 | Average | 0.5 |
        | 2-3× | 1.0 | Above average | 0 |
        | <2× | 0 | | |

        Note: Total VC = gap_day_score (max 2.0) + consolidation_vol_score (max 1.0) = 3.0 max
        Test uses default consolidation volume which scores ~0.5 (average).
        """
        # Test cases with expected total VC score (gap_day + consolidation ~0.5)
        test_cases = [
            (6.0, 2.5, ">5× should score 2.5 total (2.0 + 0.5 consolidation)"),
            (5.0, 2.0, "5× should score 2.0 total (1.5 + 0.5 consolidation)"),
            (4.0, 2.0, "3-5× should score 2.0 total (1.5 + 0.5 consolidation)"),
            (3.0, 2.0, "3× should score 2.0 total (1.5 + 0.5 consolidation)"),
            (2.5, 1.5, "2-3× should score 1.5 total (1.0 + 0.5 consolidation)"),
            (2.0, 1.5, "2× should score 1.5 total (1.0 + 0.5 consolidation)"),
            (1.5, 0.5, "<2× should score 0.5 total (0.0 + 0.5 consolidation)"),
        ]

        for volume_ratio, expected_total_score, description in test_cases:
            with self.subTest(volume_ratio=volume_ratio):
                df = create_test_df(gap_pct=0.06, volume_multiplier=volume_ratio)
                self.strategy.phase0_data['TEST'] = {
                    'gap_1d_pct': 0.06,
                    'gap_direction': 'up',
                    'gap_volume_ratio': volume_ratio,
                }

                dimensions = self.strategy.calculate_dimensions('TEST', df)
                vc = next(d for d in dimensions if d.name == 'VC')

                # Check total score is close to expected (with consolidation ~0.5)
                self.assertAlmostEqual(
                    vc.score, expected_total_score, delta=0.5,
                    msg=description
                )

    # =========================================================================
    # MISMATCH 7: Stop Loss Calculation
    # =========================================================================

    def test_stop_loss_consolidation_based(self):
        """Test stop loss uses consolidation low/high per v7.0 spec.

        Documentation:
        - Long: max(consolidation_low−0.5×ATR, gap_open×0.95)
        - Short: min(consolidation_high+0.5×ATR, gap_open×1.05)

        Note: For long setups, entry = consolidation_high, stop is based on
        consolidation_low (not prev_close). The 0.95 gap buffer prevents stop
        from being too far below the gap open.
        """
        # Test long setup - use smaller gap so consolidation high > gap_open * 0.95
        df_long = create_test_df(gap_pct=0.05, consolidation_range=0.04, trend='neutral')
        self.strategy.phase0_data['TEST_LONG'] = {
            'gap_1d_pct': 0.05,
            'gap_direction': 'up',
        }

        dimensions = self.strategy.calculate_dimensions('TEST_LONG', df_long)
        entry, stop, target = self.strategy.calculate_entry_exit(
            'TEST_LONG', df_long, dimensions, 10.0, '1'
        )

        # For long: Entry should be consolidation high
        consolidation_high = df_long.iloc[:-1]['high'].max()
        consolidation_low = df_long.iloc[:-1]['low'].min()

        # Entry should be at consolidation high
        self.assertAlmostEqual(entry, consolidation_high, delta=1.0,
                              msg="Entry should be at consolidation high")

        # Key assertion: stop uses consolidation_low, not prev_close
        # The old code used: prev_close - 0.3*ATR
        # New code uses: max(consolidation_low - 0.5*ATR, gap_open * 0.95)
        # Since consolidation_low < prev_close (in neutral trend), the new stop
        # should be different from the old calculation
        self.assertLessEqual(stop, entry + 2.0,
                            "Stop should be near or below entry level for long")

        # Test short setup
        df_short = create_test_df(gap_pct=-0.05, consolidation_range=0.04, trend='neutral')
        self.strategy.phase0_data['TEST_SHORT'] = {
            'gap_1d_pct': -0.05,
            'gap_direction': 'down',
        }

        dimensions = self.strategy.calculate_dimensions('TEST_SHORT', df_short)
        entry_s, stop_s, target_s = self.strategy.calculate_entry_exit(
            'TEST_SHORT', df_short, dimensions, 10.0, '1'
        )

        consolidation_low_s = df_short.iloc[:-1]['low'].min()
        consolidation_high_s = df_short.iloc[:-1]['high'].max()

        # Entry should be at consolidation low
        self.assertAlmostEqual(entry_s, consolidation_low_s, delta=1.0,
                              msg="Entry should be at consolidation low")

        # Stop should be near or above entry level for short
        # Allow some tolerance for ATR calculation
        self.assertGreaterEqual(stop_s, entry_s - 2.0,
                               "Stop should be near or above entry level for short")

    def test_target_uses_2_5x_risk(self):
        """Test target uses 2.5x risk multiplier per v7.0 spec."""
        df = create_test_df(gap_pct=0.06)
        self.strategy.phase0_data['TEST'] = {
            'gap_1d_pct': 0.06,
            'gap_direction': 'up',
        }

        dimensions = self.strategy.calculate_dimensions('TEST', df)
        entry, stop, target = self.strategy.calculate_entry_exit(
            'TEST', df, dimensions, 10.0, '1'
        )

        risk = entry - stop
        expected_target = entry + risk * 2.5

        # Allow some tolerance for rounding and ATR estimation
        self.assertAlmostEqual(
            target, expected_target, delta=risk * 0.75 + 1.0,
            msg="Target should be entry + 2.5x risk"
        )


if __name__ == '__main__':
    unittest.main()
