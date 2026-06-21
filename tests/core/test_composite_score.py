"""Test composite_score function.

Verifies that composite_score properly uses RS_percentile and
rs_consecutive_days_80 instead of ret_5d for the momentum dimension.
"""
import pytest
from core.sector_analyzer import StockHighlight, _composite_score


def _make_highlight(**overrides):
    """Create a StockHighlight with sensible defaults for scoring tests."""
    h = StockHighlight(
        symbol='TEST', name='Test Stock', price=100.0,
        market_cap=1_000_000_000, reason='Breakout', detail='Test detail',
        rr=2.0,
    )
    h.rs_percentile = overrides.get('rs_percentile', 50)
    h.volume_ratio = overrides.get('volume_ratio', 1.5)
    h.ret_5d = overrides.get('ret_5d', 0)
    h.ema_above = overrides.get('ema_above', True)
    h.rs_consecutive_days_80 = overrides.get('rs_consecutive_days_80', 0)
    return h


SETUP_BONUS = {'Breakout': 1.0, 'Strong Momentum': 0.9}


def test_higher_rs_percentile_gets_higher_score():
    """Stocks with higher RS_percentile should score higher, all else equal."""
    low = _make_highlight(rs_percentile=10)
    high = _make_highlight(rs_percentile=90)

    assert _composite_score(high, SETUP_BONUS) > _composite_score(low, SETUP_BONUS)


def test_rs_consecutive_days_80_boosts_score():
    """Stocks with high rs_consecutive_days_80 should get a momentum bonus."""
    no_streak = _make_highlight(rs_consecutive_days_80=0)
    strong_streak = _make_highlight(rs_consecutive_days_80=10)

    assert _composite_score(strong_streak, SETUP_BONUS) > _composite_score(no_streak, SETUP_BONUS)


def test_ret_5d_no_longer_affects_score():
    """ret_5d should not influence the composite score (removed from formula)."""
    negative_ret = _make_highlight(ret_5d=-10)
    positive_ret = _make_highlight(ret_5d=10)

    assert _composite_score(negative_ret, SETUP_BONUS) == _composite_score(positive_ret, SETUP_BONUS)
