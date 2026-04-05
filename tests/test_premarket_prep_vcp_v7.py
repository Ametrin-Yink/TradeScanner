"""Tests for Phase 0 VCP pre-calculation v7.0."""
import pytest
import sqlite3
from pathlib import Path
import tempfile
import pandas as pd

from data.db import Database
from core.premarket_prep import PreMarketPrep


class TestPremarketPrepVcpV7:
    """Test VCP pre-calculation in Phase 0 Tier 1."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_market_data.db"
            db = Database(db_path=db_path)
            yield db

    def test_vcp_columns_added_to_db(self, temp_db):
        """Should have VCP columns in tier1_cache table."""
        # Run migration
        temp_db.migrate_tier1_cache_v5()

        # Check columns exist
        conn = temp_db.get_connection()
        cursor = conn.execute("PRAGMA table_info(tier1_cache)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'vcp_detected' in columns, "vcp_detected column should exist"
        assert 'vcp_tightness' in columns, "vcp_tightness column should exist"
        assert 'vcp_volume_ratio' in columns, "vcp_volume_ratio column should exist"

    def test_vcp_metrics_saved_to_db(self, temp_db):
        """Should save VCP metrics to tier1_cache."""
        # Run migration
        temp_db.migrate_tier1_cache_v5()

        # Create test data with VCP metrics
        test_data = {
            'cache_date': '2026-04-06',
            'current_price': 150.0,
            'vcp_detected': True,
            'vcp_tightness': 0.08,
            'vcp_volume_ratio': 0.65,
        }

        # Save to database
        temp_db.save_tier1_cache('AAPL', test_data)

        # Retrieve and verify
        retrieved = temp_db.get_tier1_cache('AAPL')

        assert retrieved is not None
        # SQLite stores BOOLEAN as INTEGER (0/1), so we check for truthy value
        assert retrieved['vcp_detected'] in [True, 1]
        assert retrieved['vcp_tightness'] == 0.08
        assert retrieved['vcp_volume_ratio'] == 0.65

    def test_vcp_metrics_none_when_not_detected(self, temp_db):
        """Should save None values when VCP not detected."""
        # Run migration
        temp_db.migrate_tier1_cache_v5()

        # Create test data without VCP
        test_data = {
            'cache_date': '2026-04-06',
            'current_price': 150.0,
            'vcp_detected': False,
            'vcp_tightness': None,
            'vcp_volume_ratio': None,
        }

        # Save to database
        temp_db.save_tier1_cache('MSFT', test_data)

        # Retrieve and verify
        retrieved = temp_db.get_tier1_cache('MSFT')

        assert retrieved is not None
        # SQLite stores BOOLEAN as INTEGER (0/1), so we check for falsy value
        assert retrieved['vcp_detected'] in [False, 0]
        assert retrieved['vcp_tightness'] is None
        assert retrieved['vcp_volume_ratio'] is None
