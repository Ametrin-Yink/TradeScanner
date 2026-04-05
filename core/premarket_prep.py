"""Phase 0: Pre-market data preparation.

Initializes stock database, fetches Tier 3 market data,
fetches market data for all stocks, and calculates Tier 1 universal metrics.
Stocks with market cap <$2B are filtered out during pre-calculation.
"""
import gc
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from core.stock_universe import StockUniverseManager, get_all_market_etfs
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators
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
        logger.info("\n[1/5] Initializing stock database...")
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
        logger.info("\n[2/5] Fetching Tier 3 market data...")
        tier3_data = self._fetch_tier3_data()
        logger.info(f"✓ Tier 3 data fetched: {len(tier3_data)} symbols")

        # Step 3: Update market data for all symbols (stocks + ETFs)
        logger.info("\n[3/5] Updating market data for all symbols...")
        all_symbols = self.db.get_active_stocks()
        fetch_stats = self._update_market_data(all_symbols)
        logger.info(f"✓ Market data updated: {fetch_stats['success']}/{fetch_stats['total']} symbols")
        if fetch_stats['failed'] > 0:
            logger.warning(f"  Failed: {fetch_stats['failed']} symbols")
            errors.extend(fetch_stats['errors'])

        # Step 4: Apply pre-filter (market cap, price, volume)
        logger.info("\n[4/5] Applying pre-filter criteria...")
        prefilter_stats = self._apply_prefilter()
        qualifying_stocks = prefilter_stats['qualifying_stocks']
        logger.info(f"✓ Pre-filter: {len(qualifying_stocks)} stocks passed")
        logger.info(f"  (market cap >=$2B, price $2-3000, volume >=100K)")

        # Step 5: Update earnings dates (conditional, memory-optimized)
        logger.info("\n[5/5] Updating earnings dates...")
        self._update_earnings_dates(qualifying_stocks)

        # Step 6: Calculate Tier 1 universal metrics
        logger.info("\n[6/6] Calculating Tier 1 universal metrics...")
        tier1_count = self._calculate_tier1_cache(qualifying_stocks)
        logger.info(f"✓ Tier 1 cache calculated: {tier1_count} symbols")

        duration = (datetime.now() - start_time).total_seconds()

        logger.info("\n" + "=" * 50)
        logger.info(f"PHASE 0 Complete in {duration:.1f}s")
        logger.info(f"  Stocks for screening: {len(qualifying_stocks)}")
        logger.info(f"  Market ETFs: {len(self.universe_manager.get_market_etfs())}")
        logger.info("=" * 50)

        # Phase 0 is successful if we have qualifying stocks and Tier 1 cache
        # Some errors (e.g., delisted stocks) are expected and shouldn't fail the phase
        phase0_success = len(qualifying_stocks) > 0 and tier1_count > 0

        return {
            'success': phase0_success,
            'symbols': qualifying_stocks,
            'etfs': self.universe_manager.get_market_etfs(),
            'tier3_data': tier3_data,
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
        """Update market data for all symbols using incremental fetch.

        Args:
            symbols: List of stock symbols

        Returns:
            Dict with fetch statistics
        """
        success = 0
        failed = 0
        errors = []

        # Process in batches to avoid memory issues
        total = len(symbols)

        for i in range(0, total, self.batch_size):
            batch = symbols[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size

            logger.info(f"Fetching batch {batch_num}/{total_batches}: {len(batch)} symbols")

            for symbol in batch:
                try:
                    df = self.fetcher.fetch_stock_data(symbol, use_cache=True)
                    if df is not None and not df.empty:
                        success += 1
                    else:
                        failed += 1
                        errors.append(f"{symbol}: No data returned")
                except Exception as e:
                    failed += 1
                    errors.append(f"{symbol}: {e}")

            logger.debug(f"  Batch complete: {success} success, {failed} failed")

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
        """Update earnings dates only for stocks with expired/missing cache.

        Optimized to use ticker.calendar (4 quarters only) instead of
        ticker.earnings_dates (full history) to reduce memory usage.
        Smaller batch sizes with aggressive cleanup between batches.

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
        # Reduced from 50 to 20 to prevent yfinance memory buildup
        batch_size = 20
        updated = 0
        total_batches = (len(needs_update) + batch_size - 1) // batch_size

        for i in range(0, len(needs_update), batch_size):
            batch = needs_update[i:i + batch_size]
            logger.info(f"  Earnings batch {i//batch_size + 1}/{total_batches}: {len(batch)} stocks")

            for symbol in batch:
                try:
                    # Use ticker.calendar instead of earnings_dates
                    # calendar returns dict with 'Earnings Date' as a list
                    # earnings_dates returns full history DataFrame (memory-heavy)
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
                                            self.db.update_stock_earnings_date(symbol, date.isoformat())
                                            updated += 1
                                            break
                                    except:
                                        continue

                    # Explicit cleanup - delete in reverse order of creation
                    if 'calendar' in locals():
                        del calendar
                    if 'ticker' in locals():
                        del ticker

                except Exception as e:
                    logger.debug(f"Failed to fetch earnings for {symbol}: {e}")

            # Aggressive GC after each batch
            gc.collect()
            import time
            # Increased sleep time to allow memory release
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
        Calculate accumulation ratio: avg volume on up-days / avg volume on down-days.
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
            avg_vol_up = up_days[volume_col].mean() if len(up_days) > 0 else 0
            avg_vol_down = down_days[volume_col].mean() if len(down_days) > 0 else 0
        else:
            recent['price_change'] = recent['close'].diff()
            up_days = recent[recent['price_change'] > 0]
            down_days = recent[recent['price_change'] < 0]
            avg_vol_up = up_days['volume'].mean() if len(up_days) > 0 else 0
            avg_vol_down = down_days['volume'].mean() if len(down_days) > 0 else 0

        if avg_vol_down == 0:
            return 1.0

        return avg_vol_up / avg_vol_down

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

            # ATR/ADR
            atr = ind.get('atr', {}).get('atr14', df['high'].tail(14).mean() - df['low'].tail(14).mean())
            atr_pct = (atr / current_price * 100) if current_price > 0 else 0
            adr = ind.get('adr', {}).get('adr20', df['high'].tail(20).mean() - df['low'].tail(20).mean())
            adr_pct = (adr / current_price * 100) if current_price > 0 else 0

            # Returns (3m, 6m, 12m, 5d)
            close = df['close']
            ret_3m = (close.iloc[-1] / close.iloc[-min(63, len(close))] - 1) * 100 if len(close) >= 63 else None
            ret_6m = (close.iloc[-1] / close.iloc[-min(126, len(close))] - 1) * 100 if len(close) >= 126 else None
            ret_12m = (close.iloc[-1] / close.iloc[-min(252, len(close))] - 1) * 100 if len(close) >= 252 else None
            ret_5d = (close.iloc[-1] / close.iloc[-min(5, len(close))] - 1) * 100 if len(close) >= 5 else None

            # RS scores
            rs_raw = ret_3m if ret_3m is not None else 0
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
            rsi = ind.get('rsi', {}).get('rsi14', 50)

            # NEW: Calculate accum_ratio_15d (for Strategy H)
            accum_ratio = self._calculate_accum_ratio(df, days=15)

            # NEW: Calculate gap metrics (for Strategy G)
            gap_1d_pct = (df['open'].iloc[-1] / df['close'].iloc[-2] - 1) if len(df) >= 2 else 0
            gap_direction = 'up' if gap_1d_pct > 0.02 else ('down' if gap_1d_pct < -0.02 else 'none')

            # NEW: Get earnings date from DB cache (already populated by Step 5)
            today = datetime.now().date()
            earnings_date = self.db.get_stock_earnings_date(symbol)
            days_to_earnings = None
            if earnings_date:
                try:
                    ed = datetime.fromisoformat(earnings_date).date()
                    days_to_earnings = (ed - today).days
                except:
                    pass  # Invalid date format

            # NEW: Determine G-eligibility by gap size
            # days_post_earnings: days since earnings (positive = after earnings)
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

            # NEW: Detect VCP platform (Task 12a)
            vcp_data = indicators.detect_vcp_platform(
                lookback_range=(15, 60),
                max_range_pct=0.12,
                concentration_threshold=0.50
            )

            vcp_detected = vcp_data is not None and vcp_data.get('is_valid', False)
            vcp_tightness = vcp_data.get('platform_range_pct') if vcp_data else None
            vcp_volume_ratio = vcp_data.get('volume_contraction_ratio') if vcp_data else None

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
                'gap_1d_pct': gap_1d_pct,
                'gap_direction': gap_direction,
                # v7.0 Strategy G eligibility
                'g_max_days': g_max_days,
                'days_post_earnings': days_post_earnings,
                'g_eligible': g_eligible,
                # v7.0 Task 12a: VCP pre-calculation
                'vcp_detected': vcp_detected,
                'vcp_tightness': vcp_tightness,
                'vcp_volume_ratio': vcp_volume_ratio,
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


def run_premarket_prep() -> Dict:
    """Convenience function to run Phase 0 preparation.

    Returns:
        Phase 0 results dict
    """
    prep = PreMarketPrep()
    return prep.run_phase0()
