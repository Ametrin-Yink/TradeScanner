"""Tests for stock_universe module."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from core.stock_universe import StockUniverseManager, sync_stock_universe


class TestStockUniverseManager:
    """Tests for StockUniverseManager class."""

    def test_fetch_large_cap_universe(self):
        """Test fetching large cap stocks from Finviz."""
        manager = StockUniverseManager()

        # Mock the Finviz Overview
        mock_overview = Mock()
        mock_df = pd.DataFrame({'Ticker': ['AAPL', 'MSFT', 'GOOGL']})
        mock_overview.screener_view.return_value = mock_df

        with patch('core.stock_universe.Overview', return_value=mock_overview):
            result = manager.fetch_large_cap_universe()

        assert result == ['AAPL', 'MSFT', 'GOOGL']
        mock_overview.set_filter.assert_called_once_with(
            filters_dict={'Market Cap.': '+Mid (over $2bln)'}
        )

    def test_fetch_large_cap_universe_error(self):
        """Test handling error when fetching from Finviz."""
        manager = StockUniverseManager()

        with patch('core.stock_universe.Overview', side_effect=Exception("API Error")):
            result = manager.fetch_large_cap_universe()

        assert result == []

    def test_sync_universe_adds_new_stocks(self):
        """Test sync adds new stocks from Finviz."""
        manager = StockUniverseManager()

        # Mock database
        mock_db = Mock()
        # First call returns existing, second call returns updated
        mock_db.get_active_stocks.side_effect = [
            ['AAPL', 'MSFT'],  # First call - existing
            ['AAPL', 'MSFT', 'GOOGL', 'AMZN']  # Second call - after adds
        ]
        manager.db = mock_db

        # Mock fetch to return new stocks
        with patch.object(manager, 'fetch_large_cap_universe', return_value=['AAPL', 'MSFT', 'GOOGL', 'AMZN']):
            result = manager.sync_universe()

        assert result['symbols_added'] == 2  # GOOGL and AMZN
        assert result['total_symbols'] == 4
        assert 'GOOGL' in result['symbols']
        assert 'AMZN' in result['symbols']

    def test_sync_universe_no_changes(self):
        """Test sync when no changes needed."""
        manager = StockUniverseManager()

        mock_db = Mock()
        mock_db.get_active_stocks.return_value = ['AAPL', 'MSFT']
        manager.db = mock_db

        with patch.object(manager, 'fetch_large_cap_universe', return_value=['AAPL', 'MSFT']):
            result = manager.sync_universe()

        assert result['symbols_added'] == 0
        assert result['total_symbols'] == 2

    def test_sync_universe_finviz_failure(self):
        """Test sync handles Finviz failure."""
        manager = StockUniverseManager()

        with patch.object(manager, 'fetch_large_cap_universe', return_value=[]):
            result = manager.sync_universe()

        assert 'error' in result
        assert result['symbols_added'] == 0

    def test_get_universe_symbols(self):
        """Test getting universe symbols."""
        manager = StockUniverseManager()

        mock_db = Mock()
        mock_db.get_active_stocks.return_value = ['AAPL', 'MSFT', 'GOOGL']
        manager.db = mock_db

        result = manager.get_universe_symbols()

        assert result == ['AAPL', 'MSFT', 'GOOGL']

    def test_get_universe_size(self):
        """Test getting universe size."""
        manager = StockUniverseManager()

        mock_db = Mock()
        mock_db.get_active_stocks.return_value = ['AAPL', 'MSFT', 'GOOGL']
        manager.db = mock_db

        result = manager.get_universe_size()

        assert result == 3


class TestSyncStockUniverse:
    """Tests for sync_stock_universe convenience function."""

    def test_sync_stock_universe_returns_symbols(self):
        """Test convenience function returns symbols list."""
        with patch('core.stock_universe.StockUniverseManager') as mock_manager_class:
            mock_manager = Mock()
            mock_manager.sync_universe.return_value = {
                'symbols': ['AAPL', 'MSFT'],
                'symbols_added': 0
            }
            mock_manager_class.return_value = mock_manager

            result = sync_stock_universe()

            assert result == ['AAPL', 'MSFT']
