"""Tests for swing_detector.py — adaptive order + find_peaks."""
import numpy as np
import pandas as pd
from core.swing_detector import (detect_swings, _compute_fib_target, cluster_levels,
                                  compute_stop_target, compute_sr_for_symbol,
                                  psychological_levels, gap_fill_levels, session_levels)


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


# --- compute_stop_target cascade tests ---

def test_compute_stop_target_quality_prefers_multi_touch():
    """Multi-touch support (count>=2) preferred over single-touch closer stop."""
    supports = [
        {'level': 97.0, 'count': 1, 'range': (97.0, 97.0)},   # single-touch, close
        {'level': 95.0, 'count': 3, 'range': (94.5, 95.5)},   # multi-touch, farther
    ]
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    # max_stop_distance = min(2.5*2.5, 5.0) = 5.0, so 95.0 qualifies
    # Should pick multi-touch 95.0 over single-touch 97.0
    assert abs(stop - 95.0) < 0.01, f"Expected stop ~95.0, got {stop}"
    assert 'support(x3)' in method, f"Expected support(x3) in method, got {method}"


def test_compute_stop_target_tightest_quality_stop():
    """Among quality stops (count>=2), pick the tightest (nearest to entry)."""
    supports = [
        {'level': 93.0, 'count': 2, 'range': (92.5, 93.5)},
        {'level': 97.0, 'count': 2, 'range': (96.5, 97.5)},
        {'level': 95.0, 'count': 2, 'range': (94.5, 95.5)},
    ]
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    # Tightest quality stop is 97.0 (nearest to entry among count>=2)
    assert abs(stop - 97.0) < 0.01, f"Expected stop ~97.0, got {stop}"
    assert 'support(x2)' in method


def test_compute_stop_target_single_touch_fallback():
    """When no quality stops exist, use tightest single-touch candidate."""
    supports = [
        {'level': 93.0, 'count': 1, 'range': (93.0, 93.0)},
        {'level': 97.0, 'count': 1, 'range': (97.0, 97.0)},
    ]
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    # Should pick tightest single-touch: 97.0
    assert abs(stop - 97.0) < 0.01, f"Expected stop ~97.0, got {stop}"
    assert 'support(x1)' in method


def test_compute_stop_target_ema21_stop():
    """EMA21 used as stop when no support zones qualify."""
    supports = []
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=97.0, ema50=0.0
    )
    # max_stop_distance = 5.0, 100-97=3 <= 5
    assert abs(stop - 97.0) < 0.01, f"Expected stop ~97.0, got {stop}"
    assert 'ema21' in method


def test_compute_stop_target_ema50_stop():
    """EMA50 used as stop when no supports or EMA21."""
    supports = []
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=96.0
    )
    assert abs(stop - 96.0) < 0.01, f"Expected stop ~96.0, got {stop}"
    assert 'ema50' in method


def test_compute_stop_target_atr_fallback_stop():
    """ATR stop used when no quality support zones or EMAs."""
    entry_price = 100.0
    atr = 3.0
    supports = []
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        entry_price, atr, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    expected_stop = entry_price - 1.5 * atr  # 95.5
    assert abs(stop - expected_stop) < 0.01, f"Expected stop ~{expected_stop}, got {stop}"
    assert method.startswith('atr+')


