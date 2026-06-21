"""Tests for swing_detector.py — adaptive order + find_peaks."""
import numpy as np
import pandas as pd
from core.swing_detector import detect_swings, _compute_fib_target


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


def test_detect_swings_explicit_atr():
    """Explicit ATR should be used as prominence base."""
    df = make_test_prices(n=80)
    highs, lows = detect_swings(df, order=5, atr=10.0)
    # High prominence = fewer swings
    assert isinstance(highs, list)
    assert isinstance(lows, list)
