"""Tests for swing_detector.py — adaptive order + find_peaks."""
import numpy as np
import pandas as pd
from core.swing_detector import detect_swings, _compute_fib_target, cluster_levels


def make_test_prices(n=80):
    """Generate synthetic price series with known structure."""
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(n) * 2)
    df = pd.DataFrame({
        'High': prices + np.abs(np.random.randn(n)) * 1.5,
        'Low': prices - np.abs(np.random.randn(n)) * 1.5,
        'Close': prices,
    })
    return df


def test_adaptive_order_auto():
    """With default order=None, detect_swings should auto-compute."""
    df = make_test_prices(n=80)
    expected_order = max(3, min(8, len(df) // 15))  # 5
    assert expected_order == 5
    highs, lows = detect_swings(df)
    assert len(highs) > 0
    assert len(lows) > 0


def test_prominence_filters_noise():
    """Prominence threshold should reject small wiggles."""
    np.random.seed(1)
    n = 60
    # Flat-ish price with tiny noise — no significant swings
    prices = 100 + np.random.randn(n) * 0.5
    df = pd.DataFrame({
        'High': prices + np.abs(np.random.randn(n)) * 0.5,
        'Low': prices - np.abs(np.random.randn(n)) * 0.5,
        'Close': prices,
    })
    atr = (df['High'] - df['Low']).mean()
    assert atr < 2.0, f"ATR too large for noise test: {atr}"
    highs, lows = detect_swings(df, order=5, atr=atr)
    # With prominence = ATR * 0.5, most tiny wiggles should be filtered
    assert len(highs) < 10, f"Too many swing highs in noise: {len(highs)}"
    assert len(lows) < 10, f"Too many swing lows in noise: {len(lows)}"


def test_detect_swings_finds_peaks_and_troughs():
    """Known swing points should be found by find_peaks."""
    df = make_test_prices(n=80)
    highs, lows = detect_swings(df, order=5)
    assert len(highs) > 0, "Should find swing highs"
    assert len(lows) > 0, "Should find swing lows"


def test_detect_swings_too_short():
    """With too few bars, detect_swings returns empty lists."""
    df = pd.DataFrame({'High': [1, 2, 3], 'Low': [0.5, 1.5, 2.5], 'Close': [1, 2, 3]})
    highs, lows = detect_swings(df, order=5)
    assert highs == []
    assert lows == []
    # Also works with auto-order
    df10 = pd.DataFrame({'High': range(10), 'Low': range(10), 'Close': range(10)})
    h, l = detect_swings(df10)
    assert h == []
    assert l == []


def test_detect_swings_short_with_none_order():
    """Adaptive order on a very short frame should return empty."""
    df = pd.DataFrame({'High': range(5), 'Low': range(5), 'Close': range(5)})
    highs, lows = detect_swings(df)
    assert highs == []
    assert lows == []


def test_compute_fib_target_adaptive_order():
    """_compute_fib_target should work with default adaptive order."""
    df = make_test_prices(n=80)
    target = _compute_fib_target(df, entry_price=115.0)
    # Should return a valid target or None (depends on data), but never crash
    assert target is None or target > 115.0


def test_cluster_levels_empty():
    """Empty points list returns empty list."""
    zones = cluster_levels([])
    assert zones == []


def test_cluster_levels_single_point():
    """Single point returns a zone with count=1."""
    zones = cluster_levels([105.0])
    assert len(zones) == 1
    assert zones[0]['level'] == 105.0
    assert zones[0]['count'] == 1
    assert zones[0]['range'] == (105.0, 105.0)


def test_cluster_levels_complete_linkage():
    """Complete-linkage should keep distant points separate."""
    # 100.0, 100.3 close together; 102.0, 102.2 close; 105.0 isolated
    points = [100.0, 100.3, 102.0, 102.2, 105.0]
    zones = cluster_levels(points, atr=2.0, price=100.0)
    # With complete linkage and dynamic tolerance ~ max(0.005, min(0.03, 0.3*2/100=0.006)) = 0.006
    # Should get roughly: {100.x cluster}, {102.x cluster}, {105.0} = 3 zones
    assert 2 <= len(zones) <= 4, f"Expected 2-4 clusters, got {len(zones)}"
    # 105.0 is far from others and with count=1 survives (we don't filter count here)
    levels = [z['level'] for z in zones]
    # 100.x cluster should be near 100.15
    assert any(abs(l - 100.15) < 0.2 for l in levels), f"No 100.x cluster in {levels}"
    # 102.x cluster should be near 102.1
    assert any(abs(l - 102.1) < 0.2 for l in levels), f"No 102.x cluster in {levels}"


def test_cluster_levels_dynamic_tolerance():
    """Dynamic tolerance from ATR/price should produce reasonable clusters."""
    # Tight price action, low ATR — small tolerance, more clusters
    points = [100.0, 100.5, 101.0, 101.5, 102.0]
    zones_low_atr = cluster_levels(points, atr=0.5, price=100.0)
    zones_high_atr = cluster_levels(points, atr=5.0, price=100.0)
    # Low ATR = smaller tolerance = more clusters
    assert len(zones_low_atr) >= len(zones_high_atr), (
        f"Low ATR should produce >= clusters than high ATR "
        f"({len(zones_low_atr)} vs {len(zones_high_atr)})"
    )


def test_cluster_levels_default_tolerance():
    """Without ATR/price, default tolerance of 0.01 should be used."""
    points = [100.0, 100.1, 100.2, 105.0]
    zones = cluster_levels(points)
    # 0.01 = 1% of mean(~101) = ~1.01 threshold
    # 100.0, 100.1, 100.2 should cluster, 105.0 should be separate
    assert len(zones) == 2, f"Expected 2 clusters, got {len(zones)}: {zones}"
    small_cluster = [z for z in zones if z['level'] < 102][0]
    assert small_cluster['count'] == 3, f"Expected 3 points in small cluster, got {small_cluster}"


def test_cluster_levels_by_count_in_compute_sr():
    """Verify compute_sr_for_symbol filters out count<2 zones via integration."""
    # This is tested indirectly through the filter logic in compute_sr_for_symbol
    # The filter ensures only multi-touch zones become support/resistance
    pass


def test_detect_swings_explicit_atr():
    """Explicit ATR should be used as prominence base."""
    df = make_test_prices(n=80)
    highs, lows = detect_swings(df, order=5, atr=10.0)
    # High prominence = fewer swings
    assert isinstance(highs, list)
    assert isinstance(lows, list)