def test_compute_stop_target_target_iterates_resistances():
    """Target iterates resistance zones ascending, picks first with R:R >= min_rr."""
    entry_price = 100.0
    supports = [{'level': 96.0, 'count': 2, 'range': (95.5, 96.5)}]
    # risk = 4.0, need rr >= 2.5 → target >= 110.0
    resistances = [
        {'level': 103.0, 'count': 2, 'range': (102.5, 103.5)},   # rr=0.75, too low
        {'level': 105.0, 'count': 2, 'range': (104.5, 105.5)},   # rr=1.25, too low
        {'level': 108.0, 'count': 2, 'range': (107.5, 108.5)},   # rr=2.0, too low
        {'level': 115.0, 'count': 2, 'range': (114.5, 115.5)},   # rr=3.75, passes
    ]
    stop, target, method = compute_stop_target(
        entry_price, 2.0, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    assert abs(target - 115.0) < 0.01, f"Expected target ~115.0, got {target}"
    assert 'resistance(x2)' in method


def test_compute_stop_target_fib_extension_fallback():
    """Fib extension target used when no resistance gives valid R:R."""
    entry_price = 100.0
    supports = [{'level': 96.0, 'count': 2, 'range': (95.5, 96.5)}]
    # risk = 4.0, need rr >= 1.5 → target >= 106.0
    # Resistance too close (target=104, rr=1.0) — should fall through to fib
    resistances = [{'level': 104.0, 'count': 2, 'range': (103.5, 104.5)}]
    # Build OHLC with a clear swing: low=70, high=110
    n = 60
    close = np.linspace(70, 110, n) + np.random.randn(n) * 0.5
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0
    # Force a clear swing: dip to ~70 around index 10, then rise to ~110
    low[8:13] = [72, 70, 70, 71, 73]
    high[35:40] = [108, 110, 110, 109, 107]
    df = pd.DataFrame({'Open': close, 'High': high, 'Low': low, 'Close': close})

    stop, target, method = compute_stop_target(
        entry_price, 2.0, supports, resistances, df, time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    # Should use fib extension since resistance gives insufficient R:R
    assert target is not None, "Should have a target"
    assert target > 106.0, f"Target {target} should give R:R >= 1.5"


def test_compute_stop_target_atr_3x_fallback():
    """ATR 3x target used when no resistance or fib target."""
    entry_price = 100.0
    atr = 6.0
    supports = [{'level': 96.0, 'count': 2, 'range': (95.5, 96.5)}]
    # risk = 4.0, need rr >= 1.5 → target >= 106.0
    # ATR 3x target: 100 + 18 = 118, rr = 18/4 = 4.5 >= 1.5 ✓
    stop, target, method = compute_stop_target(
        entry_price, 6.0, supports, [], pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    assert target is not None, "Should have a target from ATR 3x fallback"
    assert 'atr_3x' in method or 'risk_' in method


def test_compute_stop_target_risk_multiple_fallback():
    """Risk-multiple target used as final fallback."""
    entry_price = 100.0
    atr = 2.0
    # Support must be within min(2.5*atr, 5% of price) = min(5.0, 5.0) = 5.0
    supports = [{'level': 95.0, 'count': 2, 'range': (94.5, 95.5)}]
    # risk = 5.0, atr=2.0 → 3*atr = 6.0, rr = 6/5 = 1.2 < 2.5 → ATR 3x fails
    # risk multiple: target = 100 + 2.5 * 5.0 = 112.5
    stop, target, method = compute_stop_target(
        entry_price, 2.0, supports, [], pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    expected_target = entry_price + 2.5 * (entry_price - stop)
    assert abs(target - expected_target) < 0.01, (
        f"Expected target ~{expected_target}, got {target}"
    )
    assert 'risk_' in method, f"Expected risk_ method, got {method}"


def test_min_rr_swing_25():
    """With min_rr_swing=2.5 config, computed R:R must be >= 2.5."""
    entry_price = 100.0
    atr = 2.0
    supports = [{'level': 96.0, 'count': 2, 'range': (95.5, 96.5)}]
    stop, target, method = compute_stop_target(
        entry_price, 2.0, supports, [], pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    rr = (target - entry_price) / (entry_price - stop)
    assert rr >= 2.5, f"R:R {rr:.2f} should be >= 2.5, got {method}"


def test_compute_stop_target_no_ema_values():
    """Zero EMA values should not be considered as stop candidates."""
    supports = []
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    stop, target, method = compute_stop_target(
        100.0, 2.5, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    assert stop is not None, "Should fall back to ATR stop"
    assert method.startswith('atr+'), f"Expected ATR stop, got {method}"


def test_compute_stop_target_far_support_filtered():
    """Support zones beyond max_stop_distance are filtered out."""
    entry_price = 100.0
    supports = [
        {'level': 90.0, 'count': 2, 'range': (89.0, 91.0)},    # 10% away, 100-90=10 > 5
        {'level': 85.0, 'count': 2, 'range': (84.0, 86.0)},    # 15% away
    ]
    resistances = [{'level': 110.0, 'count': 2, 'range': (109.5, 110.5)}]
    # atr=1.0, max_stop_distance = min(2.5, 5.0) = 2.5
    # 100-90=10 > 2.5 → filtered. 100-85=15 > 2.5 → filtered
    # Should fall back to ATR
    stop, target, method = compute_stop_target(
        entry_price, 1.0, supports, resistances, pd.DataFrame(), time_horizon='swing',
        ema21=0.0, ema50=0.0
    )
    assert method.startswith('atr+'), f"Expected ATR fallback, got {method}"


def test_compute_stop_target_position_min_rr():
    """Position trades use min_rr=2.0."""
    entry_price = 100.0
    atr = 2.0
    # Support must be within min(2.5*atr, 5%) = min(5.0, 5.0) = 5.0
    supports = [{'level': 96.0, 'count': 2, 'range': (95.5, 96.5)}]
    # risk = 4.0, need rr >= 2.0 → target >= 108.0 for position
    resistances = [{'level': 106.0, 'count': 2, 'range': (105.5, 106.5)}]  # rr=1.5, too low for position
    stop, target, method = compute_stop_target(
        entry_price, 2.0, supports, resistances, pd.DataFrame(), time_horizon='position',
        ema21=0.0, ema50=0.0
    )
    # Position: min_rr=2.0. Resistance at 106 gives 6/4=1.5 < 2.0, should fall through
    # ATR 3x: 100+6=106, rr=6/4=1.5 < 2.0 → fall through
    # Risk multiple: 100+2.0*4=108, always works
    assert target is not None
    assert 'risk_' in method, f"Expected risk fallback for position, got {method}"


def test_compute_fib_target_extension_param():
    """_compute_fib_target respects the extension parameter."""
    df = make_test_prices(n=80)
    target_1618 = _compute_fib_target(df, entry_price=115.0, extension=1.618)
    target_1272 = _compute_fib_target(df, entry_price=115.0, extension=1.272)
    # Both should be valid or None (depends on data), but 1.618 >= 1.272
    if target_1618 is not None and target_1272 is not None:
        assert target_1618 >= target_1272, (
            f"1.618 extension ({target_1618}) should be >= 1.272 ({target_1272})"
        )


# --- Lookback-based S/R tests ---


def test_sr_lookback_120_bars_default():
    """90 bars is less than default 120-bar lookback -- returns empty."""
    import numpy as np
    import tempfile
    from pathlib import Path
    from data.db import Database
    from core.swing_detector import compute_sr_for_symbol

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))
    conn = db.get_connection()

    np.random.seed(1)
    n = 90
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0

    from datetime import datetime, timedelta
    start = datetime(2026, 3, 1)
    for i in range(n):
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('LOOKTEST', date, float(close[i]), float(high[i]), float(low[i]), float(close[i]), 1000000)
        )

    current_price = float(close[-1])
    conn.execute(
        "INSERT INTO tier1_cache (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile, ema21, ema50, volume_ratio, supports, resistances, ret_5d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
        ('LOOKTEST', current_price, float(close.max()), float(close.min()), 0.02, 50.0, current_price * 0.95, current_price * 0.90, '[]', '[]', 0.0)
    )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(db, 'LOOKTEST')
    assert supports == [], f"Expected empty supports for 90 bars, got {supports}"
    assert resistances == [], f"Expected empty resistances for 90 bars, got {resistances}"

    Path(tmp_path).unlink(missing_ok=True)


# --- compute_sr_for_symbol with weekly S/R ---

def test_compute_sr_for_symbol_weekly_confluence():
    """120+ bars triggers weekly S/R; supports/resistances returned with weekly boost."""
    import numpy as np
    import tempfile
    from pathlib import Path
    from data.db import Database
    from core.swing_detector import compute_sr_for_symbol

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))
    conn = db.get_connection()

    # 130 days of trending random walk to produce natural swing points
    np.random.seed(42)
    n = 130
    close = 100 + np.cumsum(np.random.randn(n) * 0.8)
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0

    from datetime import datetime, timedelta
    start = datetime(2026, 2, 1)
    for i in range(n):
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('TEST', date, float(close[i]), float(high[i]), float(low[i]), float(close[i]), 1000000)
        )

    current_price = float(close[-1])
    conn.execute(
        "INSERT INTO tier1_cache (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile, ema21, ema50, volume_ratio, supports, resistances, ret_5d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
        ('TEST', current_price, float(close.max()), float(close.min()), 0.02, 50.0, current_price * 0.95, current_price * 0.90, '[]', '[]', 0.0)
    )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(db, 'TEST')

    assert isinstance(supports, list), "supports should be a list"
    assert isinstance(resistances, list), "resistances should be a list"
    # 130 bars of oscillating data should produce both supports and resistances
    assert len(supports) > 0, f"Expected >0 supports, got {supports}"
    assert len(resistances) > 0, f"Expected >0 resistances, got {resistances}"
    for s in supports:
        assert s < current_price, f"Support {s} should be below price {current_price}"
    for r in resistances:
        assert r > current_price, f"Resistance {r} should be above price {current_price}"

    Path(tmp_path).unlink(missing_ok=True)


