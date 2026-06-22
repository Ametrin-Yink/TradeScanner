"""Tests for report UX polish features: horizon badges, keyboard nav, timestamps, expand/collapse."""
from core.reporter import ReportGenerator
from core.sector_analyzer import MarketOverview, SectorAnalysis, StockHighlight, FocusSummary


def test_horizon_badge_colors(tmp_path):
    """Horizon should appear as title attributes on the Setup badge."""
    market = MarketOverview(
        date='2026-06-19', regime='bull_moderate', confidence=70,
        reasoning='Market is steady.', spy_price=525.0, spy_change_5d=1.2,
        vix=14.5, vix_status='low',
    )
    sectors = [
        SectorAnalysis(
            name='Semiconductors', etf='SMH', stock_count=1,
            daily_change=2.5, ret_3m=15.0, rs_percentile=85.0,
            trend='uptrend', above_ema50=True,
            outlook='Strong demand from AI.',
            key_drivers=[{'text': 'AI boom'}], risks=[{'text': 'Supply chain'}],
            highlights=[
                StockHighlight('NVDA', 'NVIDIA', 950, 2.5e12, 'Breakout',
                               'Broke 60d high', 950, 900, 1100, 3.0,
                               time_horizon='Short (3-10d)'),
                StockHighlight('AMD', 'AMD', 150, 1.5e11, 'Near Support',
                               'At support', 148, 142, 160, 2.5,
                               time_horizon='Swing (5-20d)'),
                StockHighlight('INTC', 'Intel', 35, 1e11, 'Near Support',
                               'At support', 34, 32, 38, 3.0,
                               time_horizon='Position (10-40d)'),
            ],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'title="Short (3-10d)' in content
    assert 'title="Swing (5-20d)' in content
    assert 'title="Position (10-40d)' in content


def test_table_has_9_columns(tmp_path):
    """Active Setups table should have exactly 9 columns: Sym, Price, Setup, RS, Entry+Dist, Stop, Target, R:R, Risk$."""
    market = MarketOverview(
        date='2026-06-19', regime='bull_moderate', confidence=70,
        reasoning='Market is steady.', spy_price=525.0, spy_change_5d=1.2,
        vix=14.5, vix_status='low',
    )
    sectors = [
        SectorAnalysis(
            name='Semiconductors', etf='SMH', stock_count=1,
            daily_change=2.5, ret_3m=15.0, rs_percentile=85.0,
            trend='uptrend', above_ema50=True,
            outlook='Strong demand from AI.',
            key_drivers=[{'text': 'AI boom'}], risks=[{'text': 'Supply chain'}],
            highlights=[
                StockHighlight('NVDA', 'NVIDIA', 950, 2.5e12, 'Breakout',
                               'Broke 60d high', 950, 900, 1100, 3.0,
                               time_horizon='Short (3-10d)'),
            ],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    table_header = '<th>Symbol</th><th>Price</th><th>Setup</th><th>RS</th><th>Entry+Dist</th><th>Stop</th><th>Target</th><th>R:R</th><th>Risk$</th>'
    assert table_header in content, "Table header should have exactly 9 columns"
    # Verify old column headers are absent
    assert '<th>Name</th>' not in content
    assert '<th>Horizon</th>' not in content
    assert '<th>Size</th>' not in content
    assert '<th>Cost</th>' not in content


def test_human_readable_timestamp(tmp_path):
    """Timestamp should be formatted as 'Sun, Jun 19, 2026 10:00 PM ET'."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [
        SectorAnalysis(name='Test', etf='', stock_count=0, daily_change=0,
                       ret_3m=None, rs_percentile=None, trend='neutral', above_ema50=None,
                       outlook='Test.'),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'Sat, Jun 19' in content or 'Fri, Jun 19' in content or 'Jun 19' in content


def test_keyboard_shortcuts_js(tmp_path):
    """Report should include j/k/Enter keyboard navigation JS."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Test', etf='', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None, outlook='Test.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'keydown' in content
    assert 'ArrowDown' in content or '"j"' in content or "'j'" in content
    assert 'Enter' in content
    assert 'fold-toggle' in content
    assert 'scrollIntoView' in content


def test_expand_collapse_buttons(tmp_path):
    """Report should include Expand All and Collapse All buttons."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Test', etf='', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None, outlook='Test.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'Expand All' in content
    assert 'Collapse All' in content


def test_confidence_dot_ok(tmp_path):
    """Green dot (#7ecb5a = --volt) when AI analysis is OK with no divergence."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Tech', etf='XLK', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None,
                              outlook='Sector is steady with strong fundamentals.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'color:var(--volt)' in content
    assert 'title="AI analysis OK"' in content
    # Ensure no divergence/unavailable dot classes appear for this case
    assert 'title="AI/quant divergence"' not in content
    assert 'title="AI unavailable"' not in content


def test_confidence_dot_divergence(tmp_path):
    """Red dot (#e0553d = --ember) when AI detects divergence."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Energy', etf='XLE', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None,
                              outlook='Divergence between price and volume trends.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'color:var(--ember)' in content
    assert 'title="AI/quant divergence"' in content


def test_confidence_dot_unavailable(tmp_path):
    """Gray dot (#5d6d80 = --ash) when AI analysis is unavailable."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Health', etf='XLV', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None,
                              outlook='Health sector: analysis unavailable.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'color:var(--ash)' in content
    assert 'title="AI unavailable"' in content


def test_atr_multiple_in_stop_column(tmp_path):
    """Stop column shows ATR multiple: $XX.XX (N.Nx ATR) with color coding."""
    market = MarketOverview(
        date='2026-06-19', regime='bull_moderate', confidence=70,
        reasoning='Market is steady.', spy_price=525.0, spy_change_5d=1.2,
        vix=14.5, vix_status='low',
    )
    h = StockHighlight('AAPL', 'Apple', 100, 2.5e12, 'Breakout',
                       'Broke 60d high', entry=100, stop=96, target=110, rr=2.5,
                       time_horizon='Swing (5-20d)')
    h.atr = 2.0  # dollar ATR
    sectors = [
        SectorAnalysis(
            name='Tech', etf='XLK', stock_count=1,
            daily_change=1.5, ret_3m=10.0, rs_percentile=80.0,
            trend='uptrend', above_ema50=True,
            outlook='Good sector.',
            highlights=[h],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    # ATR multiple = (100 - 96) / 2.0 = 2.0x
    assert '2.0x ATR' in content


def test_prior_picks_shows_performance_summary(tmp_path):
    """Performance summary header with win rate should appear in Prior Picks section."""
    from data.db import Database
    from datetime import datetime, timedelta

    db_path = tmp_path / "test_perf.db"
    test_db = Database(db_path)

    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    def make_rec(symbol, entry, stop, target, status, pnl_pct):
        rec = {
            'trade_date': yesterday, 'symbol': symbol, 'sector': 'Technology',
            'setup_type': 'Breakout', 'entry_price': entry, 'stop_price': stop,
            'target_price': target, 'rr': 3.0, 'composite_score': 80.0,
            'position_size': 100, 'position_cost': entry * 100,
            'risk_dollars': (entry - stop) * 100, 'current_price': entry,
            'entry_distance_pct': 0.0, 'max_days': 20,
        }
        test_db.save_recommendation(rec)
        active = test_db.get_active_recommendations()
        rec_id = active[-1]['id']
        outcome = 'win' if pnl_pct > 0 else 'loss'
        test_db.resolve_recommendation(rec_id, status, outcome, pnl_pct, 5)

    # 2 wins, 1 loss = 66.7% win rate
    make_rec('AAPL', 195.0, 190.0, 210.0, 'target_hit', 7.69)
    make_rec('NVDA', 950.0, 920.0, 1020.0, 'target_hit', 5.00)
    make_rec('MSFT', 400.0, 390.0, 420.0, 'stopped_out', -2.50)

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
    content = open(gen.generate_report(result)).read()

    assert 'Prior Picks Recap' in content
    assert 'Performance' in content
    assert 'win rate' in content


def test_csv_export_button(tmp_path):
    """CSV export button and JavaScript function should be in the report."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [SectorAnalysis(name='Test', etf='', stock_count=0, daily_change=0,
                              ret_3m=None, rs_percentile=None, trend='neutral',
                              above_ema50=None, outlook='Test.')]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert 'exportHighlightsCSV' in content
    assert 'Export CSV' in content
    assert 'tradescanner_highlights.csv' in content
    assert 'Blob' in content
    assert 'text/csv' in content


def test_entry_type_rendered_in_report(tmp_path):
    """Entry column should show order type: market='now', limit='(Limit)', stop-limit='(Stop)'."""
    market = MarketOverview(
        date='2026-06-19', regime='bull_moderate', confidence=70,
        reasoning='Market is steady.', spy_price=525.0, spy_change_5d=1.2,
        vix=14.5, vix_status='low',
    )
    nvda = StockHighlight('NVDA', 'NVIDIA', 200, 2.5e12, 'Breakout',
                          'Above resistance', 210, 190, 230, 2.0,
                          time_horizon='Swing (5-20d)')
    nvda.entry_type = 'stop-limit'

    amd = StockHighlight('AMD', 'AMD', 150, 1.5e11, 'Near Support',
                         'At support', 145, 140, 160, 3.0,
                         time_horizon='Short (3-10d)')
    amd.entry_type = 'limit'

    intc = StockHighlight('INTC', 'Intel', 35, 1e11, 'Strong Momentum',
                          'Strong volume', 35, 33, 38, 2.5,
                          time_horizon='Swing (5-20d)')
    intc.entry_type = 'market'

    sectors = [
        SectorAnalysis(
            name='Semiconductors', etf='SMH', stock_count=3,
            daily_change=2.5, ret_3m=15.0, rs_percentile=85.0,
            trend='uptrend', above_ema50=True,
            outlook='Strong demand from AI.',
            key_drivers=[{'text': 'AI boom'}], risks=[{'text': 'Supply chain'}],
            highlights=[nvda, amd, intc],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    content = open(gen.generate_report(result)).read()
    assert '$210.00 (Stop)' in content, "stop-limit entry type should show '(Stop)'"
    assert '$145.00 (Limit)' in content, "limit entry type should show '(Limit)'"
    assert '$35.00 now' in content, "market entry type should show 'now'"
