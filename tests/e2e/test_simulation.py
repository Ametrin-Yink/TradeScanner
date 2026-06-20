from core.simulation_engine import SimulationEngine
from core.sector_analyzer import StockHighlight


def test_auto_select_top_5(seeded_db):
    highlights = [
        StockHighlight('A', 'A Corp', 100, 1e9, 'Breakout', '', 100, 90, 130, 3.0),
        StockHighlight('B', 'B Corp', 50, 2e9, 'Strong Momentum', '', 50, 45, 65, 3.0),
        StockHighlight('C', 'C Corp', 200, 5e9, 'Breakout', '', 200, 180, 260, 3.0),
        StockHighlight('D', 'D Corp', 30, 1e9, 'Near Support', '', 30, 27, 39, 3.0),
        StockHighlight('E', 'E Corp', 75, 3e9, 'Good R/R', '', 75, 68, 100, 3.7),
        StockHighlight('F', 'F Corp', 150, 4e9, 'Breakout', '', 150, 135, 195, 3.0),
    ]
    for h in highlights:
        h.primary_tag = 'Test'
        h.position_size = 100
        h.risk_dollars = 500
        h.time_horizon = 'Swing (5-20d)'

    engine = SimulationEngine(seeded_db)
    conn = seeded_db.get_connection()
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

    selected = engine.auto_select(highlights, '2026-06-19')
    assert len(selected) == 5
    assert selected[0].symbol == 'E'
    symbols = {s.symbol for s in selected}
    assert len(symbols) == 5


def test_daily_check_closes_expired(seeded_db):
    engine = SimulationEngine(seeded_db)
    conn = seeded_db.get_connection()
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
    from datetime import datetime, timedelta
    old_date = (datetime.now() - timedelta(days=50)).strftime('%Y-%m-%d')
    conn.execute("""
        INSERT INTO simulation_positions
        (opened_date, symbol, tag, reason, entry_price, stop_price,
         target_price, rr_ratio, position_size_shares, risk_dollars,
         time_horizon_days, report_date)
        VALUES (?, 'TEST', 'Test', 'Breakout', 100, 90, 130,
                3.0, 100, 1000, 20, ?)
    """, (old_date, old_date))
    conn.commit()

    engine.daily_check()
    pos = conn.execute(
        "SELECT outcome FROM simulation_positions WHERE symbol = 'TEST'"
    ).fetchone()
    assert pos['outcome'] in ('expired', 'open')
