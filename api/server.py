"""Flask API server for trade scanner."""
import sys
from pathlib import Path as _Path
# Ensure project root is on sys.path when run directly
_PROJECT_ROOT = _Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request

import os
from config.settings import settings, REPORTS_DIR, CHARTS_DIR
from data.db import Database
from core.fetcher import DataFetcher
from core.sector_analyzer import SectorAnalyzer
from core.reporter import ReportGenerator
from api.config_api import config_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level singletons
_last_scan_result = None
_last_scan_time = None
_SCAN_CACHE_SECONDS = 3600  # 1 hour


def validate_symbol(symbol: str) -> bool:
    """Validate stock symbol format."""
    if not symbol or len(symbol) > 10:
        return False
    return bool(re.match(r'^[A-Z0-9.]{1,10}$', symbol))


app = Flask(__name__)
app.register_blueprint(config_api)
db = Database()
db._migrate_to_tags()
fetcher = DataFetcher(db=db)


@app.route('/')
def index():
    """Root endpoint."""
    return jsonify({
        'service': 'Trade Scanner API',
        'version': '1.0.0',
        'status': 'running'
    })


@app.route('/dashboard')
def dashboard():
    """Serve the config dashboard HTML."""
    from flask import send_from_directory
    web_dir = Path(__file__).parent.parent / "web"
    return send_from_directory(str(web_dir), "dashboard.html")


@app.route('/scan', methods=['POST'])
def trigger_scan():
    """Trigger a manual scan."""
    global _last_scan_result, _last_scan_time
    try:
        if _last_scan_result and _last_scan_time:
            age = (datetime.now() - _last_scan_time).total_seconds()
            if age < _SCAN_CACHE_SECONDS:
                return jsonify({**_last_scan_result, 'cached': True})

        logger.info("Starting sector analysis scan...")
        analyzer = SectorAnalyzer(db=Database())
        result = analyzer.analyze()
        report_path = ReportGenerator().generate_report(result)

        sectors_count = len(result['sectors'])
        total_stocks = sum(s.stock_count for s in result['sectors'])
        highlights = sum(len(s.highlights) for s in result['sectors'])

        response_data = {
            'status': 'success',
            'scan_date': datetime.now().strftime('%Y-%m-%d'),
            'scan_time': datetime.now().strftime('%H:%M:%S'),
            'regime': result['market'].regime,
            'sectors': sectors_count,
            'stocks': total_stocks,
            'highlights': highlights,
            'report_path': report_path
        }

        _last_scan_result = response_data
        _last_scan_time = datetime.now()
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status', methods=['GET'])
def get_status():
    """Get system status."""
    try:
        active_stocks = db.get_active_stocks()

        # Get last scan from DB
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT scan_date, scan_time, market_sentiment, total_stocks "
            "FROM scan_results ORDER BY id DESC LIMIT 1"
        )
        last_scan = cursor.fetchone()

        return jsonify({
            'status': 'ok',
            'active_stocks_count': len(active_stocks),
            'last_scan': {
                'date': last_scan[0] if last_scan else None,
                'time': last_scan[1] if last_scan else None,
                'sentiment': last_scan[2] if last_scan else None,
                'stocks_scanned': last_scan[3] if last_scan else None
            } if last_scan else None
        })

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stocks', methods=['GET'])
def list_stocks():
    """List all active stocks."""
    try:
        symbols = db.get_active_stocks()
        return jsonify({
            'count': len(symbols),
            'symbols': symbols
        })
    except Exception as e:
        logger.error(f"List stocks failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stocks/add', methods=['POST'])
def add_stock():
    """Add a stock to the universe."""
    try:
        data = request.get_json()
        if not data or 'symbol' not in data:
            return jsonify({'status': 'error', 'message': 'symbol required'}), 400

        symbol = data['symbol'].upper()

        # Validate symbol format
        if not validate_symbol(symbol):
            return jsonify({
                'status': 'error',
                'message': f'Invalid stock symbol format: {symbol}'
            }), 400

        name = data.get('name', '')
        sector = data.get('sector', '')

        db.add_stock(symbol, name, sector)

        return jsonify({
            'status': 'success',
            'symbol': symbol,
            'message': f'{symbol} added to universe'
        })

    except Exception as e:
        logger.error(f"Add stock failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stocks/remove', methods=['POST'])
def remove_stock():
    """Remove a stock from the universe."""
    try:
        data = request.get_json()
        if not data or 'symbol' not in data:
            return jsonify({'status': 'error', 'message': 'symbol required'}), 400

        symbol = data['symbol'].upper()

        # Validate symbol format
        if not validate_symbol(symbol):
            return jsonify({
                'status': 'error',
                'message': f'Invalid stock symbol format: {symbol}'
            }), 400

        # Soft delete by setting is_active = 0
        conn = db.get_connection()
        conn.execute(
            "UPDATE stocks SET is_active = 0 WHERE symbol = ?",
            (symbol,)
        )

        return jsonify({
            'status': 'success',
            'symbol': symbol,
            'message': f'{symbol} removed from universe'
        })

    except Exception as e:
        logger.error(f"Remove stock failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/history', methods=['GET'])
def get_history():
    """Get recent scan history."""
    try:
        n = request.args.get('n', 10, type=int)

        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT scan_date, scan_time, market_sentiment, "
            "total_stocks, report_path "
            "FROM scan_results "
            "ORDER BY id DESC LIMIT ?",
            (n,)
        )

        results = []
        for row in cursor.fetchall():
            results.append({
                'scan_date': row[0],
                'scan_time': row[1],
                'market_sentiment': row[2],
                'total_stocks': row[3],
                'report_path': row[4]
            })

        return jsonify({
            'count': len(results),
            'history': results
        })

    except Exception as e:
        logger.error(f"Get history failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/reports/<path:filename>')
def serve_report(filename):
    """Serve a report file."""
    from flask import send_from_directory
    return send_from_directory(REPORTS_DIR, filename)


@app.route('/data/charts/<path:filename>')
def serve_chart(filename):
    """Serve a chart file."""
    from flask import send_from_directory
    return send_from_directory(CHARTS_DIR, filename)


@app.route('/reports', methods=['GET'])
def list_reports():
    """List available reports."""
    try:
        reports = []

        for report_file in sorted(REPORTS_DIR.glob('report_*.html'), reverse=True):
            stat = report_file.stat()
            reports.append({
                'filename': report_file.name,
                'date': report_file.name.replace('report_', '').replace('.html', ''),
                'size': stat.st_size,
                'url': f'/reports/{report_file.name}'
            })

        return jsonify({
            'count': len(reports),
            'reports': reports
        })

    except Exception as e:
        logger.error(f"List reports failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/scan/status', methods=['GET'])
def scan_status():
    """Return last scan status."""
    try:
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT run_date, status, total_duration, symbols_count, candidates_count "
            "FROM workflow_status ORDER BY run_date DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'last_scan': None})
        return jsonify({'last_scan': {
            'date': row[0], 'status': row[1], 'duration': row[2],
            'stocks': row[3], 'candidates': row[4]
        }})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def run_server(host='0.0.0.0', port=None):
    """Run the Flask server."""
    port = port or settings.get('report', {}).get('web_port', 8080)
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"Starting API server on {host}:{port}")
    app.run(host=host, port=port, debug=debug_mode, threaded=True)

if __name__ == '__main__':
    run_server()
