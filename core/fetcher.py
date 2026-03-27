"""Data fetcher for stock market data using yfinance with incremental updates."""
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
        max_workers: int = 2,
        request_delay: float = 0.5,
        max_retries: int = 3,
        max_history_days: int = 150
    ):
        """
        Initialize data fetcher.

        Args:
            db: Database instance for caching
            max_workers: Max concurrent threads
            request_delay: Delay between requests in seconds
            max_retries: Max retry attempts for failed requests
            max_history_days: Maximum days of history to keep (150 trading days)
        """
        self.db = db or Database()
        self.max_workers = max_workers
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.max_history_days = max_history_days
        self._last_request_time = 0

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
            conn = self.db.get_connection()
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
                period = "7mo"  # 7 months to ensure 150 trading days
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
        use_cache: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data with incremental update support.

        Args:
            symbol: Stock symbol
            period: Data period (ignored if use_cache=True with existing data)
            interval: Data interval
            use_cache: Whether to use cached data

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

    def _save_to_db(self, symbol: str, df: pd.DataFrame, incremental: bool = True):
        """Save fetched data to database."""
        try:
            if incremental:
                # Check latest date in database
                conn = self.db.get_connection()
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

            saved_count = 0
            for date, row in df_to_save.iterrows():
                date_str = date.strftime('%Y-%m-%d') if isinstance(date, pd.Timestamp) else str(date)[:10]

                self.db.save_market_data(symbol, {
                    'date': date_str,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume'])
                })
                saved_count += 1

            if saved_count > 0:
                logger.debug(f"Saved {saved_count} new rows for {symbol}")

        except Exception as e:
            logger.error(f"Error saving {symbol} to database: {e}")

    def fetch_multiple(
        self,
        symbols: List[str],
        period: str = "6mo",
        interval: str = "1d",
        use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch data for multiple stocks with incremental updates.

        Args:
            symbols: List of stock symbols
            period: Data period (for non-cached fetches)
            interval: Data interval
            use_cache: Whether to use cached data

        Returns:
            Dict mapping symbol to DataFrame
        """
        results = {}
        failed_symbols = []

        logger.info(f"Fetching data for {len(symbols)} symbols (cache enabled: {use_cache})")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.fetch_stock_data, sym, period, interval, use_cache): sym
                for sym in symbols
            }

            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        results[symbol] = df
                    else:
                        failed_symbols.append(symbol)
                except Exception as e:
                    logger.error(f"Error fetching {symbol}: {e}")
                    failed_symbols.append(symbol)

        logger.info(f"Successfully fetched {len(results)} symbols, {len(failed_symbols)} failed")
        if failed_symbols:
            logger.warning(f"Failed symbols: {failed_symbols}")

        return results

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
        """Fetch earnings calendar for symbols."""
        if symbols is None:
            symbols = self.db.get_active_stocks()

        earnings = {}
        today = datetime.now().date()
        end_date = today + timedelta(days=days_ahead)

        for symbol in symbols:
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
                        earnings[symbol] = earnings_date
                        logger.debug(f"{symbol} earnings on {earnings_date}")

                time.sleep(self.request_delay)

            except Exception as e:
                logger.debug(f"Could not fetch earnings for {symbol}: {e}")
                continue

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