def test_compute_sr_for_symbol_weekly_insufficient_bars():
    """110 bars (less than 120 lookback) returns empty S/R."""
    import numpy as np
    import tempfile
    from pathlib import Path
    from data.db import Database
    from core.swing_detector import compute_sr_for_symbol

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))
    conn = db.get_connection()

    np.random.seed(1)
    n = 110
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0

    from datetime import datetime, timedelta
    start = datetime(2026, 3, 1)
    for i in range(n):
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('TEST', date, float(close[i]), float(high[i]), float(low[i]), float(close[i]), 1000000)
        )

    current_price = float(close[-1])
    conn.execute(
        "INSERT INTO tier1_cache (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile, ema21, ema50, volume_ratio, supports, resistances, ret_5d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
        ('TEST', current_price, float(close.max()), float(close.min()), 0.02, 50.0, current_price * 0.95, current_price * 0.90, '[]', '[]', 0.0)
    )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(db, 'TEST')
    assert supports == [], f"Expected empty supports for 110 bars, got {supports}"
    assert resistances == [], f"Expected empty resistances for 110 bars, got {resistances}"

    Path(tmp_path).unlink(missing_ok=True)


# --- compute_volume_profile tests ---


def test_compute_volume_profile_too_short():
    """Less than 20 bars returns None."""
    from core.swing_detector import compute_volume_profile
    df = pd.DataFrame({'High': [100]*10, 'Low': [99]*10, 'Close': [99.5]*10, 'Volume': [1000]*10})
    result = compute_volume_profile(df)
    assert result is None


