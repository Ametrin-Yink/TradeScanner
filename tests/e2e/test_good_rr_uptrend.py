"""Test Good R/R uptrend filter, ATR-based thresholds, and Near Support volume check."""
from core.sector_analyzer import SectorAnalyzer


def test_good_rr_uptrend_filter_skips_falling_knife(seeded_db, mock_ai):
    """Stock meeting Good R/R criteria but failing all uptrend checks should be skipped."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('GRRFAIL', 'Falling Knife', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('GRRFAIL', 3)")

    # low_60d=300, high_60d=360 -> stop=297, target=360, price=310
    # rr=(360-310)/(310-297)=50/13=3.85 >= 2.0 -> qualifies for Good R/R
    # Near Support: (310-300)/300=3.3% > near_threshold(1.6%) -> no match
    # Strong Momentum: rs=50 < 80 -> no match
    # ema50=315, price=310 NOT > ema50 -> fail check 1
    # Software sector: trend='neutral' (no IGV etf_cache) -> fail check 2
    # volume_ratio=1.0 NOT > 1.2 -> fail check 3
    # All 3 uptrend checks fail -> skip
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('GRRFAIL', 310.0, 360.0, 300.0, 0.02, 50.0,
                310.0, 315.0, 1.0, '[300.0]', '[360.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('GRRFAIL', '2026-06-19', 309.0, 311.0, 308.0, 310.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    for sector in result['sectors']:
        for h in sector.highlights:
            assert h.symbol != 'GRRFAIL', \
                "GRRFAIL should be skipped (fails all uptrend checks)"


def test_good_rr_passes_when_price_above_ema50(seeded_db, mock_ai):
    """Stock meeting Good R/R criteria with price > ema50 should pass uptrend filter."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('GRRPASS', 'Good RR Pass', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('GRRPASS', 3)")

    # low_60d=300, high_60d=360 -> stop=297, target=360, price=310
    # rr=(360-310)/(310-297)=3.85 >= 2.0 -> qualifies for Good R/R
    # ema50=305, price=310 > ema50 -> uptrend_ok=True (check 1 passes)
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('GRRPASS', 310.0, 360.0, 300.0, 0.02, 50.0,
                310.0, 305.0, 1.0, '[300.0]', '[360.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('GRRPASS', '2026-06-19', 309.0, 311.0, 308.0, 310.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'GRRPASS':
                assert h.reason == 'Good R/R', \
                    f"Expected 'Good R/R' but got '{h.reason}'"
                found = True

    assert found, "GRRPASS should be a highlight with 'Good R/R' reason"


def test_good_rr_passes_on_elevated_volume(seeded_db, mock_ai):
    """Stock meeting Good R/R with volume_ratio > 1.2 should pass uptrend filter."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('GRRVOL', 'Good RR Volume', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('GRRVOL', 3)")

    # low_60d=300, high_60d=360 -> stop=297, target=360, price=310
    # ema50=315, price=310 NOT > ema50 -> fail check 1
    # Software sector: trend='neutral' -> fail check 2
    # volume_ratio=1.3 > 1.2 -> uptrend_ok=True (check 3 passes)
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('GRRVOL', 310.0, 360.0, 300.0, 0.02, 50.0,
                310.0, 315.0, 1.3, '[300.0]', '[360.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('GRRVOL', '2026-06-19', 309.0, 311.0, 308.0, 310.0, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'GRRVOL':
                assert h.reason == 'Good R/R', \
                    f"Expected 'Good R/R' but got '{h.reason}'"
                found = True

    assert found, "GRRVOL should be a highlight with 'Good R/R' reason (volume > 1.2)"


def test_near_support_atr_threshold_wider_than_2pct(seeded_db, mock_ai):
    """Stock within ATR-based threshold (>2% from 60d low) should get Near Support."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('ATRSUP', 'ATR Support', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('ATRSUP', 3)")

    # low_60d=100, atr_pct=0.04
    # near_threshold = max(0.01, 0.04*0.8) = max(0.01, 0.032) = 0.032 = 3.2%
    # price=102.5 -> (102.5-100)/100 = 0.025 = 2.5%
    # 2.5% <= 3.2% -> within ATR threshold
    # 2.5% > 2% -> would fail old hardcoded 0.02 check
    # volume_ratio=0.8 < 1.0 -> passes volume check
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('ATRSUP', 102.5, 120.0, 100.0, 0.04, 50.0,
                105.0, 100.0, 0.8, '[100.0]', '[120.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('ATRSUP', '2026-06-19', 102.0, 103.0, 101.5, 102.5, 500000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'ATRSUP':
                assert h.reason == 'Near Support', \
                    f"Expected 'Near Support' but got '{h.reason}'"
                found = True

    assert found, "ATRSUP should be a highlight with 'Near Support' reason"


def test_near_support_skips_elevated_volume(seeded_db, mock_ai):
    """Stock near support with elevated volume (>= 1.0) should be skipped."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('VOLSUP', 'Volume Support', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('VOLSUP', 3)")

    # low_60d=100, atr_pct=0.025
    # near_threshold = max(0.01, 0.025*0.8) = max(0.01, 0.02) = 0.02 = 2%
    # price=101.5 -> (101.5-100)/100 = 0.015 = 1.5% <= 2% -> within threshold
    # volume_ratio=1.5 >= 1.0 -> SKIP
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('VOLSUP', 101.5, 120.0, 100.0, 0.025, 50.0,
                105.0, 100.0, 1.5, '[100.0]', '[120.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('VOLSUP', '2026-06-19', 101.0, 102.0, 100.8, 101.5, 2000000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    for sector in result['sectors']:
        for h in sector.highlights:
            assert h.symbol != 'VOLSUP', \
                "VOLSUP should be skipped (elevated volume at support)"
    # Also verify VOLSUP exists in sector stocks but not as highlight
    # (We just check no highlight has that symbol)


def test_near_support_passes_low_volume(seeded_db, mock_ai):
    """Stock near support with low volume (< 1.0) should get Near Support."""
    conn = seeded_db.get_connection()

    conn.execute("""
        INSERT INTO stocks (symbol, name, market_cap, is_active)
        VALUES ('LOWVOL', 'Low Volume Support', 100_000_000_000, 1)
    """)
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('LOWVOL', 3)")

    # low_60d=100, atr_pct=0.02
    # near_threshold = max(0.01, 0.02*0.8) = max(0.01, 0.016) = 0.016 = 1.6%
    # price=101.2 -> (101.2-100)/100 = 0.012 = 1.2% <= 1.6% -> within threshold
    # volume_ratio=0.7 < 1.0 -> passes volume check
    conn.execute("""
        INSERT INTO tier1_cache
        (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
         ema21, ema50, volume_ratio, supports, resistances, ret_5d)
        VALUES ('LOWVOL', 101.2, 120.0, 100.0, 0.02, 50.0,
                105.0, 100.0, 0.7, '[100.0]', '[120.0]', 1.0)
    """)
    conn.execute("""
        INSERT INTO market_data (symbol, date, open, high, low, close, volume)
        VALUES ('LOWVOL', '2026-06-19', 101.0, 102.0, 100.5, 101.2, 500000)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'LOWVOL':
                assert h.reason == 'Near Support', \
                    f"Expected 'Near Support' but got '{h.reason}'"
                found = True

    assert found, "LOWVOL should be a highlight with 'Near Support' reason"
