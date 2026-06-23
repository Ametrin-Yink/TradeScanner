"""Test composite_score function.

Verifies that composite_score properly uses RS_percentile and
rs_consecutive_days_80 instead of ret_5d for the momentum dimension,
plus volatility penalty and data completeness gate.
"""
import pytest
from core.sector_analyzer import StockHighlight, _composite_score


def _make_highlight(**overrides):
    """Create a StockHighlight with sensible defaults for scoring tests."""
    h = StockHighlight(
        symbol=overrides.pop('symbol', 'TEST'),
        name=overrides.pop('name', 'Test Stock'),
        price=overrides.pop('price', 100.0),
        market_cap=overrides.pop('market_cap', 1_000_000_000),
        reason=overrides.pop('reason', 'Breakout'),
        detail=overrides.pop('detail', 'Test detail'),
        rr=overrides.pop('rr', 2.0),
    )
    h.rs_percentile = overrides.get('rs_percentile', 50)
    h.volume_ratio = overrides.get('volume_ratio', 1.5)
    h.ret_5d = overrides.get('ret_5d', 0)
    h.ema_above = overrides.get('ema_above', True)
    h.rs_consecutive_days_80 = overrides.get('rs_consecutive_days_80', 0)
    h.atr_pct = overrides.get('atr_pct', 0.03)
    return h


def test_higher_rs_percentile_gets_higher_score():
    """Stocks with higher RS_percentile should score higher, all else equal."""
    low = _make_highlight(rs_percentile=10)
    high = _make_highlight(rs_percentile=90)

    assert _composite_score(high) > _composite_score(low)


def test_rs_consecutive_days_80_boosts_score():
    """Stocks with high rs_consecutive_days_80 should get a momentum bonus."""
    no_streak = _make_highlight(rs_consecutive_days_80=0)
    strong_streak = _make_highlight(rs_consecutive_days_80=10)

    assert _composite_score(strong_streak) > _composite_score(no_streak)


def test_ret_5d_no_longer_affects_score():
    """ret_5d should not influence the composite score (removed from formula)."""
    negative_ret = _make_highlight(ret_5d=-10)
    positive_ret = _make_highlight(ret_5d=10)

    assert _composite_score(negative_ret) == _composite_score(positive_ret)


def test_volatility_penalty():
    """High-volatility stocks should get a lower score from the ATR penalty."""
    low_vol = _make_highlight(atr_pct=0.02)
    high_vol = _make_highlight(atr_pct=0.08)

    assert _composite_score(low_vol) > _composite_score(high_vol)


def test_volatility_penalty_clamped():
    """ATR penalty caps at 10% (max -5.0 penalty)."""
    h = _make_highlight(atr_pct=0.15)
    score = _composite_score(h)
    # With ATR=15% -> penalty = -min(15, 10) * 0.5 = -5.0
    # With ATR=1%  -> penalty = -min(1, 10) * 0.5 = -0.5
    # Difference = -0.5 - (-5.0) = 4.5
    no_penalty = _make_highlight(atr_pct=0.01)
    diff = _composite_score(no_penalty) - score
    assert diff == pytest.approx(4.5, abs=0.01)


def test_data_completeness_gate():
    """Stocks missing both rs_percentile and volume_ratio get -999.
    Only None (not 0) counts as missing — 0 is a legitimate value."""
    h = _make_highlight(rs_percentile=None, volume_ratio=None)
    assert _composite_score(h) == -999


def test_data_completeness_one_missing_ok():
    """Missing only one field (None) should still score normally."""
    h = _make_highlight(rs_percentile=None, volume_ratio=1.5)
    # Should not return -999 since only 1 field missing
    assert _composite_score(h) != -999
    assert _composite_score(h) > 0


# ------------------------------------------------------------------
# Soft diversity gate tests
# ------------------------------------------------------------------


def test_soft_diversity_different_reasons_preferred():
    """Different reasons are always selected before same-reason picks."""
    from core.sector_analyzer import _select_diverse
    reasons = ['Breakout', 'Near Support', 'Strong Momentum']
    candidates = [_make_highlight(symbol=f'S{i}', reason=r) for i, r in enumerate(reasons)]
    result = _select_diverse(candidates, max_picks=3)
    assert len(result) == 3
    assert {h.reason for h in result} == set(reasons)


def test_soft_diversity_allows_high_score_same_reason():
    """Same-reason candidates with score >= 70% of top score are selected."""
    from core.sector_analyzer import _select_diverse
    top = _make_highlight(symbol='A', reason='Breakout', rs_percentile=95, volume_ratio=2.0, rr=3.0)
    mid = _make_highlight(symbol='B', reason='Breakout', rs_percentile=80, volume_ratio=1.5, rr=2.5)
    candidates = sorted([top, mid], key=lambda c: _composite_score(c), reverse=True)
    result = _select_diverse(candidates, max_picks=3)
    assert len(result) == 2
    assert {h.symbol for h in result} == {'A', 'B'}