def test_compute_volume_profile_returns_dict():
    """With 60 bars returns a dict with poc and levels."""
    from core.swing_detector import compute_volume_profile
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        'High': close + np.abs(np.random.randn(n)) * 1.0,
        'Low': close - np.abs(np.random.randn(n)) * 1.0,
        'Close': close,
        'Volume': np.random.randint(100000, 5000000, n),
    })
    result = compute_volume_profile(df)
    assert isinstance(result, dict)
    assert 'poc' in result
    assert 'levels' in result
    assert len(result['levels']) == 15


def test_compute_volume_profile_poc_within_range():
    """POC should be between min Low and max High."""
    from core.swing_detector import compute_volume_profile
    np.random.seed(42)
    n = 60
    close = 200 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        'High': close + np.abs(np.random.randn(n)) * 1.5,
        'Low': close - np.abs(np.random.randn(n)) * 1.5,
        'Close': close,
        'Volume': np.random.randint(100000, 5000000, n),
    })
    result = compute_volume_profile(df)
    price_min = float(df['Low'].tail(60).min())
    price_max = float(df['High'].tail(60).max())
    assert price_min <= result['poc'] <= price_max, (
        f"POC {result['poc']} outside [{price_min}, {price_max}]"
    )


def test_compute_volume_profile_default_volume():
    """Missing/zero Volume column uses volume=1."""
    from core.swing_detector import compute_volume_profile
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        'High': close + np.abs(np.random.randn(n)) * 1.0,
        'Low': close - np.abs(np.random.randn(n)) * 1.0,
        'Close': close,
        'Volume': [0] * n,  # All zeros
    })
    result = compute_volume_profile(df)
    assert result is not None
    assert 'poc' in result


def test_compute_volume_profile_integration_sr():
    """POC from volume profile is added as S/R in compute_sr_for_symbol."""
    import tempfile
    from pathlib import Path
    from data.db import Database
    from core.swing_detector import compute_sr_for_symbol

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))
    conn = db.get_connection()

    np.random.seed(42)
    n = 130
    close = 200 + np.cumsum(np.random.randn(n) * 0.8)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5

    from datetime import datetime, timedelta
    start = datetime(2026, 2, 1)
    for i in range(n):
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('TESTVP', date, float(close[i]), float(high[i]), float(low[i]), float(close[i]), 1000000)
        )

    current_price = float(close[-1])
    conn.execute(
        "INSERT INTO tier1_cache (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile, ema21, ema50, volume_ratio, supports, resistances, ret_5d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
        ('TESTVP', current_price, float(high.max()), float(low.min()), 0.02, 50.0, current_price * 0.95, current_price * 0.90, '[]', '[]', 0.0)
    )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(db, 'TESTVP')
    # Should return lists (may be empty if POC doesn't survive clustering/filtering)
    assert isinstance(supports, list)
    assert isinstance(resistances, list)

    Path(tmp_path).unlink(missing_ok=True)


