"""Tests for AI pipeline components."""
import pytest
import json
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer, AnalyzedOpportunity
from core.reporter import ReportGenerator
from core.screener import StrategyMatch


@pytest.fixture
def sample_strategy_match():
    """Create sample strategy match."""
    return StrategyMatch(
        symbol='AAPL',
        strategy='Momentum',
        entry_price=150.0,
        stop_loss=145.0,
        take_profit=160.0,
        confidence=75,
        match_reasons=['Near resistance', 'Volume spike'],
        technical_snapshot={'current_price': 149.5, 'volume_ratio': 2.5}
    )


@pytest.fixture
def sample_opportunities():
    """Create sample analyzed opportunities."""
    return [
        AnalyzedOpportunity(
            symbol='AAPL',
            strategy='Momentum',
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=80,
            match_reasons=['Near resistance', 'Volume spike'],
            ai_reasoning='Strong breakout setup with volume confirmation',
            catalyst='Earnings beat expectation',
            risk_factors=['Market volatility', 'Resistance at 155'],
            position_size='normal',
            time_frame='swing'
        ),
        AnalyzedOpportunity(
            symbol='MSFT',
            strategy='EP',
            entry_price=250.0,
            stop_loss=245.0,
            take_profit=265.0,
            confidence=70,
            match_reasons=['Earnings tomorrow'],
            ai_reasoning='Earnings play with technical support',
            catalyst='Q4 earnings report',
            risk_factors=['Earnings volatility'],
            position_size='small',
            time_frame='short-term'
        )
    ]


def test_market_analyzer_initialization():
    """Test MarketAnalyzer initialization."""
    with patch('core.market_analyzer.settings') as mock_settings:
        mock_settings.get_secret.return_value = 'test_key'
        mock_settings.get.return_value = {'api_base': 'https://test.com', 'model': 'test'}

        analyzer = MarketAnalyzer()
        assert analyzer.tavily_api_key == 'test_key'
        assert analyzer.dashscope_api_key == 'test_key'


@patch('core.market_analyzer.requests.post')
def test_tavily_search(mock_post):
    """Test Tavily search."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'results': [
            {'title': 'Test', 'content': 'Test content'}
        ]
    }
    mock_post.return_value = mock_response

    with patch('core.market_analyzer.settings') as mock_settings:
        mock_settings.get_secret.return_value = 'test_key'

        analyzer = MarketAnalyzer()
        results = analyzer.tavily_search('test query')

        assert len(results) == 1
        assert results[0]['title'] == 'Test'


@patch('core.market_analyzer.requests.post')
def test_analyze_sentiment_fallback(mock_post):
    """Test sentiment analysis fallback."""
    with patch('core.market_analyzer.settings') as mock_settings:
        mock_settings.get_secret.return_value = None  # No API key

        analyzer = MarketAnalyzer()
        result = analyzer.analyze_sentiment()

        assert result['sentiment'] == 'neutral'
        assert result['confidence'] == 50


def test_candidate_selector_initialization():
    """Test CandidateSelector initialization."""
    with patch('core.selector.settings') as mock_settings:
        mock_settings.get_secret.return_value = 'test_key'
        mock_settings.get.return_value = {'api_base': 'https://test.com', 'model': 'test'}

        selector = CandidateSelector()
        assert selector.dashscope_api_key == 'test_key'
        assert 'bullish' in selector.STRATEGY_WEIGHTS


def test_strategy_weights():
    """Test strategy weights for different sentiments."""
    with patch('core.selector.settings') as mock_settings:
        mock_settings.get_secret.return_value = None

        selector = CandidateSelector()

        # Check bullish weights
        bullish = selector.STRATEGY_WEIGHTS['bullish']
        assert bullish['Momentum'] > bullish['DTSS']

        # Check bearish weights
        bearish = selector.STRATEGY_WEIGHTS['bearish']
        assert bearish['DTSS'] > bearish['Momentum']


def test_select_top_30_no_ai():
    """Test selection without AI."""
    with patch('core.selector.settings') as mock_settings:
        mock_settings.get_secret.return_value = None

        selector = CandidateSelector()

        # Create 35 candidates
        candidates = [
            StrategyMatch(
                symbol=f'STOCK{i}',
                strategy='Momentum',
                entry_price=100.0 + i,
                stop_loss=95.0,
                take_profit=110.0,
                confidence=50 + i
            )
            for i in range(35)
        ]

        selected = selector.select_top_30(candidates, 'neutral')

        assert len(selected) == 30


def test_analyzed_opportunity_creation():
    """Test AnalyzedOpportunity dataclass."""
    opp = AnalyzedOpportunity(
        symbol='AAPL',
        strategy='Momentum',
        entry_price=150.0,
        stop_loss=145.0,
        take_profit=160.0,
        confidence=80
    )

    assert opp.symbol == 'AAPL'
    assert opp.position_size == 'normal'  # default
    assert opp.time_frame == 'short-term'  # default


def test_report_generator_initialization():
    """Test ReportGenerator initialization."""
    with patch('core.reporter.settings') as mock_settings:
        mock_settings.REPORTS_DIR = Mock()
        mock_settings.CHARTS_DIR = Mock()
        mock_settings.get.return_value = {'max_reports': 15, 'retention_days': 15}

        generator = ReportGenerator()
        assert generator.max_reports == 15


@patch('core.reporter.ReportGenerator._generate_charts')
@patch('core.reporter.ReportGenerator._cleanup_old_reports')
def test_generate_report(mock_cleanup, mock_charts, sample_opportunities):
    """Test report generation."""
    with patch('core.reporter.settings') as mock_settings:
        mock_settings.REPORTS_DIR = Mock()
        mock_settings.CHARTS_DIR = Mock()
        mock_settings.get.return_value = {'max_reports': 15, 'retention_days': 15}

        # Mock path operations
        mock_path = Mock()
        mock_path.__truediv__ = Mock(return_value=mock_path)
        mock_path.__str__ = Mock(return_value='/tmp/test_report.html')
        mock_settings.REPORTS_DIR = mock_path

        generator = ReportGenerator()
        generator.charts_dir = mock_path
        generator.reports_dir = mock_path

        mock_charts.return_value = {'AAPL': '../charts/AAPL.png'}

        # Mock file operations
        m = Mock()
        m.return_value.__enter__ = Mock(return_value=m)
        m.return_value.__exit__ = Mock(return_value=False)

        with patch('builtins.open', m):
            result = generator.generate_report(
                opportunities=sample_opportunities,
                market_sentiment='bullish',
                total_stocks=100,
                success_count=95,
                fail_count=5,
                fail_symbols=['FAILED1']
            )

            assert result is not None


def test_html_structure(sample_opportunities):
    """Test HTML report structure."""
    with patch('core.reporter.settings') as mock_settings:
        mock_settings.REPORTS_DIR = Mock()
        mock_settings.CHARTS_DIR = Mock()
        mock_settings.get.return_value = {'max_reports': 15, 'retention_days': 15}

        generator = ReportGenerator()

        # Test _build_html directly
        html = generator._build_html(
            opportunities=sample_opportunities,
            market_sentiment='bullish',
            scan_date='2025-03-27',
            scan_time='06:00:00',
            total_stocks=100,
            success_count=95,
            fail_count=5,
            fail_symbols=['FAILED1'],
            chart_paths={'AAPL': '../charts/AAPL.png'}
        )

        assert '<!DOCTYPE html>' in html
        assert 'AAPL' in html
        assert 'bullish' in html.lower()
        assert 'Momentum' in html
        assert 'Top 10 Opportunities' in html
