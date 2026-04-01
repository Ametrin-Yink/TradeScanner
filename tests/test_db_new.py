"""Tests for new database tables in data-fetch-rework project."""
import pytest
import json
import pickle
import pandas as pd
from pathlib import Path
from datetime import datetime
from data.db import Database


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with temporary path."""
    db_path = tmp_path / "test_new.db"
    return Database(db_path)


class TestTier1Cache:
    """Tests for tier1_cache table."""

    def test_save_tier1_cache(self, test_db):
        """Test saving Tier 1 cache metrics."""
        data = {
            'cache_date': '2026-04-01',
            'current_price': 150.0,
            'avg_volume_20d': 1000000.0,
            'volume_ratio': 1.5,
            'volume_sma': 900000.0,
            'ema8': 148.0,
            'ema21': 145.0,
            'ema50': 140.0,
            'ema200': 130.0,
            'atr': 2.5,
            'atr_pct': 1.67,
            'adr': 3.0,
            'adr_pct': 2.0,
            'ret_3m': 10.0,
            'ret_6m': 15.0,
            'ret_12m': 25.0,
            'ret_5d': 2.0,
            'rs_raw': 1.2,
            'rs_percentile': 75.0,
            'distance_from_52w_high': -5.0,
            'high_60d': 160.0,
            'low_60d': 140.0,
            'gaps_5d': 2,
            'rsi_14': 65.0,
            'data_days': 150
        }
        test_db.save_tier1_cache("AAPL", data)

        # Verify data was saved
        result = test_db.get_tier1_cache("AAPL")
        assert result is not None
        assert result['symbol'] == "AAPL"
        assert result['current_price'] == 150.0
        assert result['ema8'] == 148.0
        assert result['rs_percentile'] == 75.0

    def test_get_tier1_cache_not_found(self, test_db):
        """Test retrieving non-existent Tier 1 cache returns None."""
        result = test_db.get_tier1_cache("NONEXISTENT")
        assert result is None

    def test_save_tier1_cache_update(self, test_db):
        """Test updating existing Tier 1 cache."""
        data1 = {'cache_date': '2026-04-01', 'current_price': 150.0}
        data2 = {'cache_date': '2026-04-02', 'current_price': 155.0}

        test_db.save_tier1_cache("AAPL", data1)
        test_db.save_tier1_cache("AAPL", data2)

        result = test_db.get_tier1_cache("AAPL")
        assert result['current_price'] == 155.0
        assert result['cache_date'] == '2026-04-02'

    def test_save_tier1_cache_partial_data(self, test_db):
        """Test saving Tier 1 cache with only required fields."""
        data = {'cache_date': '2026-04-01', 'current_price': 150.0}
        test_db.save_tier1_cache("MSFT", data)

        result = test_db.get_tier1_cache("MSFT")
        assert result is not None
        assert result['symbol'] == "MSFT"
        assert result['current_price'] == 150.0


class TestTier3Cache:
    """Tests for tier3_cache table."""

    def test_save_tier3_cache(self, test_db):
        """Test saving market data as blob."""
        df = pd.DataFrame({
            'date': pd.date_range('2026-01-01', periods=5),
            'close': [100, 101, 102, 103, 104],
            'volume': [1000, 1100, 1200, 1300, 1400]
        })

        test_db.save_tier3_cache("SPY", df)

        # Verify data was saved
        result = test_db.get_tier3_cache("SPY")
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert list(result.columns) == ['date', 'close', 'volume']
        assert result['close'].iloc[-1] == 104

    def test_get_tier3_cache_not_found(self, test_db):
        """Test retrieving non-existent Tier 3 cache returns None."""
        result = test_db.get_tier3_cache("NONEXISTENT")
        assert result is None

    def test_save_tier3_cache_update(self, test_db):
        """Test updating existing Tier 3 cache."""
        df1 = pd.DataFrame({'close': [100, 101]})
        df2 = pd.DataFrame({'close': [105, 106, 107]})

        test_db.save_tier3_cache("VIX", df1)
        test_db.save_tier3_cache("VIX", df2)

        result = test_db.get_tier3_cache("VIX")
        assert len(result) == 3
        assert result['close'].iloc[-1] == 107


class TestUniverseSync:
    """Tests for universe_sync table."""

    def test_save_universe_sync(self, test_db):
        """Test saving universe sync history."""
        sync_data = {
            'sync_date': '2026-04-01',
            'symbols_added': 10,
            'symbols_removed': 5,
            'total_symbols': 2500
        }
        test_db.save_universe_sync(sync_data)

        # Verify data was saved by querying directly
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM universe_sync WHERE sync_date = ?",
                ('2026-04-01',)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[1] == '2026-04-01'  # sync_date
            assert row[2] == 10  # symbols_added
            assert row[3] == 5  # symbols_removed
            assert row[4] == 2500  # total_symbols

    def test_save_universe_sync_multiple(self, test_db):
        """Test saving multiple universe sync records."""
        sync_data1 = {'sync_date': '2026-04-01', 'symbols_added': 10, 'symbols_removed': 5, 'total_symbols': 2500}
        sync_data2 = {'sync_date': '2026-04-02', 'symbols_added': 3, 'symbols_removed': 2, 'total_symbols': 2501}

        test_db.save_universe_sync(sync_data1)
        test_db.save_universe_sync(sync_data2)

        with test_db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM universe_sync")
            count = cursor.fetchone()[0]
            assert count == 2


class TestWorkflowStatus:
    """Tests for workflow_status table."""

    def test_save_workflow_status(self, test_db):
        """Test saving workflow execution status."""
        status_data = {
            'run_date': '2026-04-01',
            'start_time': '2026-04-01T09:00:00',
            'end_time': '2026-04-01T09:30:00',
            'status': 'completed',
            'phase0_duration': 60,
            'phase1_duration': 300,
            'phase2_duration': 600,
            'phase3_duration': 120,
            'phase4_duration': 180,
            'phase5_duration': 60,
            'total_duration': 1320,
            'symbols_count': 2500,
            'candidates_count': 50,
            'report_path': '/reports/2026-04-01.html',
            'error_message': None
        }
        test_db.save_workflow_status(status_data)

        # Verify data was saved
        result = test_db.get_workflow_status('2026-04-01')
        assert result is not None
        assert result['run_date'] == '2026-04-01'
        assert result['status'] == 'completed'
        assert result['symbols_count'] == 2500
        assert result['candidates_count'] == 50
        assert result['phase1_duration'] == 300

    def test_get_workflow_status_not_found(self, test_db):
        """Test retrieving non-existent workflow status returns None."""
        result = test_db.get_workflow_status('2026-01-01')
        assert result is None

    def test_save_workflow_status_update(self, test_db):
        """Test updating existing workflow status."""
        status_data1 = {
            'run_date': '2026-04-01',
            'start_time': '2026-04-01T09:00:00',
            'status': 'running'
        }
        status_data2 = {
            'run_date': '2026-04-01',
            'start_time': '2026-04-01T09:00:00',
            'end_time': '2026-04-01T09:45:00',
            'status': 'completed',
            'total_duration': 2700
        }

        test_db.save_workflow_status(status_data1)
        test_db.save_workflow_status(status_data2)

        result = test_db.get_workflow_status('2026-04-01')
        assert result['status'] == 'completed'
        assert result['total_duration'] == 2700

    def test_save_workflow_status_failed(self, test_db):
        """Test saving failed workflow status with error message."""
        status_data = {
            'run_date': '2026-04-01',
            'start_time': '2026-04-01T09:00:00',
            'end_time': '2026-04-01T09:05:00',
            'status': 'failed',
            'error_message': 'Network timeout during data fetch'
        }
        test_db.save_workflow_status(status_data)

        result = test_db.get_workflow_status('2026-04-01')
        assert result['status'] == 'failed'
        assert result['error_message'] == 'Network timeout during data fetch'


class TestSchemaIntegrity:
    """Tests for database schema integrity."""

    def test_all_tables_exist(self, test_db):
        """Verify all expected tables exist."""
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            'stocks',
            'market_data',
            'scan_results',
            'system_status',
            'stock_info',
            'universe_sync',
            'tier1_cache',
            'tier3_cache',
            'workflow_status'
        }
        assert expected_tables <= tables