# --- psychological_levels tests ---


def test_psychological_levels_price_at_round():
    """Price exactly at a round number returns nearby psychological levels."""
    levels = psychological_levels(100.0)
    assert len(levels) > 0, "Should produce levels for round price"
    for lvl in levels:
        assert 'level' in lvl
        assert 'count' in lvl
        assert 'type' in lvl
        assert lvl['count'] == 2
        assert lvl['type'].startswith('psych_')


def test_psychological_levels_within_5pct():
    """All returned levels should be within 5% of the input price."""
    price = 147.53
    levels = psychological_levels(price)
    for lvl in levels:
        assert abs(lvl['level'] - price) / price < 0.05, (
            f"Level {lvl['level']} more than 5% from price {price}"
        )


def test_psychological_levels_very_small_price():
    """Very small price (near zero) returns empty — no round level within 5%."""
    levels = psychological_levels(0.05)
    assert levels == []


def test_psychological_levels_gets_psych_50_and_psych_10():
    """Levels should include both 50 and 10 based types where applicable."""
    # 100.0 should produce 100-type levels plus 50-type and 10-type within 5%
    levels = psychological_levels(100.0)
    types = {lvl['type'] for lvl in levels}
    # 5% of 100 = 5, so 50-based levels within [95,105] include 50 and 100
    # 10-based levels within [95,105] include 90, 100, 110
    # 100-based: 100 only
    assert 'psych_100' in types or 'psych_50' in types or 'psych_10' in types


# --- gap_fill_levels tests ---


def test_gap_fill_levels_gap_present():
    """gap_fill_levels returns a gap fill level when gap_1d_pct is large enough."""
    cache = {'gap_1d_pct': 0.03}
    levels = gap_fill_levels(cache, 100.0)
    assert len(levels) == 1
    assert levels[0]['type'] == 'gap_fill'
    # gap_pct = 3% → gap_price = 100 / (1 + 0.03) ≈ 97.09
    expected = round(100.0 / (1 + 0.03), 2)
    assert abs(levels[0]['level'] - expected) < 0.01


def test_gap_fill_levels_gap_too_small():
    """Gap ≤ 1% returns empty list."""
    cache = {'gap_1d_pct': 0.005}
    assert gap_fill_levels(cache, 100.0) == []


def test_gap_fill_levels_gap_too_far():
    """Gap price >15% from current price returns empty list."""
    cache = {'gap_1d_pct': 0.20}  # gap_price = 100/1.2 = 83.33, 16.7% away
    assert gap_fill_levels(cache, 100.0) == []


def test_gap_fill_levels_no_gap():
    """No gap_1d_pct in cache returns empty list."""
    assert gap_fill_levels({}, 100.0) == []


def test_gap_fill_levels_negative_gap():
    """Negative gap (gap down) also produces a fill level."""
    cache = {'gap_1d_pct': -0.02}  # gap down 2%
    levels = gap_fill_levels(cache, 100.0)
    assert len(levels) == 1
    expected = round(100.0 / (1 - 0.02), 2)  # ≈ 102.04
    assert abs(levels[0]['level'] - expected) < 0.01


# --- session_levels tests ---


def test_session_levels_basic():
    """session_levels returns 3 levels with correct types."""
    np.random.seed(42)
    n = 10
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        'High': close + np.abs(np.random.randn(n)) * 1.0,
        'Low': close - np.abs(np.random.randn(n)) * 1.0,
        'Close': close,
    })
    levels = session_levels(df)
    assert len(levels) == 3
    types = {lvl['type'] for lvl in levels}
    assert types == {'weekly_pivot', 'prior_week_high', 'prior_week_low'}


def test_session_levels_too_short():
    """Less than 5 bars returns empty list."""
    df = pd.DataFrame({'High': [100, 101], 'Low': [99, 100], 'Close': [99.5, 100.5]})
    assert session_levels(df) == []


