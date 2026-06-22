"""Test cross-sector deduplication of stock highlights."""
from core.sector_analyzer import _deduplicate_across_sectors, StockHighlight, SectorAnalysis


def test_duplicate_removed_from_lower_sector():
    """Same symbol in two sectors: kept only in higher-scored sector."""
    # High-scored highlight for AAPL in sector A (Breakout, high RS)
    h1 = StockHighlight(symbol='AAPL', name='Apple', price=200.0, market_cap=3e12,
                        reason='Breakout', detail='Broke 60d high')
    h1.rs_percentile = 90
    h1.volume_ratio = 1.5
    h1.rr = 3.0
    h1.ema_above = True
    h1.atr_pct = 0.02
    h1.rs_consecutive_days_80 = 0

    # Lower-scored highlight for AAPL in sector B (Near Support, low RS)
    h2 = StockHighlight(symbol='AAPL', name='Apple', price=200.0, market_cap=3e12,
                        reason='Near Support', detail='Near 60d low')
    h2.rs_percentile = 40
    h2.volume_ratio = 0.5
    h2.rr = 1.5
    h2.ema_above = False
    h2.atr_pct = 0.02
    h2.rs_consecutive_days_80 = 0

    sector_a = SectorAnalysis(name='Technology', etf='XLK', stock_count=10,
                              daily_change=1.0, ret_3m=10.0, rs_percentile=80,
                              trend='uptrend', above_ema50=True, outlook='good',
                              highlights=[h1])
    sector_b = SectorAnalysis(name='Consumer', etf='XLP', stock_count=10,
                              daily_change=0.5, ret_3m=5.0, rs_percentile=60,
                              trend='uptrend', above_ema50=True, outlook='ok',
                              highlights=[h2])

    assert len(sector_a.highlights) == 1
    assert len(sector_b.highlights) == 1

    _deduplicate_across_sectors([sector_a, sector_b])

    assert len(sector_a.highlights) == 1, "higher-scored sector should keep AAPL"
    assert len(sector_b.highlights) == 0, "lower-scored sector should lose AAPL"


def test_no_dedup_for_different_symbols():
    """Different symbols in sectors: no highlights removed."""
    h1 = StockHighlight(symbol='AAPL', name='Apple', price=200.0, market_cap=3e12,
                        reason='Breakout', detail='test')
    h2 = StockHighlight(symbol='MSFT', name='Microsoft', price=400.0, market_cap=3e12,
                        reason='Breakout', detail='test')
    h1.rs_percentile = 90; h1.volume_ratio = 1.5; h1.rr = 3.0; h1.ema_above = True; h1.atr_pct = 0.02
    h2.rs_percentile = 85; h2.volume_ratio = 1.2; h2.rr = 2.5; h2.ema_above = True; h2.atr_pct = 0.02

    sector_a = SectorAnalysis(name='Tech', etf='XLK', stock_count=10,
                              daily_change=1.0, ret_3m=10.0, rs_percentile=80,
                              trend='uptrend', above_ema50=True, outlook='good',
                              highlights=[h1])
    sector_b = SectorAnalysis(name='Consumer', etf='XLP', stock_count=10,
                              daily_change=0.5, ret_3m=5.0, rs_percentile=60,
                              trend='uptrend', above_ema50=True, outlook='ok',
                              highlights=[h2])

    _deduplicate_across_sectors([sector_a, sector_b])

    assert len(sector_a.highlights) == 1
    assert len(sector_b.highlights) == 1


def test_kept_pick_gets_also_in_note():
    """The kept pick's detail gets '(also in X)' appended."""
    h1 = StockHighlight(symbol='AAPL', name='Apple', price=200.0, market_cap=3e12,
                        reason='Breakout', detail='Broke 60d high')
    h1.rs_percentile = 90; h1.volume_ratio = 1.5; h1.rr = 3.0; h1.ema_above = True; h1.atr_pct = 0.02
    h2 = StockHighlight(symbol='AAPL', name='Apple', price=200.0, market_cap=3e12,
                        reason='Near Support', detail='Near 60d low')
    h2.rs_percentile = 40; h2.volume_ratio = 0.5; h2.rr = 1.5; h2.ema_above = False; h2.atr_pct = 0.02

    sector_a = SectorAnalysis(name='Technology', etf='XLK', stock_count=5,
                              daily_change=1.0, ret_3m=10.0, rs_percentile=80,
                              trend='uptrend', above_ema50=True, outlook='good',
                              highlights=[h1])
    sector_b = SectorAnalysis(name='Consumer', etf='XLP', stock_count=5,
                              daily_change=0.5, ret_3m=5.0, rs_percentile=60,
                              trend='uptrend', above_ema50=True, outlook='ok',
                              highlights=[h2])

    _deduplicate_across_sectors([sector_a, sector_b])

    assert 'also in Consumer' in sector_a.highlights[0].detail, \
        f"expected 'also in Consumer' in detail, got: {sector_a.highlights[0].detail}"
