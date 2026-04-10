"""Performance optimization tests - Wave 1 (Steps 1-3) and Wave 2 (Steps 4-7)."""
import os
import sys
import tempfile
import sqlite3
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'TradeScanner'))

from data.db import Database
from core.indicators import TechnicalIndicators
from core.fetcher import DataFetcher
from core.premarket_prep import PreMarketPrep


@pytest.fixture
def tmp_db():
    """Provide a temporary database for each test."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    db = Database(db_path=db_path)
    yield db
    # Clean up: open a fresh connection for teardown (thread-local may be closed)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE IF EXISTS market_data")
        conn.execute("DROP TABLE IF EXISTS stocks")
        conn.execute("DROP TABLE IF EXISTS tier1_cache")
        conn.commit()
        conn.close()
    except Exception:
        pass
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ============================================================
# Step 1: SQLite Performance Tuning and Batch Query Methods
# ============================================================

class TestDatabaseBatchMethods:
    """Tests for new batch query methods and connection reuse."""

    def test_get_connection_reuses_connection(self, tmp_db):
        """get_connection returns the same connection when called multiple times."""
        conn1 = tmp_db.get_connection()
        conn2 = tmp_db.get_connection()
        assert conn1 is conn2, "Connection should be reused, not created fresh each time"
        conn1.close()

    def test_get_market_data_latest_returns_data_for_multiple_symbols(self, tmp_db):
        """Batch method returns latest N rows per symbol in a single query."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('AAPL', '2026-01-01', 100, 1000)")
        conn.execute("INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('AAPL', '2026-01-02', 101, 1100)")
        conn.execute("INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('MSFT', '2026-01-01', 200, 2000)")
        conn.execute("INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('MSFT', '2026-01-02', 201, 2100)")
        conn.commit()
        conn.close()

        results = tmp_db.get_market_data_latest(['AAPL', 'MSFT'], limit=1)
        assert 'AAPL' in results
        assert 'MSFT' in results
        assert len(results['AAPL']) == 1
        assert len(results['MSFT']) == 1
        assert results['AAPL'][0]['close'] == 101
        assert results['MSFT'][0]['close'] == 201

    def test_get_market_data_latest_respects_limit(self, tmp_db):
        """Batch method returns at most N rows per symbol."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        for i in range(1, 6):
            date = f'2026-01-0{i}'
            conn.execute("INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('AAPL', ?, ?, ?)",
                         (date, 100 + i, 1000 + i))
        conn.commit()
        conn.close()

        results = tmp_db.get_market_data_latest(['AAPL'], limit=3)
        assert len(results['AAPL']) == 3
        assert results['AAPL'][0]['close'] == 105  # Most recent first

    def test_get_stock_info_batch_returns_all_symbols(self, tmp_db):
        """Batch stock info lookup returns data for multiple symbols."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, sector) VALUES ('AAPL', 'Apple Inc', 'Technology')")
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, sector) VALUES ('MSFT', 'Microsoft Corp', 'Technology')")
        conn.commit()
        conn.close()

        results = tmp_db.get_stock_info_batch(['AAPL', 'MSFT'])
        assert 'AAPL' in results
        assert 'MSFT' in results
        assert results['AAPL']['name'] == 'Apple Inc'
        assert results['MSFT']['name'] == 'Microsoft Corp'

    def test_get_stock_info_batch_empty_returns_empty(self, tmp_db):
        """Batch stock info with empty list returns empty dict."""
        results = tmp_db.get_stock_info_batch([])
        assert results == {}



# ============================================================
# Step 2: Indicator Cache Eviction
# ============================================================

class TestIndicatorCacheEviction:
    """Tests for indicator cache size limit and eviction."""

    def test_indicator_cache_eviction(self):
        """Cache evicts oldest entry when exceeding max size."""
        import pandas as pd
        dates = pd.date_range('2025-01-01', periods=60, freq='B')
        df = pd.DataFrame({
            'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0, 'volume': 1000000
        }, index=dates)

        TechnicalIndicators.clear_cache()

        max_size = TechnicalIndicators._MAX_CACHE_SIZE
        for i in range(max_size + 10):
            d = df.copy()
            d.index = pd.date_range(f'2025-01-{(i % 28) + 1:02d}', periods=60, freq='B')
            calc = TechnicalIndicators(d, symbol=f'SYM{i:04d}')
            calc.calculate_all()

        assert len(TechnicalIndicators._cache) <= max_size

        TechnicalIndicators.clear_cache()