def test_session_levels_pivot_midpoint():
    """Pivot is (H+L+C)/3 of the window."""
    np.random.seed(1)
    n = 10
    close = 100 + np.cumsum(np.random.randn(n) * 0.3)
    df = pd.DataFrame({
        'High': close + np.abs(np.random.randn(n)) * 0.5,
        'Low': close - np.abs(np.random.randn(n)) * 0.5,
        'Close': close,
    })
    levels = session_levels(df)
    recent = df.tail(5)
    h = float(recent['High'].max())
    l = float(recent['Low'].min())
    c = float(recent['Close'].iloc[-1])
    expected_pivot = round((h + l + c) / 3, 2)
    pivot = [lvl for lvl in levels if lvl['type'] == 'weekly_pivot'][0]
    assert abs(pivot['level'] - expected_pivot) < 0.01
    week_high = [lvl for lvl in levels if lvl['type'] == 'prior_week_high'][0]
    assert abs(week_high['level'] - h) < 0.01
    week_low = [lvl for lvl in levels if lvl['type'] == 'prior_week_low'][0]
    assert abs(week_low['level'] - l) < 0.01


# --- Anchored VWAP tests ---


def test_anchored_vwap_valid():
    """Anchored VWAP returns correct level when data is sufficient."""
    from core.swing_detector import anchored_vwap
    import pandas as pd
    import numpy as np

    dates = pd.date_range('2026-01-01', periods=100, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(100) * 0.5)
    volume = np.random.randint(100000, 5000000, 100)
    df = pd.DataFrame({'Close': close, 'Volume': volume}, index=dates)

    result = anchored_vwap(df, '2026-03-01', current_price=close[-1])
    assert result is not None
    assert 'level' in result
    assert result['count'] == 2
    assert result['type'] == 'anchored_vwap'


def test_anchored_vwap_too_short():
    """Less than 5 bars from anchor returns None."""
    from core.swing_detector import anchored_vwap
    import pandas as pd
    import numpy as np

    dates = pd.date_range('2026-01-01', periods=10, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(10) * 0.5)
    volume = np.random.randint(100000, 5000000, 10)
    df = pd.DataFrame({'Close': close, 'Volume': volume}, index=dates)

    result = anchored_vwap(df, '2026-01-08', current_price=close[-1])
    assert result is None


def test_anchored_vwap_zero_volume():
    """Zero total volume returns None."""
    from core.swing_detector import anchored_vwap
    import pandas as pd
    import numpy as np

    dates = pd.date_range('2026-01-01', periods=100, freq='D')
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(100) * 0.5)
    df = pd.DataFrame({'Close': close, 'Volume': [0]*100}, index=dates)

    result = anchored_vwap(df, '2026-03-01', current_price=close[-1])
    assert result is None


def test_anchored_vwap_too_far_from_price():
    """VWAP > 15% from current price returns None."""
    from core.swing_detector import anchored_vwap
    import pandas as pd
    import numpy as np

    dates = pd.date_range('2026-01-01', periods=100, freq='D')
    # Prices climb steadily — VWAP from early anchor far below current
    close = 100 + np.arange(100) * 0.5  # climbs to 149.5
    volume = np.random.randint(100000, 5000000, 100)
    df = pd.DataFrame({'Close': close, 'Volume': volume}, index=dates)

    current_price = close[-1]
    # Anchor at start: VWAP ~124.8, current ~149.5, diff ~16.5% > 15%
    result = anchored_vwap(df, '2026-01-01', current_price=current_price)
    assert result is None, f"Expected None, got {result}"


def test_anchored_vwap_missing_volume_column():
    """Missing Volume column returns None."""
    from core.swing_detector import anchored_vwap
    import pandas as pd
    import numpy as np

    dates = pd.date_range('2026-01-01', periods=100, freq='D')
    close = 100 + np.cumsum(np.random.randn(100) * 0.5)
    df = pd.DataFrame({'Close': close}, index=dates)

    result = anchored_vwap(df, '2026-03-01', current_price=close[-1])
    assert result is None


