"""Claude Skill commands for trade scanner."""
import requests
import json
from typing import Optional, List
from datetime import datetime

from config.settings import settings

API_BASE = f"http://localhost:{settings.get('report', {}).get('web_port', 8080)}"


class TradeScannerSkill:
    """Claude Skill interface for trade scanner."""

    def __init__(self, api_base: Optional[str] = None):
        """Initialize skill with API endpoint."""
        self.api_base = api_base or API_BASE

    def _call_api(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make API call."""
        url = f"{self.api_base}{endpoint}"
        try:
            if method == 'GET':
                response = requests.get(url, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, timeout=120)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            return {
                'status': 'error',
                'message': 'API server not running. Start with: python api/server.py'
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def scan(self, mode: str = 'full', symbols: Optional[List[str]] = None) -> str:
        """
        Trigger a manual scan.

        Args:
            mode: 'quick' or 'full'
            symbols: Optional list of symbols to scan
        """
        data = {'mode': mode}
        if symbols:
            data['symbols'] = symbols

        result = self._call_api('POST', '/scan', data)

        if result.get('status') == 'success':
            report_url = result.get('report_path', '')
            return f"""✅ Scan Complete

📅 Date: {result.get('scan_date')} {result.get('scan_time')}
📊 Market Sentiment: {result.get('market_sentiment', 'N/A').upper()}
🔍 Candidates Found: {result.get('candidates_found', 0)}
🎯 Top 10 Selected: {result.get('top_10_count', 0)}

📄 Report: {report_url}
"""
        else:
            return f"❌ Scan failed: {result.get('message', 'Unknown error')}"

    def status(self) -> str:
        """Get system status."""
        result = self._call_api('GET', '/status')

        if result.get('status') == 'ok':
            last_scan = result.get('last_scan')
            if last_scan:
                last_scan_info = f"""
Last Scan:
  Date: {last_scan.get('date', 'N/A')}
  Time: {last_scan.get('time', 'N/A')}
  Sentiment: {last_scan.get('sentiment', 'N/A')}
  Stocks: {last_scan.get('stocks_scanned', 0)}"""
            else:
                last_scan_info = "\nLast Scan: None"

            return f"""📊 System Status

✅ API Server: Running
📈 Active Stocks: {result.get('active_stocks_count', 0)}{last_scan_info}
"""
        else:
            return f"❌ Status check failed: {result.get('message', 'Unknown error')}"

    def list_stocks(self) -> str:
        """List current stock universe."""
        result = self._call_api('GET', '/stocks')

        if 'symbols' in result:
            symbols = result['symbols']
            symbol_list = ', '.join(symbols[:30])
            if len(symbols) > 30:
                symbol_list += f", ... ({len(symbols) - 30} more)"

            return f"""📋 Stock Universe ({result.get('count', 0)} stocks)

{symbol_list}
"""
        else:
            return f"❌ Failed to list stocks: {result.get('message', 'Unknown error')}"

    def add_stock(self, ticker: str, name: str = '', sector: str = '') -> str:
        """
        Add a stock to the universe.

        Args:
            ticker: Stock symbol (e.g., 'AAPL')
            name: Company name (optional)
            sector: Sector (optional)
        """
        ticker = ticker.upper()
        result = self._call_api('POST', '/stocks/add', {
            'symbol': ticker,
            'name': name,
            'sector': sector
        })

        if result.get('status') == 'success':
            return f"✅ {ticker} added to stock universe"
        else:
            return f"❌ Failed to add {ticker}: {result.get('message', 'Unknown error')}"

    def remove_stock(self, ticker: str) -> str:
        """
        Remove a stock from the universe.

        Args:
            ticker: Stock symbol to remove
        """
        ticker = ticker.upper()
        result = self._call_api('POST', '/stocks/remove', {'symbol': ticker})

        if result.get('status') == 'success':
            return f"✅ {ticker} removed from stock universe"
        else:
            return f"❌ Failed to remove {ticker}: {result.get('message', 'Unknown error')}"

    def history(self, n: int = 5) -> str:
        """
        View recent scan history.

        Args:
            n: Number of recent scans to show
        """
        result = self._call_api('GET', f'/history?n={n}')

        if 'history' in result:
            lines = [f"📜 Recent Scan History ({result.get('count', 0)} scans)", ""]

            for i, scan in enumerate(result['history'], 1):
                lines.append(f"{i}. {scan.get('scan_date')} {scan.get('scan_time')} "
                           f"| {scan.get('market_sentiment', 'N/A').upper()} "
                           f"| {scan.get('total_stocks', 0)} stocks")

            return '\n'.join(lines)
        else:
            return f"❌ Failed to get history: {result.get('message', 'Unknown error')}"

    def reports(self) -> str:
        """List available reports."""
        result = self._call_api('GET', '/reports')

        if 'reports' in result:
            lines = [f"📄 Available Reports ({result.get('count', 0)} total)", ""]

            for report in result['reports'][:10]:
                lines.append(f"• {report.get('date')} - {report.get('filename')} "
                           f"({report.get('size', 0) // 1024} KB)")

            return '\n'.join(lines)
        else:
            return f"❌ Failed to list reports: {result.get('message', 'Unknown error')}"


# Command handlers for Claude integration
def handle_scan(args: str = '') -> str:
    """Handle /scan command."""
    skill = TradeScannerSkill()

    parts = args.strip().split()
    mode = parts[0] if parts and parts[0] in ['quick', 'full'] else 'full'

    return skill.scan(mode=mode)


def handle_status(args: str = '') -> str:
    """Handle /status command."""
    skill = TradeScannerSkill()
    return skill.status()


def handle_list(args: str = '') -> str:
    """Handle /list command."""
    skill = TradeScannerSkill()
    return skill.list_stocks()


def handle_add(args: str) -> str:
    """Handle /add command."""
    if not args.strip():
        return "Usage: /add <ticker>"

    skill = TradeScannerSkill()
    return skill.add_stock(args.strip().upper())


def handle_remove(args: str) -> str:
    """Handle /remove command."""
    if not args.strip():
        return "Usage: /remove <ticker>"

    skill = TradeScannerSkill()
    return skill.remove_stock(args.strip().upper())


def handle_history(args: str = '') -> str:
    """Handle /history command."""
    skill = TradeScannerSkill()
    n = int(args.strip()) if args.strip().isdigit() else 5
    return skill.history(n=n)


def handle_reports(args: str = '') -> str:
    """Handle /reports command."""
    skill = TradeScannerSkill()
    return skill.reports()


# Command mapping
COMMANDS = {
    'scan': handle_scan,
    'status': handle_status,
    'list': handle_list,
    'add': handle_add,
    'remove': handle_remove,
    'history': handle_history,
    'reports': handle_reports,
}


def execute_command(command: str, args: str = '') -> str:
    """Execute a skill command."""
    handler = COMMANDS.get(command)
    if handler:
        return handler(args)
    return f"Unknown command: {command}. Available: {', '.join(COMMANDS.keys())}"


if __name__ == '__main__':
    # Test commands
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        args = ' '.join(sys.argv[2:])
        print(execute_command(cmd, args))
    else:
        print("Usage: python skill/commands.py <command> [args]")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
