"""Tests for premarket_prep module."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

from core.premarket_prep import PreMarketPrep, run_premarket_prep


class TestPreMarketPrep:
    """Tests for PreMarketPrep class."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = Mock()
        db.get_active_stocks.return_value = ['AAPL', 'MSFT']
        return db

    @pytest.fixture
    def prep(self, mock_db):
        """Create PreMarketPrep instance with mock DB."""
        return PreMarketPrep(db=mock_db, max_workers=2, batch_size=10)

    def test_init(self, prep):
        """Test initialization."""
        assert prep.max_workers == 2
        assert prep.batch_size == 10
        assert prep.TIER3_SYMBOLS['benchmarks'] == ['SPY', 'QQQ', 'IWM']

    def test_fetch_tier3_data(self, prep):
        """Test fetching Tier 3 market data."""
        # Mock fetcher
        mock_df = pd.DataFrame({
            'open': [100], 'high': [101], 'low': [99], 'close': [100.5], 'volume': [1000000]
        })
        prep.fetcher = Mock()
        prep.fetcher.fetch_stock_data.return_value = mock_df

        result = prep._fetch_tier3_data()

        # Should fetch all Tier 3 symbols
        assert len(result) > 0
        assert prep.fetcher.fetch_stock_data.called

    def test_fetch_tier3_data_empty_response(self, prep):
        """Test handling empty response for Tier 3."""
        prep.fetcher = Mock()
        prep.fetcher.fetch_stock_data.return_value = None

        result = prep._fetch_tier3_data()

        assert result == {}

    def test_calculate_tier1_metrics(self, prep):
        """Test Tier 1 metrics calculation."""
        # Create sample data
        dates = pd.date_range(end='2026-04-01', periods=100, freq='D')
        df = pd.DataFrame({
            'open': np.linspace(100, 150, 100) + np.random.randn(100) * 2,
            'high': np.linspace(102, 152, 100) + np.random.randn(100) * 2,
            'low': np.linspace(98, 148, 100) + np.random.randn(100) * 2,
            'close': np.linspace(100, 150, 100) + np.random.randn(100) * 2,
            'volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)

        result = prep._calculate_tier1_metrics('AAPL', df)

        assert result is not None
        assert 'current_price' in result
        assert 'ema8' in result
        assert 'ema21' in result
        assert 'rsi_14' in result
        assert 'atr' in result

    def test_calculate_tier1_metrics_insufficient_data(self, prep):
        """Test Tier 1 with insufficient data."""
        df = pd.DataFrame({
            'open': [100], 'high': [101], 'low': [99], 'close': [100], 'volume': [1000]
        })

        result = prep._calculate_tier1_metrics('AAPL', df)

        assert result is None

    @patch.object(PreMarketPrep, '_fetch_tier3_data')
    @patch.object(PreMarketPrep, '_update_market_data')
    @patch.object(PreMarketPrep, '_calculate_tier1_cache')
    def test_run_phase0(self, mock_tier1, mock_update, mock_tier3, prep):
        """Test complete Phase 0 run."""
        # Setup mocks
        mock_tier3.return_value = {'SPY': pd.DataFrame()}
        mock_update.return_value = {'total': 100, 'success': 95, 'failed': 5, 'errors': []}
        mock_tier1.return_value = 95

        with patch.object(prep.universe_manager, 'sync_universe', return_value={
            'symbols': ['AAPL', 'MSFT'],
            'symbols_added': 0,
            'total_symbols': 2
        }):
            result = prep.run_phase0()

        assert result['success'] is True
        assert 'symbols' in result
        assert 'tier3_data' in result
        assert 'tier1_cache_count' in result
        assert 'duration' in result

    @patch.object(PreMarketPrep, '_fetch_tier3_data')
    @patch.object(PreMarketPrep, '_update_market_data')
    @patch.object(PreMarketPrep, '_calculate_tier1_cache')
    def test_run_phase0_with_errors(self, mock_tier1, mock_update, mock_tier3, prep):
        """Test Phase 0 with some errors."""
        mock_tier3.return_value = {}
        mock_update.return_value = {
            'total': 100,
            'success': 90,
            'failed': 10,
            'errors': ['SYM1: Error', 'SYM2: Error']
        }
        mock_tier1.return_value = 90

        with patch.object(prep.universe_manager, 'sync_universe', side_effect=Exception("API Error")):
            with patch.object(prep.db, 'get_active_stocks', return_value=['AAPL', 'MSFT']):
                result = prep.run_phase0()

        assert result['success'] is False  # Has errors
        assert len(result['errors']) > 0
        assert 'symbols' in result


class TestRunPremarketPrep:
    """Tests for run_premarket_prep convenience function."""

    @patch('core.premarket_prep.PreMarketPrep')
    def test_run_premarket_prep(self, mock_prep_class):
        """Test convenience function."""
        mock_prep = Mock()
        mock_prep.run_phase0.return_value = {'success': True}
        mock_prep_class.return_value = mock_prep

        result = run_premarket_prep()

        assert result['success'] is True
        mock_prep.run_phase0.assert_called_once()
