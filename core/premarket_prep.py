"""Phase 0: Pre-market data preparation.

Initializes stock database, fetches Tier 3 market data,
fetches market data for all stocks, calculates Tier 1 universal metrics,
and pre-calculates all ETF data (market/sector ETFs).
Stocks with market cap <$2B are filtered out during pre-calculation.
"""
import gc
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from core.stock_universe import StockUniverseManager, get_all_market_etfs
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators
from core.etf_prep import ETFPreCalculator
from core.constants import SECTOR_ETFS
from data.db import Database
from config.settings import settings

logger = logging.getLogger(__name__)


class PreMarketPrep:
    """Phase 0: Prepare all data before market opens at 6 AM ET.

    Steps:
    1. Initialize stock database from CSV (stocks + market ETFs)
    2. Fetch Tier 3 market data (SPY, VIX, Sector ETFs)
    3. Fetch market data for all stocks
    4. Update market cap from yfinance
    5. Filter stocks by market cap (>=$2B)
    6. Calculate Tier 1 universal metrics for qualifying stocks
    6b. Update RS percentiles across universe
    7. Pre-calculate ETF data (market/sector ETFs)
    """

    # Minimum market cap for screening ($2B)
    MIN_MARKET_CAP = 2e9

    # Price range filter
    MIN_PRICE = 2.0
    MAX_PRICE = 3000.0

    # Minimum average volume (100K)
    MIN_AVG_VOLUME = 100000

    def __init__(
        self,
        db: Optional[Database] = None,
        max_workers: int = 4,
        batch_size: int = 50
    ):
        self.db = db or Database()
        self.fetcher = DataFetcher(db=self.db)
        self.universe_manager = StockUniverseManager(db=self.db)
        self.max_workers = max_workers
        self.batch_size = batch_size

    def run_phase0(self) -> Dict:
        """Execute complete Phase 0 data preparation.

        Returns:
            Dict with phase results:
                - success: bool
                - symbols: List[str] - stocks passing market cap filter
                - etfs: List[str] - market index ETFs
                - tier3_data: Dict[str, pd.DataFrame] - market data
                - etf_cache: Dict[str, Dict] - pre-calculated ETF data
                - tier1_cache_count: int - number of symbols with Tier 1 cache
                - market_cap_filtered: int - number of stocks filtered out
                - duration: int - execution time in seconds
                - errors: List[str] - any errors encountered
        """
        start_time = datetime.now()
        errors = []

        logger.info("=" * 50)
        logger.info("PHASE 0: Pre-Market Data Preparation")
        logger.info("=" * 50)

        # Step 1: Initialize stock database
        logger.info("\n[1/6] Initializing stock database...")
        try:
            init_result = self.universe_manager.initialize_database()
            all_stocks = init_result['symbols']
            logger.info(f"✓ Database initialized: {len(all_stocks)} total symbols")
            logger.info(f"  - Stocks: {self.universe_manager.get_stocks_count()}")
            logger.info(f"  - ETFs: {self.universe_manager.get_etfs_count()}")
        except Exception as e:
            logger.error(f"✗ Database initialization failed: {e}")
            errors.append(f"Database init: {e}")
            all_stocks = self.db.get_active_stocks()

        # Step 2: Fetch Tier 3 market data
        logger.info("\n[2/6] Fetching Tier 3 market data...")
        tier3_data = self._fetch_tier3_data()
        logger.info(f"✓ Tier 3 data fetched: {len(tier3_data)} symbols")

        # Step 3: Update market data for all symbols (stocks + ETFs)
        logger.info("\n[3/6] Updating market data for all symbols...")
        all_symbols = self.db.get_active_stocks()
        fetch_stats = self._update_market_data(all_symbols)
        logger.info(f"✓ Market data updated: {fetch_stats['success']}/{fetch_stats['total']} symbols")
        if fetch_stats['failed'] > 0:
            logger.warning(f"  Failed: {fetch_stats['failed']} symbols")
            errors.extend(fetch_stats['errors'])

        # Step 4: Apply pre-filter (market cap, price, volume)
        logger.info("\n[4/6] Applying pre-filter criteria...")
        prefilter_stats = self._apply_prefilter()
        qualifying_stocks = prefilter_stats['qualifying_stocks']
        logger.info(f"✓ Pre-filter: {len(qualifying_stocks)} stocks passed")
        logger.info(f"  (market cap >=$2B, price $2-3000, volume >=100K)")

        # Step 5: Update earnings dates (conditional, memory-optimized)
        logger.info("\n[5/6] Updating earnings dates...")
        self._update_earnings_dates(qualifying_stocks)

        # Step 6: Calculate Tier 1 universal metrics
        logger.info("\n[6/7] Calculating Tier 1 universal metrics...")
        tier1_count = self._calculate_tier1_cache(qualifying_stocks)
        logger.info(f"✓ Tier 1 cache calculated: {tier1_count} symbols")

        # Step 6b: Update RS percentiles across universe
        logger.info("\n[6b/7] Updating RS percentiles...")
        self.update_rs_percentiles()

        # Step 7: Pre-calculate ETF data (market/sector ETFs)
        logger.info("\n[7/7] Pre-calculating ETF data...")
        etf_prep = ETFPreCalculator(db=self.db)
        etf_cache = etf_prep.calculate_all_etfs()
        logger.info(f"✓ ETF pre-calculation complete: {len(etf_cache)} ETFs cached")

        duration = (datetime.now() - start_time).total_seconds()

        logger.info("\n" + "=" * 50)
        logger.info(f"PHASE 0 Complete in {duration:.1f}s")
        logger.info(f"  Stocks for screening: {len(qualifying_stocks)}")
        logger.info(f"  Market ETFs: {len(self.universe_manager.get_market_etfs())}")
        logger.info(f"  ETF cache: {len(etf_cache)} ETFs")
        logger.info("=" * 50)

        # Phase 0 is successful if we have qualifying stocks and Tier 1 cache
        # Some errors (e.g., delisted stocks) are expected and shouldn't fail the phase
        phase0_success = len(qualifying_stocks) > 0 and tier1_count > 0

        return {
            'success': phase0_success,
            'symbols': qualifying_stocks,
            'etfs': self.universe_manager.get_market_etfs(),
            'tier3_data': tier3_data,
            'etf_cache': etf_cache,
            'tier1_cache_count': tier1_count,
            'prefilter_stats': prefilter_stats,
            'duration': int(duration),
            'errors': errors,
            'fetch_stats': fetch_stats
        }

    def _fetch_tier3_data(self) -> Dict[str, pd.DataFrame]:
        """Fetch and cache Tier 3 market data.

        Returns:
            Dict mapping symbol to DataFrame
        """
        tier3_data = {}
        etf_symbols = get_all_market_etfs()

        for symbol in etf_symbols:
            try:
                df = self.fetcher.fetch_stock_data(symbol, period="13mo", interval="1d")
                if df is not None and not df.empty:
                    tier3_data[symbol] = df
                    # Cache in database
                    self.db.save_tier3_cache(symbol, df)
                    logger.debug(f"Fetched Tier 3 data: {symbol} ({len(df)} rows)")
                else:
                    logger.warning(f"No data for Tier 3 symbol: {symbol}")
            except Exception as e:
                logger.error(f"Failed to fetch Tier 3 data for {symbol}: {e}")

        return tier3_data

    def _update_market_data(self, symbols: List[str]) -> Dict:
        """Update market data for all symbols using batch fetch with caching.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict with fetch statistics
        """
        success = 0
        failed = 0
        errors = []
        total = len(symbols)

        logger.info(f"Fetching market data for {total} symbols (batch mode, cache enabled)...")

        # Process in batches to avoid memory issues AND respect rate limits
        # With max_workers=4 and request_delay=0.15s, effective rate is ~27 req/sec
        for i in range(0, total, self.batch_size):
            batch = symbols[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size

            logger.info(f"Fetching batch {batch_num}/{total_batches}: {len(batch)} symbols")

            # Use batch fetch with parallel workers (4 workers, 0.15s delay between requests)
            results = self.fetcher.fetch_multiple(batch, period="13mo", interval="1d", use_cache=True)

            success += len(results)
            batch_failed = len(batch) - len(results)
            failed += batch_failed

            if batch_failed > 0:
                failed_symbols = [s for s in batch if s not in results]
                errors.extend([f"{s}: No data returned" for s in failed_symbols])

            logger.debug(f"  Batch complete: {len(results)} success, {batch_failed} failed")

            # Rate limit pause between batches to avoid yfinance throttling
            # 0.1s per symbol in batch, capped at 5 seconds
            if i + self.batch_size < total:
                pause = min(5.0, 0.1 * len(batch))
                time.sleep(pause)

            # Memory cleanup between batches
            import gc
            gc.collect()

        return {
            'total': total,
            'success': success,
            'failed': failed,
            'errors': errors[:10]  # First 10 errors only
        }

    def _apply_prefilter(self) -> Dict:
        """Apply pre-filter criteria to select stocks for screening.

        Criteria:
        - Market cap >= $2B (always fetched from yfinance)
        - Price between $2-$3000 (from latest market data)
        - Average volume >= 100K (from latest 20 days)

        Returns:
            Dict with:
                - qualifying_stocks: List of symbols passing all filters
                - filtered_by_cap: Count filtered by market cap
                - filtered_by_price: Count filtered by price
                - filtered_by_volume: Count filtered by volume
                - total_stocks: Total stocks checked
        """
        from data.db import db

        stocks = self.universe_manager.get_stocks(min_market_cap=None)
        total_stocks = len(stocks)

        logger.info(f"Applying pre-filter to {total_stocks} stocks...")
        logger.info(f"  Criteria: market cap >= $2B, price ${self.MIN_PRICE}-{self.MAX_PRICE}, volume >= {self.MIN_AVG_VOLUME:,}")

        qualifying_stocks = []
        filtered_by_cap = 0
        filtered_by_price = 0
        filtered_by_volume = 0

        for i, symbol in enumerate(stocks):
            if (i + 1) % 500 == 0:
                logger.info(f"  Checked {i + 1}/{total_stocks} stocks...")

            try:
                # Get latest market data
                with db.get_connection() as conn:
                    cursor = conn.execute(
                        """SELECT close, volume FROM market_data
                        WHERE symbol = ? ORDER BY date DESC LIMIT 20""",
                        (symbol,)
                    )
                    rows = cursor.fetchall()

                if len(rows) < 5:  # Need at least 5 days of data
                    continue

                latest_price = rows[0][0]
                avg_volume = sum(r[1] for r in rows) / len(rows)

                # Check 1: Price range ($2 - $3000)
                if latest_price < self.MIN_PRICE or latest_price > self.MAX_PRICE:
                    filtered_by_price += 1
                    continue

                # Check 2: Volume (>= 100K average)
                if avg_volume < self.MIN_AVG_VOLUME:
                    filtered_by_volume += 1
                    continue

                # Check 3: Market cap (>= $2B) - use cached value from database
                # Market cap is fetched during data fetch phase (fetcher.py:211)
                # This avoids 2,921 individual HTTP requests to yfinance!
                stock_info = self.db.get_stock_info_full(symbol)
                market_cap = stock_info.get('market_cap', 0) if stock_info else 0

                if market_cap < self.MIN_MARKET_CAP:
                    filtered_by_cap += 1
                    continue

                # All checks passed
                qualifying_stocks.append(symbol)

            except Exception as e:
                logger.debug(f"Could not pre-filter {symbol}: {e}")
                continue

        total_filtered = total_stocks - len(qualifying_stocks)

        logger.info(f"Pre-filter complete:")
        logger.info(f"  Total stocks: {total_stocks}")
        logger.info(f"  Qualifying: {len(qualifying_stocks)}")
        logger.info(f"  Filtered by market cap (<$2B): {filtered_by_cap}")
        logger.info(f"  Filtered by price (not $2-3000): {filtered_by_price}")
        logger.info(f"  Filtered by volume (<100K): {filtered_by_volume}")

        return {
            'qualifying_stocks': qualifying_stocks,
            'filtered_by_cap': filtered_by_cap,
            'filtered_by_price': filtered_by_price,
            'filtered_by_volume': filtered_by_volume,
            'total_stocks': total_stocks
        }

    def _update_earnings_dates(self, symbols: List[str]):
        """Update earnings dates for stocks with expired/missing cache.

        Uses ticker.calendar (4 quarters only) instead of
        ticker.earnings_dates (full history) to reduce memory usage.

        Args:
            symbols: List of stock symbols
        """
        today = datetime.now().date()

        # Find stocks needing earnings update
        needs_update = []
        for symbol in symbols:
            cached_date = self.db.get_stock_earnings_date(symbol)
            if not cached_date:
                needs_update.append(symbol)
            else:
                # Check if earnings has passed
                try:
                    cached_dt = datetime.fromisoformat(cached_date).date()
                    if cached_dt < today:
                        needs_update.append(symbol)
                except:
                    needs_update.append(symbol)  # Invalid date format, refetch

        if not needs_update:
            logger.info("  All earnings dates up to date")
            return

        logger.info(f"  Fetching earnings for {len(needs_update)}/{len(symbols)} stocks")

        # Fetch in small batches with aggressive memory cleanup
        batch_size = 20
        updated = 0
        total_batches = (len(needs_update) + batch_size - 1) // batch_size

        for i in range(0, len(needs_update), batch_size):
            batch = needs_update[i:i + batch_size]
            logger.info(f"  Earnings batch {i//batch_size + 1}/{total_batches}: {len(batch)} stocks")

            for symbol in batch:
                try:
                    ticker = yf.Ticker(symbol)
                    calendar = ticker.calendar

                    earnings_date = None
                    if calendar and 'Earnings Date' in calendar:
                        earnings_dates = calendar['Earnings Date']
                        if earnings_dates and isinstance(earnings_dates, list):
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
                                            earnings_date = date.isoformat()
                                            self.db.update_stock_earnings_date(symbol, earnings_date)
                                            updated += 1
                                            break
                                    except:
                                        continue

                    # Explicit cleanup
                    if 'calendar' in locals():
                        del calendar
                    if 'ticker' in locals():
                        del ticker

                except Exception as e:
                    logger.debug(f"Failed to fetch earnings for {symbol}: {e}")

            # Aggressive GC after each batch
            gc.collect()
            time.sleep(0.5)

        logger.info(f"  Updated earnings dates for {updated} stocks")

    def _calculate_tier1_cache(self, symbols: List[str]) -> int:
        """Calculate Tier 1 universal metrics for all symbols.

        Args:
            symbols: List of stock symbols

        Returns:
            Number of symbols successfully cached
        """
        cached_count = 0
        total = len(symbols)
        batch_size = 200  # Process in batches to control memory

        logger.info(f"  Processing {total} stocks in batches of {batch_size}...")

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = symbols[batch_start:batch_end]

            logger.info(f"  Batch {(batch_start // batch_size) + 1}/{(total + batch_size - 1) // batch_size}: {batch_start + 1}-{batch_end}")

            for i, symbol in enumerate(batch):
                global_idx = batch_start + i
                if (global_idx + 1) % 50 == 0:
                    logger.info(f"    Progress: {global_idx + 1}/{total}...")

                try:
                    # Get market data from database
                    df = self._get_symbol_data(symbol)
                    if df is None or len(df) < 50:
                        continue

                    # Calculate Tier 1 metrics (earnings already cached in Step 5)
                    metrics = self._calculate_tier1_metrics(symbol, df)
                    if metrics:
                        self.db.save_tier1_cache(symbol, metrics)
                        cached_count += 1

                    # Explicit cleanup after each symbol
                    del df
                    if (global_idx + 1) % 20 == 0:
                        gc.collect()

                except Exception as e:
                    logger.debug(f"Failed to calculate Tier 1 for {symbol}: {e}")

            # Force garbage collection between batches
            gc.collect()
            logger.debug(f"  Batch complete. Memory cleaned.")

        return cached_count

    def _get_symbol_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get market data from database for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame with OHLCV data or None
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    """SELECT date, open, high, low, close, volume
                       FROM market_data WHERE symbol = ? ORDER BY date""",
                    (symbol,)
                )
                rows = cursor.fetchall()

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

            return df

        except Exception as e:
            logger.debug(f"Failed to get data for {symbol}: {e}")
            return None

    def _calculate_accum_ratio(self, df: pd.DataFrame, days: int = 15) -> float:
        """
        Calculate accumulation ratio: sum volume on up-days / sum volume on down-days.

        Per Strategy Description v7.0:
        accum_ratio = sum(vol on up-days, 15d) / sum(vol on down-days, 15d)
        """
        if len(df) < days:
            return 1.0

        recent = df.tail(days).copy()

        # Handle multi-level columns from yfinance
        if isinstance(recent.columns, pd.MultiIndex):
            close_col = ('close', recent.columns[0][1]) if recent.columns[0][1] else 'close'
            volume_col = ('volume', recent.columns[0][1]) if recent.columns[0][1] else 'volume'
            recent['price_change'] = recent[close_col].diff()
            up_days = recent[recent['price_change'] > 0]
            down_days = recent[recent['price_change'] < 0]
            sum_vol_up = up_days[volume_col].sum() if len(up_days) > 0 else 0
            sum_vol_down = down_days[volume_col].sum() if len(down_days) > 0 else 0
        else:
            recent['price_change'] = recent['close'].diff()
            up_days = recent[recent['price_change'] > 0]
            down_days = recent[recent['price_change'] < 0]
            sum_vol_up = up_days['volume'].sum() if len(up_days) > 0 else 0
            sum_vol_down = down_days['volume'].sum() if len(down_days) > 0 else 0

        if sum_vol_down == 0:
            return 1.0

        return sum_vol_up / sum_vol_down

    def _get_current_date(self) -> datetime:
        """Get current date. Extracted for testability.

        Returns:
            Current date
        """
        return datetime.now().date()

    def _is_data_stale(self, df: Optional[pd.DataFrame], max_stale_days: int = 2) -> bool:
        """
        Check if data is stale (no update within N trading days).

        Handles weekend edge case: Friday data is valid on Monday/Tuesday.
        Also handles holidays: Thursday data is valid on Monday after a Friday holiday.

        Args:
            df: OHLCV DataFrame
            max_stale_days: Maximum days since last update (default 2)

        Returns:
            True if data is stale and should be excluded
        """
        if df is None or len(df) == 0:
            return True

        last_date = df.index[-1]
        today = self._get_current_date()

        # Handle timezone-aware indices and pandas Timestamps
        if hasattr(last_date, 'date'):
            last_date = last_date.date()

        # Calculate calendar days since last update
        days_since_update = (today - last_date).days

        # Weekend handling: Friday data is valid on Monday/Tuesday
        if last_date.weekday() == 4:  # Last update was Friday
            # Monday (0) or Tuesday (1) is acceptable for Friday data
            if today.weekday() in [0, 1]:  # Today is Monday or Tuesday
                return False

        # Holiday handling: Thursday data is valid on Monday after a Friday holiday
        # (e.g., Good Friday, when markets are closed)
        if last_date.weekday() == 3:  # Last update was Thursday
            if today.weekday() == 0:  # Today is Monday
                # 3 calendar days but only 1 trading day (Friday was a holiday)
                return False

        # For other days, require update within max_stale_days
        return days_since_update > max_stale_days

    def _calculate_tier1_metrics(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """Calculate Tier 1 universal metrics for a symbol.

        Args:
            symbol: Stock symbol
            df: DataFrame with OHLCV data

        Returns:
            Dict with Tier 1 metrics or None
        """
        try:
            if len(df) < 50:
                return None

            # v7.0 Task 12b: Stale data guard
            if self._is_data_stale(df, max_stale_days=2):
                logger.debug(f"STALE_REJ: {symbol} - Data not updated within 2 days")
                return None

            indicators = TechnicalIndicators(df, symbol=symbol)
            ind = indicators.calculate_all()

            if not ind:
                return None

            # Current price
            current_price = df['close'].iloc[-1]

            # Volume metrics
            avg_volume_20d = df['volume'].tail(20).mean()
            volume_sma = ind.get('volume', {}).get('sma20', avg_volume_20d)
            volume_ratio = df['volume'].iloc[-1] / volume_sma if volume_sma > 0 else 1.0

            # EMAs
            ema_data = ind.get('ema', {})
            ema8 = ema_data.get('ema8', df['close'].ewm(span=8).mean().iloc[-1])
            ema21 = ema_data.get('ema21', df['close'].ewm(span=21).mean().iloc[-1])
            ema50 = ema_data.get('ema50', df['close'].ewm(span=50).mean().iloc[-1])
            ema200 = ema_data.get('ema200', df['close'].ewm(span=200).mean().iloc[-1])

            # ATR/ADR (decimal format, not percentage)
            atr = ind.get('atr', {}).get('atr', df['high'].tail(14).mean() - df['low'].tail(14).mean())
            atr_pct = (atr / current_price) if current_price > 0 else 0
            adr = ind.get('adr', {}).get('adr', df['high'].tail(20).mean() - df['low'].tail(20).mean())
            adr_pct = (adr / current_price) if current_price > 0 else 0

            # Returns (3m, 6m, 12m, 5d) - use 0 for insufficient data
            close = df['close']
            ret_3m = (close.iloc[-1] / close.iloc[-63] - 1) * 100 if len(close) >= 63 else 0.0
            ret_6m = (close.iloc[-1] / close.iloc[-126] - 1) * 100 if len(close) >= 126 else 0.0
            ret_12m = (close.iloc[-1] / close.iloc[-252] - 1) * 100 if len(close) >= 252 else 0.0
            ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0.0

            # RS scores
            rs_raw = ret_3m
            rs_percentile = 50.0  # Will be calculated across universe

            # 52-week metrics
            high_52w = df['high'].tail(252).max() if len(df) >= 252 else df['high'].max()
            distance_from_52w_high = (current_price / high_52w - 1) * 100 if high_52w > 0 else 0

            # 60-day range
            high_60d = df['high'].tail(60).max() if len(df) >= 60 else df['high'].max()
            low_60d = df['low'].tail(60).min() if len(df) >= 60 else df['low'].min()

            # Gaps (days with >2% gap)
            gaps = (df['open'] / df['close'].shift(1) - 1).abs()
            gaps_5d = (gaps.tail(5) > 0.02).sum()

            # RSI
            rsi = ind.get('rsi', {}).get('rsi', 50)

            # Accumulation ratio (Strategy H)
            accum_ratio = self._calculate_accum_ratio(df, days=15)

            # Gap metrics (Strategy G)
            gap_1d_pct = (df['open'].iloc[-1] / df['close'].iloc[-2] - 1) if len(df) >= 2 else 0
            gap_direction = 'up' if gap_1d_pct > 0.02 else ('down' if gap_1d_pct < -0.02 else 'none')

            # Gap volume ratio (Strategy G): gap day volume vs 20-day average
            gap_volume_ratio = (df['volume'].iloc[-1] / avg_volume_20d) if avg_volume_20d > 0 else 1.0

            # Earnings date from DB cache
            earnings_date = self.db.get_stock_earnings_date(symbol)
            days_to_earnings = None
            earnings_beat = False
            guidance_change = False
            one_time_event = False

            if earnings_date:
                try:
                    today = datetime.now().date()
                    ed = datetime.fromisoformat(earnings_date).date()
                    days_to_earnings = (ed - today).days
                except:
                    pass

            # Fetch earnings surprise data from DB (Strategy G)
            earnings_data = self.db.get_stock_earnings_data(symbol)
            if earnings_data:
                earnings_beat = earnings_data.get('earnings_beat', False)
                guidance_change = earnings_data.get('guidance_change', False)
                one_time_event = earnings_data.get('one_time_event', False)

            # G-eligibility by gap size
            days_post_earnings = -days_to_earnings if days_to_earnings and days_to_earnings < 0 else None
            g_max_days = None
            g_eligible = False

            if days_post_earnings is not None and gap_1d_pct is not None:
                abs_gap = abs(gap_1d_pct)
                if abs_gap >= 0.10:
                    g_max_days = 5
                elif abs_gap >= 0.07:
                    g_max_days = 3
                else:
                    g_max_days = 2

                g_eligible = (days_post_earnings >= 1 and days_post_earnings <= g_max_days)

            # VCP platform detection - use defaults if no valid pattern
            vcp_data = indicators.detect_vcp_platform(
                lookback_range=(15, 60),
                max_range_pct=0.12,
                concentration_threshold=0.50
            )

            vcp_detected = vcp_data is not None and vcp_data.get('is_valid', False)
            # Use defaults: 12% range (max allowed), 1.0 volume ratio (no contraction) if no VCP
            vcp_tightness = vcp_data.get('platform_range_pct') if vcp_data else 0.12
            vcp_volume_ratio = vcp_data.get('volume_contraction_ratio') if vcp_data else 1.0

            # Support/resistance levels (Strategies C, D)
            from core.support_resistance import SupportResistanceCalculator
            sr_calc = SupportResistanceCalculator(df)
            sr_levels = sr_calc.calculate_all()
            supports = sr_levels.get('support', [])
            resistances = sr_levels.get('resistance', [])

            # Nearest support/resistance distance (use large value if no level found)
            nearest_support = max([s for s in supports if s < current_price], default=None)
            nearest_resistance = min([r for r in resistances if r > current_price], default=None)
            # Use 999% as "no level found" sentinel value
            nearest_support_distance_pct = (current_price - nearest_support) / current_price if nearest_support else 999.0
            nearest_resistance_distance_pct = (nearest_resistance - current_price) / current_price if nearest_resistance else 999.0

            # Consecutive down-days (Strategy F)
            consecutive_down_days = 0
            for i in range(1, min(10, len(df))):
                if df['close'].iloc[-i] < df['close'].iloc[-i-1]:
                    consecutive_down_days += 1
                else:
                    break

            # RS consecutive days ≥80th percentile (Strategy H)
            # Get previous value from cache and update based on current RS
            prev_tier1 = self.db.get_tier1_cache(symbol)
            prev_rs_consecutive = prev_tier1.get('rs_consecutive_days_80', 0) if prev_tier1 else 0
            # Will be updated after RS percentile is calculated across universe
            rs_consecutive_days_80 = prev_rs_consecutive  # Placeholder, updated in update_rs_percentiles()

            # EMA21 slope normalized (Strategy B)
            ema21_5d_ago = df['close'].ewm(span=21).mean().iloc[-6] if len(df) >= 6 else ema21 * 0.99
            ema21_slope_norm = (ema21 - ema21_5d_ago) / atr if atr > 0 else 0

            # Pullback from high (Strategy B)
            high_20d = df['high'].tail(20).max()
            pullback_from_high_pct = (high_20d - current_price) / high_20d if high_20d > 0 else 0

            # Distance to EMA8 (Strategy B)
            distance_to_ema8_pct = abs(current_price - ema8) / ema8 if ema8 > 0 else 0

            # Sector info (multiple strategies)
            stock_info = self.db.get_stock_info_full(symbol)
            sector = stock_info.get('sector', '') if stock_info else ''
            sector_etf_symbol = self._get_sector_etf_symbol(sector)

            # Sector alignment (Strategy G): check if sector ETF trend confirms gap direction
            sector_aligned = False
            if sector_etf_symbol:
                sector_etf_data = self.db.get_tier1_cache(sector_etf_symbol)
                if sector_etf_data:
                    sector_etf_price = sector_etf_data.get('current_price', 0)
                    sector_etf_ema21 = sector_etf_data.get('ema21', 0)
                    if sector_etf_price > 0 and sector_etf_ema21 > 0:
                        if gap_direction == 'up' and sector_etf_price > sector_etf_ema21:
                            sector_aligned = True
                        elif gap_direction == 'down' and sector_etf_price < sector_etf_ema21:
                            sector_aligned = True

            return {
                'cache_date': datetime.now().date().isoformat(),
                'current_price': current_price,
                'avg_volume_20d': avg_volume_20d,
                'volume_ratio': volume_ratio,
                'volume_sma': volume_sma,
                'ema8': ema8,
                'ema21': ema21,
                'ema50': ema50,
                'ema200': ema200,
                'atr': atr,
                'atr_pct': atr_pct,
                'adr': adr,
                'adr_pct': adr_pct,
                'ret_3m': ret_3m,
                'ret_6m': ret_6m,
                'ret_12m': ret_12m,
                'ret_5d': ret_5d,
                'rs_raw': rs_raw,
                'rs_percentile': rs_percentile,
                'distance_from_52w_high': distance_from_52w_high,
                'high_60d': high_60d,
                'low_60d': low_60d,
                'gaps_5d': int(gaps_5d),
                'rsi_14': rsi,
                'data_days': len(df),
                'accum_ratio_15d': accum_ratio,
                'days_to_earnings': days_to_earnings,
                'earnings_date': earnings_date,
                'earnings_beat': earnings_beat,
                'guidance_change': guidance_change,
                'one_time_event': one_time_event,
                'gap_1d_pct': gap_1d_pct,
                'gap_direction': gap_direction,
                'gap_volume_ratio': gap_volume_ratio,
                # v7.0 Strategy G eligibility
                'g_max_days': g_max_days,
                'days_post_earnings': days_post_earnings,
                'g_eligible': g_eligible,
                # v7.0 Task 12a: VCP pre-calculation
                'vcp_detected': vcp_detected,
                'vcp_tightness': vcp_tightness,
                'vcp_volume_ratio': vcp_volume_ratio,
                # v7.1: Support/Resistance levels (Strategies C, D)
                'supports': supports[:5],  # Top 5 support levels
                'resistances': resistances[:5],  # Top 5 resistance levels
                'nearest_support_distance_pct': nearest_support_distance_pct,
                'nearest_resistance_distance_pct': nearest_resistance_distance_pct,
                # v7.1: Consecutive down-days (Strategy F)
                'consecutive_down_days': consecutive_down_days,
                # v7.1: RS consecutive days ≥80th percentile (Strategy H)
                'rs_consecutive_days_80': rs_consecutive_days_80,
                # v7.1: EMA21 slope normalized (Strategy B)
                'ema21_slope_norm': ema21_slope_norm,
                # v7.1: Pullback from high (Strategy B)
                'pullback_from_high_pct': pullback_from_high_pct,
                # v7.1: Distance to EMA8 (Strategy B)
                'distance_to_ema8_pct': distance_to_ema8_pct,
                # v7.1: Sector info (multiple strategies)
                'sector': sector,
                'sector_etf_symbol': sector_etf_symbol,
                'sector_aligned': sector_aligned,
            }

        except Exception as e:
            logger.debug(f"Error calculating Tier 1 for {symbol}: {e}")
            return None

    def get_cached_tier1(self, symbol: str) -> Optional[Dict]:
        """Get cached Tier 1 metrics for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dict with Tier 1 metrics or None
        """
        return self.db.get_tier1_cache(symbol)

    def get_cached_tier3(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get cached Tier 3 market data for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame with market data or None
        """
        return self.db.get_tier3_cache(symbol)

    def _get_sector_etf_symbol(self, sector: str) -> Optional[str]:
        """Get sector ETF symbol for a given sector.

        Args:
            sector: Sector name (e.g., 'Technology', 'Financials')

        Returns:
            ETF symbol or None
        """
        return SECTOR_ETFS.get(sector)

    def update_rs_percentiles(self) -> int:
        """Calculate and update universe-wide RS percentile rankings.

        Per Strategy Description v7.0:
        RS_pct = percentile_rank(stock_63d_return / SPY_63d_return, universe)

        This calculates RELATIVE strength (vs SPY), not just absolute returns.

        Returns:
            Number of symbols updated
        """
        logger.info("  Calculating universe-wide RS percentiles...")

        # Fetch SPY 63-day return for normalization
        spy_df = self.db.get_tier3_cache('SPY')
        if spy_df is None or len(spy_df) < 63:
            logger.warning("  SPY data unavailable for RS normalization, using absolute returns")
            spy_ret_63d = 0.0  # Flat market assumption
        else:
            spy_ret_63d = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-63] - 1) * 100

        logger.info(f"  SPY 63-day return: {spy_ret_63d:.2f}%")

        # Get all rs_raw values from database
        all_rs_data = self.db.get_all_rs_raw_values()

        if not all_rs_data:
            logger.warning("  No rs_raw values found for RS percentile calculation")
            return 0

        total_stocks = len(all_rs_data)
        logger.info(f"  Calculating percentiles for {total_stocks} stocks...")

        # Calculate SPY-relative return for each stock, then percentile rank
        # Formula: relative_return = (1 + stock_ret_63d/100) / (1 + spy_ret_63d/100) - 1
        # Then convert to percentage for ranking
        stock_relative_returns = []
        for data in all_rs_data:
            symbol = data['symbol']
            stock_ret_63d = data['rs_raw']  # Already in percentage form

            # Handle edge case: SPY return near -100% (theoretical, practically 0)
            if (1 + spy_ret_63d / 100) <= 0.01:
                # SPY down >99%, use absolute return as fallback
                relative_return_pct = stock_ret_63d
            else:
                # SPY-relative return formula
                relative_return = (1 + stock_ret_63d / 100) / (1 + spy_ret_63d / 100) - 1
                relative_return_pct = relative_return * 100

            stock_relative_returns.append({
                'symbol': symbol,
                'relative_return': relative_return_pct
            })

        # Sort by relative return (highest first)
        stock_relative_returns.sort(key=lambda x: x['relative_return'], reverse=True)

        # Calculate percentile for each stock
        # Percentile formula: (rank - 1) / (total - 1) * 100
        # Rank 0 (highest relative_return) = 100th percentile
        # Rank N-1 (lowest relative_return) = 0th percentile
        rs_percentiles = {}
        for rank, data in enumerate(stock_relative_returns):
            symbol = data['symbol']
            if total_stocks > 1:
                percentile = (total_stocks - rank - 1) / (total_stocks - 1) * 100
            else:
                percentile = 50.0  # Single stock, use neutral

            rs_percentiles[symbol] = round(percentile, 2)

        # Bulk update database
        self.db.bulk_update_rs_percentiles(rs_percentiles)

        # Update RS consecutive days ≥80th percentile (Strategy H)
        logger.info("  Updating RS consecutive days ≥80th percentile...")
        rs_consecutive_updates = {}
        for symbol, percentile in rs_percentiles.items():
            # Get previous consecutive days count
            prev_tier1 = self.db.get_tier1_cache(symbol)
            prev_consecutive = prev_tier1.get('rs_consecutive_days_80') if prev_tier1 else 0
            prev_consecutive = prev_consecutive or 0  # Handle None values from DB

            # Update based on current RS percentile
            if percentile >= 80:
                rs_consecutive_updates[symbol] = prev_consecutive + 1
            else:
                rs_consecutive_updates[symbol] = 0  # Reset if below 80th percentile

        # Bulk update consecutive days
        self.db.bulk_update_rs_consecutive_days(rs_consecutive_updates)

        logger.info(f"  RS percentiles updated for {len(rs_percentiles)} stocks")
        return len(rs_percentiles)


def run_premarket_prep() -> Dict:
    """Convenience function to run Phase 0 preparation.

    Returns:
        Phase 0 results dict
    """
    prep = PreMarketPrep()
    return prep.run_phase0()
