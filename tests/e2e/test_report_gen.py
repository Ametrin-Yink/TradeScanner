from core.reporter import ReportGenerator
from core.sector_analyzer import MarketOverview, SectorAnalysis, FocusSummary, StockHighlight


def test_report_generates_html(tmp_path):
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
                               'Broke 60d high', 950, 900, 1100, 3.0),
            ],
        ),
    ]
    focus = FocusSummary(
        focus_sectors=['Semiconductors'], avoid_sectors=['Software'],
        reasoning='Focus on strong momentum sectors.',
    )

    result = {
        'market': market, 'sectors': sectors, 'focus_summary': focus,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    report_path = gen.generate_report(result)

    assert 'report_2026' in report_path
    assert str(tmp_path) in report_path
    content = open(report_path).read()
    assert 'NVDA' in content
    assert 'Semiconductors' in content
    assert 'Breakout' in content
    assert 'bull_moderate' in content
    assert 'SPY' in content


def test_report_embeds_ohlc_data(tmp_path, seeded_db):
    """Report HTML embeds 120-bar OHLC data as JSON blob for offline charts."""
    from core.sector_analyzer import MarketOverview, SectorAnalysis, StockHighlight

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
                               'Broke 60d high', 950, 900, 1100, 3.0),
            ],
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path, db=seeded_db)
    report_path = gen.generate_report(result)
    content = open(report_path).read()
    assert 'window._EMBEDDED_OHLC' in content
    import json
    # Extract the JSON blob
    marker = 'window._EMBEDDED_OHLC = '
    start = content.index(marker) + len(marker)
    end = content.index(';</script>', start)
    ohlc_data = json.loads(content[start:end])
    assert 'NVDA' in ohlc_data
    # New format: {'bars': [...], 'atr': value}
    entry = ohlc_data['NVDA']
    bars = entry['bars'] if isinstance(entry, dict) and 'bars' in entry else entry
    assert len(bars) > 0
    assert 'open' in bars[0]
    assert 'date' in bars[0]
    # showChart references embedded data first
    assert 'window._EMBEDDED_OHLC' in content.split('function showChart')[1].split('function drawCandles')[0]


def test_report_includes_table_utils_js(tmp_path):
    """Report HTML includes a script reference to table-utils.js for client-side sorting."""
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [
        SectorAnalysis(
            name='Test', etf='', stock_count=0, daily_change=0,
            ret_3m=None, rs_percentile=None, trend='neutral', above_ema50=None,
            outlook='Test sector.',
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    report_path = gen.generate_report(result)
    content = open(report_path).read()
    assert '../js/table-utils.js' in content
    assert '<script src="../js/table-utils.js"></script>' in content


def test_report_handles_empty_ai(tmp_path):
    market = MarketOverview(
        date='2026-06-19', regime='neutral', confidence=50,
        reasoning='', spy_price=500, spy_change_5d=0, vix=20, vix_status='neutral',
    )
    sectors = [
        SectorAnalysis(
            name='Empty', etf='', stock_count=0, daily_change=0,
            ret_3m=None, rs_percentile=None, trend='neutral', above_ema50=None,
            outlook='Empty sector: no AI analysis available.',
        ),
    ]
    result = {
        'market': market, 'sectors': sectors, 'focus_summary': None,
        'timestamp': '2026-06-19T22:00',
    }
    gen = ReportGenerator(reports_dir=tmp_path)
    report_path = gen.generate_report(result)
    content = open(report_path).read()
    assert 'unavailable' in content.lower() or 'fallback' in content.lower() or 'empty' in content.lower()
    # Verify it wrote to tmp_path, not the production reports dir
    assert str(tmp_path) in report_path
