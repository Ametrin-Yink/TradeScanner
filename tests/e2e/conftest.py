# tests/e2e/conftest.py
import pytest
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import sqlite3
from flask import Flask
from data.db import Database
from api.server import app as create_app


@pytest.fixture
def in_memory_db(monkeypatch):
    """Provide a Database that uses a singleton :memory: SQLite connection."""
    db = Database()
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    monkeypatch.setattr(db, 'get_connection', lambda: conn)
    return db


@pytest.fixture
def seeded_db(in_memory_db):
    """Database with minimal fixture data: 5 stocks, 3 tags, sample OHLC."""
    conn = in_memory_db.get_connection()

    # Create tables (minimal set needed for tests)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY, name TEXT, market_cap REAL,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
            type TEXT DEFAULT 'sector', etf TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_tags (
            symbol TEXT, tag_id INTEGER,
            PRIMARY KEY (symbol, tag_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tier1_cache (
            symbol TEXT, current_price REAL, high_60d REAL, low_60d REAL,
            atr_pct REAL, rs_percentile REAL, ema21 REAL, ema50 REAL,
            volume_ratio REAL, supports TEXT, resistances TEXT, ret_5d REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etf_cache (
            symbol TEXT, current_price REAL, ret_5d REAL, ret_3m REAL,
            rs_percentile REAL, above_ema50 BOOLEAN, vix_current REAL,
            vix_status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime TEXT, allocation TEXT, ai_regime TEXT,
            ai_confidence INTEGER, ai_reasoning TEXT, cache_date TEXT
        )
    """)

    # Seed stocks
    for sym, name, cap in [
        ('AAPL', 'Apple Inc.', 3_000_000_000_000),
        ('NVDA', 'NVIDIA Corp.', 2_500_000_000_000),
        ('MSFT', 'Microsoft Corp.', 2_800_000_000_000),
        ('TSLA', 'Tesla Inc.', 600_000_000_000),
        ('PLTR', 'Palantir Technologies', 80_000_000_000),
    ]:
        conn.execute(
            "INSERT INTO stocks (symbol, name, market_cap, is_active) VALUES (?, ?, ?, 1)",
            (sym, name, cap)
        )

    # Seed tags
    conn.execute("INSERT INTO tags (name, type, etf) VALUES ('Semiconductors', 'sector', 'SMH')")
    conn.execute("INSERT INTO tags (name, type, etf) VALUES ('AI_Infra', 'theme', '')")
    conn.execute("INSERT INTO tags (name, type, etf) VALUES ('Software', 'sector', 'IGV')")

    # Seed stock_tags
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('NVDA', 1)")
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('NVDA', 2)")
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('AAPL', 3)")
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('MSFT', 3)")
    conn.execute("INSERT INTO stock_tags (symbol, tag_id) VALUES ('PLTR', 3)")

    # Seed tier1_cache
    import json
    for sym, price, high60, low60, atr_pct, rs, sup, res in [
        ('AAPL', 195.0, 200.0, 170.0, 0.025, 72.0, '[170.5, 165.0]', '[198.0, 200.0]'),
        ('NVDA', 950.0, 980.0, 750.0, 0.035, 95.0, '[755.0, 740.0]', '[975.0, 985.0]'),
        ('MSFT', 420.0, 435.0, 380.0, 0.020, 82.0, '[382.0, 378.0]', '[432.0, 438.0]'),
        ('TSLA', 245.0, 280.0, 210.0, 0.045, 45.0, '[212.0]', '[275.0]'),
        ('PLTR', 28.0, 32.0, 22.0, 0.040, 88.0, '[22.5, 21.8]', '[31.5, 33.0]'),
    ]:
        conn.execute("""
            INSERT INTO tier1_cache
            (symbol, current_price, high_60d, low_60d, atr_pct, rs_percentile,
             ema21, ema50, volume_ratio, supports, resistances, ret_5d)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?)
        """, (sym, price, high60, low60, atr_pct, rs, price * 0.95, price * 0.90, sup, res, 1.5))

    # Seed etf_cache (SPY)
    conn.execute("""
        INSERT INTO etf_cache
        (symbol, current_price, ret_5d, ret_3m, rs_percentile, above_ema50, vix_current, vix_status)
        VALUES ('SPY', 525.0, 1.2, 8.5, 65.0, 1, 14.5, 'low')
    """)

    # Seed regime_cache
    conn.execute("""
        INSERT INTO regime_cache (regime, allocation, ai_regime, ai_confidence, ai_reasoning, cache_date)
        VALUES ('bull_moderate', '{}', 'bull_moderate', 70, 'Market in steady uptrend with low volatility.', '2026-06-19')
    """)

    # Create simulation_positions table (needed by _apply_feedback in pipeline)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulation_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opened_date TEXT, symbol TEXT, tag TEXT, reason TEXT,
            entry_price REAL, stop_price REAL, target_price REAL,
            rr_ratio REAL, position_size_shares INTEGER, risk_dollars REAL,
            time_horizon_days INTEGER, close_date TEXT, close_price REAL,
            outcome TEXT DEFAULT 'open', pnl_dollars REAL, pnl_r REAL,
            report_date TEXT
        )
    """)

    conn.commit()
    return in_memory_db


@pytest.fixture
def mock_ai(monkeypatch):
    """Patch core.ai_client.chat to return deterministic responses."""
    def _mock_chat(messages=None, system=None, enable_search=False,
                   search_query=None, temperature=0.3):
        if 'macro' in (system or '').lower() or 'US stock market' in str(messages):
            import json
            return json.dumps({
                'drivers': ['Strong earnings season boosting sentiment.'],
                'risks': ['Inflation remains sticky at 3.5%.'],
            })
        if 'sector' in (system or '').lower() or 'outlook' in (system or '').lower():
            import json
            return json.dumps({
                'outlook': 'Positive outlook driven by AI infrastructure spending.',
                'drivers': [
                    {'text': 'AI data center expansion driving demand.', 'catalyst_date': None}
                ],
                'risks': [
                    {'text': 'Supply chain constraints could limit growth.', 'catalyst_date': 'Q3 2026'}
                ],
            })
        if 'strategist' in (system or '').lower() or 'focus' in (system or '').lower():
            import json
            return json.dumps({
                'reasoning': 'Focus on top-ranked sectors showing relative strength.'
            })
        return '{}'

    monkeypatch.setattr('core.ai_client.chat', _mock_chat)
    monkeypatch.setattr('core.sector_analyzer.chat', _mock_chat)


@pytest.fixture
def app(seeded_db, mock_ai, monkeypatch):
    """Flask test client with seeded DB and auth disabled."""
    monkeypatch.setenv('API_KEY', '')
    create_app.config['TESTING'] = True
    import api.server
    api.server.db = seeded_db
    api.server.API_KEY = ''
    return create_app


@pytest.fixture
def client(app):
    return app.test_client()
