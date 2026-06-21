"""Tests for Prior Picks Recap section in daily reports."""
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from core.reporter import ReportGenerator
from core.sector_analyzer import MarketOverview, SectorAnalysis, StockHighlight
from data.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_prior_picks.db"
    return Database(db_path)


def make_recommendation(test_db, trade_date, symbol, sector="Technology",
                        setup_type="Breakout", entry=100.0, stop=95.0,
                        target=115.0, rr=3.0, status='active',
                        pnl_pct=None):
    """Helper to save a recommendation and optionally resolve it."""
    rec = {
        'trade_date': trade_date,
        'symbol': symbol,
        'sector': sector,
        'setup_type': setup_type,
        'entry_price': entry,
        'stop_price': stop,
        'target_price': target,
        'rr': rr,
        'composite_score': 80.0,
        'position_size': 100,
        'position_cost': entry * 100,
        'risk_dollars': (entry - stop) * 100,
        'current_price': entry,
        'entry_distance_pct': 0.0,
        'max_days': 20,
    }
    test_db.save_recommendation(rec)
    if status != 'active':
        active = test_db.get_active_recommendations()
        rec_id = active[-1]['id']
        test_db.resolve_recommendation(rec_id, status, status, pnl_pct, 5)


def build_minimal_report(tmp_path, test_db):
    """Build a minimal analysis result and generate a report."""
    market = MarketOverview(
        date='2026-06-21', regime='bull_moderate', confidence=70,
        reasoning='Market is steady.', spy_price=525.0, spy_change_5d=1.2,
        vix=14.5, vix_status='low',
    )
    sectors = [
        SectorAnalysis(
            name='Technology', etf='XLK', stock_count=1,
            daily_change=1.5, ret_3m=12.0, rs_percentile=80.0,
            trend='uptrend', above_ema50=True,
            outlook='Tech sector strong.',
            highlights=[
                StockHighlight('AAPL', 'Apple Inc', 200, 3.0e12, 'Breakout',
                               'Broke resistance', 200, 195, 215, 2.5),
            ],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-21T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path, db=test_db)
    return gen.generate_report(result)


def test_prior_picks_recap_section_present_when_data_exists(tmp_path, test_db):
    """Recap section should appear when recommendations exist."""
    # Insert some recommendations from last 7 days
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    make_recommendation(test_db, yesterday, 'AAPL', setup_type='Breakout',
                        entry=195.0, stop=190.0, target=210.0, rr=3.0,
                        status='target_hit', pnl_pct=7.69)
    make_recommendation(test_db, yesterday, 'NVDA', setup_type='Near Support',
                        entry=950.0, stop=920.0, target=1020.0, rr=2.33,
                        status='stopped_out', pnl_pct=-3.16)

    report_path = build_minimal_report(tmp_path, test_db)
    content = open(report_path).read()

    assert 'Prior Picks Recap' in content
    assert 'AAPL' in content
    assert 'NVDA' in content
    assert 'Hit' in content
    assert 'Stopped' in content
    assert '+7.7%' in content or '+7.7' in content
    assert '-3.2%' in content or '-3.2' in content


def test_prior_picks_recap_omitted_when_no_data(tmp_path, test_db):
    """Recap section should NOT appear when there are no recommendations."""
    report_path = build_minimal_report(tmp_path, test_db)
    content = open(report_path).read()
    assert 'Prior Picks Recap' not in content


def test_prior_picks_recap_shows_max_30_records(tmp_path, test_db):
    """Recap should show at most 30 recommendations."""
    today = datetime.now().strftime('%Y-%m-%d')
    for i in range(40):
        make_recommendation(test_db, today, f'TEST{i}', setup_type='Breakout',
                            entry=100.0, stop=95.0, target=115.0)

    report_path = build_minimal_report(tmp_path, test_db)
    content = open(report_path).read()
    # Count rows (rough check: count <tr> inside Prior Picks section)
    # There should be at most 30 rows
    td_count = content.count('<td class="sym">')
    assert td_count <= 30


def test_prior_picks_recap_uses_db_from_constructor(tmp_path, test_db):
    """ReportGenerator should use the db passed to constructor."""
    gen = ReportGenerator(reports_dir=tmp_path, db=test_db)
    assert gen.db is test_db
