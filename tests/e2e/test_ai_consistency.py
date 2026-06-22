"""Tests for AI-quantitative consistency check and report footer AI status."""
from core.sector_analyzer import SectorAnalyzer
from core.reporter import ReportGenerator


def test_consistency_check_uptrend_bearish_outlook(seeded_db, mock_ai, monkeypatch):
    """When trend is uptrend but AI says bearish, divergence warning is appended."""
    conn = seeded_db.get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO etf_cache
            (symbol, current_price, ret_5d, ret_3m, rs_percentile, above_ema50)
        VALUES ('SMH', 200.0, 2.0, 15.0, 80.0, 1)
    """)
    conn.commit()

    analyzer = SectorAnalyzer(db=seeded_db)

    original_ai = analyzer._ai_sector_analysis
    def mock_ai_fn(sector_name):
        if sector_name == 'Semiconductors':
            return 'Bearish outlook for the sector due to declining demand.', [], []
        return original_ai(sector_name)
    monkeypatch.setattr(analyzer, '_ai_sector_analysis', mock_ai_fn)

    market = analyzer._analyze_market()
    sector_info = {'name': 'Semiconductors', 'stock_count': 1}
    result = analyzer._analyze_sector(sector_info, market)

    assert 'AI/quantitative divergence' in result.outlook
    assert 'uptrend detected but AI outlook cautious' in result.outlook


def test_consistency_check_downtrend_bullish_outlook(seeded_db, mock_ai, monkeypatch):
    """When trend is downtrend but AI says bullish, divergence warning is appended."""
    analyzer = SectorAnalyzer(db=seeded_db)

    def mock_trend(self, daily_change, ret_3m, above_ema50):
        return 'downtrend'
    monkeypatch.setattr(SectorAnalyzer, '_determine_trend', mock_trend)

    original_ai = analyzer._ai_sector_analysis
    def mock_ai_fn(sector_name):
        if sector_name == 'Software':
            return 'Strong bullish momentum expected to continue accelerating.', [], []
        return original_ai(sector_name)
    monkeypatch.setattr(analyzer, '_ai_sector_analysis', mock_ai_fn)

    market = analyzer._analyze_market()
    sector_info = {'name': 'Software', 'stock_count': 2}
    result = analyzer._analyze_sector(sector_info, market)

    assert 'AI/quantitative divergence' in result.outlook
    assert 'downtrend detected but AI outlook optimistic' in result.outlook


def test_consistency_check_no_conflict(seeded_db, mock_ai):
    """When AI outlook matches trend, no divergence warning is appended."""
    analyzer = SectorAnalyzer(db=seeded_db)

    market = analyzer._analyze_market()
    sector_info = {'name': 'Semiconductors', 'stock_count': 1}
    result = analyzer._analyze_sector(sector_info, market)

    assert 'AI/quantitative divergence' not in result.outlook


def test_ai_prompt_contains_stock_symbols(seeded_db, mock_ai, monkeypatch):
    """AI sector analysis prompt includes stock symbols for the analyzed sector."""
    captured_messages = []

    def capturing_chat(**kwargs):
        captured_messages.extend(kwargs.get('messages', []))
        import json
        return json.dumps({
            'outlook': 'Positive outlook driven by AI infrastructure spending.',
            'drivers': [{'text': 'AI data center expansion driving demand.', 'catalyst_date': None}],
            'risks': [{'text': 'Supply chain constraints could limit growth.', 'catalyst_date': 'Q3 2026'}],
        })

    monkeypatch.setattr('core.sector_analyzer.chat', capturing_chat)

    analyzer = SectorAnalyzer(db=seeded_db)
    market = analyzer._analyze_market()
    sector_info = {'name': 'Semiconductors', 'stock_count': 1}
    result = analyzer._analyze_sector(sector_info, market)

    user_msgs = [m['content'] for m in captured_messages if m.get('role') == 'user']
    sector_msgs = [m for m in user_msgs if 'Stocks in this sector:' in m]
    assert len(sector_msgs) > 0, (
        f"No user message contains 'Stocks in this sector:'. Messages: {user_msgs}"
    )
    assert 'NVDA' in sector_msgs[0], (
        f"Expected NVDA in sector message but got: {sector_msgs[0]}"
    )


def test_report_footer_shows_ai_status(tmp_path, seeded_db, mock_ai):
    """Report footer includes AI sector coverage status."""
    analyzer = SectorAnalyzer(db=seeded_db)
    result = analyzer.analyze()

    gen = ReportGenerator(reports_dir=tmp_path)
    report_path = gen.generate_report(result)
    content = open(report_path).read()

    assert 'sectors OK' in content
    assert 'AI:' in content
    # With mock_ai, all 3 sectors return valid outlooks
    assert 'AI: 3/3 sectors OK' in content