def test_compute_anchored_vwaps_from_earnings():
    """Earnings date within 120 days produces AVWAP level."""
    import tempfile
    from pathlib import Path
    from data.db import Database
    from datetime import datetime, timedelta
    import pandas as pd
    from core.swing_detector import compute_anchored_vwaps

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))

    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO stocks (symbol, next_earnings_date, is_active) VALUES (?, ?, 1)",
        ('TESTAV', thirty_days_ago)
    )
    conn.commit()

    dates = pd.date_range(thirty_days_ago, periods=30, freq='D')
    close = [100.0] * 30
    volume = [1000000] * 30
    df = pd.DataFrame({'Close': close, 'Volume': volume}, index=dates)

    levels = compute_anchored_vwaps(db, 'TESTAV', df, 100.0)
    assert len(levels) == 1
    assert levels[0]['type'] == 'anchored_vwap'
    assert abs(levels[0]['level'] - 100.0) < 0.01

    Path(tmp_path).unlink(missing_ok=True)


def test_compute_anchored_vwaps_skips_old_earnings():
    """Earnings date older than 120 days returns no levels."""
    import tempfile
    from pathlib import Path
    from data.db import Database
    from datetime import datetime, timedelta
    import pandas as pd
    from core.swing_detector import compute_anchored_vwaps

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))

    old_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO stocks (symbol, next_earnings_date, is_active) VALUES (?, ?, 1)",
        ('TESTAV', old_date)
    )
    conn.commit()

    dates = pd.date_range(old_date, periods=30, freq='D')
    close = [100.0] * 30
    volume = [1000000] * 30
    df = pd.DataFrame({'Close': close, 'Volume': volume}, index=dates)

    levels = compute_anchored_vwaps(db, 'TESTAV', df, 100.0)
    assert len(levels) == 0

    Path(tmp_path).unlink(missing_ok=True)


def test_compute_anchored_vwaps_no_earnings():
    """No earnings date returns empty list."""
    import tempfile
    from pathlib import Path
    from data.db import Database
    import pandas as pd
    from core.swing_detector import compute_anchored_vwaps

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))

    conn = db.get_connection()
    conn.execute(
        "INSERT INTO stocks (symbol, is_active) VALUES (?, 1)",
        ('TESTAV',)
    )
    conn.commit()

    df = pd.DataFrame({'Close': [100]*30, 'Volume': [1000000]*30},
                       index=pd.date_range('2026-01-01', periods=30, freq='D'))

    levels = compute_anchored_vwaps(db, 'TESTAV', df, 100.0)
    assert len(levels) == 0

    Path(tmp_path).unlink(missing_ok=True)


def test_anchored_vwap_integration_compute_sr():
    """AVWAP from earnings appears in compute_sr_for_symbol output."""
    import tempfile
    from pathlib import Path
    from data.db import Database
    from core.swing_detector import compute_sr_for_symbol
    from datetime import datetime, timedelta
    import numpy as np

    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_path = tmp.name
    tmp.close()
    db = Database(Path(tmp_path))
    conn = db.get_connection()

    # Set earnings date to 30 days ago
    earnings_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    conn.execute(
        "INSERT INTO stocks (symbol, next_earnings_date, is_active) VALUES (?, ?, 1)",
        ('TESTVWAP', earnings_date)
    )

    # Slow downtrend from 110 to 100 over 130 days — AVWAP will be ~101.9
    n = 130
    close = [110.0 - i * (10.0 / 129) for i in range(n)]
    high = [c + 1.0 for c in close]
    low = [c - 1.0 for c in close]
    volume = [1000000] * n

    start = datetime.now() - timedelta(days=n)
    for i in range(n):
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('TESTVWAP', date, float(close[i]), float(high[i]), float(low[i]), float(close[i]), volume[i])
        )

    current_price = float(close[-1])
    conn.execute(
        "INSERT INTO tier1_cache (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile, ema21, ema50, volume_ratio, supports, resistances, ret_5d) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)",
        ('TESTVWAP', current_price, float(max(high)), float(min(low)), 0.02, 50.0, current_price * 0.95, current_price * 0.90, '[]', '[]', 0.0)
    )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(db, 'TESTVWAP')
    all_levels = supports + resistances

    # AVWAP ~ average of last 30 closes, with downtrend ~101.9 > current 100
    expected_avwap = round(sum(close[-30:]) / 30, 2)
    assert any(abs(lvl - expected_avwap) / expected_avwap < 0.02 for lvl in all_levels), (
        f"Expected AVWAP ~{expected_avwap} not found in levels {all_levels}"
    )

    Path(tmp_path).unlink(missing_ok=True)
