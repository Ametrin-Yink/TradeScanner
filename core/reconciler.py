"""Daily recommendation reconciliation and performance tracking."""
import logging
from datetime import datetime, date
from data.db import Database

logger = logging.getLogger(__name__)


def reconcile_recommendations(db: Database):
    """Check all active recommendations against current prices."""
    active = db.get_active_recommendations()
    today = date.today()
    resolved = 0

    for rec in active:
        cache = db.get_tier1_cache(rec['symbol'])
        if not cache or not cache.get('current_price'):
            continue

        price = cache['current_price']
        trade_date = datetime.strptime(rec['trade_date'], '%Y-%m-%d').date()
        days_open = (today - trade_date).days

        # Stop hit
        if price <= rec['stop_price']:
            pnl_pct = (rec['stop_price'] - rec['entry_price']) / rec['entry_price'] * 100
            db.resolve_recommendation(rec['id'], 'stopped_out', 'loss', round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: stopped out, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

        # Target hit
        elif price >= rec['target_price']:
            pnl_pct = (rec['target_price'] - rec['entry_price']) / rec['entry_price'] * 100
            db.resolve_recommendation(rec['id'], 'target_hit', 'win', round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: target hit, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

        # Expired
        elif days_open >= rec['max_days']:
            pnl_pct = (price - rec['entry_price']) / rec['entry_price'] * 100
            outcome = 'win' if pnl_pct > 0 else 'loss'
            db.resolve_recommendation(rec['id'], 'expired', outcome, round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: expired, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

    logger.info(f"Reconciliation: {resolved} resolved, {len(active) - resolved} still active")
    return resolved


def generate_performance_summary(db: Database, lookback_days: int = 30):
    """Generate performance metrics from resolved recommendations."""
    resolved = db.get_resolved_recommendations(lookback_days)

    if not resolved:
        return {'total_trades': 0, 'note': 'No resolved trades in lookback period'}

    wins = [r for r in resolved if r['outcome'] == 'win']
    losses = [r for r in resolved if r['outcome'] == 'loss']

    total_pnl = sum(r['pnl_pct'] for r in wins) + sum(r['pnl_pct'] for r in losses)

    # By sector
    by_sector = {}
    for r in resolved:
        sec = r['sector']
        if sec not in by_sector:
            by_sector[sec] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
        if r['outcome'] == 'win':
            by_sector[sec]['wins'] += 1
        else:
            by_sector[sec]['losses'] += 1
        by_sector[sec]['total_pnl'] += r['pnl_pct']

    # By setup type
    by_setup = {}
    for r in resolved:
        st = r['setup_type']
        if st not in by_setup:
            by_setup[st] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
        if r['outcome'] == 'win':
            by_setup[st]['wins'] += 1
        else:
            by_setup[st]['losses'] += 1
        by_setup[st]['total_pnl'] += r['pnl_pct']

    return {
        'total_trades': len(resolved),
        'win_rate': round(len(wins) / len(resolved) * 100, 1) if resolved else 0,
        'avg_win_pct': round(sum(w['pnl_pct'] for w in wins) / len(wins), 2) if wins else 0,
        'avg_loss_pct': round(sum(l['pnl_pct'] for l in losses) / len(losses), 2) if losses else 0,
        'total_pnl_pct': round(total_pnl, 2),
        'profit_factor': round(
            abs(sum(w['pnl_pct'] for w in wins) / sum(l['pnl_pct'] for l in losses)), 2
        ) if losses and sum(l['pnl_pct'] for l in losses) != 0 else None,
        'by_sector': {s: {'win_rate': round(d['wins']/(d['wins']+d['losses'])*100, 1),
                          'pnl': round(d['total_pnl'], 2)}
                      for s, d in by_sector.items()},
        'by_setup': {s: {'win_rate': round(d['wins']/(d['wins']+d['losses'])*100, 1),
                         'pnl': round(d['total_pnl'], 2)}
                     for s, d in by_setup.items()},
    }
