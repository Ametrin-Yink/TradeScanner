"""Tests for daily recommendation reconciliation and performance tracking."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from core.reconciler import reconcile_recommendations, generate_performance_summary


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_db():
    """Create a mock Database instance."""
    db = MagicMock()
    return db


def _make_rec(overrides=None):
    """Create a recommendation dict with sensible defaults."""
    base = {
        'id': 1,
        'trade_date': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
        'symbol': 'TEST',
        'sector': 'Technology',
        'setup_type': 'Breakout',
        'entry_price': 100.0,
        'stop_price': 95.0,
        'target_price': 110.0,
        'max_days': 20,
    }
    if overrides:
        base.update(overrides)
    return base


def _make_cache(overrides=None):
    """Create a tier1 cache dict with sensible defaults."""
    base = {
        'current_price': 103.0,
        'atr_pct': 0.03,
    }
    if overrides:
        base.update(overrides)
    return base


# ------------------------------------------------------------------
# reconcile_recommendations tests
# ------------------------------------------------------------------

class TestReconcileRecommendations:
    """Tests for reconcile_recommendations()."""

    def test_no_active_recs_returns_zero(self, mock_db):
        """When no active recommendations exist, should return 0."""
        mock_db.get_active_recommendations.return_value = []
        result = reconcile_recommendations(mock_db)
        assert result == 0

    def test_stop_loss_hit_resolves_correctly(self, mock_db):
        """When price <= stop_price, resolve as stopped_out with loss."""
        rec = _make_rec({'entry_price': 100.0, 'stop_price': 95.0})
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': 94.0})

        result = reconcile_recommendations(mock_db)

        assert result == 1
        expected_pnl = (95.0 - 100.0) / 100.0 * 100  # -5.0%
        mock_db.resolve_recommendation.assert_called_once_with(
            1, 'stopped_out', 'loss', pytest.approx(-5.0, abs=0.01), 5
        )

    def test_target_hit_resolves_correctly(self, mock_db):
        """When price >= target_price, resolve as target_hit with win."""
        rec = _make_rec({'entry_price': 100.0, 'target_price': 110.0})
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': 112.0})

        result = reconcile_recommendations(mock_db)

        assert result == 1
        expected_pnl = (110.0 - 100.0) / 100.0 * 100  # +10.0%
        mock_db.resolve_recommendation.assert_called_once_with(
            1, 'target_hit', 'win', pytest.approx(10.0, abs=0.01), 5
        )

    def test_expired_with_profit(self, mock_db):
        """When days_open >= max_days and price > entry, resolve as expired with win."""
        rec = _make_rec({
            'entry_price': 100.0, 'max_days': 3,
            'trade_date': (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'),
        })
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': 105.0})

        result = reconcile_recommendations(mock_db)

        assert result == 1
        expected_pnl = (105.0 - 100.0) / 100.0 * 100  # +5.0%
        mock_db.resolve_recommendation.assert_called_once_with(
            1, 'expired', 'win', pytest.approx(5.0, abs=0.01), 10
        )

    def test_expired_with_loss(self, mock_db):
        """When days_open >= max_days and price <= entry, resolve as expired with loss."""
        rec = _make_rec({
            'entry_price': 100.0, 'max_days': 3,
            'trade_date': (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'),
        })
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': 98.0})

        result = reconcile_recommendations(mock_db)

        assert result == 1
        expected_pnl = (98.0 - 100.0) / 100.0 * 100  # -2.0%
        mock_db.resolve_recommendation.assert_called_once_with(
            1, 'expired', 'loss', pytest.approx(-2.0, abs=0.01), 10
        )

    def test_no_cache_skips_rec(self, mock_db):
        """When no tier1 cache exists, skip the recommendation."""
        rec = _make_rec()
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = None

        result = reconcile_recommendations(mock_db)

        assert result == 0
        mock_db.resolve_recommendation.assert_not_called()

    def test_no_current_price_skips_rec(self, mock_db):
        """When cache exists but has no current_price, skip."""
        rec = _make_rec()
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': None})

        result = reconcile_recommendations(mock_db)

        assert result == 0
        mock_db.resolve_recommendation.assert_not_called()

    def test_active_rec_not_resolved(self, mock_db):
        """When price is between stop and target and not expired, don't resolve."""
        rec = _make_rec({
            'entry_price': 100.0, 'stop_price': 95.0, 'target_price': 110.0,
            'max_days': 20,
        })
        mock_db.get_active_recommendations.return_value = [rec]
        mock_db.get_tier1_cache.return_value = _make_cache({'current_price': 103.0})

        result = reconcile_recommendations(mock_db)

        assert result == 0
        mock_db.resolve_recommendation.assert_not_called()

    def test_multiple_recs_mixed_outcomes(self, mock_db):
        """Multiple recommendations should each be resolved independently."""
        recs = [
            _make_rec({
                'id': 1, 'symbol': 'STOP', 'entry_price': 100.0, 'stop_price': 95.0,
                'target_price': 110.0, 'max_days': 20,
            }),
            _make_rec({
                'id': 2, 'symbol': 'TARG', 'entry_price': 100.0, 'stop_price': 95.0,
                'target_price': 110.0, 'max_days': 20,
                'trade_date': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
            }),
        ]
        mock_db.get_active_recommendations.return_value = recs

        def _cache(sym):
            caches = {'STOP': _make_cache({'current_price': 93.0}),
                      'TARG': _make_cache({'current_price': 112.0})}
            return caches.get(sym)

        mock_db.get_tier1_cache.side_effect = _cache

        result = reconcile_recommendations(mock_db)

        assert result == 2
        assert mock_db.resolve_recommendation.call_count == 2


