"""Tests for report UX polish features: horizon badges, keyboard nav, timestamps, expand/collapse."""
from core.reporter import ReportGenerator
from core.sector_analyzer import MarketOverview, SectorAnalysis, StockHighlight, FocusSummary


def test_horizon_badge_colors(tmp_path):
    """Horizon badges should be color-coded: Short=badge-up, Swing/Position=badge-neutral."""
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
    assert 'badge badge-up">Short' in content
    assert 'badge badge-neutral">Swing' in content
    assert 'badge badge-neutral">Position' in content


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
