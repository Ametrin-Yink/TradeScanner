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
