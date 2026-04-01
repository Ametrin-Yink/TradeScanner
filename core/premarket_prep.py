"""Phase 0: Pre-market data preparation.

Fetches universe, syncs database, fetches Tier 3 market data,
and calculates Tier 1 universal metrics for all symbols.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from core.stock_universe import StockUniverseManager
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators
from data.db import Database
from config.settings import settings

logger = logging.getLogger(__name__)


class PreMarketPrep:
    """Phase 0: Prepare all data before market opens at 6 AM ET.

    Steps:
    1. Fetch stock universe (>$2B market cap) from Finviz
    2. Sync with local database
    3. Fetch Tier 3 market data (SPY, VIX, Sector ETFs)
    4. Calculate Tier 1 universal metrics for all symbols
    """

    # Tier 3 symbols (market data)
    TIER3_SYMBOLS = {
        'benchmarks': ['SPY', 'QQQ', 'IWM'],
        'volatility': ['VIXY', 'UVXY'],
        'sectors': ['XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLV',
                   'XBI', 'SMH', 'IGV', 'IYT', 'KRE', 'XRT']
    }

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
                - symbols: List[str] - active universe symbols
                - tier3_data: Dict[str, pd.DataFrame] - market data
                - tier1_cache_count: int - number of symbols with Tier 1 cache
                - duration: int - execution time in seconds
                - errors: List[str] - any errors encountered
        """
        start_time = datetime.now()
        errors = []

        logger.info("=" * 50)
        logger.info("PHASE 0: Pre-Market Data Preparation")
        logger.info("=" * 50)

        # Step 1: Sync stock universe
        logger.info("\n[1/4] Syncing stock universe from Finviz...")
        try:
            sync_result = self.universe_manager.sync_universe()
            symbols = sync_result['symbols']
            logger.info(f"✓ Universe synced: {len(symbols)} symbols")
        except Exception as e:
            logger.error(f"✗ Universe sync failed: {e}")
            errors.append(f"Universe sync: {e}")
            # Fall back to existing symbols
            symbols = self.db.get_active_stocks()
            logger.info(f"Using existing {len(symbols)} symbols from database")

        # Step 2: Fetch Tier 3 market data
        logger.info("\n[2/4] Fetching Tier 3 market data...")
        tier3_data = self._fetch_tier3_data()
        logger.info(f"✓ Tier 3 data fetched: {len(tier3_data)} symbols")

        # Step 3: Update market data for all symbols
        logger.info("\n[3/4] Updating market data for all symbols...")
        fetch_stats = self._update_market_data(symbols)
        logger.info(f"✓ Market data updated: {fetch_stats['success']}/{fetch_stats['total']} symbols")
        if fetch_stats['failed'] > 0:
            logger.warning(f"  Failed: {fetch_stats['failed']} symbols")
            errors.extend(fetch_stats['errors'])

        # Step 4: Calculate Tier 1 universal metrics
        logger.info("\n[4/4] Calculating Tier 1 universal metrics...")
        tier1_count = self._calculate_tier1_cache(symbols)
        logger.info(f"✓ Tier 1 cache calculated: {tier1_count} symbols")

        duration = (datetime.now() - start_time).total_seconds()

        logger.info("\n" + "=" * 50)
        logger.info(f"PHASE 0 Complete in {duration:.1f}s")
        logger.info("=" * 50)

        return {
            'success': len(errors) == 0,
            'symbols': symbols,
            'tier3_data': tier3_data,
            'tier1_cache_count': tier1_count,
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
        all_symbols = (
            self.TIER3_SYMBOLS['benchmarks'] +
            self.TIER3_SYMBOLS['volatility'] +
            self.TIER3_SYMBOLS['sectors']
        )

        for symbol in all_symbols:
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

        return {
            'total': total,
            'success': success,
            'failed': failed,
            'errors': errors[:10]  # First 10 errors only
        }

    def _calculate_tier1_cache(self, symbols: List[str]) -> int:
        """Calculate Tier 1 universal metrics for all symbols.

        Args:
            symbols: List of stock symbols

        Returns:
            Number of symbols successfully cached
        """
        cached_count = 0
        total = len(symbols)

        for i, symbol in enumerate(symbols):
            if (i + 1) % 100 == 0:
                logger.info(f"  Calculating Tier 1: {i + 1}/{total}...")

            try:
                # Get market data from database
                df = self._get_symbol_data(symbol)
                if df is None or len(df) < 50:
                    continue

                # Calculate Tier 1 metrics
                metrics = self._calculate_tier1_metrics(symbol, df)
                if metrics:
                    self.db.save_tier1_cache(symbol, metrics)
                    cached_count += 1

            except Exception as e:
                logger.debug(f"Failed to calculate Tier 1 for {symbol}: {e}")

        return cached_count

    def _get_symbol_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get market data from database for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame with OHLCV data or None
        """
        try:
            conn = self.db.get_connection()
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
                'data_days': len(df)
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
