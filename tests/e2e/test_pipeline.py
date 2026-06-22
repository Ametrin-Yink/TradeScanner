from core.sector_analyzer import SectorAnalyzer


def test_full_pipeline_runs(seeded_db, mock_ai):
    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    assert 'market' in result
    assert 'sectors' in result
    assert 'focus_summary' in result
    assert 'timestamp' in result

    market = result['market']
    assert market.regime == 'bull_moderate'
    assert market.spy_price > 0

    assert len(result['sectors']) == 3
    for sector in result['sectors']:
        assert sector.name
        assert sector.stock_count >= 0


def test_pipeline_deduplicates_picks(seeded_db, mock_ai):
    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    for s in result['sectors']:
        assert len(s.highlights) <= 3


def test_pipeline_rr_values(seeded_db, mock_ai):
    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    for s in result['sectors']:
        for h in s.highlights:
            assert h.rr > 0
            assert h.stop < h.entry
            assert h.target > h.entry
            assert h.stop > 0
            assert h.target > 0


# ------------------------------------------------------------------
# Volume threshold relaxation tests (Task 13.3)
# ------------------------------------------------------------------


def test_breakout_vol_1x(seeded_db, mock_ai):
    """Breakout fires at volume_ratio > 1.0 (relaxed from 1.5)."""
    from core.sector_analyzer import SectorAnalyzer
    conn = seeded_db.get_connection()

    # Make NVDA a breakout candidate: price above 60d high, volume_ratio=1.2
    conn.execute("""
        UPDATE tier1_cache
        SET current_price = 1000.0, high_60d = 980.0, volume_ratio = 1.2
        WHERE symbol = 'NVDA'
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'NVDA':
                assert h.reason == 'Breakout', f"Expected Breakout, got {h.reason}"
                found = True
    assert found, "NVDA not found in any sector highlights"


def test_near_support_vol_relaxed(seeded_db, mock_ai):
    """Near Support fires at volume_ratio 1.3 (no longer skipped at >=1.0)."""
    from core.sector_analyzer import SectorAnalyzer
    conn = seeded_db.get_connection()

    # Make PLTR a near-support candidate with volume_ratio=1.3
    conn.execute("""
        UPDATE tier1_cache
        SET current_price = 22.2, low_60d = 22.0, high_60d = 30.0,
            volume_ratio = 1.3, rs_percentile = 50,
            ema21 = 21.5, ema50 = 20.0
        WHERE symbol = 'PLTR'
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    found = False
    for sector in result['sectors']:
        for h in sector.highlights:
            if h.symbol == 'PLTR':
                assert h.reason == 'Near Support', f"Expected Near Support, got {h.reason}"
                found = True
    assert found, "PLTR not found in any sector highlights"
