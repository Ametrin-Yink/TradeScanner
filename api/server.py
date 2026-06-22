"""Flask API server for trade scanner."""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request

import os
from functools import wraps
from config.settings import settings, REPORTS_DIR, CHARTS_DIR
from data.db import Database
from core.sector_analyzer import SectorAnalyzer
from core.reporter import ReportGenerator
from api.config_api import config_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_last_scan_result = None
_last_scan_time = None
_SCAN_CACHE_SECONDS = 3600  # 1 hour

API_KEY = os.getenv('API_KEY', 'Ametrin+1')


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {API_KEY}':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


def validate_symbol(symbol: str) -> bool:
    """Validate stock symbol format."""
    if not symbol or len(symbol) > 10:
        return False
    return bool(re.match(r'^[A-Z0-9.]{1,10}$', symbol))


app = Flask(__name__, static_folder=None)
db = Database()
db._migrate_to_tags()
app.register_blueprint(config_api)


@app.route('/')
def index():
    """Root endpoint."""
    return jsonify({
        'service': 'Trade Scanner API',
        'version': '1.0.0',
        'status': 'running'
    })


@app.route('/api/config/auth-key', methods=['POST'])
def verify_auth_key():
    """Verify an API key. Returns {'valid': true} if correct."""
    try:
        data = request.get_json()
        if not data or 'key' not in data:
            return jsonify({'valid': False}), 400
        if data['key'] == API_KEY:
            return jsonify({'valid': True})
        return jsonify({'valid': False})
    except Exception:
        return jsonify({'valid': False}), 400


@app.route('/scan', methods=['POST'])
@require_auth
def trigger_scan():
    """Trigger a sector analysis scan."""
    global _last_scan_result, _last_scan_time
    try:
        data = request.get_json(silent=True) or {}

        # Check cache
        if _last_scan_result and _last_scan_time:
            age = (datetime.now() - _last_scan_time).total_seconds()
            if age < _SCAN_CACHE_SECONDS:
                return jsonify({**_last_scan_result, 'cached': True})

        logger.info("Starting sector analysis scan...")
        scan_db = Database()
        analyzer = SectorAnalyzer(db=Database())
        result = analyzer.analyze()
        report_path = ReportGenerator(db=scan_db).generate_report(result)

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
            'candidates_found': highlights,
            'report_path': report_path
        }

        _last_scan_result = response_data
        _last_scan_time = datetime.now()
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status', methods=['GET'])
@require_auth
def get_status():
    """Get system status."""
    try:
        active_stocks = db.get_active_stocks()

        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT run_date, status, total_duration, symbols_count, candidates_count "
            "FROM workflow_status ORDER BY run_date DESC LIMIT 1"
        )
        last_scan = cursor.fetchone()

        return jsonify({
            'status': 'ok',
            'active_stocks_count': len(active_stocks),
            'last_scan': {
                'date': last_scan[0] if last_scan else None,
                'status': last_scan[1] if last_scan else None,
                'duration': last_scan[2] if last_scan else None,
                'stocks': last_scan[3] if last_scan else None,
                'candidates': last_scan[4] if last_scan else None,
            } if last_scan else None
        })

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stocks', methods=['GET'])
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files from the web/ directory."""
    from flask import send_from_directory, current_app
    import os
    web_dir = Path(__file__).resolve().parent.parent / "web"
    return send_from_directory(str(web_dir), filename)


@app.route('/dashboard')
def dashboard():
    """Redirect to the dashboard SPA."""
    from flask import redirect
    return redirect('/static/dashboard.html')


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
@require_auth
def list_reports():
    """List available reports."""
    try:
        reports = []

        for report_file in sorted(REPORTS_DIR.glob('report_*.html'), reverse=True):
            stat = report_file.stat()
            date_str = report_file.name.replace('report_', '').replace('.html', '')
            # Get actual scan time from workflow_status, fall back to file mtime
            scan_time = None
            try:
                row = db.get_workflow_status(date_str)
                if row and row.get('start_time'):
                    scan_time = row['start_time'][:5]  # "HH:MM"
            except Exception:
                pass
            if not scan_time:
                scan_time = datetime.fromtimestamp(stat.st_mtime).strftime('%H:%M')
            reports.append({
                'filename': report_file.name,
                'date': f"{date_str}T{scan_time}:00",
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


# --- Config endpoints ---
import json
from pathlib import Path as _Path

CONFIG_FILE = _Path(__file__).parent.parent / "config" / "app_config.json"

def _load_app_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def _save_app_config(data):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/api/config/settings', methods=['GET'])
@require_auth
def get_settings():
    cfg = _load_app_config()
    return jsonify({'settings': {
        'scan_time': cfg.get('scan_time', '06:00'),
        'account_value': cfg.get('account_value', 50000),
        'risk_per_trade_pct': cfg.get('risk_per_trade_pct', 1.0),
        'ai_api_key': cfg.get('ai_api_key', ''),
        'ai_model': cfg.get('ai_model', 'deepseek-chat'),
    }})

@app.route('/api/config/settings', methods=['PUT'])
@require_auth
def update_settings():
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data'}), 400
    cfg = _load_app_config()
    cfg.update({k: v for k, v in data.items() if v is not None})
    _save_app_config(cfg)
    return jsonify({'status': 'ok'})


@app.route('/api/data/ohlc/<symbol>')
@require_auth
def get_ohlc(symbol):
    import json
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM market_data "
        "WHERE symbol = ? ORDER BY date DESC LIMIT 60",
        (symbol.upper(),)
    ).fetchall()
    data = [{'date': r[0], 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5]} for r in rows]
    data.reverse()
    cache = db.get_tier1_cache(symbol.upper())
    supports, resistances = [], []
    if cache:
        for key, target in [('supports', supports), ('resistances', resistances)]:
            val = cache.get(key)
            if val is None or val == '':
                continue
            if isinstance(val, (list, tuple)):
                target.extend(float(v) for v in val)
            elif isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        target.extend(float(v) for v in parsed)
                except (json.JSONDecodeError, TypeError):
                    pass
    return jsonify({'symbol': symbol.upper(), 'data': data, 'supports': supports, 'resistances': resistances})




def run_server(host='0.0.0.0', port=None):
    """Run the Flask server."""
    port = port or settings.get('report', {}).get('web_port', 8080)
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"Starting API server on {host}:{port}")
    app.run(host=host, port=port, debug=debug_mode, threaded=True)

if __name__ == '__main__':
    run_server()
