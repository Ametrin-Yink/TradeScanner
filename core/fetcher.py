"""Data fetcher for stock market data using yfinance."""
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yfinance as yf
import pandas as pd

from config.settings import settings
from data.db import Database

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetch stock data from yfinance with rate limiting and retries."""

    def __init__(
        self,
        db: Optional[Database] = None,
        max_workers: int = 2,
        request_delay: float = 0.5,
        max_retries: int = 3
    ):
        """
        Initialize data fetcher.

        Args:
            db: Database instance for caching
            max_workers: Max concurrent threads (default 2 for 2C2G VPS)
            request_delay: Delay between requests in seconds
            max_retries: Max retry attempts for failed requests
        """
        self.db = db or Database()
        self.max_workers = max_workers
        self.request_delay = request_delay
        self.max_retries = max_retries
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
                    wait_time = (2 ** attempt) * self.request_delay  # Exponential backoff
                    logger.info(f"Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    raise

        return None

    def fetch_stock_data(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical data for a single stock.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

        Returns:
            DataFrame with OHLCV data or None if failed
        """
        try:
            ticker = yf.Ticker(symbol)
            df = self._rate_limited_request(
                ticker.history,
                period=period,
                interval=interval,
                auto_adjust=True
            )

            if df is None or df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None

            # Standardize column names
            df.columns = [c.lower().replace(' ', '_') for c in df.columns]

            # Remove timezone info from index
            df.index = df.index.tz_localize(None) if df.index.tz else df.index

            logger.debug(f"Fetched {len(df)} rows for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")
            return None

    def fetch_multiple(
        self,
        symbols: List[str],
        period: str = "6mo",
        interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch data for multiple stocks with parallel processing.

        Args:
            symbols: List of stock symbols
            period: Data period
            interval: Data interval

        Returns:
            Dict mapping symbol to DataFrame
        """
        results = {}
        failed_symbols = []

        logger.info(f"Fetching data for {len(symbols)} symbols with {self.max_workers} workers")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_symbol = {
                executor.submit(self.fetch_stock_data, sym, period, interval): sym
                for sym in symbols
            }

            # Collect results
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        results[symbol] = df
                        # Save to database
                        self._save_to_db(symbol, df)
                    else:
                        failed_symbols.append(symbol)
                except Exception as e:
                    logger.error(f"Error fetching {symbol}: {e}")
                    failed_symbols.append(symbol)

        logger.info(f"Successfully fetched {len(results)} symbols, {len(failed_symbols)} failed")
        if failed_symbols:
            logger.warning(f"Failed symbols: {failed_symbols}")

        return results

    def _save_to_db(self, symbol: str, df: pd.DataFrame):
        """Save fetched data to database."""
        try:
            for date, row in df.iterrows():
                # Handle both Timestamp and string dates
                if isinstance(date, pd.Timestamp):
                    date_str = date.strftime('%Y-%m-%d')
                else:
                    date_str = str(date)[:10]

                self.db.save_market_data(symbol, {
                    'date': date_str,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume'])
                })
        except Exception as e:
            logger.error(f"Error saving {symbol} to database: {e}")

    def fetch_earnings_calendar(
        self,
        symbols: Optional[List[str]] = None,
        days_ahead: int = 7
    ) -> Dict[str, datetime]:
        """
        Fetch earnings calendar for symbols.

        Args:
            symbols: List of symbols (if None, uses active stocks from DB)
            days_ahead: Number of days to look ahead

        Returns:
            Dict mapping symbol to earnings date
        """
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
                    # Parse earnings date
                    earnings_date = calendar.index[0] if hasattr(calendar.index[0], 'date') else calendar.index[0]
                    if isinstance(earnings_date, pd.Timestamp):
                        earnings_date = earnings_date.date()
                    elif isinstance(earnings_date, datetime):
                        earnings_date = earnings_date.date()

                    # Check if within range
                    if today <= earnings_date <= end_date:
                        earnings[symbol] = earnings_date
                        logger.debug(f"{symbol} earnings on {earnings_date}")

                time.sleep(self.request_delay)

            except Exception as e:
                logger.debug(f"Could not fetch earnings for {symbol}: {e}")
                continue

        logger.info(f"Found {len(earnings)} earnings in next {days_ahead} days")
        return earnings

    def download_batch(
        self,
        symbols: List[str],
        period: str = "6mo",
        interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """
        Download data using yfinance.download for batch efficiency.

        Args:
            symbols: List of stock symbols
            period: Data period
            interval: Data interval

        Returns:
            Dict mapping symbol to DataFrame
        """
        if not symbols:
            return {}

        try:
            # Use yfinance.download with threads=False for VPS stability
            data = yf.download(
                tickers=symbols,
                period=period,
                interval=interval,
                group_by='ticker',
                auto_adjust=True,
                prepost=False,
                threads=False,  # Disable parallel in yfinance, we handle our own
                progress=True
            )

            results = {}

            if len(symbols) == 1:
                # Single symbol returns different structure
                symbol = symbols[0]
                df = data.copy()
                df.columns = [c.lower().replace(' ', '_') for c in df.columns]
                df.index = df.index.tz_localize(None) if df.index.tz else df.index
                if not df.empty:
                    results[symbol] = df
                    self._save_to_db(symbol, df)
            else:
                # Multiple symbols
                for symbol in symbols:
                    try:
                        if symbol in data.columns.levels[0]:
                            df = data[symbol].copy()
                            df.columns = [c.lower().replace(' ', '_') for c in df.columns]
                            df.index = df.index.tz_localize(None) if df.index.tz else df.index
                            df = df.dropna()

                            if not df.empty:
                                results[symbol] = df
                                self._save_to_db(symbol, df)
                    except Exception as e:
                        logger.warning(f"Error processing {symbol}: {e}")

            logger.info(f"Batch download complete: {len(results)}/{len(symbols)} symbols")
            return results

        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            return {}

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

            # Find the table with NASDAQ-100 components
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
