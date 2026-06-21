"""Test Resistance Test setup type replaces Near Resistance.

Verifies that:
- Stocks meeting all 4 confirmations get 'Resistance Test' reason.
- Stocks missing any confirmation are skipped (no highlight).
- Setup bonus includes 'Resistance Test' at 0.80.
"""
import pytest
from core.sector_analyzer import SectorAnalyzer, _composite_score, StockHighlight


def test_resistance_test_setup_bonus_in_composite_score():
    """Resistance Test (0.80 bonus) should score higher than Good R/R (0.50) all else equal."""
    setup_bonus = {
        'Resistance Test': 0.80,
        'Breakout': 1.0,
        'Strong Momentum': 0.9,
        'Good R/R': 0.5,
        'Near Support': 0.7,
    }

    rt = StockHighlight(
        symbol='RT', name='Resistance Test', price=100.0,
        market_cap=1_000_000_000, reason='Resistance Test', detail='Test', rr=2.0,
    )
    rt.rs_percentile = 70
    rt.volume_ratio = 1.5
    rt.ema_above = True
    rt.rs_consecutive_days_80 = 0

    grr = StockHighlight(
        symbol='GRR', name='Good RR', price=100.0,
        market_cap=1_000_000_000, reason='Good R/R', detail='Test', rr=2.0,
    )
    grr.rs_percentile = 70
    grr.volume_ratio = 1.5
    grr.ema_above = True
    grr.rs_consecutive_days_80 = 0

    assert _composite_score(rt, setup_bonus) > _composite_score(grr, setup_bonus)


def test_resistance_test_requires_all_confirmations(seeded_db, mock_ai):
    """Stock within near_threshold but missing rs_percentile >= 50 gets no highlight."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('RESIST', 'Resistance Test Stock', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('RESIST', 1)")
    # Seed SMH etf_cache so Semiconductors sector trend=uptrend
    conn.execute("""
        INSERT INTO etf_cache
        (symbol, current_price, ret_5d, ret_3m, rs_percentile, above_ema50)
        VALUES ('SMH', 200.0, 2.0, 10.0, 70.0, 1)
    """)
    # price=198, high_60d=200 (1% below), atr_pct=0.02 -> near_threshold=0.016
    # (200-198)/198 = 0.0101 <= 0.016 -> within threshold
    # rs_percentile=40 (< 50) -> FAILS confirmation
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('RESIST', 198.0, 200.0, 180.0, 0.02, 40.0,
                190.0, 185.0, 1.2, '[180.0]', '[200.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('RESIST', '2026-06-19', 197.0, 199.0, 196.0, 198.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    for sector in result['sectors']:
        for h in sector.highlights:
            assert h.symbol != 'RESIST', \
                "RESIST should not be a highlight (rs_percentile=40 fails confirmation)"


def test_resistance_test_passes_all_confirmations(seeded_db, mock_ai):
    """Stock meeting all 4 confirmations should get 'Resistance Test' reason."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('GOODRT', 'Good Resistance Test', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('GOODRT', 1)")
    # Seed SMH etf_cache so Semiconductors sector gets ret_3m and above_ema50 -> trend=uptrend
    conn.execute("""
        INSERT INTO etf_cache
        (symbol, current_price, ret_5d, ret_3m, rs_percentile, above_ema50)
        VALUES ('SMH', 200.0, 2.0, 10.0, 70.0, 1)
    """)
    # All confirmations pass: ema50=180 < 198, volume_ratio=1.2 > 1.0, rs=72 >= 50
    # Semiconductors sector now has daily_change>0.5, ret_3m=10>5, above_ema50=True -> uptrend
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('GOODRT', 198.0, 200.0, 180.0, 0.02, 72.0,
                190.0, 180.0, 1.2, '[180.0]', '[200.0]', 1.5)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('GOODRT', '2026-06-19', 197.0, 199.0, 196.0, 198.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'GOODRT':
                assert h.reason == 'Resistance Test', \
                    f"Expected 'Resistance Test' but got '{h.reason}'"
                found = True

    assert found, "GOODRT should be a highlight with 'Resistance Test' reason"


def test_near_resistance_no_longer_exists(seeded_db, mock_ai):
    """Verify no highlight has 'Near Resistance' reason."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('CHECK', 'Check Stock', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('CHECK', 1)")
    conn.execute("""
        INSERT INTO etf_cache
        (symbol, current_price, ret_5d, ret_3m, rs_percentile, above_ema50)
        VALUES ('SMH', 200.0, 2.0, 10.0, 70.0, 1)
    """)
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('CHECK', 198.0, 200.0, 180.0, 0.02, 72.0,
                190.0, 180.0, 1.2, '[180.0]', '[200.0]', 1.5)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('CHECK', '2026-06-19', 197.0, 199.0, 196.0, 198.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found_resistance_test = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'CHECK':
                assert h.reason == 'Resistance Test', \
                    f"Expected 'Resistance Test' but got {h.reason} on {h.symbol}"
                found_resistance_test = True
            assert h.reason != 'Near Resistance', \
                f"'Near Resistance' should not appear; got {h.reason} on {h.symbol}"
    assert found_resistance_test, \
        "CHECK should be highlighted as 'Resistance Test' (replacing old 'Near Resistance')"
