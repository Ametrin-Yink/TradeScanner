"""Cleanup after bulk fetch: retry earnings with secondary source, remove symbols without shares.

Steps:
1. Retry missing earnings using ticker.earnings_dates (secondary source)
2. Remove stocks without shares_outstanding (debt/preferred instruments)
3. Remove stocks that have 'No fundamentals data' from yfinance
"""
import gc
import logging
import random
import sys
import time
from datetime import datetime

import yfinance as yf

sys.path.insert(0, '.')
from data.db import Database
from core.stock_universe import StockUniverseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

REQUEST_DELAY = 1.0
DELAY_JITTER = 0.1
last_request_time = 0


def rate_limit():
    global last_request_time
    elapsed = time.time() - last_request_time
    delay = REQUEST_DELAY + random.uniform(-DELAY_JITTER, DELAY_JITTER)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    last_request_time = time.time()


def retry_missing_earnings(db: Database):
    """Use ticker.earnings_dates as secondary source for missing earnings."""
    missing = db.get_connection().execute(
        "SELECT symbol FROM stocks WHERE category = 'stocks' AND next_earnings_date IS NULL"
    ).fetchall()
    missing_symbols = [row[0] for row in missing]

    if not missing_symbols:
        logger.info("No missing earnings dates to retry")
        return 0

    logger.info(f"Retrying earnings for {len(missing_symbols)} stocks using secondary source...")

    today = datetime.now().date()
    success = 0
    failed = 0

    for i, symbol in enumerate(missing_symbols):
        rate_limit()
        found = False
        try:
            ticker = yf.Ticker(symbol)
            earnings_df = ticker.earnings_dates

            if earnings_df is not None and not earnings_df.empty:
                earnings_df = earnings_df.reset_index()
                # Find date column
                date_col = None
                for col in earnings_df.columns:
                    if 'date' in str(col).lower():
                        date_col = col
                        break

                if date_col:
                    for _, row in earnings_df.iterrows():
                        try:
                            date_val = row[date_col]
                            if hasattr(date_val, 'date'):
                                date_val = date_val.date()
                            elif isinstance(date_val, str):
                                date_val = datetime.fromisoformat(date_val).date()
                            if date_val >= today:
                                db.update_stock_earnings_date(symbol, date_val.isoformat())
                                found = True
                                break
                        except:
                            continue

        except Exception as e:
            logger.debug(f"  {symbol}: failed - {type(e).__name__}")

        if found:
            success += 1
        else:
            failed += 1

        if (i + 1) % 50 == 0:
            logger.info(f"  Progress: {i + 1}/{len(missing_symbols)}, {success} found, {failed} missing")
            gc.collect()

    logger.info(f"Earnings retry done: {success} found, {failed} still missing")
    return failed


def remove_symbols_without_shares(db: Database):
    """Remove stocks without shares_outstanding from the database.

    These are debt securities, preferred shares, or instruments that
    yfinance doesn't provide fundamentals data for.
    """
    # Find symbols to remove
    to_remove = db.get_connection().execute(
        "SELECT symbol, name FROM stocks WHERE category = 'stocks' AND shares_outstanding IS NULL"
    ).fetchall()

    if not to_remove:
        logger.info("All stocks have shares_outstanding data")
        return

    logger.info(f"Removing {len(to_remove)} symbols without shares data:")
    for sym, name in to_remove:
        logger.info(f"  {sym}: {name}")
        db.get_connection().execute("DELETE FROM stocks WHERE symbol = ?", (sym,))
        db.get_connection().execute("DELETE FROM market_data WHERE symbol = ?", (sym,))
        db.get_connection().execute("DELETE FROM tier1_cache WHERE symbol = ?", (sym,))

    db.get_connection().commit()
    logger.info(f"Removed {len(to_remove)} symbols")


def main():
    db = Database()

    # Step 1: Retry missing earnings with secondary source
    logger.info("=" * 50)
    logger.info("Step 1: Retry missing earnings with secondary source")
    logger.info("=" * 50)
    still_missing = retry_missing_earnings(db)

    # Step 2: Remove symbols without shares
    logger.info("\n" + "=" * 50)
    logger.info("Step 2: Remove symbols without shares_outstanding")
    logger.info("=" * 50)
    remove_symbols_without_shares(db)

    # Final summary
    logger.info("\n" + "=" * 50)
    logger.info("Final Summary")
    logger.info("=" * 50)

    total = db.get_connection().execute(
        "SELECT COUNT(*) FROM stocks WHERE category = 'stocks'"
    ).fetchone()[0]
    with_shares = db.get_connection().execute(
        "SELECT COUNT(*) FROM stocks WHERE shares_outstanding IS NOT NULL"
    ).fetchone()[0]
    with_earnings = db.get_connection().execute(
        "SELECT COUNT(*) FROM stocks WHERE next_earnings_date IS NOT NULL"
    ).fetchone()[0]

    logger.info(f"Total stocks remaining: {total}")
    logger.info(f"With shares_outstanding: {with_shares}")
    logger.info(f"With earnings_date: {with_earnings}")


if __name__ == '__main__':
    main()
