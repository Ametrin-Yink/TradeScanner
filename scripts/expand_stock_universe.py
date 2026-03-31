#!/usr/bin/env python3
"""Expand stock universe using finvizfinance - market cap > $2B."""
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finvizfinance.screener.overview import Overview
from data.db import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_large_cap_stocks():
    """Fetch all stocks with market cap > $2B from Finviz."""
    overview = Overview()

    logger.info("Fetching stocks with market cap > $2B...")

    # Use '+Mid (over $2bln)' to get all stocks > $2B
    overview.set_filter(filters_dict={'Market Cap.': '+Mid (over $2bln)'})
    df = overview.screener_view()


    tickers = df['Ticker'].tolist()
    logger.info(f"Found {len(tickers)} stocks with market cap > $2B")

    return tickers

def expand_universe():
    """Add large cap stocks to database."""
    db = Database()

    # Get current universe
    current = db.get_active_stocks()
    current_set = set(current)
    logger.info(f"Current universe: {len(current_set)} stocks")

    # Fetch from Finviz
    new_tickers = get_large_cap_stocks()
    new_set = set(new_tickers)

    # Find additions
    to_add = new_set - current_set
    logger.info(f"New stocks to add: {len(to_add)}")

    # Add to database
    added = 0
    for ticker in sorted(to_add):
        try:
            db.add_stock(ticker)
            added += 1
            if added % 100 == 0:
                logger.info(f"Added {added}/{len(to_add)}...")
        except Exception as e:
            logger.warning(f"Failed to add {ticker}: {e}")
            continue

    logger.info(f"✓ Added {added} new stocks")

    logger.info(f"✓ Total universe now: {len(current_set) + added}")

if __name__ == "__main__":
    expand_universe()