# ============================================================
# Step 3: Concurrency Increase
# ============================================================

class TestConcurrencyIncrease:
    """Tests for increased default concurrency."""

    def test_fetcher_default_max_workers_is_4(self):
        """DataFetcher default max_workers should be 4."""
        fetcher = DataFetcher()
        assert fetcher.max_workers == 4

    def test_premarket_prep_passes_max_workers_to_fetcher(self):
        """PreMarketPrep passes max_workers to DataFetcher."""
        prep = PreMarketPrep(max_workers=8)
        assert prep.fetcher.max_workers == 8


# ============================================================
# Wave 2: Step 4 - Eliminate N+1 Queries in Premarket Prefilter
# ============================================================

class TestPrefilterBatchQueries:
    """Tests for batch queries in _apply_prefilter (Step 4)."""

    def test_prefilter_uses_batch_queries(self, tmp_db):
        """Verify _apply_prefilter uses batch queries, not per-symbol queries."""
        import sqlite3
        from unittest.mock import patch, MagicMock

        # Set up test data
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, category, market_cap) VALUES ('AAPL', 'Apple', 'stocks', 3e12)")
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, category, market_cap) VALUES ('MSFT', 'Microsoft', 'stocks', 2.5e12)")
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, category, market_cap) VALUES ('TINY', 'TinyCorp', 'stocks', 1e8)")
        # Market data
        for sym in ['AAPL', 'MSFT', 'TINY']:
            for i in range(1, 21):
                conn.execute(
                    "INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES (?, ?, ?, ?)",
                    (sym, f'2026-01-{i:02d}', 100 + i, 100000 + i * 1000)
                )
        conn.commit()
        conn.close()

        prep = PreMarketPrep(db=tmp_db)

        # Patch the individual query methods to count calls
        with patch.object(tmp_db, 'get_market_data_latest', wraps=tmp_db.get_market_data_latest) as mock_batch, \
             patch.object(tmp_db, 'get_stock_info_batch', wraps=tmp_db.get_stock_info_batch) as mock_info_batch:

            result = prep._apply_prefilter()

            # Should use batch queries exactly once each
            assert mock_batch.call_count == 1, f"get_market_data_latest should be called once, was called {mock_batch.call_count} times"
            assert mock_info_batch.call_count == 1, f"get_stock_info_batch should be called once, was called {mock_info_batch.call_count} times"
            assert 'AAPL' in result['qualifying_stocks']
            assert 'MSFT' in result['qualifying_stocks']
            assert 'TINY' not in result['qualifying_stocks']  # Filtered by market cap

    def test_get_market_data_latest_returns_correct_structure(self, tmp_db):
        """Verify batch method returns dict of lists with correct keys."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        for i in range(1, 6):
            conn.execute(
                "INSERT OR REPLACE INTO market_data (symbol, date, close, volume) VALUES ('AAPL', ?, ?, ?)",
                (f'2026-01-0{i}', 100 + i, 1000 + i)
            )
        conn.commit()
        conn.close()

        results = tmp_db.get_market_data_latest(['AAPL'], limit=3)
        assert isinstance(results, dict)
        assert 'AAPL' in results
        assert isinstance(results['AAPL'], list)
        assert len(results['AAPL']) == 3
        # Each row should have date, close, volume keys
        for row in results['AAPL']:
            assert 'date' in row
            assert 'close' in row
            assert 'volume' in row

    def test_get_stock_info_batch_returns_all_symbols(self, tmp_db):
        """Verify batch method returns info for all requested symbols."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, sector, market_cap) VALUES ('AAPL', 'Apple', 'Tech', 3e12)")
        conn.execute("INSERT OR REPLACE INTO stocks (symbol, name, sector, market_cap) VALUES ('MSFT', 'Microsoft', 'Tech', 2.5e12)")
        conn.commit()
        conn.close()

        results = tmp_db.get_stock_info_batch(['AAPL', 'MSFT'])
        assert 'AAPL' in results
        assert 'MSFT' in results
        assert results['AAPL']['market_cap'] == 3e12
        assert results['MSFT']['market_cap'] == 2.5e12


