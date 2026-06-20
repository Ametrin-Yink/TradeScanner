import numpy as np
import pandas as pd
from core.swing_detector import detect_swings, cluster_levels, compute_stop_target


def make_test_data():
    """OHLC data with obvious swing points at indices 5, 15, 25."""
    np.random.seed(42)
    n = 60
    base = 100.0
    # Create two clear swings
    trend = np.linspace(0, 20, n)
    noise = np.random.randn(n) * 0.5
    close = base + trend + noise
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    # Force clear swing highs at index 20 and 40
    high[20] = base + 18.0
    high[40] = base + 28.0
    # Force clear swing lows at index 30
    low[30] = base + 8.0
    df = pd.DataFrame({'Open': close - 0.3, 'High': high, 'Low': low, 'Close': close})
    return df


def test_detect_swings_finds_peaks():
    df = make_test_data()
    highs, lows = detect_swings(df, order=5)
    assert len(highs) > 0, "Should find at least one swing high"
    assert len(lows) > 0, "Should find at least one swing low"
    # The forced swing highs should be in the detected set
    assert any(abs(h - df['High'].iloc[20]) < 1.0 for h in highs)


def test_cluster_levels_merges_nearby():
    points = [98.2, 98.5, 98.8, 105.0, 105.3]
    zones = cluster_levels(points, tolerance=0.01)
    # 3 close points at ~98.5 should merge into one zone
    # 2 close points at ~105.15 should merge into one zone
    assert len(zones) == 2
    assert any(abs(z['level'] - 98.5) < 0.5 for z in zones)
    assert any(abs(z['level'] - 105.15) < 0.5 for z in zones)


def test_compute_stop_target_uses_swing_low():
    """Nearest support below entry becomes stop. Target from nearest resistance or fallback."""
    df = make_test_data()
    entry_price = 115.0
    atr = 2.5
    highs, lows = detect_swings(df, order=5)
    low_zones = cluster_levels(lows, tolerance=0.005)
    high_zones = cluster_levels(highs, tolerance=0.005)
    stop, target, method = compute_stop_target(
        entry_price, atr, low_zones, high_zones, df, time_horizon='swing'
    )
    assert stop < entry_price, f"Stop {stop} should be below entry {entry_price}"
    assert target > entry_price, f"Target {target} should be above entry {entry_price}"
    assert method.startswith('support'), f"Should use support, got {method}"


def test_compute_stop_target_fallback_atr():
    """If no valid swing low, fall back to 2x ATR."""
    entry_price = 115.0
    atr = 3.0
    # Empty zones — no swing lows below entry
    stop, target, method = compute_stop_target(
        entry_price, atr, [], [], pd.DataFrame(), time_horizon='swing'
    )
    expected_stop = entry_price - 1.5 * atr  # 109.0
    assert abs(stop - expected_stop) < 0.01
    assert target > entry_price
    assert method.startswith('atr+')
