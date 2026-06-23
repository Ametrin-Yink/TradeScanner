"""Read-only evaluation harness for resolved trade recommendations.

CLAUDE.md constraint: NO live simulation. Only analyzes already-resolved
recommendations whose outcomes are known (target_hit, stopped_out, expired).
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def evaluate_recommendations(db, lookback_days: int = 90) -> Dict:
    """Evaluate resolved recommendations grouped by setup_type.

    Args:
        db: Database instance
        lookback_days: only consider trades resolved within this window

    Returns:
        Dict with: total_trades, win_rate, total_pnl_pct, profit_factor, by_setup
        Returns empty dict if no resolved trades found.
    """
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')

    conn = db.get_connection()
    rows = conn.execute(
        "SELECT symbol, sector, setup_type, entry_price, stop_price, "
        "target_price, rr, status, outcome, pnl_pct, resolved_date "
        "FROM recommendations "
        "WHERE status != 'active' AND resolved_date >= ? "
        "ORDER BY resolved_date DESC",
        (cutoff,)
    ).fetchall()

    if not rows:
        return {}

    resolved = []
    for r in rows:
        resolved.append({
            'symbol': r[0],
            'sector': r[1],
            'setup_type': r[2],
            'entry_price': r[3],
            'stop_price': r[4],
            'target_price': r[5],
            'rr': r[6],
            'status': r[7],
            'outcome': r[8],
            'pnl_pct': r[9] or 0.0,
            'resolved_date': r[10],
        })

    # Overall metrics
    total = len(resolved)
    wins = [t for t in resolved if (t['outcome'] or '').lower() == 'win']
    losses = [t for t in resolved if (t['outcome'] or '').lower() == 'loss']
    win_count = len(wins)
    total_pnl = sum(t['pnl_pct'] for t in resolved)

    # Profit factor: abs(sum wins) / abs(sum losses)
    sum_wins = abs(sum(t['pnl_pct'] for t in wins))
    sum_losses = abs(sum(t['pnl_pct'] for t in losses))
    profit_factor = round(sum_wins / sum_losses, 2) if sum_losses > 0 else None

    # By setup_type
    by_setup = {}
    for t in resolved:
        st = t['setup_type']
        if st not in by_setup:
            by_setup[st] = {'total': 0, 'wins': 0, 'losses': 0, 'pnl_sum': 0.0}
        by_setup[st]['total'] += 1
        by_setup[st]['pnl_sum'] += t['pnl_pct']
        if (t['outcome'] or '').lower() == 'win':
            by_setup[st]['wins'] += 1
        else:
            by_setup[st]['losses'] += 1

    for st, stats in by_setup.items():
        stats['win_rate'] = round(stats['wins'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0.0

    return {
        'total_trades': total,
        'win_rate': round(win_count / total * 100, 1) if total > 0 else 0.0,
        'total_pnl_pct': round(total_pnl, 2),
        'profit_factor': profit_factor,
        'by_setup': by_setup,
    }
