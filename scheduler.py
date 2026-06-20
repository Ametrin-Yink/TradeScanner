"""Daily sector analysis scheduler."""
import argparse
import logging
import sys
from datetime import datetime

from config.settings import settings
from data.db import Database
from core.sector_analyzer import SectorAnalyzer
from core.reporter import ReportGenerator
from core.simulation_engine import SimulationEngine
from core.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# NYSE 2026 holidays (market closed)
HOLIDAYS_2026 = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
    '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
    '2026-11-26', '2026-12-25',
}


def is_trading_day() -> bool:
    """Check if today is a US trading day."""
    today = datetime.now().strftime('%Y-%m-%d')
    if today in HOLIDAYS_2026:
        logger.info(f"Today is a holiday - not a trading day")
        return False
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
        analyzer = SectorAnalyzer(db=Database())
        result = analyzer.analyze()
        report_path = ReportGenerator().generate_report(result)

        sectors_count = len(result['sectors'])
        total_stocks = sum(s.stock_count for s in result['sectors'])
        highlights = sum(len(s.highlights) for s in result['sectors'])

        # Simulation auto-select
        try:
            engine = SimulationEngine(Database())
            all_highlights = []
            for sector in result['sectors']:
                for h in sector.highlights:
                    h.primary_tag = sector.name
                    all_highlights.append(h)
            engine.auto_select(all_highlights, run_date)
            engine.daily_check()
        except Exception as e:
            logger.warning(f"Simulation step failed (non-fatal): {e}")

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


def main():
    parser = argparse.ArgumentParser(description='Trade Scanner - Sector Analysis')
    parser.add_argument('--test', action='store_true', help='Run test scan')
    parser.add_argument('--symbols', type=str, help='Comma-separated test symbols')
    parser.add_argument('--force', action='store_true', help='Skip trading day check')
    parser.add_argument('--server', action='store_true', help='Start API server')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    if args.test:
        symbols = args.symbols.split(',') if args.symbols else None
        report_path = run_sector_scan(test_symbols=symbols)
    else:
        report_path = run_sector_scan()

    if report_path:
        print(f"\nScan complete! Report: {report_path}")
    else:
        print("\nScan failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
