"""Flask API server for trade scanner."""
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
from core.screener import StrategyScreener
from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_symbol(symbol: str) -> bool:
    """Validate stock symbol format."""
    if not symbol or len(symbol) > 10:
        return False
    return bool(re.match(r'^[A-Z0-9.]{1,10}$', symbol))


app = Flask(__name__)
db = Database()
fetcher = DataFetcher(db=db)


@app.route('/')
def index():
    """Root endpoint."""
    return jsonify({
        'service': 'Trade Scanner API',
        'version': '1.0.0',
        'status': 'running'
    })


@app.route('/scan', methods=['POST'])
def trigger_scan():
    """Trigger a manual scan."""
    try:
        data = request.get_json() or {}
        mode = data.get('mode', 'full')  # quick, full
        symbols = data.get('symbols')

        if symbols:
            # Validate all symbols
            invalid_symbols = [s for s in symbols if not validate_symbol(s)]
            if invalid_symbols:
                return jsonify({
                    'status': 'error',
                    'message': f'Invalid stock symbols: {invalid_symbols}'
                }), 400
        else:
            symbols = db.get_active_stocks()

        # Run scan pipeline
        screener = StrategyScreener(fetcher=fetcher, db=db)
        market_analyzer = MarketAnalyzer()
        selector = CandidateSelector()
        opportunity_analyzer = OpportunityAnalyzer(fetcher=fetcher)
        reporter = ReportGenerator(fetcher=fetcher)

        # Step 1: Market sentiment
        logger.info("Analyzing market sentiment...")
        sentiment_result = market_analyzer.analyze_sentiment()
        market_sentiment = sentiment_result.get('sentiment', 'neutral')

        # Step 2: Screen all symbols
        logger.info(f"Screening {len(symbols)} symbols...")
        candidates = screener.screen_all(symbols)

        # Step 3: Select top 30
        logger.info("Selecting top 30...")
        top_30 = selector.select_top_30(candidates, market_sentiment)

        # Step 4: Deep analysis
        logger.info("Analyzing opportunities...")
        analyzed = opportunity_analyzer.analyze_all(top_30, market_sentiment)

        # Step 5: Generate report
        logger.info("Generating report...")
        fail_symbols = []  # Track failed symbols during fetch
        report_path = reporter.generate_report(
            opportunities=analyzed,
            market_sentiment=market_sentiment,
            total_stocks=len(symbols),
            success_count=len(symbols),  # Simplified
            fail_count=len(fail_symbols),
            fail_symbols=fail_symbols
        )

        # Save scan result to DB
        from data.db import Database
        db_save = Database()
        scan_result = {
            'scan_date': datetime.now().strftime('%Y-%m-%d'),
            'scan_time': datetime.now().strftime('%H:%M:%S'),
            'market_sentiment': market_sentiment,
            'top_opportunities': [{
                'symbol': o.symbol,
                'strategy': o.strategy,
                'entry_price': o.entry_price,
                'stop_loss': o.stop_loss,
                'take_profit': o.take_profit,
                'confidence': o.confidence
            } for o in analyzed[:10]],
            'all_candidates': [{
                'symbol': o.symbol,
                'strategy': o.strategy,
                'confidence': o.confidence
            } for o in analyzed],
            'total_stocks': len(symbols),
            'success_count': len(symbols),
            'fail_count': 0,
            'fail_symbols': [],
            'report_path': report_path
        }
        db_save.save_scan_result(scan_result)

        return jsonify({
            'status': 'success',
            'scan_date': scan_result['scan_date'],
            'scan_time': scan_result['scan_time'],
            'market_sentiment': market_sentiment,
            'candidates_found': len(candidates),
            'top_10_count': len(analyzed),
            'report_path': report_path
        })

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

def run_server(host='0.0.0.0', port=None):
    """Run the Flask server."""
    port = port or settings.get('report', {}).get('web_port', 8080)
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"Starting API server on {host}:{port}")
    app.run(host=host, port=port, debug=debug_mode)

if __name__ == '__main__':
    run_server()
