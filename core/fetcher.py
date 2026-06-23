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
from core.swing_detector import detect_swings, cluster_levels

logger = logging.getLogger(__name__)


def validate_cache_freshness(db, max_age_hours=24):
    """Abort if any cache table lacks today's data."""
    today = datetime.now().strftime('%Y-%m-%d')
    tables = ['tier1_cache', 'etf_cache']
    stale = []
    for table in tables:
        try:
            rows = db.get_connection().execute(
                f"SELECT COUNT(*) FROM {table} WHERE cache_date >= ?", (today,)
            ).fetchone()
            if rows and rows[0] == 0:
                stale.append(table)
        except Exception:
            stale.append(f"{table} (error checking)")

    if stale:
        raise RuntimeError(
            f"Stale cache detected in: {', '.join(stale)}. "
            f"Run data fetch before analysis."
        )
    logger.info(f"Cache freshness OK: {today}")


class DataFetcher:
    """Fetch stock data from yfinance with incremental updates and caching."""

    def __init__(
        self,
        db: Optional[Database] = None,
        max_workers: int = 8,  # 24GB server
        request_delay: float = 0.25,  # yfinance free tier tolerates ~4 req/s
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

    def _compute_tier1_cache_for_symbol(self, symbol: str, df: pd.DataFrame):
        """Compute tier1 cache metrics and save.

        Computes all fields needed for setup detection: EMAs, ATR, 60d range,
        volume ratio, 5d return, in addition to current_price and rs_raw.
        """
        if df is None or df.empty:
            return

        cache_data = {}
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values

        # Current price
        current_price = float(closes[-1])
        cache_data['current_price'] = current_price

        # RS_raw: 3-month relative strength
        rs_raw = None
        if len(closes) >= 63:
            price_63d_ago = float(closes[-63])
            if price_63d_ago > 0:
                rs_raw = (current_price / price_63d_ago - 1) * 100
        cache_data['rs_raw'] = rs_raw

        # 60-day high/low
        if len(closes) >= 60:
            cache_data['high_60d'] = float(max(highs[-60:]))
            cache_data['low_60d'] = float(min(lows[-60:]))
        elif len(closes) > 0:
            cache_data['high_60d'] = float(max(highs))
            cache_data['low_60d'] = float(min(lows))

        # EMAs
        if len(closes) >= 21:
            ema21_series = pd.Series(closes).ewm(span=21, adjust=False).mean()
            cache_data['ema21'] = float(ema21_series.iloc[-1])
        if len(closes) >= 50:
            ema50_series = pd.Series(closes).ewm(span=50, adjust=False).mean()
            cache_data['ema50'] = float(ema50_series.iloc[-1])

        # ATR (14-day)
        if len(closes) >= 15:
            trs = []
            for i in range(1, len(closes)):
                tr = max(highs[i] - lows[i],
                         abs(highs[i] - closes[i-1]),
                         abs(lows[i] - closes[i-1]))
                trs.append(tr)
            atr = float(pd.Series(trs).tail(14).mean())
            cache_data['atr'] = atr
            cache_data['atr_pct'] = round(atr / current_price, 4) if current_price > 0 else 0.03

        # Volume ratio (current vs 20d avg)
        if len(volumes) >= 20:
            avg_vol = float(pd.Series(volumes).tail(20).mean())
            cache_data['avg_volume_20d'] = avg_vol
            if avg_vol > 0:
                cache_data['volume_ratio'] = round(float(volumes[-1]) / avg_vol, 2)
            else:
                cache_data['volume_ratio'] = 1.0
        elif len(volumes) > 0:
            cache_data['avg_volume_20d'] = float(volumes.mean())

        # 5-day return
        if len(closes) >= 6:
            cache_data['ret_5d'] = round((closes[-1] / closes[-6] - 1) * 100, 1)

        # Save to tier1_cache
        self.db.save_tier1_cache(symbol, cache_data)

    def _update_rs_percentiles(self, symbols: List[str]):
        """Rank all cached symbols by rs_raw, assign percentiles, track streaks.

        Args:
            symbols: List of symbols to update
        """
        rs_values = []
        for sym in symbols:
            cache = self.db.get_tier1_cache(sym)
            if isinstance(cache, dict) and cache.get('rs_raw') is not None:
                rs_values.append((sym, cache['rs_raw']))

        if not rs_values:
            return

        rs_values.sort(key=lambda x: x[1])
        n = len(rs_values)

        # Assign percentiles
        for rank, (sym, rs_raw) in enumerate(rs_values):
            percentile = int(rank / (n - 1) * 99) if n > 1 else 50
            self.db.update_rs_percentile(sym, percentile)

        min_rs = rs_values[0][1]
        max_rs = rs_values[-1][1]
        logger.info(f"RS percentile range: {min_rs:.1f}–{max_rs:.1f}, stocks ranked: {n}")

        # Track consecutive days >= 80th percentile
        for sym, rs_raw in rs_values:
            cache = self.db.get_tier1_cache(sym)
            if not isinstance(cache, dict):
                continue
            rs_pct = cache.get('rs_percentile', 0) or 0
            prev_streak = cache.get('rs_consecutive_days_80', 0) or 0
            if rs_pct >= 80:
                new_streak = prev_streak + 1
            elif rs_pct < 50:
                new_streak = 0
            else:
                new_streak = prev_streak  # hold steady between 50-79
            self.db.update_tier1_field(sym, 'rs_consecutive_days_80', new_streak)

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
        Also computes and caches tier1 metrics (current_price, RS_raw, etc.)
        and ranks RS percentiles for all fetched symbols.

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
                    # Compute and cache tier1 metrics
                    self._compute_tier1_cache_for_symbol(sym, merged)
                    results[sym] = df  # Return fresh data, not merged
                else:
                    failed_symbols.append(sym)

            if i + batch_size < len(symbols):
                time.sleep(self.request_delay)

        # Post-batch RS percentile ranking
        self._update_rs_percentiles(list(results.keys()))

        logger.info(f"Successfully fetched {len(results)} symbols, {len(failed_symbols)} failed")
        if failed_symbols:
            logger.warning(f"Failed symbols: {failed_symbols}")

        return results

    def fetch_etf_data(self, etf_symbols: List[str]) -> Dict[str, Dict]:
        """Fetch current price and metrics for ETFs (SPY, VIX, sector ETFs).

        Downloads recent data, computes daily/3m returns, RS percentile,
        EMA status, and VIX metrics. Saves to etf_cache table.
        """
        import numpy as np
        results = {}
        for etf in etf_symbols:
            try:
                ticker = yf.Ticker(etf)
                hist = ticker.history(period="6mo", interval="1d")
                if hist.empty:
                    logger.warning(f"ETF {etf}: no data from yfinance")
                    continue

                current_price = float(hist['Close'].iloc[-1])
                closes = hist['Close'].values
                ret_5d = float((closes[-1] / closes[-6] - 1) * 100) if len(closes) >= 6 else None
                ret_3m = float((closes[-1] / closes[-63] - 1) * 100) if len(closes) >= 63 else None

                ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1]
                above_ema50 = bool(current_price > ema50)

                etf_data = {
                    'symbol': etf,
                    'current_price': current_price,
                    'ret_5d': ret_5d,
                    'ret_3m': ret_3m,
                    'above_ema50': above_ema50,
                }

                # VIX-specific metrics
                if etf in ('VIX', '^VIX', 'VIXM'):
                    vix_val = current_price
                    if vix_val < 15:
                        vix_status = 'low'
                    elif vix_val < 20:
                        vix_status = 'normal'
                    elif vix_val < 30:
                        vix_status = 'elevated'
                    else:
                        vix_status = 'high'
                    etf_data['vix_current'] = vix_val
                    etf_data['vix_status'] = vix_status

                self.db.save_etf_cache(etf, etf_data)
                results[etf] = etf_data
                logger.info(f"ETF {etf}: ${current_price:.2f}, 5d={ret_5d:+.1f}%")

            except Exception as e:
                logger.warning(f"ETF {etf} fetch failed: {e}")

        # Compute RS percentiles across all fetched ETFs
        if len(results) >= 3:
            rets = {s: d.get('ret_3m', 0) or 0 for s, d in results.items()}
            ranked = sorted(rets.items(), key=lambda x: x[1])
            n = len(ranked)
            for rank, (sym, _) in enumerate(ranked):
                rs_pct = round(rank / (n - 1) * 100, 1) if n > 1 else 50.0
                if sym in results:
                    results[sym]['rs_percentile'] = rs_pct
                    self.db.save_etf_cache(sym, results[sym])

        logger.info(f"ETF data updated for {len(results)}/{len(etf_symbols)} symbols")
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