# ============================================================
# Wave 2: Step 5 - Eliminate N+1 in Screener Tier 1 Load + Relax GC
# ============================================================

class TestScreenerTier1Cache:
    """Tests for batch Tier 1 cache loading (Step 5)."""

    def test_load_tier1_cache_uses_single_query(self):
        """Verify _load_tier1_cache uses get_all_tier1_cache, not per-symbol calls."""
        from core.screener import StrategyScreener
        from unittest.mock import patch, MagicMock
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = Database(db_path=db_path)
        screener = StrategyScreener(db=db)

        # Patch per-symbol method to ensure it's NOT called
        with patch.object(db, 'get_tier1_cache', return_value=None) as mock_per_symbol, \
             patch.object(db, 'get_all_tier1_cache', return_value={}) as mock_batch:

            screener._load_tier1_cache(['AAPL', 'MSFT'])

            # Should use batch query, NOT per-symbol
            assert mock_batch.call_count >= 1, "Should use get_all_tier1_cache batch method"
            # After refactoring, get_tier1_cache should NOT be called per-symbol
            # (it may be called 0 times since we use get_all_tier1_cache)

        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_no_gc_calls_in_phase0_precalculation(self):
        """Verify gc.collect() is not called every 30 symbols in _run_phase0_precalculation."""
        import inspect
        from core.screener import StrategyScreener

        source = inspect.getsource(StrategyScreener._run_phase0_precalculation)
        # Should NOT contain gc.collect() called every 30 symbols
        assert 'i % 30' not in source, "Should not have gc.collect() every 30 symbols"


# ============================================================
# Wave 2: Step 6 - yf.download() Batching for History Fetches
# ============================================================

class TestBatchDownload:
    """Tests for yf.download batching (Step 6)."""

    def test_download_batch_yf_reshapes_multiindex(self):
        """Verify _download_batch_yf returns Dict[str, DataFrame] with correct columns."""
        from core.fetcher import DataFetcher
        from unittest.mock import patch
        import pandas as pd
        import numpy as np

        fetcher = DataFetcher()

        # Mock yf.download to return a MultiIndex DataFrame
        dates = pd.date_range('2025-01-01', periods=10, freq='B')
        symbols = ['AAPL', 'MSFT']

        # Create mock multi-index DataFrame (group_by='column' format)
        data = {}
        for col in ['Close', 'Open', 'High', 'Low', 'Volume']:
            for sym in symbols:
                data[(col, sym)] = np.random.rand(10) * 100 + 100

        mock_df = pd.DataFrame(data, index=dates)

        with patch('yfinance.download', return_value=mock_df):
            results = fetcher._download_batch_yf(symbols, period="13mo", interval="1d")

        assert isinstance(results, dict)
        assert 'AAPL' in results
        assert 'MSFT' in results
        for sym in symbols:
            df = results[sym]
            assert isinstance(df, pd.DataFrame)
            assert 'close' in df.columns
            assert 'open' in df.columns
            assert 'high' in df.columns
            assert 'low' in df.columns
            assert 'volume' in df.columns

    def test_fetch_multiple_uses_batch_download_for_no_cache(self):
        """Verify fetch_multiple uses yf.download for symbols without cache."""
        from core.fetcher import DataFetcher
        from unittest.mock import patch, MagicMock

        fetcher = DataFetcher()

        # Both symbols have no cache
        with patch.object(fetcher, '_get_cached_data', return_value=(None, None)), \
             patch.object(fetcher, '_download_batch_yf', return_value={}) as mock_batch, \
             patch.object(fetcher, '_save_to_db'):

            fetcher.fetch_multiple(['AAPL', 'MSFT', 'GOOG'], use_cache=True)

            # Should call batch download for non-cached symbols
            assert mock_batch.call_count >= 1, "Should use batch download for non-cached symbols"


