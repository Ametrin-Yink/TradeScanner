"""E2E test for simulation feedback weights in SectorAnalyzer."""

from core.sector_analyzer import SectorAnalyzer
from data.db import Database

_MINIMAL_POS_COLS = (
    "opened_date, symbol, tag, reason, entry_price, stop_price, target_price, "
    "rr_ratio, position_size_shares, risk_dollars, time_horizon_days, report_date, outcome, close_price"
)
_MINIMAL_POS_VALS = (
    "'2026-06-01', 'TST', '{tag}', 'test', 100, 99, 110, 2.0, "
    "1, 1.0, 10, '2026-06-01', '{outcome}', {close_price}"
)


def _seed_position(conn, tag, outcome, close_price):
    cols = _MINIMAL_POS_COLS.format(tag=tag)
    vals = _MINIMAL_POS_VALS.format(tag=tag, outcome=outcome, close_price=close_price)
    conn.execute(f"INSERT INTO simulation_positions ({cols}) VALUES ({vals})")


def test_feedback_boosts_winning_tags():
    """Tags with >50% win rate get score boost."""
    db = Database()
    conn = db.get_connection()

    conn.execute("DELETE FROM simulation_positions")

    # Tech: 8 wins / 10 total = 80% win rate
    for _ in range(8):
        _seed_position(conn, 'Technology', 'win', 110)
    for _ in range(2):
        _seed_position(conn, 'Technology', 'loss', 95)

    # Energy: 2 wins / 8 total = 25% win rate
    for _ in range(2):
        _seed_position(conn, 'Energy', 'win', 110)
    for _ in range(6):
        _seed_position(conn, 'Energy', 'loss', 95)

    conn.commit()

    analyzer = SectorAnalyzer(db)

    scored = [(0.50, 'Technology'), (0.45, 'Energy')]
    adjusted = analyzer._apply_feedback(scored)

    tech_score = [s for s in adjusted if s[1] == 'Technology'][0][0]
    energy_score = [s for s in adjusted if s[1] == 'Energy'][0][0]

    assert tech_score > 0.50, f"Expected tech_score > 0.50, got {tech_score}"
    assert energy_score < 0.45, f"Expected energy_score < 0.45, got {energy_score}"

    conn.execute("DELETE FROM simulation_positions")
    conn.commit()
    db.close()
