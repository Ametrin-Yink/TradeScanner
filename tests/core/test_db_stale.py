"""Tests for stale stock detection and data fixes."""
import pytest
from datetime import datetime, timedelta
from data.db import Database


def test_sndk_inactive(tmp_path):
    """SNDK should be marked as inactive after database initialization."""
    db_path = tmp_path / "test.db"

    # Create database and add SNDK as active
    db = Database(db_path)
    db.add_stock("SNDK", "SanDisk Corp", "Technology")
    assert "SNDK" in db.get_active_stocks()

    # Verify SNDK is active before re-init
    info = db.get_stock_info_full("SNDK")
    assert info is not None
    assert info['is_active'] == 1
    db.close()

    # Re-init database -- should trigger SNDK fix
    db2 = Database(db_path)

    # SNDK should now be inactive
    assert "SNDK" not in db2.get_active_stocks()
    info = db2.get_stock_info_full("SNDK")
    assert info is not None
    assert info['is_active'] == 0
    db2.close()


def test_detect_stale_stocks(tmp_path):
    """Stocks with <= 2 unique close prices in last N days should be detected."""
    from data.db import detect_stale_stocks

    db_path = tmp_path / "test.db"
    db = Database(db_path)

    today = datetime.now()

    # Stock A: flat prices (close == 100 every day)
    db.add_stock("FLAT", "Flat Corp", "Technology")
    for i in range(30):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        db.save_market_data("FLAT", {
            'date': date, 'open': 100.0, 'high': 101.0,
            'low': 99.0, 'close': 100.0, 'volume': 1000000,
        })

    # Stock B: normal varying prices
    db.add_stock("NORMAL", "Normal Corp", "Technology")
    for i in range(30):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        db.save_market_data("NORMAL", {
            'date': date, 'open': 100 + i, 'high': 101 + i,
            'low': 99 + i, 'close': 100 + i, 'volume': 1000000,
        })

    stale = detect_stale_stocks(db, days_unchanged=30)
    assert "FLAT" in stale
    assert "NORMAL" not in stale
    assert len(stale) == 1

    db.close()
