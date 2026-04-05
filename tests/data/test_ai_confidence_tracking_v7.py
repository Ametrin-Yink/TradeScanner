"""Tests for AI confidence feedback loop v7.0."""
import pytest
from data.db import Database
from datetime import datetime
from pathlib import Path


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with temporary path."""
    db_path = tmp_path / "test_confidence_tracking.db"
    return Database(db_path)


class TestAIConfidenceTracking:
    """Test AI confidence outcome tracking."""

    def test_create_ai_confidence_outcomes_table(self, test_db):
        """Should create ai_confidence_outcomes table."""
        # Create table
        test_db.create_ai_confidence_outcomes_table()

        # Verify table exists
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_confidence_outcomes'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 'ai_confidence_outcomes'

    def test_save_and_query_outcome(self, test_db):
        """Should save outcome and query by strategy/regime."""
        # Create table first
        test_db.create_ai_confidence_outcomes_table()

        # Save outcome
        scan_date = datetime.now().date().isoformat()
        test_db.save_ai_confidence_outcome(
            scan_date=scan_date,
            symbol='AAPL',
            strategy='MomentumBreakout',
            ai_confidence=85,
            tier='A',
            regime='bear_moderate',
            entry_price=150.0
        )

        # Query outcomes for Strategy A in bear regimes
        outcomes = test_db.get_ai_confidence_outcomes(
            strategy='MomentumBreakout',
            regime='bear_moderate'
        )

        assert len(outcomes) > 0
        assert outcomes[0]['symbol'] == 'AAPL'
        assert outcomes[0]['ai_confidence'] == 85
        assert outcomes[0]['strategy'] == 'MomentumBreakout'
        assert outcomes[0]['regime'] == 'bear_moderate'
        assert outcomes[0]['tier'] == 'A'
        assert outcomes[0]['entry_price'] == 150.0

    def test_update_outcome_with_returns(self, test_db):
        """Should update outcome with 5d and 10d returns."""
        # Create table first
        test_db.create_ai_confidence_outcomes_table()

        # Save outcome
        scan_date = datetime.now().date().isoformat()
        test_db.save_ai_confidence_outcome(
            scan_date=scan_date,
            symbol='MSFT',
            strategy='PullbackEntry',
            ai_confidence=75,
            tier='B',
            regime='neutral',
            entry_price=300.0
        )

        # Get the ID of the saved outcome
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM ai_confidence_outcomes WHERE symbol = 'MSFT'"
            )
            outcome_id = cursor.fetchone()[0]

        # Update with returns
        test_db.update_ai_confidence_outcome(
            id=outcome_id,
            outcome_5d=5.2,
            outcome_10d=8.7
        )

        # Verify update
        outcomes = test_db.get_ai_confidence_outcomes(
            strategy='PullbackEntry',
            regime='neutral'
        )

        assert len(outcomes) == 1
        assert outcomes[0]['outcome_5d_return'] == 5.2
        assert outcomes[0]['outcome_10d_return'] == 8.7

    def test_query_by_multiple_filters(self, test_db):
        """Should query outcomes by multiple filters."""
        # Create table first
        test_db.create_ai_confidence_outcomes_table()

        # Save multiple outcomes
        scan_date = datetime.now().date().isoformat()
        test_db.save_ai_confidence_outcome(
            scan_date=scan_date, symbol='AAPL', strategy='MomentumBreakout',
            ai_confidence=85, tier='A', regime='bear_moderate', entry_price=150.0
        )
        test_db.save_ai_confidence_outcome(
            scan_date=scan_date, symbol='MSFT', strategy='MomentumBreakout',
            ai_confidence=90, tier='S', regime='bear_moderate', entry_price=300.0
        )
        test_db.save_ai_confidence_outcome(
            scan_date=scan_date, symbol='GOOGL', strategy='MomentumBreakout',
            ai_confidence=70, tier='B', regime='bull_strong', entry_price=140.0
        )

        # Query by strategy only
        outcomes = test_db.get_ai_confidence_outcomes(strategy='MomentumBreakout')
        assert len(outcomes) == 3

        # Query by strategy + regime
        outcomes = test_db.get_ai_confidence_outcomes(
            strategy='MomentumBreakout',
            regime='bear_moderate'
        )
        assert len(outcomes) == 2

        # Query by tier only
        outcomes = test_db.get_ai_confidence_outcomes(tier='A')
        assert len(outcomes) == 1

        # Query by confidence range
        outcomes = test_db.get_ai_confidence_outcomes(
            strategy='MomentumBreakout',
            min_confidence=80,
            max_confidence=95
        )
        assert len(outcomes) == 2

    def test_multiple_outcomes_same_symbol(self, test_db):
        """Should handle multiple outcomes for same symbol on different dates."""
        # Create table first
        test_db.create_ai_confidence_outcomes_table()

        # Save outcomes for different dates
        test_db.save_ai_confidence_outcome(
            scan_date='2026-04-01',
            symbol='NVDA',
            strategy='EarningsGap',
            ai_confidence=88,
            tier='A',
            regime='bull_strong',
            entry_price=500.0
        )
        test_db.save_ai_confidence_outcome(
            scan_date='2026-04-02',
            symbol='NVDA',
            strategy='EarningsGap',
            ai_confidence=82,
            tier='A',
            regime='bull_moderate',
            entry_price=510.0
        )

        # Query all NVDA outcomes
        outcomes = test_db.get_ai_confidence_outcomes(symbol='NVDA')
        assert len(outcomes) == 2

        # Query by specific date
        outcomes = test_db.get_ai_confidence_outcomes(
            symbol='NVDA',
            scan_date='2026-04-02'
        )
        assert len(outcomes) == 1
        assert outcomes[0]['ai_confidence'] == 82
