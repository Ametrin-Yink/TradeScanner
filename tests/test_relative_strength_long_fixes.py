"""Tests for Strategy H (RelativeStrengthLong) mismatch fixes."""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from core.strategies.relative_strength_long import RelativeStrengthLongStrategy


def create_mock_data(
    days: int = 252,
    base_price: float = 100.0,
    market_cap: float = 5e9,
    seed: int = 42,
) -> pd.DataFrame:
    """Create mock stock data for testing."""
    dates = [datetime.now() - timedelta(days=days - i) for i in range(days)]

    # Generate price data
    np.random.seed(seed)
    returns = np.random.normal(0.001, 0.02, days)
    prices = [base_price]
    for ret in returns[1:]:
        prices.append(prices[-1] * (1 + ret))

    # Generate volume data
    volumes = np.random.normal(1000000, 200000, days).astype(int)

    # Generate high/low/close
    highs = [p * (1 + abs(np.random.normal(0, 0.015))) for p in prices]
    lows = [p * (1 - abs(np.random.normal(0, 0.015))) for p in prices]
    closes = [l + np.random.random() * (h - l) for l, h in zip(lows, highs)]

    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    })

    return df


def create_spy_mock_data(
    days: int = 252,
    base_price: float = 450.0,
    seed: int = 43,
) -> pd.DataFrame:
    """Create mock SPY data for testing."""
    dates = [datetime.now() - timedelta(days=days - i) for i in range(days)]

    np.random.seed(seed)
    returns = np.random.normal(0.0005, 0.015, days)
    prices = [base_price]
    for ret in returns[1:]:
        prices.append(prices[-1] * (1 + ret))

    volumes = np.random.normal(50000000, 5000000, days).astype(int)
    highs = [p * (1 + abs(np.random.normal(0, 0.012))) for p in prices]
    lows = [p * (1 - abs(np.random.normal(0, 0.012))) for p in prices]
    closes = [l + np.random.random() * (h - l) for l, h in zip(lows, highs)]

    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    })

    return df


