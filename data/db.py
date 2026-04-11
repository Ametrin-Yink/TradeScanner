"""SQLite database operations."""
import atexit
import sqlite3
import json
import pickle
import logging
import threading
import weakref
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

import pandas as pd

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

# Track all Database instances for cleanup at exit
_instances: weakref.WeakSet = weakref.WeakSet()

def _close_all_instances():
    for inst in list(_instances):
        inst.close()

atexit.register(_close_all_instances)

DB_PATH = DATA_DIR / "market_data.db"

class Database:
    """Database manager for trade scanner."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        _instances.add(self)

    def close(self):
        """Close the thread-local database connection."""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def __del__(self):
        """Ensure connection is closed on garbage collection."""
        self.close()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA)
            self._migrate_db(conn)
            conn.commit()
        finally:
            conn.close()
        self._add_performance_indexes()

    def _add_performance_indexes(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_symbol ON market_data(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tier1_cache_date ON tier1_cache(cache_date)")
            conn.commit()
        finally:
            conn.close()

    def _migrate_db(self, conn: sqlite3.Connection):
        """Migrate database schema if needed."""
        # Check if stocks table has category column
        cursor = conn.execute("PRAGMA table_info(stocks)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'category' not in columns:
            logger.info("Migrating stocks table: adding category column")
            conn.execute("ALTER TABLE stocks ADD COLUMN category TEXT DEFAULT 'stocks'")

        if 'market_cap' not in columns:
            logger.info("Migrating stocks table: adding market_cap column")
            conn.execute("ALTER TABLE stocks ADD COLUMN market_cap REAL")

        # Add earnings date columns
        if 'next_earnings_date' not in columns:
            logger.info("Migrating stocks table: adding next_earnings_date column")
            conn.execute("ALTER TABLE stocks ADD COLUMN next_earnings_date TEXT")

        if 'earnings_fetched_at' not in columns:
            logger.info("Migrating stocks table: adding earnings_fetched_at column")
            conn.execute("ALTER TABLE stocks ADD COLUMN earnings_fetched_at TEXT")

        if 'shares_outstanding' not in columns:
            logger.info("Migrating stocks table: adding shares_outstanding column")
            conn.execute("ALTER TABLE stocks ADD COLUMN shares_outstanding REAL")

        if 'shares_outstanding_date' not in columns:
            logger.info("Migrating stocks table: adding shares_outstanding_date column")
            conn.execute("ALTER TABLE stocks ADD COLUMN shares_outstanding_date TEXT")

        # Migrate tier1_cache table for v5.0/v7.0 columns
        self._migrate_tier1_cache(conn)

        # Create regime_cache table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regime_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                regime TEXT NOT NULL,
                allocation TEXT NOT NULL,
                ai_regime TEXT,
                ai_confidence INTEGER,
                ai_reasoning TEXT,
                cache_date TEXT
            )
        """)

    def _migrate_tier1_cache(self, conn: sqlite3.Connection):
        """Add v5.0/v7.0/v7.1 columns to tier1_cache table."""
        cursor = conn.cursor()

        # Check if columns exist
        cursor.execute("PRAGMA table_info(tier1_cache)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = {
            # v5.0 universal metrics
            'accum_ratio_15d': 'REAL',
            'days_to_earnings': 'INTEGER',
            'earnings_date': 'TEXT',
            'gap_1d_pct': 'REAL',
            'gap_direction': 'TEXT',
            'spy_regime': 'TEXT',
            # v7.0 Strategy G eligibility pre-calculation
            'g_max_days': 'INTEGER',
            'days_post_earnings': 'INTEGER',
            'g_eligible': 'INTEGER',
            # v7.0 Strategy G earnings data
            'earnings_beat': 'BOOLEAN',
            'guidance_change': 'BOOLEAN',
            'one_time_event': 'BOOLEAN',
            # v7.0 Task 12a: VCP pre-calculation
            'vcp_detected': 'BOOLEAN',
            'vcp_tightness': 'REAL',
            'vcp_volume_ratio': 'REAL',
            # v7.1: Support/Resistance (Strategies C, D)
            'supports': 'TEXT',  # JSON array of top 5 support levels
            'resistances': 'TEXT',  # JSON array of top 5 resistance levels
            'nearest_support_distance_pct': 'REAL',
            'nearest_resistance_distance_pct': 'REAL',
            # v7.1: Consecutive down-days (Strategy F)
            'consecutive_down_days': 'INTEGER',
            # v7.1: RS consecutive days ≥80th percentile (Strategy H)
            'rs_consecutive_days_80': 'INTEGER',
            # v7.1: EMA21 slope normalized (Strategy B)
            'ema21_slope_norm': 'REAL',
            # v7.1: Pullback from high (Strategy B)
            'pullback_from_high_pct': 'REAL',
            # v7.1: Distance to EMA8 (Strategy B)
            'distance_to_ema8_pct': 'REAL',
            # v7.1: Sector info (multiple strategies)
            'sector': 'TEXT',
            'sector_etf_symbol': 'TEXT',
            # v7.1: Earnings surprise for Strategy G
            'earnings_surprise_pct': 'REAL',
        }

        for column, dtype in new_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE tier1_cache ADD COLUMN {column} {dtype}")
                logger.info(f"Added column {column} to tier1_cache")

        conn.commit()

    def migrate_tier1_cache_v5(self):
        """Add v5.0 columns to tier1_cache table."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if columns exist
        cursor.execute("PRAGMA table_info(tier1_cache)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = {
            'accum_ratio_15d': 'REAL',
            'days_to_earnings': 'INTEGER',
            'earnings_date': 'TEXT',
            'gap_1d_pct': 'REAL',
            'gap_direction': 'TEXT',
            'spy_regime': 'TEXT',
            # v7.0 Strategy G eligibility pre-calculation
            'g_max_days': 'INTEGER',
            'days_post_earnings': 'INTEGER',
            'g_eligible': 'INTEGER',
            # v7.0 Task 12a: VCP pre-calculation
            'vcp_detected': 'BOOLEAN',
            'vcp_tightness': 'REAL',
            'vcp_volume_ratio': 'REAL'
        }

        for column, dtype in new_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE tier1_cache ADD COLUMN {column} {dtype}")
                logger.info(f"Added column {column} to tier1_cache")

        conn.commit()

    def get_connection(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def add_stock(self, symbol: str, name: str = "", sector: str = ""):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stocks (symbol, name, sector, added_date, is_active) VALUES (?, ?, ?, ?, 1)",
                (symbol, name, sector, datetime.now().date().isoformat())
            )

    def get_active_stocks(self) -> List[str]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT symbol FROM stocks WHERE is_active = 1")
            return [row[0] for row in cursor.fetchall()]

    def save_market_data(self, symbol: str, data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO market_data
                (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (symbol, data['date'], data['open'], data['high'],
                 data['low'], data['close'], data['volume'])
            )

    def save_market_data_batch(self, symbol: str, data_list: list):
        """
        Save multiple market data rows in a single batch operation.

        Args:
            symbol: Stock symbol
            data_list: List of dicts with keys ['date', 'open', 'high', 'low', 'close', 'volume']
        """
        if not data_list:
            return

        with self.get_connection() as conn:
            rows = [
                (symbol, d['date'], d['open'], d['high'], d['low'], d['close'], d['volume'])
                for d in data_list
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO market_data
                (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows
            )

    def save_scan_result(self, result: dict) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO scan_results
                (scan_date, scan_time, market_sentiment, top_opportunities,
                all_candidates, total_stocks, success_count, fail_count, fail_symbols,
                report_path, pushed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result['scan_date'], result['scan_time'], result['market_sentiment'],
                json.dumps(result['top_opportunities']),
                json.dumps(result['all_candidates']),
                result['total_stocks'], result['success_count'], result['fail_count'],
                json.dumps(result.get('fail_symbols', [])),
                result['report_path'], 0)
            )
            return cursor.lastrowid

    # ========== New Methods for data-fetch-rework ==========

    def save_tier1_cache(self, symbol: str, data: Dict[str, Any]):
        """Save Tier 1 cache metrics (universal pre-calculated metrics).

        Args:
            symbol: Stock symbol
            data: Dictionary of metrics (current_price, ema8, rsi_14, etc.)
        """
        # Define all columns and their default values
        columns = [
            'symbol', 'cache_date', 'current_price', 'avg_volume_20d', 'volume_ratio',
            'volume_sma', 'ema8', 'ema21', 'ema50', 'ema200', 'atr', 'atr_pct',
            'adr', 'adr_pct', 'ret_3m', 'ret_6m', 'ret_12m', 'ret_5d',
            'rs_raw', 'rs_percentile', 'distance_from_52w_high', 'high_60d', 'low_60d',
            'gaps_5d', 'rsi_14', 'data_days',
            'accum_ratio_15d', 'days_to_earnings', 'earnings_date', 'gap_1d_pct',
            'gap_direction', 'spy_regime',
            # v7.0 Strategy G eligibility
            'g_max_days', 'days_post_earnings', 'g_eligible',
            # v7.0 Strategy G earnings data
            'earnings_beat', 'guidance_change', 'one_time_event',
            # v7.0 Task 12a: VCP pre-calculation
            'vcp_detected', 'vcp_tightness', 'vcp_volume_ratio',
            # v7.1: Support/Resistance
            'supports', 'resistances', 'nearest_support_distance_pct', 'nearest_resistance_distance_pct',
            # v7.1: Consecutive down-days
            'consecutive_down_days',
            # v7.1: RS consecutive days ≥80th percentile
            'rs_consecutive_days_80',
            # v7.1: EMA21 slope normalized
            'ema21_slope_norm',
            # v7.1: Pullback from high
            'pullback_from_high_pct',
            # v7.1: Distance to EMA8
            'distance_to_ema8_pct',
            # v7.1: Sector info
            'sector', 'sector_etf_symbol',
        ]

        values = []
        for col in columns:
            if col == 'symbol':
                values.append(symbol)
            else:
                val = data.get(col, None)
                # Convert lists to JSON for TEXT columns
                if col in ('supports', 'resistances') and isinstance(val, list):
                    import json
                    val = json.dumps(val)
                values.append(val)

        try:
            with self.get_connection() as conn:
                placeholders = ', '.join(['?' for _ in columns])
                update_clause = ', '.join([f"{col}=excluded.{col}" for col in columns if col != 'symbol'])

                conn.execute(f"""
                    INSERT INTO tier1_cache ({', '.join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(symbol) DO UPDATE SET
                        {update_clause}
                """, values)
        except sqlite3.Error as e:
            logger.error(f"Database error saving tier1_cache for {symbol}: {e}")
            raise

    def get_tier1_cache(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve Tier 1 cache metrics for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary of metrics or None if not found
        """
        import json

        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tier1_cache WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()

            if row is None:
                return None

            data = dict(row)
            # Parse JSON TEXT columns back to lists
            for col in ('supports', 'resistances'):
                val = data.get(col)
                if isinstance(val, str):
                    try:
                        data[col] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        data[col] = []
            return data

    def get_all_tier1_cache(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve all Tier 1 cache metrics.

        Returns:
            Dict mapping symbol to metrics
        """
        import json

        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM tier1_cache")

            result = {}
            for row in cursor.fetchall():
                data = dict(row)
                # Parse JSON TEXT columns back to lists
                for col in ('supports', 'resistances'):
                    val = data.get(col)
                    if isinstance(val, str):
                        try:
                            data[col] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            data[col] = []
                result[row['symbol']] = data

            return result

    def save_regime(self, regime: str, allocation: Dict, ai_regime: str = None,
                    ai_confidence: int = None, ai_reasoning: str = None):
        """Save Phase 1 regime result for Phase 2 to load."""
        import json
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO regime_cache (id, regime, allocation, ai_regime,
                                         ai_confidence, ai_reasoning, cache_date)
                VALUES (1, ?, ?, ?, ?, ?, date('now'))
                ON CONFLICT(id) DO UPDATE SET
                    regime=excluded.regime, allocation=excluded.allocation,
                    ai_regime=excluded.ai_regime, ai_confidence=excluded.ai_confidence,
                    ai_reasoning=excluded.ai_reasoning, cache_date=excluded.cache_date
            """, (regime, json.dumps(allocation), ai_regime, ai_confidence, ai_reasoning))

    def load_regime(self) -> Optional[Dict[str, Any]]:
        """Load Phase 1 regime result. Returns None if Phase 1 hasn't run."""
        import json
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM regime_cache WHERE id = 1").fetchone()
            if row is None:
                return None
            return {
                'regime': row[1],
                'allocation': json.loads(row[2]),
                'ai_regime': row[3],
                'ai_confidence': row[4],
                'ai_reasoning': row[5],
                'cache_date': row[6],
            }

    def get_market_data_latest(self, symbols: List[str], limit: int = 20) -> Dict[str, List]:
        """Single query: latest N rows per symbol for all symbols."""
        if not symbols:
            return {}
        placeholders = ','.join(['?' for _ in symbols])
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"""
                SELECT symbol, date, close, volume FROM market_data
                WHERE symbol IN ({placeholders})
                ORDER BY date DESC
            """, symbols)
            results = {}
            for row in cursor.fetchall():
                sym = row['symbol']
                if sym not in results:
                    results[sym] = []
                if len(results[sym]) < limit:
                    results[sym].append({'date': row['date'], 'close': row['close'], 'volume': row['volume']})
            return results

    def get_stock_info_batch(self, symbols: List[str]) -> Dict[str, Dict]:
        """Batch stock info lookup in single query."""
        if not symbols:
            return {}
        placeholders = ','.join(['?' for _ in symbols])
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"SELECT * FROM stocks WHERE symbol IN ({placeholders})",
                symbols
            )
            return {row['symbol']: dict(row) for row in cursor.fetchall()}

    def save_tier3_cache(self, symbol: str, df: pd.DataFrame):
        """Save market data as pickled blob (Tier 3 cache).

        Args:
            symbol: Stock symbol (e.g., SPY, VIX)
            df: DataFrame with market data
        """
        cache_date = datetime.now().date().isoformat()
        blob = pickle.dumps(df)

        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tier3_cache
                (symbol, cache_date, market_data)
                VALUES (?, ?, ?)""",
                (symbol, cache_date, blob)
            )

    def get_tier3_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        """Retrieve market data from Tier 3 cache.

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT market_data FROM tier3_cache WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()

            if row is None or row[0] is None:
                return None

            return pickle.loads(row[0])

    def get_market_data_df(self, symbol: str) -> Optional[pd.DataFrame]:
        """Retrieve market data for a symbol from market_data table.

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame with OHLCV data or None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT date, open, high, low, close, volume FROM market_data WHERE symbol = ? ORDER BY date",
                    (symbol,)
                )
                rows = cursor.fetchall()

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df

        except Exception as e:
            logger.debug(f"Failed to get market data for {symbol}: {e}")
            return None

    def save_etf_cache(self, symbol: str, etf_data: Dict[str, Any]):
        """Save pre-calculated ETF data.

        Args:
            symbol: ETF symbol (e.g., SPY, XLK, VIX)
            etf_data: Dictionary with pre-calculated metrics
        """
        cache_date = datetime.now().date().isoformat()

        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO etf_cache
                (symbol, cache_date, current_price, ema50, ema200, atr, rsi_14,
                 ret_5d, ret_3m, ret_6m, ret_12m, rs_percentile, above_ema50,
                 volume_ratio, sector_name, price_vs_ema50_pct,
                 vix_current, vix_5d_slope, vix_status,
                 spy_regime, spy_price_vs_ema50_pct, qqq_price_vs_ema50_pct, market_trend)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, cache_date,
                 etf_data.get('current_price'),
                 etf_data.get('ema50'),
                 etf_data.get('ema200'),
                 etf_data.get('atr'),
                 etf_data.get('rsi_14'),
                 etf_data.get('ret_5d'),
                 etf_data.get('ret_3m'),
                 etf_data.get('ret_6m'),
                 etf_data.get('ret_12m'),
                 etf_data.get('rs_percentile'),
                 etf_data.get('above_ema50'),
                 etf_data.get('volume_ratio'),
                 etf_data.get('sector_name'),
                 etf_data.get('price_vs_ema50_pct'),
                 etf_data.get('vix_current'),
                 etf_data.get('vix_5d_slope'),
                 etf_data.get('vix_status'),
                 etf_data.get('spy_regime'),
                 etf_data.get('spy_price_vs_ema50_pct'),
                 etf_data.get('qqq_price_vs_ema50_pct'),
                 etf_data.get('market_trend'))
            )

    def get_etf_cache(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve pre-calculated ETF data.

        Args:
            symbol: ETF symbol

        Returns:
            Dict with ETF metrics or None if not found
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM etf_cache WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def get_all_etf_cache(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve all pre-calculated ETF data.

        Returns:
            Dict mapping symbol to ETF metrics
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM etf_cache")

            result = {}
            for row in cursor.fetchall():
                result[row['symbol']] = dict(row)

            return result

    def save_universe_sync(self, sync_data: Dict[str, Any]):
        """Record universe sync history.

        Args:
            sync_data: Dictionary with keys:
                - sync_date (str)
                - symbols_added (int)
                - symbols_removed (int)
                - total_symbols (int)
        """
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO universe_sync
                (sync_date, symbols_added, symbols_removed, total_symbols)
                VALUES (?, ?, ?, ?)""",
                (
                    sync_data['sync_date'],
                    sync_data.get('symbols_added', 0),
                    sync_data.get('symbols_removed', 0),
                    sync_data.get('total_symbols', 0)
                )
            )

    def save_workflow_status(self, status_data: Dict[str, Any]):
        """Record workflow execution status.

        Args:
            status_data: Dictionary with keys:
                - run_date (str, required)
                - start_time (str, optional)
                - end_time (str, optional)
                - status (str, optional): 'running', 'completed', 'failed'
                - phase0_duration, phase1_duration, etc. (int, optional)
                - total_duration (int, optional)
                - symbols_count (int, optional)
                - candidates_count (int, optional)
                - report_path (str, optional)
                - error_message (str, optional)
        """
        columns = [
            'run_date', 'start_time', 'end_time', 'status',
            'phase0_duration', 'phase1_duration', 'phase2_duration',
            'phase3_duration', 'phase4_duration', 'phase5_duration',
            'total_duration', 'symbols_count', 'candidates_count',
            'report_path', 'error_message'
        ]

        values = [status_data.get(col, None) for col in columns]

        with self.get_connection() as conn:
            placeholders = ', '.join(['?' for _ in columns])
            update_clause = ', '.join([f"{col}=excluded.{col}" for col in columns if col != 'run_date'])

            conn.execute(f"""
                INSERT INTO workflow_status ({', '.join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(run_date) DO UPDATE SET
                    {update_clause}
            """, values)

    def get_workflow_status(self, run_date: str) -> Optional[Dict[str, Any]]:
        """Retrieve workflow status for a specific run date.

        Args:
            run_date: Date string (e.g., '2026-04-01')

        Returns:
            Dictionary of workflow status or None if not found
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM workflow_status WHERE run_date = ?",
                (run_date,)
            )
            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

    def add_stock_with_category(
        self,
        symbol: str,
        name: str = "",
        sector: str = "",
        category: str = "stocks",
        market_cap: Optional[float] = None
    ):
        """Add stock with category and market cap information.

        Args:
            symbol: Stock symbol
            name: Company name
            sector: Industry sector
            category: 'stocks' or 'market_index_etf'
            market_cap: Market cap in USD (optional)
        """
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO stocks
                (symbol, name, sector, category, market_cap, added_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (symbol, name, sector, category, market_cap,
                 datetime.now().date().isoformat())
            )

    def update_stock_market_cap(self, symbol: str, market_cap: float):
        """Update market cap for a stock.

        Args:
            symbol: Stock symbol
            market_cap: Market cap in USD
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE stocks SET market_cap = ? WHERE symbol = ?",
                (market_cap, symbol)
            )

    def update_shares_outstanding(self, symbol: str, shares: float, date_str: str):
        """Update shares outstanding for a stock.

        Args:
            symbol: Stock symbol
            shares: Number of shares outstanding
            date_str: ISO date string when fetched
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE stocks SET shares_outstanding = ?, shares_outstanding_date = ? WHERE symbol = ?",
                (shares, date_str, symbol)
            )

    def update_market_cap_from_shares(self, symbol: str, shares: float, close_price: float):
        """Recompute market_cap = shares_outstanding × close_price.

        Args:
            symbol: Stock symbol
            shares: Number of shares outstanding
            close_price: Latest closing price
        """
        if shares and close_price:
            with self.get_connection() as conn:
                conn.execute(
                    "UPDATE stocks SET market_cap = ? WHERE symbol = ?",
                    (shares * close_price, symbol)
                )

    def get_stock_earnings_date(self, symbol: str) -> Optional[str]:
        """Get cached next earnings date for a stock.

        Args:
            symbol: Stock symbol

        Returns:
            ISO date string (YYYY-MM-DD) or None if not cached
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT next_earnings_date FROM stocks WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
            return None

    def update_stock_earnings_date(self, symbol: str, earnings_date: str):
        """Update next earnings date for a stock.

        Args:
            symbol: Stock symbol
            earnings_date: ISO date string (YYYY-MM-DD)
        """
        today = datetime.now().date().isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """UPDATE stocks SET
                    next_earnings_date = ?,
                    earnings_fetched_at = ?
                WHERE symbol = ?""",
                (earnings_date, today, symbol)
            )

    def update_stock_earnings_surprise(self, symbol: str, surprise_pct: Optional[float]):
        """Store earnings surprise percentage in tier1_cache.

        Args:
            symbol: Stock symbol
            surprise_pct: (actual_eps - estimate_eps) / abs(estimate_eps), or None
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE tier1_cache SET earnings_surprise_pct = ? WHERE symbol = ?",
                (surprise_pct, symbol)
            )

    def get_stock_earnings_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get earnings surprise data for a stock from tier1_cache.

        Args:
            symbol: Stock symbol

        Returns:
            Dict with earnings_beat, guidance_change, one_time_event or None
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT earnings_beat, guidance_change, one_time_event FROM tier1_cache WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'earnings_beat': bool(row['earnings_beat']) if row['earnings_beat'] else False,
                    'guidance_change': bool(row['guidance_change']) if row['guidance_change'] else False,
                    'one_time_event': bool(row['one_time_event']) if row['one_time_event'] else False,
                }
            return None

    def get_stocks_by_category(self, category: str) -> List[str]:
        """Get symbols by category.

        Args:
            category: 'stocks' or 'market_index_etf'

        Returns:
            List of stock symbols
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT symbol FROM stocks WHERE category = ? AND is_active = 1",
                (category,)
            )
            return [row[0] for row in cursor.fetchall()]

    def get_active_stocks_min_market_cap(self, min_market_cap: float = 2e9) -> List[str]:
        """Get active stocks with market cap >= minimum AND Tier 1 cache available.

        Args:
            min_market_cap: Minimum market cap in USD (default $2B)

        Returns:
            List of stock symbols meeting criteria with cached data
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT DISTINCT s.symbol FROM stocks s
                INNER JOIN tier1_cache tc ON tc.symbol = s.symbol
                WHERE s.category = 'stocks'
                AND s.is_active = 1
                AND (s.market_cap >= ? OR s.market_cap IS NULL)""",
                (min_market_cap,)
            )
            return [row[0] for row in cursor.fetchall()]

    def get_stock_info_full(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get full stock info including category and market cap.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary with stock info or None
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM stocks WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def create_ai_confidence_outcomes_table(self):
        """Create table for AI confidence outcome tracking."""
        conn = self.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_confidence_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                ai_confidence INTEGER NOT NULL,
                tier TEXT NOT NULL,
                regime TEXT NOT NULL,
                entry_price REAL,
                outcome_5d_return REAL,
                outcome_10d_return REAL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("Created ai_confidence_outcomes table")

    def save_ai_confidence_outcome(
        self,
        scan_date: str,
        symbol: str,
        strategy: str,
        ai_confidence: int,
        tier: str,
        regime: str,
        entry_price: float
    ):
        """Record AI confidence outcome for later audit."""
        conn = self.get_connection()
        conn.execute("""
            INSERT INTO ai_confidence_outcomes
            (scan_date, symbol, strategy, ai_confidence, tier, regime, entry_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (scan_date, symbol, strategy, ai_confidence, tier, regime, entry_price))
        conn.commit()

    def update_ai_confidence_outcome(
        self,
        id: int,
        outcome_5d: float,
        outcome_10d: float = None
    ):
        """Update outcome returns after 5/10 days."""
        conn = self.get_connection()
        conn.execute("""
            UPDATE ai_confidence_outcomes
            SET outcome_5d_return = ?, outcome_10d_return = ?
            WHERE id = ?
        """, (outcome_5d, outcome_10d, id))
        conn.commit()

    def get_ai_confidence_outcomes(
        self,
        strategy: str = None,
        regime: str = None,
        tier: str = None,
        symbol: str = None,
        scan_date: str = None,
        min_confidence: int = None,
        max_confidence: int = None
    ) -> List[Dict[str, Any]]:
        """Query AI confidence outcomes with optional filters.

        Args:
            strategy: Filter by strategy name
            regime: Filter by market regime
            tier: Filter by tier (S/A/B/C)
            symbol: Filter by symbol
            scan_date: Filter by scan date
            min_confidence: Minimum AI confidence score
            max_confidence: Maximum AI confidence score

        Returns:
            List of outcome records as dictionaries
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row

        # Build dynamic query with filters
        conditions = []
        params = []

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if regime:
            conditions.append("regime = ?")
            params.append(regime)
        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if scan_date:
            conditions.append("scan_date = ?")
            params.append(scan_date)
        if min_confidence is not None:
            conditions.append("ai_confidence >= ?")
            params.append(min_confidence)
        if max_confidence is not None:
            conditions.append("ai_confidence <= ?")
            params.append(max_confidence)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"SELECT * FROM ai_confidence_outcomes {where_clause} ORDER BY recorded_at DESC"

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_all_rs_raw_values(self) -> List[Dict[str, Any]]:
        """Get all rs_raw values from tier1_cache for universe-wide RS percentile calculation.

        Returns:
            List of dicts with 'symbol' and 'rs_raw' keys
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT symbol, rs_raw FROM tier1_cache WHERE rs_raw IS NOT NULL ORDER BY rs_raw DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_rs_percentile(self, symbol: str, rs_percentile: float):
        """Update rs_percentile for a symbol.

        Args:
            symbol: Stock symbol
            rs_percentile: Calculated percentile rank (0-100)
        """
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE tier1_cache SET rs_percentile = ? WHERE symbol = ?",
                (rs_percentile, symbol)
            )

    def bulk_update_rs_percentiles(self, rs_percentiles: Dict[str, float]):
        """Bulk update rs_percentile for multiple symbols.

        Args:
            rs_percentiles: Dict mapping symbol to percentile rank
        """
        with self.get_connection() as conn:
            conn.executemany(
                "UPDATE tier1_cache SET rs_percentile = ? WHERE symbol = ?",
                [(pct, sym) for sym, pct in rs_percentiles.items()]
            )

    def bulk_update_rs_consecutive_days(self, rs_consecutive_days: Dict[str, int]):
        """Bulk update rs_consecutive_days_80 for multiple symbols.

        Args:
            rs_consecutive_days: Dict mapping symbol to consecutive days count
        """
        with self.get_connection() as conn:
            conn.executemany(
                "UPDATE tier1_cache SET rs_consecutive_days_80 = ? WHERE symbol = ?",
                [(days, sym) for sym, days in rs_consecutive_days.items()]
            )


SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    category TEXT DEFAULT 'stocks',  -- 'stocks' or 'market_index_etf'
    market_cap REAL,  -- Market cap in USD
    next_earnings_date TEXT,  -- Next earnings date (ISO format)
    earnings_fetched_at TEXT,  -- When earnings date was fetched
    added_date TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS market_data (
    symbol TEXT,
    date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY,
    scan_date TEXT,
    scan_time TEXT,
    market_sentiment TEXT,
    top_opportunities TEXT,
    all_candidates TEXT,
    total_stocks INTEGER,
    success_count INTEGER,
    fail_count INTEGER,
    fail_symbols TEXT,
    report_path TEXT,
    pushed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_status (
    last_scan_time TEXT,
    last_scan_date TEXT,
    total_scans INTEGER DEFAULT 0,
    avg_scan_duration INTEGER
);

CREATE TABLE IF NOT EXISTS stock_info (
    symbol TEXT PRIMARY KEY,
    sector TEXT,
    industry TEXT,
    updated_date TEXT
);

-- Universe sync history
CREATE TABLE IF NOT EXISTS universe_sync (
    id INTEGER PRIMARY KEY,
    sync_date TEXT,
    symbols_added INTEGER,
    symbols_removed INTEGER,
    total_symbols INTEGER
);

-- Tier 1 cache (universal metrics)
CREATE TABLE IF NOT EXISTS tier1_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    current_price REAL,
    avg_volume_20d REAL,
    volume_ratio REAL,
    volume_sma REAL,
    ema8 REAL, ema21 REAL, ema50 REAL, ema200 REAL,
    atr REAL, atr_pct REAL, adr REAL, adr_pct REAL,
    ret_3m REAL, ret_6m REAL, ret_12m REAL, ret_5d REAL,
    rs_raw REAL, rs_percentile REAL,
    distance_from_52w_high REAL, high_60d REAL, low_60d REAL,
    gaps_5d INTEGER, rsi_14 REAL,
    data_days INTEGER,
    accum_ratio_15d REAL,
    days_to_earnings INTEGER,
    earnings_date TEXT,
    gap_1d_pct REAL,
    gap_direction TEXT,
    spy_regime TEXT,
    g_max_days INTEGER,
    days_post_earnings INTEGER,
    g_eligible INTEGER,
    vcp_detected BOOLEAN,
    vcp_tightness REAL,
    vcp_volume_ratio REAL,
    earnings_surprise_pct REAL
);

-- Tier 3 cache (market data)
CREATE TABLE IF NOT EXISTS tier3_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    market_data BLOB
);

-- ETF cache (pre-calculated market/sector ETF data)
CREATE TABLE IF NOT EXISTS etf_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    current_price REAL,
    ema50 REAL,
    ema200 REAL,
    atr REAL,
    rsi_14 REAL,
    ret_5d REAL,
    ret_3m REAL,
    ret_6m REAL,
    ret_12m REAL,
    rs_percentile REAL,
    above_ema50 BOOLEAN,
    volume_ratio REAL,
    -- Sector ETF specific
    sector_name TEXT,
    price_vs_ema50_pct REAL,
    -- VIX specific
    vix_current REAL,
    vix_5d_slope REAL,
    vix_status TEXT,
    -- SPY/QQQ specific (market regime)
    spy_regime TEXT,
    spy_price_vs_ema50_pct REAL,
    qqq_price_vs_ema50_pct REAL,
    market_trend TEXT
);

-- Workflow status
CREATE TABLE IF NOT EXISTS workflow_status (
    run_date TEXT PRIMARY KEY,
    start_time TEXT,
    end_time TEXT,
    status TEXT,  -- 'running', 'completed', 'failed'
    phase0_duration INTEGER,
    phase1_duration INTEGER,
    phase2_duration INTEGER,
    phase3_duration INTEGER,
    phase4_duration INTEGER,
    phase5_duration INTEGER,
    total_duration INTEGER,
    symbols_count INTEGER,
    candidates_count INTEGER,
    report_path TEXT,
    error_message TEXT
);

-- AI confidence outcome tracking for quarterly audits
CREATE TABLE IF NOT EXISTS ai_confidence_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    ai_confidence INTEGER NOT NULL,
    tier TEXT NOT NULL,
    regime TEXT NOT NULL,
    entry_price REAL,
    outcome_5d_return REAL,
    outcome_10d_return REAL,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

db = Database()
