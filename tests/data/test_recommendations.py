"""Tests for recommendations table lifecycle tracking."""
import pytest
from data.db import Database
from pathlib import Path


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with temporary path."""
    db_path = tmp_path / "test_recommendations.db"
    return Database(db_path)


class TestRecommendations:
    """Test recommendations CRUD and lifecycle."""

    def test_create_recommendations_table(self, test_db):
        """Should create recommendations table."""
        test_db.create_recommendations_table()
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendations'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 'recommendations'

    def test_save_and_get_active(self, test_db):
        """Should save a recommendation and retrieve it as active."""
        test_db.create_recommendations_table()
        rec = {
            'trade_date': '2026-06-20',
            'symbol': 'AAPL',
            'sector': 'Technology',
            'setup_type': 'Breakout',
            'entry_price': 195.0,
            'stop_price': 190.0,
            'target_price': 210.0,
            'rr': 3.0,
            'composite_score': 85.0,
            'position_size': 100,
            'position_cost': 19500.0,
            'risk_dollars': 500.0,
            'current_price': 195.0,
            'entry_distance_pct': 0.0,
        }
        test_db.save_recommendation(rec)
        active = test_db.get_active_recommendations()
        assert len(active) == 1
        assert active[0]['symbol'] == 'AAPL'
        assert active[0]['status'] == 'active'
        assert active[0]['rr'] == 3.0
        assert active[0]['composite_score'] == 85.0

    def test_resolve_recommendation(self, test_db):
        """Should resolve an active recommendation with outcome."""
        test_db.create_recommendations_table()
        rec = {
            'trade_date': '2026-06-20',
            'symbol': 'NVDA',
            'sector': 'Semiconductors',
            'setup_type': 'Near Support',
            'entry_price': 950.0,
            'stop_price': 920.0,
            'target_price': 1020.0,
            'rr': 2.33,
            'composite_score': 72.0,
            'position_size': 50,
            'position_cost': 47500.0,
            'risk_dollars': 1500.0,
            'current_price': 955.0,
            'entry_distance_pct': 0.5,
        }
        test_db.save_recommendation(rec)

        # Get the ID
        active = test_db.get_active_recommendations()
        rec_id = active[0]['id']

        # Resolve as target_hit
        test_db.resolve_recommendation(rec_id, 'target_hit', 'target_hit', 7.37, 12)

        # Verify no longer active
        active = test_db.get_active_recommendations()
        assert len(active) == 0

        # Verify resolved
        resolved = test_db.get_resolved_recommendations()
        assert len(resolved) == 1
        assert resolved[0]['id'] == rec_id
        assert resolved[0]['status'] == 'target_hit'
        assert resolved[0]['outcome'] == 'target_hit'
        assert resolved[0]['pnl_pct'] == 7.37
        assert resolved[0]['days_held'] == 12

    def test_get_resolved_recommendations_lookback(self, test_db):
        """Should respect lookback_days filter."""
        test_db.create_recommendations_table()
        # Save an active rec
        test_db.save_recommendation({
            'trade_date': '2026-05-01',
            'symbol': 'MSFT',
            'sector': 'Technology',
            'setup_type': 'Breakout',
            'entry_price': 420.0,
            'stop_price': 410.0,
            'target_price': 450.0,
        })
        active = test_db.get_active_recommendations()
        rec_id = active[0]['id']

        # Resolve it (resolved_date will be today)
        test_db.resolve_recommendation(rec_id, 'stopped_out', 'stopped_out', -2.38, 5)

        resolved = test_db.get_resolved_recommendations(lookback_days=1)
        assert len(resolved) == 1

        resolved = test_db.get_resolved_recommendations(lookback_days=0)
        # With lookback=0, only today's resolved records should match
        assert len(resolved) == 1

    def test_multiple_active_recommendations(self, test_db):
        """Should handle multiple active recommendations."""
        test_db.create_recommendations_table()
        recs = [
            {
                'trade_date': '2026-06-20', 'symbol': 'AAPL',
                'sector': 'Technology', 'setup_type': 'Breakout',
                'entry_price': 195.0, 'stop_price': 190.0, 'target_price': 210.0,
            },
            {
                'trade_date': '2026-06-20', 'symbol': 'NVDA',
                'sector': 'Semiconductors', 'setup_type': 'Near Support',
                'entry_price': 950.0, 'stop_price': 920.0, 'target_price': 1020.0,
            },
            {
                'trade_date': '2026-06-20', 'symbol': 'MSFT',
                'sector': 'Technology', 'setup_type': 'Strong Momentum',
                'entry_price': 420.0, 'stop_price': 410.0, 'target_price': 450.0,
            },
        ]
        for rec in recs:
            test_db.save_recommendation(rec)

        active = test_db.get_active_recommendations()
        assert len(active) == 3

        # Resolve one
        test_db.resolve_recommendation(active[0]['id'], 'expired', 'expired', 0.0, 20)
        active = test_db.get_active_recommendations()
        assert len(active) == 2

    def test_recommendation_auto_table_creation(self, test_db):
        """Should auto-create recommendations table via _init_db."""
        # Database() calls _init_db which should call create_recommendations_table
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendations'"
            )
            row = cursor.fetchone()
            assert row is not None
