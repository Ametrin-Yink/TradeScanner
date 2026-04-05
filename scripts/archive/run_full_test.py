#!/usr/bin/env python3
"""Run full test with DEBUG logging to see filter diagnostics."""
import logging
import sys
from datetime import datetime

# Configure DEBUG logging before anything else
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/full_test_debug.log', mode='w')
    ]
)

from scheduler import CompleteScanner

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("=" * 70)
    logger.info("STARTING FULL TEST WITH ALL STOCKS")
    logger.info("=" * 70)
    logger.info(f"Start time: {datetime.now()}")

    scanner = CompleteScanner()

    # Run complete workflow with all stocks
    report_path = scanner.run_complete_workflow(skip_market_hours_check=True)

    if report_path:
        logger.info("=" * 70)
        logger.info(f"✅ WORKFLOW COMPLETE!")
        logger.info(f"📄 Report: {report_path}")
        logger.info("=" * 70)
        print(f"\n✅ Workflow complete!")
        print(f"📄 Report: {report_path}")
    else:
        logger.error("❌ WORKFLOW FAILED")
        print("\n❌ Workflow failed")
        sys.exit(1)
