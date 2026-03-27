"""Tests for database operations."""
import pytest
from pathlib import Path
from data.db import Database

@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test.db"
    return Database(db_path)

def test_add_stock(test_db):
    test_db.add_stock("AAPL", "Apple Inc", "Technology")
    stocks = test_db.get_active_stocks()
    assert "AAPL" in stocks

def test_get_active_stocks_empty(test_db):
    stocks = test_db.get_active_stocks()
    assert stocks == []

def test_save_market_data(test_db):
    test_db.save_market_data("AAPL", {
        'date': '2025-03-27',
        'open': 170.0,
        'high': 175.0,
        'low': 169.0,
        'close': 173.0,
        'volume': 50000000
    })
    with test_db.get_connection() as conn:
        cursor = conn.execute("SELECT * FROM market_data WHERE symbol = 'AAPL'")
        row = cursor.fetchone()
        assert row is not None
        assert row[2] == 170.0  # open
