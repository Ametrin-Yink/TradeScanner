"""Forward-return validation for resolved recommendations.

Read-only: looks up what actually happened in the market after each
recommendation was issued. Used to calibrate setup bonuses and scoring weights.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_forward_returns(db, lookback_days: int = 90) -> List[Dict]:
    """Compute forward returns for resolved recommendations.

    For each resolved trade, look up:
    - forward_5d: price 5 trading days after trade_date
    - forward_10d: price 10 trading days after trade_date
    - forward_20d: price 20 trading days after trade_date
    - hit_stop_first: True if low touched stop before target
    - hit_target_first: True if high touched target before stop

    Returns list of dicts with forward return data.
    """
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    conn = db.get_connection()
    rows = conn.execute(
        "SELECT id, trade_date, symbol, entry_price, stop_price, target_price, "
        "setup_type, sector, status, outcome "
        "FROM recommendations "
        "WHERE status != 'active' AND trade_date >= ? "
        "ORDER BY trade_date",
        (cutoff,)
    ).fetchall()

    results = []
    for row in rows:
        rid, trade_date, symbol, entry, stop, target, setup, sector, status, outcome = row
        result = {
            'id': rid,
            'trade_date': trade_date,
            'symbol': symbol,
            'entry_price': entry,
            'stop_price': stop,
            'target_price': target,
            'setup_type': setup,
            'sector': sector,
            'status': status,
            'outcome': outcome,
        }

        # Look up forward prices from market_data
        for days, key in [(5, 'forward_5d'), (10, 'forward_10d'), (20, 'forward_20d')]:
            end_date = (datetime.strptime(trade_date, '%Y-%m-%d') + timedelta(days=days)).strftime('%Y-%m-%d')
            fwd = conn.execute(
                "SELECT close, high, low FROM market_data "
                "WHERE symbol = ? AND date >= ? AND date <= ? "
                "ORDER BY date ASC",
                (symbol, trade_date, end_date)
            ).fetchall()

            if fwd:
                result[key] = round(fwd[-1][0], 2)  # last close
                # Check if stop or target was hit
                highs = [r[1] for r in fwd]
                lows = [r[2] for r in fwd]
                result[f'hit_target_{days}d'] = any(h >= target for h in highs) if target else False
                result[f'hit_stop_{days}d'] = any(l <= stop for l in lows) if stop else False
            else:
                result[key] = None
                result[f'hit_target_{days}d'] = False
                result[f'hit_stop_{days}d'] = False

        results.append(result)

    return results