def test_soft_diversity_excludes_low_score_same_reason():
    """Same-reason candidates below 70% of top score are excluded."""
    from core.sector_analyzer import _select_diverse
    top = _make_highlight(symbol='A', reason='Breakout', rs_percentile=95, volume_ratio=2.0, rr=3.0)
    low = _make_highlight(symbol='B', reason='Breakout', rs_percentile=10, volume_ratio=0.5, rr=0.5)
    candidates = sorted([top, low], key=lambda c: _composite_score(c), reverse=True)
    result = _select_diverse(candidates, max_picks=3)
    assert len(result) == 1
    assert result[0].symbol == 'A'


def test_soft_diversity_max_three():
    """At most max_picks candidates are returned."""
    from core.sector_analyzer import _select_diverse
    candidates = [_make_highlight(symbol=f'S{i}', reason=f'R{i}') for i in range(5)]
    result = _select_diverse(candidates, max_picks=3)
    assert len(result) == 3


def test_diversity_cap_60pct():
    """Excess picks of a single setup type are culled when >60% of total."""
    from core.sector_analyzer import _enforce_setup_diversity, SectorAnalysis

    # Create 2 sectors with total 8 picks: 5 Breakout (62.5%), 3 Near Support (37.5%)
    # 5/8 = 62.5% > 60% => remove lowest-scored Breakout
    sectors = [
        SectorAnalysis(
            name='Tech', etf='XLK', stock_count=5,
            daily_change=1.0, ret_3m=10.0, rs_percentile=70.0,
            trend='uptrend', above_ema50=True,
            outlook='Positive',
        ),
        SectorAnalysis(
            name='Energy', etf='XLE', stock_count=3,
            daily_change=-0.5, ret_3m=5.0, rs_percentile=30.0,
            trend='neutral', above_ema50=False,
            outlook='Mixed',
        ),
    ]

    # 5 Breakout picks in Tech (with varied scores)
    for i in range(5):
        h = _make_highlight(
            symbol=f'BO{i}', reason='Breakout',
            rs_percentile=90 - i * 15,  # descending scores
            volume_ratio=2.0, rr=3.0,
        )
        sectors[0].highlights.append(h)

    # 3 Near Support picks in Energy
    for i in range(3):
        h = _make_highlight(
            symbol=f'NS{i}', reason='Near Support',
            rs_percentile=50 - i * 5,
            volume_ratio=0.8, rr=2.0,
        )
        sectors[1].highlights.append(h)

    _enforce_setup_diversity(sectors)

    # Collect all remaining picks
    all_remaining = sectors[0].highlights + sectors[1].highlights
    total = len(all_remaining)
    breakout_count = sum(1 for h in all_remaining if h.reason == 'Breakout')

    # Breakout must be <= 60% of total
    assert breakout_count / total <= 0.60, \
        f"Breakout {breakout_count}/{total} = {breakout_count/total:.0%} exceeds 60% cap"

    # The lowest-scored Breakout should have been removed
    # BO4 has rs_percentile=30 (lowest). Check it's gone
    remaining_symbols = {h.symbol for h in all_remaining}
    assert 'BO4' not in remaining_symbols, \
        "Lowest-scored Breakout (BO4) should have been removed"


# ------------------------------------------------------------------
# Focus summary: avoid list excludes sectors with picks
# ------------------------------------------------------------------


def test_sector_with_picks_not_in_avoid(monkeypatch):
    """Sectors with stock picks are excluded from the avoid list."""
    from core.sector_analyzer import (
        SectorAnalyzer, SectorAnalysis, MarketOverview, StockHighlight,
    )

    monkeypatch.setattr(
        SectorAnalyzer, '_ai_focus_reasoning',
        lambda self, market, focus, avoid, top5: "Mock reasoning"
    )

    market = MarketOverview(
        date='2026-06-21', regime='neutral', confidence=50,
        reasoning='Test', spy_price=500.0, spy_change_5d=0.0,
        vix=15.0, vix_status='low',
    )

    # 6 sectors with descending daily_change => descending scores
    # Same ret_3m makes ret_norm=0 for all
    # Focus: S_0, S_1, S_2.  Avoid: S_3, S_4, S_5
    sectors = []
    for i, daily in enumerate([10.0, 8.0, 6.0, 4.0, 2.0, 0.0]):
        name = f'S_{i}'
        s = SectorAnalysis(
            name=name, etf='', stock_count=10,
            daily_change=daily, ret_3m=10.0, rs_percentile=50.0,
            trend='uptrend', above_ema50=True, outlook='Positive',
        )
        if i == 3:  # 3rd-worst sector has picks
            h = StockHighlight(
                symbol='TEST', name='Test', price=100.0,
                market_cap=1_000_000_000, reason='Breakout', detail='Test',
            )
            s.highlights.append(h)
        sectors.append(s)

    analyzer = SectorAnalyzer(db=object())
    result = analyzer._generate_focus_summary(market, sectors)

    # S_3 (with picks) must NOT be in avoid list
    assert 'S_3' not in result.avoid_sectors, \
        f"Sector with picks (S_3) should not be in avoid: {result.avoid_sectors}"

    # Top 3 should still be focus
    assert result.focus_sectors == ['S_0', 'S_1', 'S_2']
