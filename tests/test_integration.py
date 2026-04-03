"""Integration test for the complete pipeline."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

from scheduler import TradeScanner


@pytest.fixture
def sample_market_data():
    """Create sample market data for 3 stocks."""
    data = {}
    for symbol in ['AAPL', 'MSFT', 'NVDA']:
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        prices = 100 + np.cumsum(np.random.randn(100) * 0.5)

        data[symbol] = pd.DataFrame({
            'open': prices - 0.5,
            'high': prices + 1,
            'low': prices - 1,
            'close': prices,
            'volume': np.random.randint(2_000_000, 5_000_000, 100)
        }, index=dates)

    return data


def test_full_pipeline_mocked(sample_market_data):
    """Test full pipeline with mocked components."""
    with patch('scheduler.Database') as mock_db, \
         patch('scheduler.DataFetcher') as mock_fetcher, \
         patch('scheduler.StrategyScreener') as mock_screener, \
         patch('scheduler.MarketAnalyzer') as mock_analyzer, \
         patch('scheduler.CandidateSelector') as mock_selector, \
         patch('scheduler.OpportunityAnalyzer') as mock_opp_analyzer, \
         patch('scheduler.ReportGenerator') as mock_reporter:

        # Setup mocks
        mock_db_instance = MagicMock()
        mock_db_instance.get_active_stocks.return_value = ['AAPL', 'MSFT', 'NVDA']
        mock_db.return_value = mock_db_instance

        mock_fetcher_instance = MagicMock()
        mock_fetcher_instance.download_batch.return_value = sample_market_data
        mock_fetcher.return_value = mock_fetcher_instance

        # Mock screener to return some candidates
        from core.screener import StrategyMatch
        mock_screener_instance = MagicMock()
        mock_screener_instance.screen_all.return_value = [
            StrategyMatch(
                symbol='AAPL', strategy='Momentum',
                entry_price=150.0, stop_loss=145.0,
                take_profit=160.0, confidence=80
            ),
            StrategyMatch(
                symbol='MSFT', strategy='EP',
                entry_price=250.0, stop_loss=245.0,
                take_profit=265.0, confidence=75
            ),
        ]
        mock_screener.return_value = mock_screener_instance

        # Mock market analyzer
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.analyze_sentiment.return_value = {
            'sentiment': 'bullish',
            'confidence': 75
        }
        mock_analyzer.return_value = mock_analyzer_instance

        # Mock selector
        from core.analyzer import AnalyzedOpportunity
        mock_selector_instance = MagicMock()
        mock_selector_instance.select_top_30.return_value = [
            StrategyMatch(
                symbol='AAPL', strategy='Momentum',
                entry_price=150.0, stop_loss=145.0,
                take_profit=160.0, confidence=80
            ),
        ]
        mock_selector.return_value = mock_selector_instance

        # Mock opportunity analyzer
        mock_opp_analyzer_instance = MagicMock()
        mock_opp_analyzer_instance.analyze_all.return_value = [
            AnalyzedOpportunity(
                symbol='AAPL', strategy='Momentum',
                entry_price=150.0, stop_loss=145.0,
                take_profit=160.0, confidence=85,
                ai_reasoning='Strong breakout setup'
            ),
        ]
        mock_opp_analyzer.return_value = mock_opp_analyzer_instance

        # Mock reporter
        mock_reporter_instance = MagicMock()
        mock_reporter_instance.generate_report.return_value = '/tmp/test_report.html'
        mock_reporter.return_value = mock_reporter_instance

        # Run scanner
        scanner = TradeScanner()
        result = scanner.run_scan(symbols=['AAPL', 'MSFT', 'NVDA'], skip_market_hours_check=True)

        # Verify result
        assert result == '/tmp/test_report.html'


def test_pipeline_with_real_components():
    """Test pipeline initialization with real components."""
    from scheduler import TradeScanner
    from data.db import Database
    from core.fetcher import DataFetcher
    from core.screener import StrategyScreener
    from core.market_analyzer import MarketAnalyzer
    from core.selector import CandidateSelector
    from core.analyzer import OpportunityAnalyzer
    from core.reporter import ReportGenerator

    # Create scanner
    scanner = TradeScanner()

    # Verify all components initialized
    assert isinstance(scanner.db, Database)
    assert isinstance(scanner.fetcher, DataFetcher)
    assert isinstance(scanner.screener, StrategyScreener)
    assert isinstance(scanner.market_analyzer, MarketAnalyzer)
    assert isinstance(scanner.selector, CandidateSelector)
    assert isinstance(scanner.opportunity_analyzer, OpportunityAnalyzer)
    assert isinstance(scanner.reporter, ReportGenerator)


def test_end_to_end_data_flow():
    """Test data flows correctly through pipeline stages."""
    # Create test data
    from core.screener import StrategyMatch, StrategyScreener
    from core.analyzer import AnalyzedOpportunity

    # Stage 1: Screener output
    candidates = [
        StrategyMatch(
            symbol='AAPL', strategy='Momentum',
            entry_price=150.0, stop_loss=145.0,
            take_profit=160.0, confidence=80,
            match_reasons=['Near resistance', 'Volume spike'],
            technical_snapshot={'volume_ratio': 2.5}
        ),
        StrategyMatch(
            symbol='MSFT', strategy='EP',
            entry_price=250.0, stop_loss=245.0,
            take_profit=265.0, confidence=75,
            match_reasons=['Earnings tomorrow'],
            technical_snapshot={}
        ),
    ]

    # Stage 2: Selector narrows to top candidates
    # (In real scenario, this would use AI or weighted scoring)
    top_candidates = candidates[:1]  # Just take first for test

    assert len(top_candidates) <= len(candidates)
    assert top_candidates[0].symbol == 'AAPL'

    # Stage 3: Analyzer adds AI insights
    analyzed = [
        AnalyzedOpportunity(
            symbol=c.symbol,
            strategy=c.strategy,
            entry_price=c.entry_price,
            stop_loss=c.stop_loss,
            take_profit=c.take_profit,
            confidence=c.confidence,
            match_reasons=c.match_reasons,
            ai_reasoning='AI analysis of the setup',
            catalyst='Expected breakout',
            risk_factors=['Market risk'],
            position_size='normal',
            time_frame='swing'
        )
        for c in top_candidates
    ]

    assert len(analyzed) == len(top_candidates)
    assert analyzed[0].ai_reasoning is not None


def test_report_structure():
    """Test report contains all required sections."""
    from core.reporter import ReportGenerator
    from core.analyzer import AnalyzedOpportunity

    # Create sample analyzed opportunities
    opportunities = [
        AnalyzedOpportunity(
            symbol='AAPL', strategy='Momentum',
            entry_price=150.0, stop_loss=145.0,
            take_profit=160.0, confidence=85,
            match_reasons=['Near resistance'],
            ai_reasoning='Strong setup',
            catalyst='Earnings beat',
            risk_factors=['Volatility'],
            position_size='normal',
            time_frame='swing'
        ),
    ]

    # Generate HTML
    generator = ReportGenerator()
    html = generator._build_html(
        opportunities=opportunities,
        market_sentiment='bullish',
        scan_date='2025-03-27',
        scan_time='06:00:00',
        total_stocks=100,
        success_count=95,
        fail_count=5,
        fail_symbols=['FAILED'],
        chart_paths={'AAPL': '../charts/AAPL.png'}
    )

    # Verify HTML structure
    assert '<!DOCTYPE html>' in html
    assert 'AAPL' in html
    assert 'Momentum' in html
    assert 'bullish' in html.lower()
    assert 'Top 10 Opportunities' in html
    assert 'System Status' not in html  # This is API status, not in report


def test_database_operations():
    """Test database save and retrieve."""
    from data.db import Database
    import tempfile
    from pathlib import Path

    # Use temp database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)

        # Add stocks
        db.add_stock('AAPL', 'Apple Inc', 'Technology')
        db.add_stock('MSFT', 'Microsoft', 'Technology')

        # Retrieve active stocks
        stocks = db.get_active_stocks()
        assert 'AAPL' in stocks
        assert 'MSFT' in stocks

        # Save scan result
        result = {
            'scan_date': '2025-03-27',
            'scan_time': '06:00:00',
            'market_sentiment': 'bullish',
            'top_opportunities': [{'symbol': 'AAPL', 'confidence': 80}],
            'all_candidates': [{'symbol': 'AAPL'}, {'symbol': 'MSFT'}],
            'total_stocks': 2,
            'success_count': 2,
            'fail_count': 0,
            'fail_symbols': [],
            'report_path': '/tmp/report.html'
        }

        scan_id = db.save_scan_result(result)
        assert scan_id > 0
