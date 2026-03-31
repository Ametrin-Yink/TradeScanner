#!/usr/bin/env python3
"""Update market data for all active stocks - incremental fetch."""
import sys
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fetcher import DataFetcher
from data.db import Database

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def update_all_market_data():
    """Fetch incremental market data for all active stocks."""
    db = Database()
    fetcher = DataFetcher(db=db)

    # Get all active stocks
    symbols = db.get_active_stocks()
    logger.info(f"Updating market data for {len(symbols)} stocks...")

    # Fetch data (incremental - only new dates)
    start_time = datetime.now()
    results = fetcher.download_batch(symbols, use_cache=True)

    elapsed = (datetime.now() - start_time).total_seconds()

    logger.info(f"Update complete!")
    logger.info(f"  Successfully fetched: {len(results)} stocks")
    logger.info(f"  Failed: {len(symbols) - len(results)} stocks")
    logger.info(f"  Time: {elapsed:.1f}s")

    return len(results), len(symbols) - len(results)

if __name__ == "__main__":
    success, failed = update_all_market_data()
    print(f"\n✅ Updated: {success} stocks")
    if failed > 0:
        print(f"❌ Failed: {failed} stocks")