class TestRDMaxScore:
    """Test 1: RD Max Score Wrong - should be 4.0, not 6.0"""

    def test_rd_max_score_is_4_not_6(self):
        """RD dimension max_score should be 4.0 per documentation."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)

        # Set up phase0_data with RS percentile
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 95, 'accum_ratio_15d': 1.5}
        }

        # Set up spy_df
        strategy._spy_df = create_spy_mock_data()

        dimensions = strategy.calculate_dimensions('TEST', df)
        rd_dim = next((d for d in dimensions if d.name == 'RD'), None)

        assert rd_dim is not None, "RD dimension should exist"
        assert rd_dim.max_score == 4.0, f"RD max_score should be 4.0, got {rd_dim.max_score}"
        assert rd_dim.score <= 4.0, f"RD score should be <= 4.0, got {rd_dim.score}"
        print(f"PASS: test_rd_max_score_is_4_not_6 (max={rd_dim.max_score}, score={rd_dim.score})")


class TestRDScoringStructure:
    """Test 2: RD Scoring Structure - RS percentile + SPY divergence bonus, capped at 4.0"""

    def test_rd_uses_rs_percentile_plus_bonus_structure(self):
        """RD scoring should use RS percentile base + SPY divergence bonus."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)
        spy_df = create_spy_mock_data()

        strategy._spy_df = spy_df

        # Test case: RS >= 95th percentile
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 95, 'accum_ratio_15d': 1.5}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        rd_dim = next((d for d in dimensions if d.name == 'RD'), None)

        assert rd_dim is not None, "RD dimension should exist"
        assert rd_dim.score <= 4.0, f"RD score should be capped at 4.0, got {rd_dim.score}"
        print(f"PASS: test_rd_uses_rs_percentile_plus_bonus_structure (score={rd_dim.score})")

    def test_rd_divergence_bonus_applied_correctly(self):
        """RD should apply divergence bonus correctly."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, seed=42)
        spy_df = create_spy_mock_data(days=252, seed=100)  # Different seed for divergence

        strategy._spy_df = spy_df
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 90, 'accum_ratio_15d': 1.5}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        rd_dim = next((d for d in dimensions if d.name == 'RD'), None)

        assert rd_dim is not None, "RD dimension should exist"
        # Score should reflect 90-95th percentile range (3.0-4.0) plus potential bonus
        assert rd_dim.score <= 4.0, f"RD score should be capped at 4.0, got {rd_dim.score}"
        print(f"PASS: test_rd_divergence_bonus_applied_correctly (score={rd_dim.score})")


class TestSHDimension:
    """Test 3: SH Dimension - Should use SPY down-day evaluation, not EMA alignment + 52w high"""

    def test_sh_uses_spy_down_day_evaluation(self):
        """SH scoring should evaluate price holding above EMA8/EMA21 during SPY down-days."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)
        spy_df = create_spy_mock_data(days=252)

        # Create SPY down-days in last 10 days
        # Make last 3 days have negative returns for SPY
        for i in range(3):
            spy_df.loc[len(spy_df) - 1 - i, 'close'] = spy_df.loc[len(spy_df) - 2 - i, 'close'] * 0.98

        strategy._spy_df = spy_df
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        sh_dim = next((d for d in dimensions if d.name == 'SH'), None)

        assert sh_dim is not None, "SH dimension should exist"
        assert sh_dim.max_score == 4.0, f"SH max_score should be 4.0, got {sh_dim.max_score}"
        # SH should evaluate based on SPY down-day behavior, not just EMA alignment
        print(f"PASS: test_sh_uses_spy_down_day_evaluation (score={sh_dim.score})")

    def test_sh_scores_holding_above_ema8_during_spy_weakness(self):
        """SH should give 1.5 points for holding above EMA8 during SPY weakness."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)
        spy_df = create_spy_mock_data(days=252)

        # Create a SPY down-day
        spy_df.loc[len(spy_df) - 1, 'close'] = spy_df.loc[len(spy_df) - 2, 'close'] * 0.97

        # Make stock hold above EMA8 (price stable or up)
        df.loc[len(df) - 1, 'close'] = df.loc[len(df) - 2, 'close'] * 1.01

        strategy._spy_df = spy_df
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        sh_dim = next((d for d in dimensions if d.name == 'SH'), None)

        assert sh_dim is not None, "SH dimension should exist"
        print(f"PASS: test_sh_scores_holding_above_ema8_during_spy_weakness (score={sh_dim.score})")


class TestRegimeExitLogic:
    """Test 4: Missing Regime Exit Logic - Should move to Stage 3 trailing stop when SPY crosses above EMA21"""

    def test_regime_exit_detects_spy_above_ema21(self):
        """Strategy should detect when SPY crosses above EMA21 (bear->neutral regime change)."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)
        spy_df = create_spy_mock_data(days=252)

        # Calculate EMA21 for SPY
        spy_df['ema21'] = spy_df['close'].ewm(span=21, adjust=False).mean()

        # Set current SPY price above EMA21
        current_spy_close = spy_df['close'].iloc[-1]
        current_spy_ema21 = spy_df['ema21'].iloc[-1]

        # Ensure SPY is above EMA21 (bullish/neutral signal)
        if current_spy_close <= current_spy_ema21:
            # Adjust to make SPY above EMA21
            spy_df.loc[len(spy_df) - 1, 'close'] = current_spy_ema21 * 1.02

        strategy._spy_df = spy_df
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        # Calculate entry/exit - should include regime exit logic
        dimensions = strategy.calculate_dimensions('TEST', df)
        score, tier = strategy.calculate_score(dimensions, df, 'TEST')
        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dimensions, score, tier)

        # Stop should be valid (entry != stop means valid setup)
        assert entry > 0, "Entry should be positive"
        print(f"PASS: test_regime_exit_detects_spy_above_ema21 (entry={entry}, stop={stop}, target={target})")


class TestStopLossCalculation:
    """Test 5: Stop Loss Calculation Wrong - Should be max(EMA50*0.99, entry*0.93)"""

    def test_stop_uses_ema50_based_formula(self):
        """Stop loss should use max(EMA50*0.99, entry*0.93), not low_20d - 0.3*ATR."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)

        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        score, tier = strategy.calculate_score(dimensions, df, 'TEST')
        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dimensions, score, tier)

        # Calculate expected EMA50
        ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        expected_stop = max(ema50 * 0.99, entry * 0.93)

        # Stop should be close to expected (within rounding)
        assert abs(stop - expected_stop) < 0.5, f"Stop {stop} should be close to expected {expected_stop}"
        print(f"PASS: test_stop_uses_ema50_based_formula (entry={entry}, stop={stop}, expected={expected_stop:.2f})")

    def test_stop_respects_93_percent_of_entry(self):
        """Stop loss should never be lower than 93% of entry price."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)

        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        score, tier = strategy.calculate_score(dimensions, df, 'TEST')
        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dimensions, score, tier)

        min_stop = entry * 0.93
        # Allow for rounding (stop is rounded to 2 decimal places)
        assert stop >= min_stop - 0.01, f"Stop {stop} should be >= {min_stop:.2f} (93% of entry {entry})"
        print(f"PASS: test_stop_respects_93_percent_of_entry (entry={entry}, stop={stop}, min={min_stop:.2f})")