def fetch_all_pipeline_data(db: Database, symbols: List[str] = None,
                            etf_symbols: List[str] = None) -> bool:
    """Fetch fresh stock OHLC and ETF data for the full pipeline.

    Called before a scan to ensure tier1_cache and etf_cache are fresh.
    Returns True if fetch succeeded (even partially), False on total failure.
    """
    logger = logging.getLogger(__name__)
    fetcher = DataFetcher(db=db)

    # 1. Fetch stock OHLC data
    if symbols is None:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM stocks WHERE is_active = 1"
        ).fetchall()
        symbols = [r[0] for r in rows]

    if not symbols:
        logger.warning("No active stocks to fetch")
        return False

    logger.info(f"Auto-fetch: {len(symbols)} stocks")
    try:
        fetcher.fetch_multiple(symbols)
    except Exception as e:
        logger.error(f"Stock data fetch failed: {e}")

    # 2. Fetch ETF data
    if etf_symbols is None:
        from core.constants import SECTOR_ETFS
        etf_symbols = ['SPY', 'VIX', 'QQQ'] + [e for e in SECTOR_ETFS.values() if e]
        # Deduplicate
        etf_symbols = list(dict.fromkeys(etf_symbols))

    logger.info(f"Auto-fetch: {len(etf_symbols)} ETFs")
    try:
        fetcher.fetch_etf_data(etf_symbols)
    except Exception as e:
        logger.error(f"ETF data fetch failed: {e}")

    return True

