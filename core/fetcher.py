"""Data fetcher for stock market data using yfinance with incremental updates."""
import gc
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import yfinance as yf
import pandas as pd

from config.settings import settings
from data.db import Database

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetch stock data from yfinance with incremental updates and caching."""

    def __init__(
        self,
        db: Optional[Database] = None,
        max_workers: int = 4,  # Increased for better throughput
        request_delay: float = 0.5,  # Increased to 0.5s for rate limiting
        max_retries: int = 3,
        max_history_days: int = 252
    ):
        """
        Initialize data fetcher.

        Args:
            db: Database instance for caching
            max_workers: Max concurrent threads
            request_delay: Delay between requests in seconds
            max_retries: Max retry attempts for failed requests
            max_history_days: Maximum days of history to keep (280 trading days)
        """
        self.db = db or Database()
        self.max_workers = max_workers
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.max_history_days = max_history_days
        self._last_request_time = 0

    def _normalize_timezone(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize timezone to UTC for consistent comparisons."""
        if df.index.tz is not None:
            df.index = df.index.tz_convert('UTC').tz_localize(None)
        return df

    def _rate_limited_request(self, func: Callable, *args, **kwargs):
        """Execute function with rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)

        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                self._last_request_time = time.time()
                return result
            except Exception as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * self.request_delay
                    logger.info(f"Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    raise

        return None

    def _get_cached_data(self, symbol: str) -> Tuple[Optional[pd.DataFrame], Optional[datetime.date]]:
        """
        Get cached data from database and return latest date.

        Returns:
            Tuple of (DataFrame or None, latest_date or None)
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT date, open, high, low, close, volume FROM market_data WHERE symbol = ? ORDER BY date",
                    (symbol,)
                )
                rows = cursor.fetchall()

                if not rows:
                    return None, None

                # Convert to DataFrame
                df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)

                # Get latest date
                latest_date = df.index.max().date()

                logger.debug(f"Cached data for {symbol}: {len(df)} rows, latest {latest_date}")
                return df, latest_date

        except Exception as e:
            logger.debug(f"No cached data for {symbol}: {e}")
            return None, None

    def _fetch_incremental(
        self,
        symbol: str,
        cached_df: Optional[pd.DataFrame],
        latest_cached_date: Optional[datetime.date]
    ) -> Optional[pd.DataFrame]:
        """
        Fetch incremental data for a symbol.

        If we have cached data, only fetch from the day after latest date.
        Otherwise fetch full history.
        """
        try:
            ticker = yf.Ticker(symbol)

            if cached_df is not None and latest_cached_date is not None:
                # Calculate days needed (buffer of 3 days for weekends/holidays)
                today = datetime.now().date()
                days_needed = (today - latest_cached_date).days + 3

                if days_needed <= 0:
                    logger.debug(f"{symbol}: cache up to date")
                    return cached_df

                # Fetch only needed period
                period = f"{max(days_needed, 5)}d"  # Minimum 5 days
                logger.debug(f"{symbol}: fetching incremental {period} (latest cached: {latest_cached_date})")
            else:
                # No cache, fetch full history
                period = "13mo"  # 13 months to ensure 252 trading days
                logger.debug(f"{symbol}: no cache, fetching full {period}")

            df = self._rate_limited_request(
                ticker.history,
                period=period,
                interval="1d",
                auto_adjust=True
            )

            if df is None or df.empty:
                return cached_df  # Return cached data if fetch fails

            # Standardize column names
            df.columns = [c.lower().replace(' ', '_') for c in df.columns]
            df.index = df.index.tz_localize(None) if df.index.tz else df.index

            # Merge with cached data if exists
            if cached_df is not None:
                # Normalize timezone before comparison
                cached_df = self._normalize_timezone(cached_df)
                df = self._normalize_timezone(df)
                # Remove overlapping dates from cached data
                cached_df = cached_df[cached_df.index < df.index.min()]
                # Concatenate
                df = pd.concat([cached_df, df])

            # Keep only last max_history_days
            if len(df) > self.max_history_days:
                df = df.tail(self.max_history_days)

            logger.debug(f"{symbol}: merged data has {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")
            return cached_df  # Return cached data on error

    def fetch_stock_data(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        use_cache: bool = True,
        fetch_info: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data with incremental update support.
        Also fetches market cap info if fetch_info=True.

        Args:
            symbol: Stock symbol
            period: Data period (ignored if use_cache=True with existing data)
            interval: Data interval
            use_cache: Whether to use cached data
            fetch_info: Whether to also fetch market cap info

        Returns:
            DataFrame with OHLCV data or None if failed
        """
        if use_cache:
            # Try to get cached data
            cached_df, latest_date = self._get_cached_data(symbol)

            # Fetch incremental data
            df = self._fetch_incremental(symbol, cached_df, latest_date)

            if df is not None and not df.empty:
                # Save to database (incremental rows only)
                self._save_to_db(symbol, df, incremental=True)

                # Fetch market cap info in parallel (non-blocking)
                if fetch_info:
                    try:
                        self.fetch_stock_info(symbol)
                    except Exception:
                        pass  # Don't fail if info fetch fails

                return df

            return cached_df  # Return cached if incremental fails
        else:
            # Bypass cache, fetch directly
            try:
                ticker = yf.Ticker(symbol)
                df = self._rate_limited_request(
                    ticker.history,
                    period=period,
                    interval=interval,
                    auto_adjust=True
                )

                if df is None or df.empty:
                    return None

                df.columns = [c.lower().replace(' ', '_') for c in df.columns]
                df.index = df.index.tz_localize(None) if df.index.tz else df.index

                self._save_to_db(symbol, df)
                return df

            except Exception as e:
                logger.error(f"Failed to fetch {symbol}: {e}")
                return None

    def _download_batch_yf(self, symbols: List[str], period: str = "13mo", interval: str = "1d") -> Dict[str, pd.DataFrame]:
        """Download using yf.download with MultiIndex reshaping."""
        import warnings
        warnings.filterwarnings('ignore')

        try:
            multi_df = yf.download(symbols, period=period, interval=interval, auto_adjust=True, threads=True)

            if multi_df is None or (hasattr(multi_df, 'empty') and multi_df.empty):
                return {}

            results = {}
            for symbol in symbols:
                try:
                    df = pd.DataFrame()
                    for col in ['Close', 'Open', 'High', 'Low', 'Volume']:
                        if (col, symbol) in multi_df.columns:
                            df[col.lower()] = multi_df[(col, symbol)]
                        elif (symbol, col) in multi_df.columns:
                            df[col.lower()] = multi_df[(symbol, col)]
                    if not df.empty and len(df) > 0:
                        df.index.name = 'date'
                        df = df.dropna(subset=['close'])
                        results[symbol] = df
                except Exception as e:
                    logger.debug(f"Failed to extract {symbol} from batch download: {e}")
                    continue
            return results
        except Exception as e:
            logger.error(f"yf.download batch failed: {e}")
            return {}
        finally:
            warnings.resetwarnings()

    def _save_to_db(self, symbol: str, df: pd.DataFrame, incremental: bool = True):
        """Save fetched data to database using batch insert."""
        try:
            if incremental:
                # Check latest date in database
                with self.db.get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT MAX(date) FROM market_data WHERE symbol = ?",
                        (symbol,)
                    )
                    result = cursor.fetchone()
                    latest_db_date = result[0] if result and result[0] else None

                # Filter only new rows
                if latest_db_date:
                    df_to_save = df[df.index > latest_db_date]
                else:
                    df_to_save = df
            else:
                df_to_save = df

            # Prepare batch data
            data_list = []
            for date, row in df_to_save.iterrows():
                date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
                record = {'date': date_str}

                # Add NaN/null checks before type conversions
                for col in ['open', 'high', 'low', 'close']:
                    val = row.get(col, None)
                    if val is None or (isinstance(val, float) and np.isnan(val)):
                        continue
                    record[col] = float(val)

                volume_val = row.get('volume', None)
                if volume_val is not None and not (isinstance(volume_val, float) and np.isnan(volume_val)):
                    record['volume'] = int(volume_val)

                # Only add record if we have all required price columns
                if all(k in record for k in ['open', 'high', 'low', 'close']):
                    data_list.append(record)

            # Batch insert
            if data_list:
                self.db.save_market_data_batch(symbol, data_list)
                logger.debug(f"Saved {len(data_list)} new rows for {symbol} (batch)")

        except Exception as e:
            logger.error(f"Error saving {symbol} to database: {e}")

    def fetch_multiple(
        self,
        symbols: List[str],
        period: str = "6mo",
        interval: str = "1d",
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple stocks using batch yf.download.

        All symbols are fetched via yf.download() batch calls (50 per batch).
        Results are merged with DB history and truncated to 280 trading days.

        Args:
            symbols: List of stock symbols
            period: Data period (for new symbols without DB data)
            interval: Data interval
            use_cache: Ignored - all symbols use batch download

        Returns:
            Dict mapping symbol to DataFrame
        """
        results = {}
        failed_symbols = []
        batch_size = 50

        logger.info(f"Fetching data for {len(symbols)} symbols via batch download")

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(symbols) + batch_size - 1) // batch_size
            logger.info(f"Batch {batch_num}/{total_batches}: {len(batch)} symbols")

            batch_results = self._download_batch_yf(batch, period="5d", interval=interval)

            for sym, df in batch_results.items():
                if df is not None and not df.empty:
                    # Merge with DB history
                    merged = self._merge_batch_with_db_cache(sym, df)
                    self._save_to_db(sym, merged, incremental=False)
                    results[sym] = df  # Return fresh data, not merged
                else:
                    failed_symbols.append(sym)

            if i + batch_size < len(symbols):
                time.sleep(self.request_delay)

            gc.collect()

        logger.info(f"Successfully fetched {len(results)} symbols, {len(failed_symbols)} failed")
        if failed_symbols:
            logger.warning(f"Failed symbols: {failed_symbols}")

        return results

    def _merge_batch_with_db_cache(self, symbol: str, batch_df: pd.DataFrame) -> pd.DataFrame:
        """Merge batch download with DB history, deduplicate by date.

        Args:
            symbol: Stock symbol
            batch_df: Fresh DataFrame from batch download (5 days)

        Returns:
            Merged DataFrame with ~280 trading days of history
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT date, open, high, low, close, volume FROM market_data WHERE symbol = ? ORDER BY date",
                    (symbol,)
                )
                rows = cursor.fetchall()
        except Exception:
            return batch_df

        if not rows:
            return batch_df

        db_df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
        db_df['date'] = pd.to_datetime(db_df['date'])
        db_df.set_index('date', inplace=True)

        # Deduplicate: remove DB rows that overlap with batch dates
        batch_dates = set(batch_df.index)
        db_df = db_df[~db_df.index.isin(batch_dates)]

        # Merge and sort
        merged = pd.concat([db_df, batch_df])
        merged.sort_index(inplace=True)

        # Keep last 280 trading days
        if len(merged) > 280:
            merged = merged.tail(280)

        return merged

    def download_batch(
        self,
        symbols: List[str],
        period: str = "6mo",
        interval: str = "1d",
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Download data using incremental updates.

        This method uses fetch_multiple internally which supports caching.
        """
        return self.fetch_multiple(symbols, period, interval, use_cache)

    def fetch_earnings_calendar(
        self,
        symbols: Optional[List[str]] = None,
        days_ahead: int = 7
    ) -> Dict[str, datetime]:
        """Fetch earnings calendar for symbols using parallel workers."""
        if symbols is None:
            symbols = self.db.get_active_stocks()

        earnings = {}
        lock = threading.Lock()
        today = datetime.now().date()
        end_date = today + timedelta(days=days_ahead)

        def fetch_single(symbol):
            try:
                ticker = yf.Ticker(symbol)
                calendar = self._rate_limited_request(lambda: ticker.calendar)

                if calendar is not None and not calendar.empty:
                    earnings_date = calendar.index[0] if hasattr(calendar.index[0], 'date') else calendar.index[0]
                    if isinstance(earnings_date, pd.Timestamp):
                        earnings_date = earnings_date.date()
                    elif isinstance(earnings_date, datetime):
                        earnings_date = earnings_date.date()

                    if today <= earnings_date <= end_date:
                        with lock:
                            earnings[symbol] = earnings_date
                            logger.debug(f"{symbol} earnings on {earnings_date}")

            except Exception as e:
                logger.debug(f"Could not fetch earnings for {symbol}: {e}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(fetch_single, s): s for s in symbols}
            for future in as_completed(futures):
                future.result()  # Swallow exceptions

        logger.info(f"Found {len(earnings)} earnings in next {days_ahead} days")
        return earnings

    def get_sp500_symbols(self) -> List[str]:
        """Fetch S&P 500 symbols from Wikipedia."""
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            sp500_df = tables[0]
            symbols = sp500_df['Symbol'].tolist()
            logger.info(f"Loaded {len(symbols)} S&P 500 symbols")
            return symbols
        except Exception as e:
            logger.error(f"Failed to fetch S&P 500 symbols: {e}")
            return []

    def get_nasdaq100_symbols(self) -> List[str]:
        """Fetch NASDAQ 100 symbols."""
        try:
            url = "https://en.wikipedia.org/wiki/NASDAQ-100"
            tables = pd.read_html(url)

            for table in tables:
                if 'Ticker' in table.columns or 'Symbol' in table.columns:
                    col_name = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                    symbols = table[col_name].tolist()
                    logger.info(f"Loaded {len(symbols)} NASDAQ 100 symbols")
                    return symbols

            return []
        except Exception as e:
            logger.error(f"Failed to fetch NASDAQ 100 symbols: {e}")
            return []

    def get_dow_symbols(self) -> List[str]:
        """Fetch Dow Jones Industrial Average symbols."""
        try:
            url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
            tables = pd.read_html(url)

            for table in tables:
                if 'Symbol' in table.columns:
                    symbols = table['Symbol'].tolist()
                    logger.info(f"Loaded {len(symbols)} Dow Jones symbols")
                    return symbols

            return []
        except Exception as e:
            logger.error(f"Failed to fetch Dow Jones symbols: {e}")
            return []
    def fetch_earnings_date(self, symbol: str, use_cache: bool = True) -> Optional[str]:
        """
        Fetch next earnings date for symbol with smart caching.

        Uses cached value if earnings hasn't occurred yet. Only fetches from
        yfinance when earnings date has passed or no cache exists.

        Optimized to use ticker.calendar (4 quarters only) instead of
        ticker.earnings_dates (full history) to reduce memory usage.

        Args:
            symbol: Stock symbol
            use_cache: Whether to use cached value (default True)

        Returns:
            ISO date string (YYYY-MM-DD) or None
        """
        today = datetime.now().date()

        # Check cache first
        if use_cache:
            try:
                cached_date = self.db.get_stock_earnings_date(symbol)
                if cached_date:
                    # Parse cached date
                    cached_dt = datetime.fromisoformat(cached_date).date()
                    # If earnings hasn't happened yet, use cache
                    if cached_dt >= today:
                        logger.debug(f"Using cached earnings date for {symbol}: {cached_date}")
                        return cached_date
                    # If earnings passed, we need fresh data - fall through
                    logger.debug(f"Earnings passed for {symbol}, fetching new date")
            except Exception as e:
                logger.debug(f"Cache check failed for {symbol}: {e}")

        # Fetch from yfinance using calendar (lighter than earnings_dates)
        try:
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar

            # calendar is a dict with keys like 'Earnings Date', 'Dividend Date', etc.
            if calendar and 'Earnings Date' in calendar:
                earnings_dates = calendar['Earnings Date']
                if earnings_dates and isinstance(earnings_dates, list):
                    # Get the first (nearest) future earnings date
                    for date_val in earnings_dates:
                        if date_val:
                            try:
                                # Handle both date objects and ISO strings
                                if isinstance(date_val, str):
                                    date = datetime.fromisoformat(date_val).date()
                                elif hasattr(date_val, 'date'):
                                    date = date_val.date()
                                else:
                                    date = date_val  # Already a date object
                                if date >= today:
                                    earnings_date = date.isoformat()
                                    # Store in cache
                                    try:
                                        self.db.update_stock_earnings_date(symbol, earnings_date)
                                        logger.debug(f"Cached earnings date for {symbol}: {earnings_date}")
                                    except Exception as e:
                                        logger.debug(f"Failed to cache earnings date for {symbol}: {e}")
                                    return earnings_date
                            except:
                                continue

            return None
        except Exception as e:
            logger.debug(f"Failed to fetch earnings date for {symbol}: {e}")
            return None

    def fetch_stock_info(self, symbol: str) -> Dict[str, str]:
        """
        Fetch stock info including sector and industry from yfinance.
        Also updates market cap in the stocks database table.

        Args:
            symbol: Stock symbol

        Returns:
            Dict with sector, industry, market_cap, and name
        """
        try:
            ticker = yf.Ticker(symbol)
            info = self._rate_limited_request(lambda: ticker.info)

            if info:
                market_cap = info.get('marketCap', 0)

                # Update market cap in stocks table
                if market_cap and market_cap > 0:
                    try:
                        self.db.update_stock_market_cap(symbol, float(market_cap))
                        logger.debug(f"Updated market cap for {symbol}: {market_cap:,.0f}")
                    except Exception as e:
                        logger.debug(f"Could not update market cap for {symbol}: {e}")

                return {
                    'sector': info.get('sector', 'Unknown'),
                    'industry': info.get('industry', 'Unknown'),
                    'market_cap': market_cap,
                    'name': info.get('longName', symbol)
                }
        except Exception as e:
            logger.debug(f"Could not fetch info for {symbol}: {e}")

        return {'sector': 'Unknown', 'industry': 'Unknown', 'market_cap': 0, 'name': symbol}

    def fetch_batch_stock_info(self, symbols: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Fetch stock info for multiple symbols with caching.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to info dict
        """
        results = {}

        # Check database cache first
        try:
            with self.db.get_connection() as conn:
                placeholders = ','.join(['?' for _ in symbols])
                cursor = conn.execute(
                    f"SELECT symbol, sector, industry FROM stock_info WHERE symbol IN ({placeholders})",
                    symbols
                )
                cached = {row[0]: {'sector': row[1], 'industry': row[2]} for row in cursor.fetchall()}
                results.update(cached)
        except Exception as e:
            logger.debug(f"Could not fetch cached stock info: {e}")
            cached = {}

        # Fetch missing symbols
        missing = [s for s in symbols if s not in cached]
        for symbol in missing:
            try:
                info = self.fetch_stock_info(symbol)
                results[symbol] = info

                # Cache to database
                try:
                    with self.db.get_connection() as conn:
                        conn.execute('''
                            INSERT OR REPLACE INTO stock_info (symbol, sector, industry, updated_date)
                            VALUES (?, ?, ?, date('now'))
                        ''', (symbol, info.get('sector'), info.get('industry')))
                        conn.commit()
                except Exception as e:
                    logger.debug(f"Could not cache stock info: {e}")

                time.sleep(self.request_delay)
            except Exception as e:
                logger.warning(f"Failed to fetch info for {symbol}: {e}")
                results[symbol] = {'sector': 'Unknown', 'industry': 'Unknown'}

        return results