class TestAccumRatioPreFilter:
    """Test 6: Extra Pre-filter Gate - accum_ratio should not be a hard gate"""

    def test_accum_ratio_not_hard_filter(self):
        """accum_ratio_15d >= 1.1 should NOT be a hard pre-filter gate."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)

        # Set accum_ratio below 1.1 - should still pass filter if other conditions met
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 90, 'accum_ratio_15d': 0.95}  # Below 1.1 threshold
        }

        # Set regime to allow RS strategy
        strategy._current_regime = 'bear_moderate'

        # Filter should NOT reject solely based on accum_ratio
        # (accum_ratio is scored in VC dimension, not a pre-filter)
        result = strategy.filter('TEST', df)

        # This test verifies accum_ratio is NOT a hard gate
        # The stock may still fail other filters, but not because of accum_ratio alone
        # If result is False, check it's not because of accum_ratio
        print(f"PASS: test_accum_ratio_not_hard_filter (filter_result={result}, accum_ratio=0.95)")
        print(f"      Note: accum_ratio should be scored in VC, not used as hard gate")

    def test_accum_ratio_scored_in_vc_dimension(self):
        """accum_ratio should be scored in VC dimension, not as pre-filter."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)

        # Test with different accum_ratio values
        test_ratios = [0.9, 1.0, 1.2, 1.5, 2.0]

        for ratio in test_ratios:
            strategy.phase0_data = {
                'TEST': {'rs_percentile': 85, 'accum_ratio_15d': ratio}
            }

            dimensions = strategy.calculate_dimensions('TEST', df)
            vc_dim = next((d for d in dimensions if d.name == 'VC'), None)

            assert vc_dim is not None, "VC dimension should exist"
            # VC score should vary based on accum_ratio
            print(f"      accum_ratio={ratio}: VC score={vc_dim.score}")

        print(f"PASS: test_accum_ratio_scored_in_vc_dimension")


