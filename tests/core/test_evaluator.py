import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import datetime, timedelta
from tests.e2e.conftest import in_memory_db, seeded_db
from core.evaluator import evaluate_recommendations


def seed_resolved_trades(conn, trades):
    for t in trades:
        conn.execute("""
            INSERT INTO recommendations
            (trade_date, symbol, sector, setup_type, entry_price, stop_price,
             target_price, rr, status, outcome, pnl_pct, resolved_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'target_hit' , ?, ?, ?)
        """, (
            t.get('trade_date', (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')),
            t.get('symbol', 'TEST'),
            t.get('sector', 'Tech'),
            t.get('setup_type', 'Breakout'),
            t.get('entry_price', 100.0),
            t.get('stop_price', 95.0),
            t.get('target_price', 110.0),
            t.get('rr', 2.0),
            t.get('outcome', 'win'),
            t.get('pnl_pct', 5.0),
            t.get('resolved_date', (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')),
        ))
    conn.commit()


def test_evaluate_recommendations_empty(seeded_db):
    result = evaluate_recommendations(seeded_db)
    assert result == {}


def test_evaluate_recommendations_one_hit_one_stop(seeded_db):
    conn = seeded_db.get_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    seed_resolved_trades(conn, [
        {'symbol': 'AAPL', 'outcome': 'win', 'pnl_pct': 10.0, 'resolved_date': today},
        {'symbol': 'NVDA', 'outcome': 'loss', 'pnl_pct': -5.0, 'resolved_date': today},
    ])
    result = evaluate_recommendations(seeded_db)
    assert result['total_trades'] == 2
    assert result['win_rate'] == 50.0
    assert result['total_pnl_pct'] == 5.0


def test_evaluate_recommendations_groups_by_setup_type(seeded_db):
    conn = seeded_db.get_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    seed_resolved_trades(conn, [
        {'symbol': 'AAPL', 'setup_type': 'Breakout', 'outcome': 'win', 'pnl_pct': 10.0, 'resolved_date': today},
        {'symbol': 'NVDA', 'setup_type': 'Breakout', 'outcome': 'loss', 'pnl_pct': -5.0, 'resolved_date': today},
        {'symbol': 'MSFT', 'setup_type': 'Swing', 'outcome': 'win', 'pnl_pct': 3.0, 'resolved_date': today},
    ])
    result = evaluate_recommendations(seeded_db)
    assert 'by_setup' in result
    assert 'Breakout' in result['by_setup']
    assert 'Swing' in result['by_setup']
    assert result['by_setup']['Breakout']['total'] == 2
    assert result['by_setup']['Breakout']['win_rate'] == 50.0
    assert result['by_setup']['Swing']['total'] == 1
    assert result['by_setup']['Swing']['win_rate'] == 100.0


def test_evaluate_recommendations_profit_factor(seeded_db):
    conn = seeded_db.get_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    seed_resolved_trades(conn, [
        {'symbol': 'AAPL', 'outcome': 'win', 'pnl_pct': 10.0, 'resolved_date': today},
        {'symbol': 'NVDA', 'outcome': 'win', 'pnl_pct': 5.0, 'resolved_date': today},
        {'symbol': 'MSFT', 'outcome': 'loss', 'pnl_pct': -3.0, 'resolved_date': today},
    ])
    result = evaluate_recommendations(seeded_db)
    assert result['profit_factor'] == 5.0


def test_evaluate_recommendations_division_by_zero(seeded_db):
    conn = seeded_db.get_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    seed_resolved_trades(conn, [
        {'symbol': 'AAPL', 'outcome': 'win', 'pnl_pct': 8.0, 'resolved_date': today},
    ])
    result = evaluate_recommendations(seeded_db)
    assert result['profit_factor'] is None


def test_evaluate_recommendations_lookback_window(seeded_db):
    conn = seeded_db.get_connection()
    seed_resolved_trades(conn, [
        {'symbol': 'AAPL', 'outcome': 'win', 'pnl_pct': 5.0,
         'resolved_date': (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')},
        {'symbol': 'NVDA', 'outcome': 'loss', 'pnl_pct': -5.0,
         'resolved_date': (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')},
    ])
    result = evaluate_recommendations(seeded_db, lookback_days=30)
    assert result['total_trades'] == 1
    assert result['win_rate'] == 100.0