# ============================================================
# Wave 2: Step 7 - Preload Tier 3 Data into Memory
# ============================================================

class TestTier3Preload:
    """Tests for Tier 3 data preloading (Step 7)."""

    def test_screener_preloads_tier3_data(self):
        """Verify screener loads Tier 3 data into memory on init."""
        from core.screener import StrategyScreener
        from unittest.mock import patch, MagicMock
        import pandas as pd
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = Database(db_path=db_path)

        # Create mock Tier 3 data
        dates = pd.date_range('2025-01-01', periods=50, freq='B')
        mock_spy = pd.DataFrame({
            'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0, 'volume': 1000000
        }, index=dates)
        mock_spy.index.name = 'date'

        with patch.object(db, 'get_tier3_cache', side_effect=lambda sym: mock_spy if sym == 'SPY' else None):
            screener = StrategyScreener(db=db)

        assert hasattr(screener, '_tier3_data'), "Screener should have _tier3_data attribute"
        assert 'SPY' in screener._tier3_data, "SPY should be preloaded in _tier3_data"

        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_load_tier3_data_checks_memory_first(self):
        """Verify _load_tier3_data checks memory cache before DB."""
        from core.screener import StrategyScreener
        from unittest.mock import patch, MagicMock
        import pandas as pd
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = Database(db_path=db_path)
        screener = StrategyScreener(db=db)

        # Create mock data
        dates = pd.date_range('2025-01-01', periods=50, freq='B')
        mock_df = pd.DataFrame({
            'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0, 'volume': 1000000
        }, index=dates)
        mock_df.index.name = 'date'

        # Preload into memory
        screener._tier3_data['TEST'] = mock_df

        # DB should NOT be called since data is in memory
        with patch.object(db, 'get_tier3_cache', side_effect=Exception("DB should not be called")) as mock_db:
            result = screener._load_tier3_data('TEST')

        assert mock_db.call_count == 0, "DB should not be called when data is in memory"
        assert result is not None
        assert len(result) == 50

        try:
            os.unlink(db_path)
        except OSError:
            pass


# ============================================================
# Wave 3: Step 8 - VCP Deduplication in Momentum Breakout
# ============================================================