# ------------------------------------------------------------------
# generate_performance_summary tests
# ------------------------------------------------------------------

class TestGeneratePerformanceSummary:
    """Tests for generate_performance_summary()."""

    def test_no_resolved_trades(self, mock_db):
        """When no resolved trades exist, return empty summary."""
        mock_db.get_resolved_recommendations.return_value = []
        result = generate_performance_summary(mock_db)
        assert result['total_trades'] == 0
        assert 'note' in result

    def test_all_wins(self, mock_db):
        """When all trades are wins, win_rate should be 100%."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'AAPL', 'sector': 'Tech', 'setup_type': 'Breakout',
             'outcome': 'win', 'pnl_pct': 5.0},
            {'id': 2, 'symbol': 'NVDA', 'sector': 'Tech', 'setup_type': 'Momentum',
             'outcome': 'win', 'pnl_pct': 3.0},
        ]
        result = generate_performance_summary(mock_db)
        assert result['total_trades'] == 2
        assert result['win_rate'] == 100.0
        assert result['avg_win_pct'] == 4.0
        assert result['avg_loss_pct'] == 0

    def test_mixed_outcomes(self, mock_db):
        """Mix of wins and losses should calculate correctly."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'A', 'sector': 'Tech', 'setup_type': 'Breakout',
             'outcome': 'win', 'pnl_pct': 10.0},
            {'id': 2, 'symbol': 'B', 'sector': 'Energy', 'setup_type': 'Swing',
             'outcome': 'loss', 'pnl_pct': -5.0},
            {'id': 3, 'symbol': 'C', 'sector': 'Tech', 'setup_type': 'Breakout',
             'outcome': 'win', 'pnl_pct': 2.0},
            {'id': 4, 'symbol': 'D', 'sector': 'Energy', 'setup_type': 'Swing',
             'outcome': 'loss', 'pnl_pct': -3.0},
        ]
        result = generate_performance_summary(mock_db)
        assert result['total_trades'] == 4
        assert result['win_rate'] == 50.0
        assert result['avg_win_pct'] == 6.0
        assert result['avg_loss_pct'] == -4.0
        assert result['total_pnl_pct'] == 4.0  # 10+2-5-3 = 4

    def test_profit_factor_calculation(self, mock_db):
        """Profit factor should be total wins / abs(total losses)."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'A', 'sector': 'X', 'setup_type': 'T',
             'outcome': 'win', 'pnl_pct': 10.0},
            {'id': 2, 'symbol': 'B', 'sector': 'X', 'setup_type': 'T',
             'outcome': 'win', 'pnl_pct': 5.0},
            {'id': 3, 'symbol': 'C', 'sector': 'X', 'setup_type': 'T',
             'outcome': 'loss', 'pnl_pct': -3.0},
        ]
        result = generate_performance_summary(mock_db)
        # profit_factor = 15.0 / 3.0 = 5.0
        assert result['profit_factor'] == 5.0

    def test_profit_factor_no_losses(self, mock_db):
        """When there are no losses, profit_factor should be None."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'A', 'sector': 'X', 'setup_type': 'T',
             'outcome': 'win', 'pnl_pct': 5.0},
        ]
        result = generate_performance_summary(mock_db)
        assert result['profit_factor'] is None

    def test_by_sector_breakdown(self, mock_db):
        """Performance should be broken down by sector."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'A', 'sector': 'Tech', 'setup_type': 'T',
             'outcome': 'win', 'pnl_pct': 10.0},
            {'id': 2, 'symbol': 'B', 'sector': 'Tech', 'setup_type': 'T',
             'outcome': 'loss', 'pnl_pct': -2.0},
            {'id': 3, 'symbol': 'C', 'sector': 'Energy', 'setup_type': 'T',
             'outcome': 'win', 'pnl_pct': 5.0},
        ]
        result = generate_performance_summary(mock_db)
        assert 'by_sector' in result
        tech = result['by_sector']['Tech']
        assert tech['win_rate'] == 50.0  # 1 win / 2 total
        assert tech['pnl'] == 8.0  # 10 + (-2) = 8
        energy = result['by_sector']['Energy']
        assert energy['win_rate'] == 100.0  # 1 win / 1 total
        assert energy['pnl'] == 5.0

    def test_by_setup_breakdown(self, mock_db):
        """Performance should be broken down by setup type."""
        mock_db.get_resolved_recommendations.return_value = [
            {'id': 1, 'symbol': 'A', 'sector': 'X', 'setup_type': 'Breakout',
             'outcome': 'win', 'pnl_pct': 10.0},
            {'id': 2, 'symbol': 'B', 'sector': 'X', 'setup_type': 'Breakout',
             'outcome': 'loss', 'pnl_pct': -5.0},
            {'id': 3, 'symbol': 'C', 'sector': 'X', 'setup_type': 'Swing',
             'outcome': 'win', 'pnl_pct': 3.0},
        ]
        result = generate_performance_summary(mock_db)
        assert 'by_setup' in result
        breakout = result['by_setup']['Breakout']
        assert breakout['win_rate'] == 50.0
        assert breakout['pnl'] == 5.0
        swing = result['by_setup']['Swing']
        assert swing['win_rate'] == 100.0
        assert swing['pnl'] == 3.0
