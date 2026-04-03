"""SQLite database operations."""
import sqlite3
import json
import pickle
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

import pandas as pd

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "market_data.db"

class Database:
    """Database manager for trade scanner."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            self._migrate_db(conn)

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
            'spy_regime': 'TEXT'
        }

        for column, dtype in new_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE tier1_cache ADD COLUMN {column} {dtype}")
                logger.info(f"Added column {column} to tier1_cache")

        conn.commit()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

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
            'gap_direction', 'spy_regime'
        ]

        values = []
        for col in columns:
            if col == 'symbol':
                values.append(symbol)
            else:
                values.append(data.get(col, None))

        with self.get_connection() as conn:
            placeholders = ', '.join(['?' for _ in columns])
            update_clause = ', '.join([f"{col}=excluded.{col}" for col in columns if col != 'symbol'])

            conn.execute(f"""
                INSERT INTO tier1_cache ({', '.join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(symbol) DO UPDATE SET
                    {update_clause}
            """, values)

    def get_tier1_cache(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve Tier 1 cache metrics for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary of metrics or None if not found
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tier1_cache WHERE symbol = ?",
                (symbol,)
            )
            row = cursor.fetchone()

            if row is None:
                return None

            return dict(row)

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
        """Get active stocks with market cap >= minimum.

        Args:
            min_market_cap: Minimum market cap in USD (default $2B)

        Returns:
            List of stock symbols meeting criteria
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT symbol FROM stocks
                WHERE category = 'stocks'
                AND is_active = 1
                AND (market_cap >= ? OR market_cap IS NULL)""",
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


SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    category TEXT DEFAULT 'stocks',  -- 'stocks' or 'market_index_etf'
    market_cap REAL,  -- Market cap in USD
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
    data_days INTEGER
);

-- Tier 3 cache (market data)
CREATE TABLE IF NOT EXISTS tier3_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    market_data BLOB
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
"""

db = Database()