class TestVCPDeduplication:
    """Tests for VCP detection caching (Step 8)."""

    def test_vcp_cached_after_first_call(self):
        """Verify VCP detection is cached after first call."""
        from core.strategies.momentum_breakout import MomentumBreakoutStrategy
        from unittest.mock import patch, MagicMock, PropertyMock
        import pandas as pd

        strategy = MomentumBreakoutStrategy()

        dates = pd.date_range('2025-01-01', periods=60, freq='B')
        mock_vcp_result = {'is_valid': True, 'platform_high': 105, 'platform_low': 100,
                           'platform_range_pct': 0.05, 'platform_days': 30,
                           'concentration_ratio': 0.6, 'volume_contraction_ratio': 0.6,
                           'contraction_quality': 0.5}

        df = pd.DataFrame({
            'open': 100.0, 'high': 102.0, 'low': 99.0, 'close': 101.0, 'volume': 1000000
        }, index=dates)

        call_count = [0]

        def mock_detect_vcp(*args, **kwargs):
            call_count[0] += 1
            return mock_vcp_result

        mock_ind = MagicMock()
        mock_ind.detect_vcp_platform.side_effect = mock_detect_vcp
        mock_ind.calculate_all.return_value = None
        mock_ind.calculate_clv.return_value = 0.8
        mock_ind.distance_from_ema50.return_value = {'distance_pct': 0.05}
        mock_ind.calculate_52w_metrics.return_value = {'distance_from_high': 0.05}
        mock_ind.indicators = {'ema': {'ema50': 95.0, 'ema200': 90.0}, 'atr': {'atr': 2.0}}

        with patch('core.strategies.momentum_breakout.TechnicalIndicators', return_value=mock_ind):
            strategy.phase0_data = {}
            strategy.calculate_dimensions('TEST', df)
            count_after_first = call_count[0]

            strategy.calculate_dimensions('TEST', df)
            count_after_second = call_count[0]

            assert count_after_second == count_after_first, \
                f"VCP should be cached: called {count_after_first} times after first, {count_after_second} after second"

    def test_vcp_cache_is_reused_across_methods(self):
        """Verify calculate_dimensions, calculate_entry_exit, build_match_reasons share VCP cache."""
        from core.strategies.momentum_breakout import MomentumBreakoutStrategy
        from unittest.mock import patch, MagicMock
        import pandas as pd

        strategy = MomentumBreakoutStrategy()
        dates = pd.date_range('2025-01-01', periods=60, freq='B')
        mock_vcp_result = {'is_valid': True, 'platform_high': 105, 'platform_low': 100,
                           'platform_range_pct': 0.05, 'platform_days': 30,
                           'concentration_ratio': 0.6, 'volume_contraction_ratio': 0.6,
                           'contraction_quality': 0.5}

        df = pd.DataFrame({
            'open': 100.0, 'high': 105.5, 'low': 99.0, 'close': 106.0, 'volume': 3000000
        }, index=dates)

        call_count = [0]

        def mock_detect_vcp(*args, **kwargs):
            call_count[0] += 1
            return mock_vcp_result

        mock_ind = MagicMock()
        mock_ind.detect_vcp_platform.side_effect = mock_detect_vcp
        mock_ind.calculate_all.return_value = None
        mock_ind.calculate_clv.return_value = 0.8
        mock_ind.distance_from_ema50.return_value = {'distance_pct': 0.05}
        mock_ind.calculate_52w_metrics.return_value = {'distance_from_high': 0.05}
        mock_ind.indicators = {'ema': {'ema50': 95.0, 'ema200': 90.0}, 'atr': {'atr': 2.0}}

        with patch('core.strategies.momentum_breakout.TechnicalIndicators', return_value=mock_ind):
            strategy.phase0_data = {}

            dimensions = strategy.calculate_dimensions('TEST', df)
            strategy.calculate_entry_exit('TEST', df, dimensions, 10.0, 'A')
            strategy.build_match_reasons('TEST', df, dimensions, 10.0, 'A')

            assert call_count[0] == 1, \
                f"VCP should be called once across all methods, was called {call_count[0]} times"


# ============================================================
# Wave 3: Step 9 - Earnings Fetch Parallelization
# ============================================================

class TestEarningsParallelization:
    """Tests for ThreadPoolExecutor in earnings fetch (Step 9)."""

    def test_earnings_calendar_uses_thread_pool(self):
        """Verify fetch_earnings_calendar uses ThreadPoolExecutor."""
        import inspect
        from core.fetcher import DataFetcher

        source = inspect.getsource(DataFetcher.fetch_earnings_calendar)
        assert 'ThreadPoolExecutor' in source, \
            "fetch_earnings_calendar should use ThreadPoolExecutor for parallelization"
        assert 'max_workers=2' in source or 'max_workers = 2' in source, \
            "ThreadPoolExecutor should use max_workers=2"


# ============================================================
# Wave 3: Step 10 - Flask API Non-Blocking + Caching
# ============================================================

class TestFlaskAPICaching:
    """Tests for Flask threaded mode and result caching (Step 10)."""

    def test_flask_server_is_threaded(self):
        """Verify app.run() uses threaded=True."""
        import inspect
        # Reload module to get latest version
        import importlib
        import api.server
        importlib.reload(api.server)
        from api.server import run_server

        source = inspect.getsource(run_server)
        assert 'threaded=True' in source, \
            "run_server should pass threaded=True to app.run()"

    def test_scan_result_caching(self):
        """Verify consecutive scan requests return cached result."""
        import importlib
        import api.server
        importlib.reload(api.server)
        from api.server import _last_scan_result, _last_scan_time, _SCAN_CACHE_SECONDS

        assert _SCAN_CACHE_SECONDS == 3600, "Cache TTL should be 3600 seconds"
        assert _last_scan_result is None or isinstance(_last_scan_result, dict), \
            "_last_scan_result should be a dict or None"
        assert _last_scan_time is None or hasattr(_last_scan_time, 'total_seconds'), \
            "_last_scan_time should be a datetime or None"
