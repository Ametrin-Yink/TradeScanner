"""Generate weekly performance summary."""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.db import Database
from core.reconciler import generate_performance_summary


def main():
    db = Database()
    summary = generate_performance_summary(db, lookback_days=30)

    if summary.get('total_trades', 0) == 0:
        print("No resolved trades in last 30 days")
        return

    print(f"=== Weekly Performance Summary ({datetime.now().strftime('%Y-%m-%d')}) ===")
    print(f"Trades resolved (30d): {summary['total_trades']}")
    print(f"Win rate: {summary['win_rate']}%")
    print(f"Avg win: {summary['avg_win_pct']:+.1f}%")
    print(f"Avg loss: {summary['avg_loss_pct']:+.1f}%")
    print(f"Total P&L (30d): {summary['total_pnl_pct']:+.1f}%")
    if summary.get('profit_factor'):
        print(f"Profit factor: {summary['profit_factor']}")

    print("\nBy sector:")
    for sector, stats in sorted(summary.get('by_sector', {}).items(),
                                 key=lambda x: x[1]['pnl'], reverse=True):
        print(f"  {sector}: {stats['win_rate']}% win, {stats['pnl']:+.1f}% P&L")

    print("\nBy setup type:")
    for setup, stats in sorted(summary.get('by_setup', {}).items(),
                                key=lambda x: x[1]['pnl'], reverse=True):
        print(f"  {setup}: {stats['win_rate']}% win, {stats['pnl']:+.1f}% P&L")


if __name__ == '__main__':
    main()
