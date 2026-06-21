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
    """Stocks missing both rs_percentile and volume_ratio get -999."""
    h = _make_highlight(rs_percentile=0, volume_ratio=0)
    assert _composite_score(h) == -999


def test_data_completeness_one_missing_ok():
    """Missing only one field should still score normally."""
    h = _make_highlight(rs_percentile=0, volume_ratio=1.5)
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
