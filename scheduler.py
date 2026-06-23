"""Daily sector analysis scheduler."""
import argparse
import logging
import sys
from datetime import datetime

from config.settings import settings
from config.portfolio_config import load_config
from data.db import Database, detect_stale_stocks
from core.sector_analyzer import SectorAnalyzer
from core.reporter import ReportGenerator
from core.fetcher import validate_cache_freshness, fetch_all_pipeline_data
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def is_trading_day() -> bool:
    """Check if today is a US trading day using pandas_market_calendars."""
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar('NYSE')
        today = datetime.now().date()
        schedule = nyse.schedule(start_date=today, end_date=today)
        if schedule.empty:
            logger.info("No trading schedule today (holiday or weekend)")
            return False
        return True
    except ImportError:
        # Fallback: basic weekday check
        if datetime.now().weekday() >= 5:
            logger.info(f"Today is {datetime.now().strftime('%A')} - not a trading day")
            return False
        return True


def run_sector_scan(test_symbols=None):
    """Run the sector analysis scan and generate a report."""
    run_date = datetime.now().strftime('%Y-%m-%d')
    start = datetime.now()

    if test_symbols is None and not is_trading_day():
        logger.info("Not a trading day, skipping")
        return None

    db = Database()
    db.save_workflow_status({
        'run_date': run_date,
        'start_time': start.strftime('%H:%M:%S'),
        'status': 'running',
    })

    try:
        # Auto-fetch fresh data if configured
        pconfig = load_config()
        schedule_cfg = pconfig.get('schedule', {})
        if schedule_cfg.get('auto_fetch_before_scan', True):
            logger.info("Auto-fetching pipeline data before scan...")
            fetch_all_pipeline_data(db)
        else:
            # Abort if cache is stale — must run data fetch first
            try:
                validate_cache_freshness(db)
            except RuntimeError as e:
                logger.error(f"Aborting: {e}")
                db.save_workflow_status({
                    'run_date': run_date,
                    'status': 'aborted_stale_cache',
                    'error_message': str(e),
                })
                return None

        # Reconcile previous recommendations before new analysis
        from core.reconciler import reconcile_recommendations
        reconciled = reconcile_recommendations(db)
        logger.info(f"Reconciled {reconciled} prior recommendations")

        # Detect and deactivate stale stocks (flatlined price data)
        stale = detect_stale_stocks(db)
        for symbol in stale:
            with db.get_connection() as conn:
                conn.execute("UPDATE stocks SET is_active = 0 WHERE symbol = ?", (symbol,))
            logger.warning("Deactivated stale stock: %s", symbol)

        analyzer = SectorAnalyzer(db=db)
        result = analyzer.analyze()
        report_path = ReportGenerator(db=db).generate_report(result)

        sectors_count = len(result['sectors'])
        total_stocks = sum(s.stock_count for s in result['sectors'])
        highlights = sum(len(s.highlights) for s in result['sectors'])

        duration = (datetime.now() - start).total_seconds()
        db.save_workflow_status({
            'run_date': run_date,
            'status': 'completed',
            'total_duration': int(duration),
            'symbols_count': total_stocks,
            'candidates_count': highlights,
            'report_path': report_path,
        })

        logger.info(f"Scan complete in {duration:.0f}s — {sectors_count} sectors, {highlights} picks")
        return report_path

    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=True)
        db.save_workflow_status({
            'run_date': run_date,
            'status': 'failed',
            'error_message': str(e),
        })
        return None


def run_scheduled_loop():
    """Run daily: auto-fetch at configured time, then scan at configured time."""
    import time as time_mod
    pconfig = load_config()
    schedule_cfg = pconfig.get('schedule', {})
    fetch_time = schedule_cfg.get('data_fetch_time', '06:00')
    scan_time = schedule_cfg.get('scan_time', '07:00')

    logger.info(f"Scheduled: data fetch at {fetch_time}, scan at {scan_time} EST (NYSE days only)")

    while True:
        if is_trading_day():
            now = datetime.now()
            fetch_h, fetch_m = map(int, fetch_time.split(':'))
            scan_h, scan_m = map(int, scan_time.split(':'))

            fetch_dt = now.replace(hour=fetch_h, minute=fetch_m, second=0, microsecond=0)
            scan_dt = now.replace(hour=scan_h, minute=scan_m, second=0, microsecond=0)

            if now < fetch_dt:
                wait = (fetch_dt - now).total_seconds()
                logger.info(f"Waiting {wait/60:.0f}m until data fetch at {fetch_time}")
                time_mod.sleep(wait)

            if now < scan_dt:
                db = Database()
                logger.info(f"Running scheduled data fetch at {datetime.now().strftime('%H:%M')}")
                fetch_all_pipeline_data(db)

                wait = (scan_dt - datetime.now()).total_seconds()
                if wait > 0:
                    logger.info(f"Waiting {wait/60:.0f}m until scan at {scan_time}")
                    time_mod.sleep(wait)

                logger.info(f"Running scheduled scan at {datetime.now().strftime('%H:%M')}")
                run_sector_scan(test_symbols=[])

        # Sleep until next check (every 10 minutes)
        time_mod.sleep(600)


def main():
    parser = argparse.ArgumentParser(description='Trade Scanner - Sector Analysis')
    parser.add_argument('--test', action='store_true', help='Run test scan')
    parser.add_argument('--symbols', type=str, help='Comma-separated test symbols')
    parser.add_argument('--force', action='store_true', help='Skip trading day check')
    parser.add_argument('--server', action='store_true', help='Start API server')
    parser.add_argument('--schedule', action='store_true', help='Run daily auto-fetch+scan on schedule')
    parser.add_argument('--fetch-only', action='store_true', help='Run data fetch only (no scan)')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    if args.schedule:
        run_scheduled_loop()
        return

    if args.fetch_only:
        db = Database()
        fetch_all_pipeline_data(db)
        print("Data fetch complete.")
        return

    if args.test:
        symbols = args.symbols.split(',') if args.symbols else None
        report_path = run_sector_scan(test_symbols=symbols)
    elif args.force:
        report_path = run_sector_scan(test_symbols=[])  # empty list = skip trading day check
    else:
        report_path = run_sector_scan()

    if report_path:
        print(f"\nScan complete! Report: {report_path}")
    else:
        print("\nScan failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