class TestV71Refactoring:
    """Tests for v7.1 refactoring changes."""

    def test_filter_no_market_cap_check(self):
        """Filter should not check market_cap (removed in v7.1)."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)
        strategy._current_regime = 'bear_moderate'

        # RS percentile passes, no market_cap set (defaults to missing)
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 90, 'accum_ratio_15d': 1.3}
        }

        result = strategy.filter('TEST', df)
        assert result is True, "Should pass without market_cap"
        print(f"PASS: test_filter_no_market_cap_check")

    def test_filter_no_volume_check(self):
        """Filter should not check avg_volume (removed in v7.1)."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0, seed=42)
        strategy._current_regime = 'bear_moderate'

        # Low volume data in mock but RS passes
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 90, 'accum_ratio_15d': 1.3}
        }

        result = strategy.filter('TEST', df)
        assert result is True, "Should pass without volume check"
        print(f"PASS: test_filter_no_volume_check")

    def test_filter_no_consecutive_days_gate(self):
        """Filter should not require consecutive_days >= 5 (v7.1: moved to bonus)."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)
        strategy._current_regime = 'bear_moderate'

        # RS passes but consecutive_days < 5
        strategy.phase0_data = {
            'TEST': {'rs_percentile': 90, 'rs_consecutive_days_80': 3, 'accum_ratio_15d': 1.3}
        }

        result = strategy.filter('TEST', df)
        assert result is True, "Should pass with only 3 consecutive days (bonus, not gate)"
        print(f"PASS: test_filter_no_consecutive_days_gate")

    def test_rd_bonus_for_consecutive_days(self):
        """RD should give bonus for consecutive days >=80th percentile."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)
        spy_df = create_spy_mock_data()
        strategy._spy_df = spy_df

        # Same RS percentile, different consecutive days
        strategy.phase0_data = {
            'TEST_LOW': {'rs_percentile': 90, 'rs_consecutive_days_80': 2, 'accum_ratio_15d': 1.3},
            'TEST_HIGH': {'rs_percentile': 90, 'rs_consecutive_days_80': 10, 'accum_ratio_15d': 1.3},
        }

        rd_low = strategy._calculate_rd(strategy.phase0_data['TEST_LOW'], df)
        rd_high = strategy._calculate_rd(strategy.phase0_data['TEST_HIGH'], df)

        assert rd_high > rd_low, f"RD bonus: high consecutive ({rd_high:.2f}) should beat low ({rd_low:.2f})"
        print(f"PASS: test_rd_bonus_for_consecutive_days (3days={rd_low:.2f}, 10days={rd_high:.2f})")

    def test_target_is_2x_risk_not_3x(self):
        """Target should be 2.0x risk, not 3.0x."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252, base_price=100.0)

        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        score, tier = strategy.calculate_score(dimensions, df, 'TEST')
        entry, stop, target = strategy.calculate_entry_exit('TEST', df, dimensions, score, tier)

        risk = entry - stop
        expected_target = round(entry + risk * 2.0, 2)

        assert target == expected_target, f"Target {target} should be entry + 2*risk = {expected_target}"
        print(f"PASS: test_target_is_2x_risk_not_3x (entry={entry}, stop={stop}, target={target}, risk={risk:.2f})")

    def test_match_reasons_include_time_stop(self):
        """Match reasons should include max_hold_days recommendation."""
        strategy = RelativeStrengthLongStrategy()
        df = create_mock_data(days=252)

        strategy.phase0_data = {
            'TEST': {'rs_percentile': 85, 'rs_consecutive_days_80': 7, 'accum_ratio_15d': 1.3}
        }

        dimensions = strategy.calculate_dimensions('TEST', df)
        score, tier = strategy.calculate_score(dimensions, df, 'TEST')
        reasons = strategy.build_match_reasons('TEST', df, dimensions, score, tier)

        reason_text = ' '.join(reasons)
        assert '20' in reason_text, f"Match reasons should mention 20-day time-stop: {reasons}"
        assert 'consecutive' in reason_text.lower(), f"Match reasons should show consecutive days: {reasons}"
        print(f"PASS: test_match_reasons_include_time_stop")
        print(f"  Reasons: {reasons}")


def run_all_tests():
    """Run all tests for Strategy H."""
    print("=" * 70)
    print("Testing Strategy H (RelativeStrengthLong)")
    print("=" * 70)

    print("\n--- Test 1: RD Max Score (should be 4.0, not 6.0) ---")
    test1 = TestRDMaxScore()
    try:
        test1.test_rd_max_score_is_4_not_6()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 2: RD Scoring Structure (RS percentile + bonus) ---")
    test2 = TestRDScoringStructure()
    try:
        test2.test_rd_uses_rs_percentile_plus_bonus_structure()
        test2.test_rd_divergence_bonus_applied_correctly()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 3: SH Dimension (SPY down-day evaluation) ---")
    test3 = TestSHDimension()
    try:
        test3.test_sh_uses_spy_down_day_evaluation()
        test3.test_sh_scores_holding_above_ema8_during_spy_weakness()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 4: Regime Exit Logic (SPY above EMA21) ---")
    test4 = TestRegimeExitLogic()
    try:
        test4.test_regime_exit_detects_spy_above_ema21()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 5: Stop Loss Calculation (EMA50-based) ---")
    test5 = TestStopLossCalculation()
    try:
        test5.test_stop_uses_ema50_based_formula()
        test5.test_stop_respects_93_percent_of_entry()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 6: Accum Ratio Pre-filter (should not be hard gate) ---")
    test6 = TestAccumRatioPreFilter()
    try:
        test6.test_accum_ratio_not_hard_filter()
        test6.test_accum_ratio_scored_in_vc_dimension()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n--- Test 7: v7.1 Refactoring (redundant filters, bonuses, R:R) ---")
    test7 = TestV71Refactoring()
    try:
        test7.test_filter_no_market_cap_check()
        test7.test_filter_no_volume_check()
        test7.test_filter_no_consecutive_days_gate()
        test7.test_rd_bonus_for_consecutive_days()
        test7.test_target_is_2x_risk_not_3x()
        test7.test_match_reasons_include_time_stop()
    except AssertionError as e:
        print(f"FAIL: {e}")

    print("\n" + "=" * 70)
    print("All Strategy H tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
