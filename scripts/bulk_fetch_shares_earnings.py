"""One-time bulk fetch of shares outstanding and earnings dates for all stocks.

Run this ONCE to populate shares_outstanding and earnings dates for all ~2,900 stocks.
Uses conservative rate limiting (1 worker, 2s delay) to avoid yfinance rate limits.
Expected runtime: ~3-4 hours for 2,900 symbols x 2 API calls each.
"""
import gc
import logging
import random
import sys
import time
import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, '.')
from data.db import Database
from core.stock_universe import StockUniverseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Conservative settings for one-time bulk fetch
REQUEST_DELAY = 1.0  # 1 second base between requests
DELAY_JITTER = 0.1   # Random +/- 0.1s jitter
MAX_RETRIES = 5
BATCH_SIZE = 10  # Small batches for easy recovery if interrupted


def bulk_fetch_shares_and_earnings():
    """Fetch shares outstanding and earnings dates for ALL stocks, one at a time."""
    db = Database()
    universe = StockUniverseManager(db)

    # Get all stocks (not ETFs)
    symbols = universe.get_stocks()
    logger.info(f"Total stocks to process: {len(symbols)}")

    # Check how many already have data
    already_shares = 0
    already_earnings = 0
    needs_fetch = []

    for sym in symbols:
        row = db.get_connection().execute(
            "SELECT shares_outstanding FROM stocks WHERE symbol = ?", (sym,)
        ).fetchone()
        has_shares = row and row[0] and row[0] > 0
        has_earnings = db.get_stock_earnings_date(sym) is not None

        if has_shares:
            already_shares += 1
        if has_earnings:
            already_earnings += 1

        if not has_shares or not has_earnings:
            needs_fetch.append(sym)

    logger.info(f"Already have shares_outstanding: {already_shares}")
    logger.info(f"Already have earnings_date: {already_earnings}")
    logger.info(f"Still need to fetch: {len(needs_fetch)}")

    if not needs_fetch:
        logger.info("All data already fetched. Nothing to do.")
        return

    # Process one at a time with rate limiting
    last_request_time = 0
    success_shares = 0
    success_earnings = 0
    failed_shares = 0
    failed_earnings = 0
    total_processed = 0
    start_time = time.time()

    def rate_limit():
        nonlocal last_request_time
        elapsed = time.time() - last_request_time
        delay = REQUEST_DELAY + random.uniform(-DELAY_JITTER, DELAY_JITTER)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        last_request_time = time.time()

    def fetch_one(symbol):
        nonlocal success_shares, success_earnings, failed_shares, failed_earnings

        # Fetch shares outstanding
        shares_ok = False
        for attempt in range(MAX_RETRIES):
            try:
                rate_limit()
                ticker = yf.Ticker(symbol)
                info = ticker.info
                if info:
                    shares = info.get('sharesOutstanding') or info.get('floatShares')
                    if shares and shares > 0:
                        today_str = datetime.now().date().isoformat()
                        db.update_shares_outstanding(symbol, float(shares), today_str)
                        shares_ok = True
                        break
                logger.info(f"  {symbol} shares: no data (attempt {attempt+1})")
                break  # No data, don't retry
            except Exception as e:
                logger.warning(f"  {symbol} shares attempt {attempt+1}/{MAX_RETRIES}: {type(e).__name__}")
                time.sleep(REQUEST_DELAY * 2)

        # Fetch earnings calendar
        earnings_ok = False
        for attempt in range(MAX_RETRIES):
            try:
                rate_limit()
                ticker = yf.Ticker(symbol)
                calendar = ticker.calendar
                if calendar and 'Earnings Date' in calendar:
                    earnings_dates = calendar['Earnings Date']
                    if earnings_dates and isinstance(earnings_dates, list):
                        today = datetime.now().date()
                        for date_val in earnings_dates:
                            if date_val:
                                try:
                                    if isinstance(date_val, str):
                                        date = datetime.fromisoformat(date_val).date()
                                    elif hasattr(date_val, 'date'):
                                        date = date_val.date()
                                    else:
                                        date = date_val
                                    if date >= today:
                                        db.update_stock_earnings_date(symbol, date.isoformat())
                                        earnings_ok = True
                                        break
                                except:
                                    continue
                break  # Either found or no data, don't retry
            except Exception as e:
                logger.warning(f"  {symbol} earnings attempt {attempt+1}/{MAX_RETRIES}: {type(e).__name__}")
                time.sleep(REQUEST_DELAY * 2)

        return shares_ok, earnings_ok

    # Process in small batches
    for i in range(0, len(needs_fetch), BATCH_SIZE):
        batch = needs_fetch[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(needs_fetch) + BATCH_SIZE - 1) // BATCH_SIZE
        batch_start = time.time()

        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} symbols)...")

        for symbol in batch:
            shares_ok, earnings_ok = fetch_one(symbol)
            if shares_ok:
                success_shares += 1
            else:
                failed_shares += 1
            if earnings_ok:
                success_earnings += 1
            else:
                failed_earnings += 1
            total_processed += 1

        batch_time = time.time() - batch_start
        elapsed_total = time.time() - start_time
        avg_per_symbol = elapsed_total / total_processed
        remaining = (len(needs_fetch) - total_processed) * avg_per_symbol

        logger.info(
            f"  Done: {total_processed}/{len(needs_fetch)} | "
            f"Shares: {success_shares} ok / {failed_shares} fail | "
            f"Earnings: {success_earnings} ok / {failed_earnings} fail | "
            f"ETA: {remaining/60:.0f}m"
        )

        gc.collect()

    total_time = time.time() - start_time
    logger.info(f"\n{'='*50}")
    logger.info(f"BULK FETCH COMPLETE in {total_time/60:.0f}m")
    logger.info(f"Shares outstanding: {success_shares} updated, {failed_shares} failed")
    logger.info(f"Earnings dates: {success_earnings} updated, {failed_earnings} failed")
    logger.info(f"{'='*50}")


if __name__ == '__main__':
    bulk_fetch_shares_and_earnings()
