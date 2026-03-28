"""SQLite database operations."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from config.settings import DATA_DIR

DB_PATH = DATA_DIR / "market_data.db"

class Database:
    """Database manager for trade scanner."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
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
"""

db = Database()
