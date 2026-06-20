"""Configuration API Blueprint for TradeScanner."""
import logging
import os
import yaml
from pathlib import Path
from flask import Blueprint, jsonify, request

from core.tag_manager import TagManager
from data.db import Database

logger = logging.getLogger(__name__)

config_api = Blueprint('config_api', __name__)
db = Database()
CONFIG_DIR = Path(__file__).parent.parent / "config"
STRATEGY_CONFIG_PATH = CONFIG_DIR / "strategy_config.yaml"


@config_api.before_request
def check_auth():
    api_key = os.getenv('API_KEY', 'Ametrin+1')
    if not api_key:
        return
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {api_key}':
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401


@config_api.route('/api/config/sectors', methods=['GET'])
def get_sectors():
    """Return all sectors with ETF mapping and stock counts."""
    try:
        manager = TagManager()
        sectors = manager.get_tags(db)
        unique = len(manager.get_pipeline_stocks(None, db))
        # Add daily change per sector
        for s in sectors:
            s['daily_change'] = manager.get_tag_daily_change(s['name'], db)
        # Sort by daily change descending
        sectors.sort(key=lambda s: s.get('daily_change') or float('-inf'), reverse=True)
        return jsonify({'sectors': sectors, 'total_stocks_assigned': unique})
    except Exception as e:
        logger.error(f"Get sectors failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/sectors', methods=['POST'])
def add_sector():
    """Add a new sector."""
    try:
        data = request.get_json()
        if not data or not data.get('name', '').strip():
            return jsonify({'status': 'error', 'message': 'Sector name is required'}), 400
        name = data['name'].strip()
        etf = data.get('etf', '').strip()
        manager = TagManager()
        manager.add_tag(name, etf, db)
        return jsonify({'status': 'success', 'sector': {'name': name, 'etf': etf}})
    except Exception as e:
        logger.error(f"Add sector failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/sectors/<name>', methods=['DELETE'])
def delete_sector(name):
    """Remove a sector and all its stock assignments."""
    try:
        manager = TagManager()
        manager.remove_tag(name, db)
        return jsonify({'status': 'success', 'message': f"Sector '{name}' removed"})
    except Exception as e:
        logger.error(f"Delete sector failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/sectors/<name>/stocks', methods=['GET'])
def get_sector_stocks(name):
    """Return stocks assigned to a sector."""
    try:
        manager = TagManager()
        stocks = manager.get_tag_stocks(name, db)
        return jsonify({'sector': name, 'stocks': stocks, 'count': len(stocks)})
    except Exception as e:
        logger.error(f"Get sector stocks failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/sectors/<name>/stocks', methods=['POST'])
def add_sector_stock(name):
    """Assign a stock to a sector."""
    try:
        data = request.get_json()
        if not data or not data.get('symbol', '').strip():
            return jsonify({'status': 'error', 'message': 'Stock symbol is required'}), 400
        symbol = data['symbol'].strip().upper()
        if not symbol.isalnum():
            return jsonify({'status': 'error', 'message': 'Invalid stock symbol'}), 400
        manager = TagManager()
        manager.add_stock_to_tag(symbol, name, db)
        return jsonify({'status': 'success', 'symbol': symbol, 'sector': name})
    except Exception as e:
        logger.error(f"Add sector stock failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/sectors/<name>/stocks/<symbol>', methods=['DELETE'])
def delete_sector_stock(name, symbol):
    """Remove a stock from a sector."""
    try:
        manager = TagManager()
        manager.remove_stock_from_tag(symbol.upper(), name, db)
        return jsonify({'status': 'success', 'message': f"{symbol.upper()} removed from '{name}'"})
    except Exception as e:
        logger.error(f"Delete sector stock failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/stocks/search', methods=['GET'])
def search_stocks():
    """Search stocks by symbol or name."""
    try:
        q = request.args.get('q', '').strip()
        if not q:
            return jsonify({'results': []})
        manager = TagManager()
        results = manager.search_stocks(q, db, limit=20)
        return jsonify({'results': results})
    except Exception as e:
        logger.error(f"Search stocks failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/stocks/unassigned', methods=['GET'])
def get_unassigned_stocks():
    """Return stocks with no sector assignment."""
    try:
        manager = TagManager()
        stocks = manager.get_unassigned_stocks(db, limit=100)
        return jsonify({'stocks': stocks})
    except Exception as e:
        logger.error(f"Get unassigned stocks failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/seed', methods=['POST'])
def seed_sectors():
    """Seed sector assignments from CSV."""
    try:
        manager = TagManager()
        result = manager.seed_from_csv(db)
        return jsonify({'status': 'success', 'added': result['added'], 'tags': result['tags']})
    except Exception as e:
        logger.error(f"Seed sectors failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/strategies', methods=['GET'])
def get_strategies():
    """Return strategy configuration from YAML."""
    try:
        if not STRATEGY_CONFIG_PATH.exists():
            return jsonify({'strategies': {}})
        with open(STRATEGY_CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        return jsonify({'strategies': data})
    except Exception as e:
        logger.error(f"Get strategies failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@config_api.route('/api/config/strategies', methods=['PUT'])
def update_strategies():
    """Save strategy configuration to YAML."""
    try:
        data = request.get_json()
        if not data or 'strategies' not in data:
            return jsonify({'status': 'error', 'message': 'strategies object required'}), 400
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(STRATEGY_CONFIG_PATH, 'w') as f:
            yaml.dump(data['strategies'], f, default_flow_style=False, sort_keys=False)
        return jsonify({'status': 'success', 'message': 'Strategy config saved'})
    except Exception as e:
        logger.error(f"Update strategies failed: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
