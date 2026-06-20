"""Simulated trade tracking and feedback loop."""
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from data.db import Database

logger = logging.getLogger(__name__)

HORIZON_DAYS = {
    'Swing (5-20d)': 20,
    'Position (10-40d)': 40,
    'swing': 20,
    'position': 40,
}


class SimulationEngine:
    def __init__(self, db: Database):
        self.db = db

    def auto_select(self, highlights: List, report_date: str):
        """Select top 5 unique picks, skip already-open symbols."""
        conn = self.db.get_connection()
        open_symbols = set(
            row[0] for row in conn.execute(
                "SELECT symbol FROM simulation_positions WHERE outcome = 'open'"
            ).fetchall()
        )

        selected = []
        for h in sorted(highlights, key=lambda x: x.rr, reverse=True):
            if h.symbol in open_symbols:
                continue
            if h.symbol in {s.symbol for s in selected}:
                continue
            selected.append(h)
            if len(selected) >= 5:
                break

        for h in selected:
            horizon_str = getattr(h, 'time_horizon', 'Swing (5-20d)')
            horizon_days = HORIZON_DAYS.get(horizon_str, 20)
            size = getattr(h, 'position_size', 0)
            risk = getattr(h, 'risk_dollars', 0)

            conn.execute("""
                INSERT INTO simulation_positions
                (opened_date, symbol, tag, reason, entry_price, stop_price,
                 target_price, rr_ratio, position_size_shares, risk_dollars,
                 time_horizon_days, report_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_date, h.symbol, getattr(h, 'primary_tag', ''),
                h.reason, h.entry, h.stop, h.target, h.rr,
                size, risk, horizon_days, report_date
            ))
        conn.commit()
        logger.info("Auto-selected %d new simulation positions", len(selected))
        return selected

    def daily_check(self):
        """Check all open positions against current prices."""
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        open_positions = conn.execute(
            "SELECT * FROM simulation_positions WHERE outcome = 'open'"
        ).fetchall()

        updated = 0
        for pos in open_positions:
            pos = dict(pos)
            cache = self.db.get_tier1_cache(pos['symbol'])
            if not cache or not cache.get('current_price'):
                continue

            current_price = cache['current_price']
            days_open = (datetime.now() - datetime.strptime(pos['opened_date'], '%Y-%m-%d')).days

            outcome = None
            close_price = current_price

            # Check stop hit (use daily low if available, else current)
            low_price = cache.get('low_60d')
            if low_price and low_price <= pos['stop_price']:
                outcome = 'loss'
                close_price = pos['stop_price']
            # Check target hit
            elif cache.get('high_60d') and cache['high_60d'] >= pos['target_price']:
                outcome = 'win'
                close_price = pos['target_price']
            # Check expiry
            elif days_open > pos['time_horizon_days']:
                outcome = 'expired'

            if outcome:
                pnl_dollars = (close_price - pos['entry_price']) * pos['position_size_shares']
                pnl_r = (close_price - pos['entry_price']) / (pos['entry_price'] - pos['stop_price']) if pos['stop_price'] else 0

                conn.execute("""
                    UPDATE simulation_positions
                    SET close_date = ?, close_price = ?, outcome = ?,
                        pnl_dollars = ?, pnl_r = ?
                    WHERE id = ?
                """, (
                    datetime.now().strftime('%Y-%m-%d'),
                    close_price, outcome, round(pnl_dollars, 2), round(pnl_r, 2),
                    pos['id']
                ))
                updated += 1

        if updated:
            conn.commit()
            logger.info("Closed %d simulation positions", updated)

    def get_summary(self) -> Dict:
        """Return aggregate stats for the simulation tab."""
        conn = self.db.get_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM simulation_positions WHERE outcome != 'open'"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM simulation_positions WHERE outcome = 'win'"
        ).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM simulation_positions WHERE outcome = 'loss'"
        ).fetchone()[0]
        expired = conn.execute(
            "SELECT COUNT(*) FROM simulation_positions WHERE outcome = 'expired'"
        ).fetchone()[0]

        avg_r = conn.execute(
            "SELECT AVG(pnl_r) FROM simulation_positions WHERE outcome != 'open' AND pnl_r IS NOT NULL"
        ).fetchone()[0]

        gross_wins = conn.execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM simulation_positions WHERE pnl_dollars > 0"
        ).fetchone()[0]
        gross_losses = conn.execute(
            "SELECT COALESCE(SUM(ABS(pnl_dollars)), 0) FROM simulation_positions WHERE pnl_dollars < 0"
        ).fetchone()[0]

        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        win_rate = (wins / total * 100) if total > 0 else 0
        expectancy = avg_r or 0

        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'expired': expired,
            'win_rate': round(win_rate, 1),
            'avg_r': round(avg_r, 2) if avg_r else 0.0,
            'profit_factor': round(profit_factor, 2),
            'expectancy': round(expectancy, 2),
        }

    def get_active_positions(self) -> List[Dict]:
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM simulation_positions WHERE outcome = 'open' ORDER BY opened_date DESC"
        ).fetchall()
        results = []
        for row in rows:
            row = dict(row)
            cache = self.db.get_tier1_cache(row['symbol'])
            current_price = cache.get('current_price') if cache else None
            pnl = ((current_price - row['entry_price']) / row['entry_price'] * 100) if current_price else None
            risk = row['entry_price'] - row['stop_price']
            progress = ((current_price - row['entry_price']) / (row['target_price'] - row['entry_price']) * 100) if current_price and risk > 0 else 0
            results.append({
                **row,
                'current_price': current_price,
                'pnl_pct': round(pnl, 2) if pnl else None,
                'progress': round(max(0, min(100, progress)), 0),
                'days_open': (datetime.now() - datetime.strptime(row['opened_date'], '%Y-%m-%d')).days,
            })
        return results

    def get_closed_positions(self, outcome_filter: str = 'all') -> List[Dict]:
        conn = self.db.get_connection()
        conn.row_factory = sqlite3.Row
        if outcome_filter and outcome_filter != 'all':
            rows = conn.execute(
                "SELECT * FROM simulation_positions WHERE outcome = ? ORDER BY close_date DESC",
                (outcome_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM simulation_positions WHERE outcome != 'open' ORDER BY close_date DESC"
            ).fetchall()
        return [dict(r) for r in rows]
