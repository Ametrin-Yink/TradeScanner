import numpy as np
import pandas as pd
from core.swing_detector import (detect_swings, cluster_levels,
                                  compute_stop_target, compute_sr_for_symbol)


def make_test_data():
    """OHLC data with obvious swing points at indices 5, 15, 25."""
    np.random.seed(42)
    n = 60
    base = 100.0
    # Create two clear swings
    trend = np.linspace(0, 20, n)
    noise = np.random.randn(n) * 0.5
    close = base + trend + noise
    # Small high/low noise so ATR stays moderate
    high = close + np.abs(np.random.randn(n)) * 0.7
    low = close - np.abs(np.random.randn(n)) * 0.7
    # Force clear swing highs at index 20 and 40
    high[20] = 120.0
    high[40] = 130.0
    # Force clear swing low at index 30 (deep enough for prominence=ATR)
    low[30] = 104.0
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
    """Nearest quality support below entry becomes stop. Target from nearest resistance or fallback."""
    df = make_test_data()
    # Use lower entry so forced swing low (~104) is within max_stop_distance
    entry_price = 107.0
    atr = 2.5
    highs, lows = detect_swings(df, order=5)
    low_zones = cluster_levels(lows, tolerance=0.005)
    high_zones = cluster_levels(highs, tolerance=0.005)
    stop, target, method = compute_stop_target(
        entry_price, atr, low_zones, high_zones, df, time_horizon='swing'
    )
    assert stop is not None, f"Stop should not be None"
    assert stop < entry_price, f"Stop {stop} should be below entry {entry_price}"
    assert target is not None, f"Target should not be None"
    assert target > entry_price, f"Target {target} should be above entry {entry_price}"
    assert 'support' in method, f"Should use support stop, got {method}"


def test_compute_stop_target_fallback_atr():
    """If no valid swing low, fall back to 2x ATR."""
    entry_price = 115.0
    atr = 3.0
    # Empty zones — no swing lows below entry
    stop, target, method = compute_stop_target(
        entry_price, atr, [], [], pd.DataFrame(), time_horizon='swing'
    )
    expected_stop = entry_price - 1.5 * atr  # 110.5
    assert abs(stop - expected_stop) < 0.01
    assert target > entry_price
    assert method.startswith('atr+')


def test_compute_sr_for_symbol_dynamic_price_filter(seeded_db):
    """ATR-based dynamic filter rejects levels beyond ~10% from current price."""
    conn = seeded_db.get_connection()
    n = 130
    close = np.full(n, 100.0)
    # Two dips to 88 (bars 5-14, 25-34) — creates swing lows near ~87.25
    close[5:15] = [100, 95, 92, 90, 88, 89, 91, 93, 96, 100]
    close[25:35] = [100, 95, 92, 90, 88, 89, 91, 93, 96, 100]
    # Two spikes to 112 (bars 15-24, 35-44) — creates swing highs near ~112.75
    close[15:25] = [100, 104, 107, 110, 112, 111, 109, 106, 103, 100]
    close[35:45] = [100, 104, 107, 110, 112, 111, 109, 106, 103, 100]
    # Near-100 swings (bars 45-129) — creates swing levels near ~97.25 and ~102.75
    for i in range(45, n):
        close[i] = 100 + (i % 6 - 3) * 0.5

    from datetime import datetime, timedelta
    start = datetime(2026, 1, 1)
    for i in range(n):
        cp = close[i]
        date = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO market_data (symbol, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('TEST', date, cp, cp + 0.75, cp - 0.75, cp, 1000000)
        )
    conn.commit()

    supports, resistances = compute_sr_for_symbol(seeded_db, 'TEST')

    # ATR = 1.5 (High-Low = 1.5 each bar), current_price = 100.0
    # atr_pct_val = 0.015, filter_pct = max(0.10, 0.075) = 0.10
    # floor = 90.0, ceiling = 110.0
    # Old 50% filter: floor=50, ceiling=150 → 87.25 and 112.75 pass
    # New dynamic filter: floor=90, ceiling=110 → 87.25 and 112.75 rejected

    assert len(supports) > 0, "Should have at least one support near current price"
    assert len(resistances) > 0, "Should have at least one resistance near current price"
    for s in supports:
        assert s >= 90.0, f"Support {s:.2f} is below dynamic floor 90.0"
    for r in resistances:
        assert r <= 110.0, f"Resistance {r:.2f} is above dynamic ceiling 110.0"
