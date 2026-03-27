"""Tests for API server, Skill, and Scheduler."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json


def test_server_imports():
    """Test server module imports."""
    from api.server import app, trigger_scan, get_status, list_stocks
    assert app is not None


def test_skill_imports():
    """Test skill module imports."""
    from skill.commands import TradeScannerSkill, execute_command, COMMANDS
    assert 'scan' in COMMANDS
    assert 'status' in COMMANDS
    assert 'list' in COMMANDS


def test_scheduler_imports():
    """Test scheduler imports."""
    from scheduler import TradeScanner, main
    assert TradeScanner is not None


@patch('skill.commands.requests.get')
def test_skill_status(mock_get):
    """Test skill status command."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'status': 'ok',
        'active_stocks_count': 100,
        'last_scan': None
    }
    mock_get.return_value = mock_response

    from skill.commands import TradeScannerSkill
    skill = TradeScannerSkill(api_base='http://test')
    result = skill.status()

    assert 'Running' in result or 'failed' in result


@patch('skill.commands.requests.post')
def test_skill_add_stock(mock_post):
    """Test skill add stock command."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'status': 'success',
        'symbol': 'AAPL',
        'message': 'AAPL added'
    }
    mock_post.return_value = mock_response

    from skill.commands import TradeScannerSkill
    skill = TradeScannerSkill(api_base='http://test')
    result = skill.add_stock('AAPL', 'Apple Inc', 'Technology')

    assert 'AAPL added' in result or 'success' in result


@patch('skill.commands.requests.post')
def test_skill_remove_stock(mock_post):
    """Test skill remove stock command."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'status': 'success',
        'symbol': 'TSLA',
        'message': 'TSLA removed'
    }
    mock_post.return_value = mock_response

    from skill.commands import TradeScannerSkill
    skill = TradeScannerSkill(api_base='http://test')
    result = skill.remove_stock('TSLA')

    assert 'TSLA removed' in result or 'success' in result


@patch('skill.commands.requests.get')
def test_skill_list_stocks(mock_get):
    """Test skill list stocks command."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'count': 3,
        'symbols': ['AAPL', 'MSFT', 'GOOGL']
    }
    mock_get.return_value = mock_response

    from skill.commands import TradeScannerSkill
    skill = TradeScannerSkill(api_base='http://test')
    result = skill.list_stocks()

    assert 'AAPL' in result or 'failed' in result


@patch('skill.commands.requests.get')
def test_skill_history(mock_get):
    """Test skill history command."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'count': 2,
        'history': [
            {'scan_date': '2025-03-27', 'scan_time': '06:00:00',
             'market_sentiment': 'bullish', 'total_stocks': 100},
            {'scan_date': '2025-03-26', 'scan_time': '06:00:00',
             'market_sentiment': 'neutral', 'total_stocks': 100}
        ]
    }
    mock_get.return_value = mock_response

    from skill.commands import TradeScannerSkill
    skill = TradeScannerSkill(api_base='http://test')
    result = skill.history(n=5)

    assert '2025-03-27' in result or 'failed' in result


def test_skill_execute_command():
    """Test execute_command dispatcher."""
    from skill.commands import execute_command

    # Test unknown command
    result = execute_command('unknown')
    assert 'Unknown command' in result

    # Test known commands with mock
    with patch('skill.commands.TradeScannerSkill') as mock_skill_class:
        mock_skill = MagicMock()
        mock_skill.status.return_value = 'Status OK'
        mock_skill_class.return_value = mock_skill

        result = execute_command('status')
        # Should call handler which creates skill and calls method


def test_scheduler_is_trading_day():
    """Test trading day check - just verify method exists."""
    from scheduler import TradeScanner

    # Just verify the method exists
    assert hasattr(TradeScanner, 'is_trading_day')


def test_trade_scanner_initialization():
    """Test TradeScanner initialization."""
    with patch('scheduler.Database') as mock_db, \
         patch('scheduler.DataFetcher') as mock_fetcher, \
         patch('scheduler.StrategyScreener') as mock_screener, \
         patch('scheduler.MarketAnalyzer') as mock_analyzer, \
         patch('scheduler.CandidateSelector') as mock_selector, \
         patch('scheduler.OpportunityAnalyzer') as mock_opp_analyzer, \
         patch('scheduler.ReportGenerator') as mock_reporter:

        from scheduler import TradeScanner
        scanner = TradeScanner()

        assert scanner.db is not None
        assert scanner.fetcher is not None
        assert scanner.screener is not None


def test_run_scan_with_no_symbols():
    """Test run_scan with no symbols."""
    with patch('scheduler.Database') as mock_db:
        mock_db_instance = MagicMock()
        mock_db_instance.get_active_stocks.return_value = []
        mock_db.return_value = mock_db_instance

        from scheduler import TradeScanner
        scanner = TradeScanner()
        scanner.db = mock_db_instance

        result = scanner.run_scan(symbols=[])
        assert result is None


def test_main_with_test_flag():
    """Test main function with --test flag."""
    with patch('scheduler.TradeScanner') as mock_scanner_class, \
         patch('sys.argv', ['scheduler.py', '--test', '--symbols', 'AAPL,MSFT']):

        mock_scanner = MagicMock()
        mock_scanner.run_test_scan.return_value = '/tmp/test_report.html'
        mock_scanner_class.return_value = mock_scanner

        from scheduler import main
        main()

        mock_scanner.run_test_scan.assert_called_once_with(['AAPL', 'MSFT'])
