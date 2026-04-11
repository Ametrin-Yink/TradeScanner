#!/usr/bin/env python3
"""Standalone Phase 0 runner for process isolation.

Runs Phase 0 data preparation as a separate process,
writes all results to database, and exits cleanly to release memory.

Usage:
    python3 scripts/run_phase0.py

The main scanner process should run this as a subprocess, then
read results from the database with fresh memory.
"""
import sys
import os
import logging
import json
from datetime import datetime
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.db import Database
from core.premarket_prep import PreMarketPrep

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_phase0_standalone() -> Dict:
    start_time = datetime.now()
    db = Database()

    logger.info("=" * 60)
    logger.info("PHASE 0 RUNNER: Standalone Process")
    logger.info("=" * 60)

    try:
        prep = PreMarketPrep(db=db)
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
                'error': None,
            }
        else:
            logger.error("Phase 0 failed - no qualifying stocks or Tier 1 cache")
            return {
                'success': False,
                'symbols_count': 0, 'symbols': [],
                'etfs_count': 0, 'tier1_count': 0,
                'duration': int(duration),
                'error': 'Phase 0 failed - no qualifying stocks',
            }

    except Exception as e:
        logger.exception(f"Phase 0 runner failed: {e}")
        return {
            'success': False,
            'symbols_count': 0, 'symbols': [],
            'etfs_count': 0, 'tier1_count': 0,
            'duration': int((datetime.now() - start_time).total_seconds()),
            'error': str(e),
        }


def main():
    result = run_phase0_standalone()

    print("\n=== PHASE0_RESULT_START ===")
    print(json.dumps(result))
    print("=== PHASE0_RESULT_END ===")

    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
