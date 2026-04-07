#!/usr/bin/env python3
"""
Standalone Phase 0 runner for process isolation.

This script runs Phase 0 data preparation as a separate process,
writes all results to database, and exits cleanly to release memory.

Usage:
    python3 -m core.phase0_runner

The main scanner process should run this as a subprocess, then
read results from the database with fresh memory.
"""
import sys
import os
import logging
import json
from datetime import datetime
from typing import Dict, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.db import Database
from core.premarket_prep import PreMarketPrep
from core.stock_universe import StockUniverseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_phase0_standalone() -> Dict:
    """
    Run Phase 0 as standalone process.

    Returns dict with:
        - success: bool
        - symbols_count: int - number of stocks for screening
        - etfs_count: int - number of market ETFs
        - tier1_count: int - number of Tier 1 cache entries
        - duration: int - execution time in seconds
        - error: str or None
    """
    start_time = datetime.now()
    db = Database()

    logger.info("=" * 60)
    logger.info("PHASE 0 RUNNER: Standalone Process")
    logger.info("=" * 60)

    try:
        prep = PreMarketPrep(db=db)

        # Run Phase 0 - this will:
        # 1. Initialize stock database
        # 2. Fetch Tier 3 market data (cached in DB)
        # 3. Update market data for all symbols (cached in DB)
        # 4. Apply pre-filter (market cap >=$2B)
        # 5. Calculate Tier 1 universal metrics (cached in DB)
        # 6. Update RS percentiles (cached in DB)
        # 7. Pre-calculate ETF data (cached in DB)
        result = prep.run_phase0()

        duration = (datetime.now() - start_time).total_seconds()

        if result['success']:
            logger.info("=" * 60)
            logger.info(f"PHASE 0 COMPLETE in {duration:.1f}s")
            logger.info(f"  Symbols for screening: {len(result['symbols'])}")
            logger.info(f"  Tier 1 cache entries: {result['tier1_cache_count']}")
            logger.info("=" * 60)

            return {
                'success': True,
                'symbols_count': len(result['symbols']),
                'etfs_count': len(result['etfs']),
                'tier1_count': result['tier1_cache_count'],
                'duration': int(duration),
                'error': None
            }
        else:
            logger.error("Phase 0 failed - no qualifying stocks or Tier 1 cache")
            return {
                'success': False,
                'symbols_count': 0,
                'symbols': [],
                'etfs_count': 0,
                'tier1_count': 0,
                'duration': int(duration),
                'error': 'Phase 0 failed - no qualifying stocks'
            }

    except Exception as e:
        logger.exception(f"Phase 0 runner failed: {e}")
        return {
            'success': False,
            'symbols_count': 0,
            'symbols': [],
            'etfs_count': 0,
            'tier1_count': 0,
            'duration': int((datetime.now() - start_time).total_seconds()),
            'error': str(e)
        }


def main():
    """Main entry point for standalone Phase 0 runner."""
    result = run_phase0_standalone()

    # Output result as JSON for parent process to parse
    print("\n=== PHASE0_RESULT_START ===")
    print(json.dumps(result))
    print("=== PHASE0_RESULT_END ===")

    # Exit with appropriate code
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
