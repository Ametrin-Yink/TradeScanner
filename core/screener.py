"""Strategy screener - thin orchestrator using plugin architecture."""
import copy
import gc
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from core.fetcher import DataFetcher
from core.strategies import (
    create_strategy,
    get_all_strategies,
    StrategyType,
    StrategyMatch,
    STRATEGY_NAME_TO_LETTER,
    STRATEGY_METADATA,
)
from core.indicators import TechnicalIndicators
from core.market_regime import MarketRegimeDetector, REGIME_ALLOCATION_TABLE
from data.db import Database

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ['StrategyScreener', 'StrategyType', 'StrategyMatch']


class StrategyScreener:
    """Screen stocks using 6 trading strategies via plugin architecture."""

    # Dynamic allocation: total 30 candidates distributed by market regime
    TOTAL_CANDIDATES_TARGET = 30

    # Phase 0 pre-calculation thresholds (universal for all strategies)
    MIN_PRICE = 2.0
    MAX_PRICE = 3000.0
    MIN_VOLUME = 100000  # 100K daily average
    MIN_ADR_PCT = 0.03  # 3% minimum ADR - for backward compat

    # Strategy name to group mapping for allocation
    STRATEGY_NAME_TO_GROUP = {
        "MomentumBreakout": "breakout_momentum",
        "PullbackEntry": "trend_pullback",
        "SupportBounce": "rebound_range",
        "DistributionTop": "distribution_top",
        "AccumulationBottom": "accumulation_bottom",
        "CapitulationRebound": "extreme_reversal",
        "EarningsGap": "breakout_momentum",
        "RelativeStrengthLong": "trend_pullback",
    }

    # Phase 0: Data requirements
    MIN_HISTORY_DAYS = 200  # Maximum needed by any strategy (Momentum for EMA200)
    TARGET_HISTORY_DAYS = 280  # Target for RS calculation (52 weeks)

    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        db: Optional[Database] = None
    ):
        """Initialize screener with data fetcher and database."""
        self.fetcher = fetcher or DataFetcher()
        self.db = db or Database()
        self.earnings_calendar: Dict[str, pd.Timestamp] = {}
        self.market_data: Dict[str, pd.DataFrame] = {}
        self._market_regime: Optional[str] = None

        # Phase 0 pre-calculation cache (shared across all strategies)
        self._phase0_data: Dict[str, Dict] = {}
        self._spy_data: Optional[pd.DataFrame] = None
        self._spy_return_5d: float = 0.0

        # Initialize all strategy plugins (9 strategies with A1/A2 sub-modes)
        self._strategies = {}
        for strategy_type in [StrategyType.A1, StrategyType.A2, StrategyType.B,
                               StrategyType.C, StrategyType.D, StrategyType.E,
                               StrategyType.F, StrategyType.G, StrategyType.H]:
            self._strategies[strategy_type] = create_strategy(
                strategy_type, fetcher=self.fetcher, db=self.db
            )

        logger.info(f"Initialized {len(self._strategies)} strategy plugins")

    def _run_phase0_precalculation(
        self,
        symbols: List[str],
        market_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Dict]:
        """
        Phase 0: Universal pre-calculation for all symbols.

        Uses cached Tier 1 data from database if available (set by PreMarketPrep),
        otherwise calculates on-the-fly for backward compatibility.

        Returns:
            Dict mapping symbol to pre-calculated data
        """
        logger.info(f"Phase 0: Universal pre-calculation for {len(symbols)} symbols...")

        # Try to load Tier 3 data (SPY) from cache first
        spy_data = self._load_tier3_data('SPY')
        if spy_data is None:
            spy_data = self._get_data('SPY')
        self._spy_data = spy_data

        if self._spy_data is not None and len(self._spy_data) >= 5:
            spy_current = self._spy_data['close'].iloc[-1]
            spy_5d_ago = self._spy_data['close'].iloc[-5]
            self._spy_return_5d = (spy_current - spy_5d_ago) / spy_5d_ago if spy_5d_ago > 0 else 0.0
            logger.info(f"Phase 0: SPY 5-day return = {self._spy_return_5d:.2%}")

        # Try to load cached Tier 1 data
        cached_tier1 = self._load_tier1_cache(symbols)
        logger.info(f"Phase 0: Loaded {len(cached_tier1)} symbols from Tier 1 cache")

        phase0_data = {}
        rs_scores = []
        passed_basic = 0
        used_cache = 0
        calculated = 0

        for i, symbol in enumerate(symbols):
            # Batch processing: clear memory every 30 symbols to prevent OOM
            if i > 0 and i % 30 == 0:
                import gc
                gc.collect()
                logger.debug(f"Phase 0: Processed {i} symbols, garbage collected")

            # First try cached Tier 1 data
            if symbol in cached_tier1:
                cache_entry = cached_tier1[symbol]
                try:
                    # Get DataFrame from market_data or fetch temporarily
                    df = market_data.get(symbol)
                    if df is None:
                        df = self._get_data(symbol)
                    if df is None or len(df) < 50:
                        continue

                    # Calculate indicators (temporarily, don't store)
                    ind = TechnicalIndicators(df, symbol=symbol)
                    ind.calculate_all()

                    # Store ONLY scalar values - NO DataFrames or Indicator objects
                    phase0_data[symbol] = {
                        # Scalar metrics only - memory efficient
                        'current_price': cache_entry.get('current_price', 0),
                        'avg_volume': cache_entry.get('avg_volume_20d', 0),
                        'adr_pct': cache_entry.get('adr_pct', 0),
                        'atr': cache_entry.get('atr', 0),
                        'ret_3m': cache_entry.get('ret_3m', 0) or 0,
                        'ret_6m': cache_entry.get('ret_6m', 0) or 0,
                        'ret_12m': cache_entry.get('ret_12m', 0) or 0,
                        'ret_5d': cache_entry.get('ret_5d', 0) or 0,
                        'rs_raw': cache_entry.get('rs_raw', 0) or 0,
                        'rs_percentile': cache_entry.get('rs_percentile', 50),
                        'distance_from_52w_high': cache_entry.get('distance_from_52w_high', 0),
                        'ema21': cache_entry.get('ema21', 0),
                        'ema50': cache_entry.get('ema50', 0),
                        'ema200': cache_entry.get('ema200', 0),
                        'high_50d': cache_entry.get('high_60d', 0),
                        'volume_sma20': cache_entry.get('volume_sma', 0),
                        'data_days': cache_entry.get('data_days', len(df)),
                        # v7.0 Strategy G earnings data
                        'earnings_beat': cache_entry.get('earnings_beat', False),
                        'guidance_change': cache_entry.get('guidance_change', False),
                        'one_time_event': cache_entry.get('one_time_event', False),
                        'days_to_earnings': cache_entry.get('days_to_earnings'),
                        'earnings_date': cache_entry.get('earnings_date'),
                        'gap_1d_pct': cache_entry.get('gap_1d_pct', 0),
                        'gap_direction': cache_entry.get('gap_direction', 'none'),
                        # v7.0 Strategy G eligibility
                        'g_max_days': cache_entry.get('g_max_days'),
                        'days_post_earnings': cache_entry.get('days_post_earnings'),
                        'g_eligible': cache_entry.get('g_eligible', False),
                    }

                    # Delete temporary objects immediately
                    del df, ind

                    rs_scores.append({'symbol': symbol, 'rs': phase0_data[symbol]['rs_raw']})
                    used_cache += 1
                    continue  # Skip calculation
                except Exception as e:
                    logger.debug(f"Failed to use cache for {symbol}: {e}")

            # Fall back to calculation
            df = market_data.get(symbol)
            if df is None or len(df) < self.MIN_HISTORY_DAYS:
                continue

            try:
                current_price = df['close'].iloc[-1]
                avg_volume = df['volume'].tail(20).mean()

                # Phase 0.1: Basic filters (price and volume)
                if not (self.MIN_PRICE <= current_price <= self.MAX_PRICE):
                    continue
                if avg_volume < self.MIN_VOLUME:
                    continue

                passed_basic += 1
                calculated += 1

                # Phase 0.2: Calculate technical indicators
                ind = TechnicalIndicators(df)
                ind.calculate_all()

                # Phase 0.3: Calculate RS metrics
                returns = {}
                if len(df) >= 64:
                    price_3m_ago = df['close'].iloc[-63]
                    returns['3m'] = (current_price - price_3m_ago) / price_3m_ago
                if len(df) >= 127:
                    price_6m_ago = df['close'].iloc[-126]
                    returns['6m'] = (current_price - price_6m_ago) / price_6m_ago
                if len(df) >= 253:
                    price_12m_ago = df['close'].iloc[-252]
                    returns['12m'] = (current_price - price_12m_ago) / price_12m_ago

                # 5-day return
                if len(df) >= 6:
                    price_5d_ago = df['close'].iloc[-5]
                elif len(df) > 1:
                    price_5d_ago = df['close'].iloc[0]
                else:
                    price_5d_ago = current_price
                ret_5d = (current_price - price_5d_ago) / price_5d_ago if price_5d_ago > 0 else 0.0

                # Weighted average of available returns
                weights = {'3m': 0.4, '6m': 0.3, '12m': 0.3}
                total_weight = sum(weights.get(k, 0) for k in returns.keys())
                if total_weight > 0:
                    rs_raw = sum(returns.get(k, 0) * weights[k] for k in returns) / total_weight
                else:
                    rs_raw = 0.0

                ret_3m = returns.get('3m', 0.0)
                ret_6m = returns.get('6m', 0.0)
                ret_12m = returns.get('12m', 0.0)

                # Phase 0.4: 52-week metrics
                metrics_52w = ind.calculate_52w_metrics()

                # Fetch earnings data from Tier 1 cache (calculated in Phase 0)
                tier1_cache = self._load_tier1_cache([symbol])
                cache_entry = tier1_cache.get(symbol, {})

                # Store pre-calculated data - ONLY scalars, NO DataFrames/objects
                phase0_data[symbol] = {
                    # Scalar metrics only
                    'current_price': current_price,
                    'avg_volume': avg_volume,
                    'adr_pct': ind.indicators.get('adr', {}).get('adr_pct', 0),
                    'atr': ind.indicators.get('atr', {}).get('atr', 0),
                    'ret_3m': ret_3m,
                    'ret_6m': ret_6m,
                    'ret_12m': ret_12m,
                    'ret_5d': ret_5d,
                    'rs_raw': rs_raw,
                    'distance_from_52w_high': metrics_52w.get('distance_from_high', 1.0),
                    'ema21': ind.indicators.get('ema', {}).get('ema21', 0),
                    'ema50': ind.indicators.get('ema', {}).get('ema50', 0),
                    'ema200': ind.indicators.get('ema', {}).get('ema200', 0),
                    'high_50d': float(df['high'].tail(50).max()),
                    'volume_sma20': float(df['volume'].tail(20).mean()),
                    'data_days': len(df),
                    # v7.0 Strategy G earnings data (from Tier 1 cache)
                    'earnings_beat': cache_entry.get('earnings_beat', False),
                    'guidance_change': cache_entry.get('guidance_change', False),
                    'one_time_event': cache_entry.get('one_time_event', False),
                    'days_to_earnings': cache_entry.get('days_to_earnings'),
                    'earnings_date': cache_entry.get('earnings_date'),
                    'gap_1d_pct': cache_entry.get('gap_1d_pct', 0),
                    'gap_direction': cache_entry.get('gap_direction', 'none'),
                    # v7.0 Strategy G eligibility
                    'g_max_days': cache_entry.get('g_max_days'),
                    'days_post_earnings': cache_entry.get('days_post_earnings'),
                    'g_eligible': cache_entry.get('g_eligible', False),
                }

                # Delete temporary objects immediately to free memory
                del df, ind, metrics_52w

                rs_scores.append({'symbol': symbol, 'rs': rs_raw})

            except Exception as e:
                logger.warning(f"Phase 0: Error processing {symbol}: {e}")
                continue

        logger.info(f"Phase 0: {used_cache} from cache, {calculated} calculated, {len(phase0_data)} total")

        # Phase 0.5: Calculate RS percentiles
        if rs_scores:
            sorted_scores = sorted(rs_scores, key=lambda x: x['rs'])
            n = len(sorted_scores)

            for i, item in enumerate(sorted_scores):
                percentile = ((i + 1) / n) * 100
                if item['symbol'] in phase0_data:
                    phase0_data[item['symbol']]['rs_percentile'] = min(99.9, percentile)

        logger.info(f"Phase 0: Complete for {len(phase0_data)} symbols")
        return phase0_data

    def _load_tier1_cache(self, symbols: List[str]) -> Dict[str, Dict]:
        """Load Tier 1 cache from database for given symbols.

        Args:
            symbols: List of symbols to load

        Returns:
            Dict mapping symbol to cached Tier 1 data
        """
        cached = {}
        today = datetime.now().date()
        max_age_days = 2  # Accept cache up to 2 days old

        for symbol in symbols:
            try:
                data = self.db.get_tier1_cache(symbol)
                if data:
                    cache_date_str = data.get('cache_date')
                    if cache_date_str:
                        try:
                            cache_date = datetime.fromisoformat(cache_date_str).date()
                            days_old = (today - cache_date).days
                            if 0 <= days_old <= max_age_days:
                                cached[symbol] = data
                                continue
                        except (ValueError, TypeError):
                            pass
                    # Also accept if cache_date matches today's ISO format (backward compat)
                    if data.get('cache_date') == today.isoformat():
                        cached[symbol] = data
            except Exception as e:
                logger.debug(f"Failed to load Tier 1 cache for {symbol}: {e}")

        return cached

    def _load_tier3_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Load Tier 3 market data from cache.

        Args:
            symbol: Symbol to load (e.g., SPY, VIX)

        Returns:
            DataFrame or None
        """
        try:
            df = self.db.get_tier3_cache(symbol)
            if df is not None and not df.empty:
                logger.debug(f"Loaded Tier 3 cache for {symbol}: {len(df)} rows")
                return df
        except Exception as e:
            logger.debug(f"Failed to load Tier 3 cache for {symbol}: {e}")

        return None

    def _get_market_regime(self) -> str:
        """
        Get current market regime based on SPY vs EMA200.

        Returns:
            'bullish' if SPY > EMA200 and rising
            'bearish' if SPY < EMA200
            'neutral' otherwise or if no data
        """
        if self._market_regime is not None:
            return self._market_regime

        try:
            spy_df = self._get_data('SPY')
            if spy_df is None or len(spy_df) < 200:
                self._market_regime = 'neutral'
                return 'neutral'

            close = spy_df['close']
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema50_prev = close.ewm(span=50, adjust=False).mean().iloc[-10]

            if current_price > ema200:
                if ema50 > ema50_prev:
                    self._market_regime = 'bullish'
                else:
                    self._market_regime = 'neutral'
            else:
                self._market_regime = 'bearish'

            logger.info(f"Market regime: {self._market_regime} (SPY: ${current_price:.2f}, EMA200: ${ema200:.2f})")
            return self._market_regime

        except Exception as e:
            logger.warning(f"Could not determine market regime: {e}")
            self._market_regime = 'neutral'
            return 'neutral'

    def _allocate_candidates_by_strategy(
        self,
        all_candidates: List[StrategyMatch],
        strategy_slots: Dict[str, int]
    ) -> List[StrategyMatch]:
        """
        Allocate 30 candidates from global pool based on per-strategy slots.

        Args:
            all_candidates: All candidates from all strategies (global pool)
            strategy_slots: Target slots per strategy (e.g., {'MomentumBreakout': 4, ...})

        Returns:
            List of 30 selected StrategyMatch objects
        """
        from collections import defaultdict

        # Group candidates by strategy name
        strategy_candidates = defaultdict(list)
        for candidate in all_candidates:
            strategy_candidates[candidate.strategy].append(candidate)

        selected = []
        selected_symbols_strategies = set()  # Track (symbol, strategy) pairs

        # Phase 2.1: Select from each strategy according to slots
        for strategy, slots in strategy_slots.items():
            candidates = strategy_candidates.get(strategy, [])

            # Sort by score descending
            candidates.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

            # Select top N for this strategy (up to slot limit)
            selected_from_strategy = 0
            for candidate in candidates:
                if len(selected) >= self.TOTAL_CANDIDATES_TARGET:
                    break
                if selected_from_strategy >= slots:
                    break
                key = (candidate.symbol, candidate.strategy)
                if key not in selected_symbols_strategies:
                    selected.append(candidate)
                    selected_symbols_strategies.add(key)
                    selected_from_strategy += 1

            logger.info(f"[{strategy}] Selected {selected_from_strategy}/{len(candidates)} candidates (target: {slots})")

        # Phase 2.2: If underfilled, add from underrepresented strategies first
        if len(selected) < self.TOTAL_CANDIDATES_TARGET:
            needed = self.TOTAL_CANDIDATES_TARGET - len(selected)

            # Calculate how underfilled each strategy is
            strategy_fill_ratio = {}
            for strategy, slots in strategy_slots.items():
                strategy_count = len([c for c in selected if c.strategy == strategy])
                strategy_fill_ratio[strategy] = strategy_count / slots if slots > 0 else 1.0

            # Sort strategies by fill ratio (most underfilled first)
            underfilled_strategies = sorted(strategy_fill_ratio.keys(), key=lambda s: strategy_fill_ratio[s])

            # Add from underfilled strategies first
            for strategy in underfilled_strategies:
                if len(selected) >= self.TOTAL_CANDIDATES_TARGET:
                    break

                candidates = [c for c in strategy_candidates.get(strategy, [])
                             if (c.symbol, c.strategy) not in selected_symbols_strategies]
                candidates.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

                for candidate in candidates:
                    if len(selected) >= self.TOTAL_CANDIDATES_TARGET:
                        break
                    key = (candidate.symbol, candidate.strategy)
                    if key not in selected_symbols_strategies:
                        selected.append(candidate)
                        selected_symbols_strategies.add(key)

        # Sort final list by score descending
        selected.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

        return selected[:self.TOTAL_CANDIDATES_TARGET]

    def _allocate_by_table(
        self,
        all_candidates: List[StrategyMatch],
        allocation: Dict[str, int],
        regime: str
    ) -> List[StrategyMatch]:
        """
        Select candidates with duplicate handling and sector cap.
        If stock appears in multiple strategies, keep highest technical score.
        Apply soft sector cap of max 4 candidates per sector.
        Return up to 30 unique candidates.
        """
        from collections import defaultdict

        # Group candidates by strategy letter
        by_strategy = defaultdict(list)
        for c in all_candidates:
            letter = STRATEGY_NAME_TO_LETTER.get(c.strategy, '')
            if letter:
                by_strategy[letter].append(c)

        # Select top N per strategy and track unused slots
        selected_by_letter = {}
        unused_slots = 0  # Track slots not filled by strategies

        for letter, slots in allocation.items():
            if slots == 0:
                continue

            strategy_cands = by_strategy.get(letter, [])
            strategy_cands.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)
            actual_cands = strategy_cands[:slots]
            selected_by_letter[letter] = actual_cands

            # Track unused slots for redistribution
            if len(strategy_cands) < slots:
                unused_slots += slots - len(strategy_cands)
                logger.debug(f"Strategy {letter}: {len(strategy_cands)}/{slots} slots filled ({slots - len(strategy_cands)} unused)")

        logger.info(f"Slot allocation: {sum(len(v) for v in selected_by_letter.values())} candidates selected, {unused_slots} unused slots available for redistribution")

        # Redistribute unused slots to strategies with extra candidates
        if unused_slots > 0:
            logger.info(f"Redistributing {unused_slots} unused slots to strategies with extra candidates")

            # Find strategies with candidates beyond their allocated slots
            extra_candidates = []
            for letter, slots in allocation.items():
                if slots == 0:
                    continue
                strategy_cands = by_strategy.get(letter, [])
                if len(strategy_cands) > slots:
                    # Add candidates beyond allocated slots
                    for c in strategy_cands[slots:]:
                        extra_candidates.append((c, letter))

            # Sort extra candidates by score
            extra_candidates.sort(key=lambda x: x[0].technical_snapshot.get('score', 0), reverse=True)

            # Add top extra candidates up to unused slots
            added = 0
            for candidate, letter in extra_candidates:
                if added >= unused_slots:
                    break
                if letter not in selected_by_letter:
                    selected_by_letter[letter] = []
                selected_by_letter[letter].append(candidate)
                added += 1

            logger.info(f"Redistributed {added} extra candidates from strategies with surplus")

        # Flatten and handle duplicates with sector cap
        SECTOR_MAX = 4  # Soft cap per sector
        sector_counts = defaultdict(int)  # Track sector counts
        best_by_symbol = {}

        for letter, candidates in selected_by_letter.items():
            for c in candidates:
                symbol = c.symbol
                sector = c.technical_snapshot.get('sector', 'Unknown')
                current_score = c.technical_snapshot.get('score', 0)

                # Skip if sector already at cap (Unknown sector exempt from cap)
                if sector != 'Unknown' and sector_counts[sector] >= SECTOR_MAX:
                    logger.debug(f"Skipping {symbol} ({sector}): sector at cap ({sector_counts[sector]}/{SECTOR_MAX})")
                    continue

                if symbol not in best_by_symbol:
                    best_by_symbol[symbol] = c
                    if sector != 'Unknown':
                        sector_counts[sector] += 1
                else:
                    # Keep the one with higher technical score
                    existing_score = best_by_symbol[symbol].technical_snapshot.get('score', 0)
                    if current_score > existing_score:
                        # Decrement old sector count, increment new
                        old_sector = best_by_symbol[symbol].technical_snapshot.get('sector', 'Unknown')
                        if old_sector != 'Unknown' and old_sector != sector:
                            sector_counts[old_sector] -= 1
                        best_by_symbol[symbol] = c
                        if sector != 'Unknown':
                            sector_counts[sector] += 1

        # Convert to list (up to 30)
        selected = list(best_by_symbol.values())

        # Sort by score descending for consistent ordering
        selected.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

        # Limit to 30
        final = selected[:30]

        logger.info(f"Selected {len(final)} unique candidates (removed {len(selected) - len(final)} duplicates)")
        logger.info(f"Sector distribution: {dict(sector_counts)}")

        # Set regime on all
        for c in final:
            c.regime = regime

        return final

    def load_earnings_calendar(self, symbols: Optional[List[str]] = None):
        """Load earnings calendar for EP strategy."""
        self.earnings_calendar = self.fetcher.fetch_earnings_calendar(symbols)
        logger.info(f"Loaded {len(self.earnings_calendar)} earnings dates")

    def _get_data(self, symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol.

        Priority:
        1. In-memory cache (self.market_data) - fastest
        2. Database cache (market_data table) - fast, no network
        3. yfinance fetch - slow, rate-limited (fallback only)
        """
        # 1. Check in-memory cache first
        if symbol in self.market_data:
            return self.market_data[symbol]

        # 2. Check database cache (Phase 0 should have populated this)
        df = self.db.get_market_data_df(symbol)
        if df is not None and len(df) >= 200:
            self.market_data[symbol] = df  # Cache for subsequent calls
            return df

        # 3. Fallback to yfinance (should not happen if Phase 0 completed)
        logger.warning(f"No cached data for {symbol}, fetching from yfinance...")
        df = self.fetcher.fetch_stock_data(symbol, period=period, interval="1d")
        if df is not None:
            self.market_data[symbol] = df
        return df

    def _check_basic_requirements(self, df: pd.DataFrame, ind) -> bool:
        """
        Check basic requirements: ADR and volume (backward compatibility).

        Args:
            df: OHLCV DataFrame
            ind: TechnicalIndicators instance

        Returns:
            True if symbol passes all filters
        """
        try:
            adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
            volume_data = ind.indicators.get('volume', {})
            volume_sma = volume_data.get('volume_sma', 0)

            if adr_pct is None or adr_pct < self.MIN_ADR_PCT:
                return False

            if volume_sma is None or volume_sma < self.MIN_VOLUME:
                return False

            return True
        except (KeyError, IndexError, AttributeError, ValueError) as e:
            logger.debug(f"Basic requirements check failed: {e}")
            return False

    def screen(
        self,
        strategy_types: List[StrategyType],
        symbols: List[str],
        market_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> List[StrategyMatch]:
        """
        Screen symbols using specific strategy types.

        Args:
            strategy_types: List of strategy types to screen with
            symbols: List of stock symbols to screen
            market_data: Optional pre-loaded market data cache

        Returns:
            List of StrategyMatch
        """
        self.market_data = market_data or {}

        # Run Phase 0 pre-calculation
        # Note: _get_data() will load from database cache, no yfinance calls needed
        phase0_data = self._run_phase0_precalculation(symbols, self.market_data)

        all_matches = []

        for strategy_type in strategy_types:
            strategy = self._strategies.get(strategy_type)
            if not strategy:
                continue

            # Set SPY data for strategies that need it
            if hasattr(strategy, '_spy_df'):
                strategy._spy_df = self._spy_data

            # Run strategy screen
            matches = strategy.screen(symbols)
            all_matches.extend(matches)

        return all_matches

    def screen_all(
        self,
        symbols: List[str],
        regime: str = 'neutral',
        market_data: Optional[Dict[str, pd.DataFrame]] = None,
        batch_size: int = 100
    ) -> List[StrategyMatch]:
        """
        Screen all symbols using strategy plugins with regime-based allocation.

        Phase 1: Get allocation from regime table
        Phase 2: Run only strategies with slots > 0
        Phase 3: Select exactly N per strategy (no backfill)

        Args:
            symbols: List of stock symbols to screen
            regime: Market regime from MarketRegimeDetector
            market_data: Optional pre-loaded market data cache (must have 280+ days)
            batch_size: Number of symbols to process per batch (default 100)

        Returns:
            List of StrategyMatch (max 10 total, distributed per table)
        """
        self.market_data = market_data or {}

        # Get allocation from table
        detector = MarketRegimeDetector()
        allocation = detector.get_allocation(regime)

        logger.info(f"Regime: {regime}")
        logger.info(f"Allocation: {allocation}")

        # Filter to active strategies (slots > 0)
        active_strategies = {}
        for stype, strategy in self._strategies.items():
            # Map strategy to its letter (A-H)
            letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
            slots = allocation.get(letter, 0) if letter else 0
            if slots > 0:
                active_strategies[stype] = strategy
                logger.info(f"  {strategy.NAME} ({letter}): {slots} slots")
            else:
                logger.info(f"  {strategy.NAME} ({letter}): SKIPPED (0 slots)")

        # Run Phase 0 pre-calculation
        # Note: _get_data() will load from database cache, no yfinance calls needed
        self._phase0_data = self._run_phase0_precalculation(symbols, self.market_data)

        # Share data with active strategies
        for strategy in active_strategies.values():
            strategy.market_data = self.market_data
            strategy.phase0_data = self._phase0_data
            strategy.spy_return_5d = self._spy_return_5d
            strategy._spy_df = self._spy_data
            strategy._current_regime = regime

        # Phase 1: Screen with each active strategy
        all_candidates = []
        for stype, strategy in active_strategies.items():
            letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
            max_slots = allocation.get(letter, 0)
            candidates = strategy.screen(symbols, max_candidates=max_slots)
            all_candidates.extend(candidates)
            logger.info(f"{strategy.NAME}: {len(candidates)} candidates (max {max_slots})")

        # Phase 2: Allocate by table (strict, no backfill)
        selected = self._allocate_by_table(all_candidates, allocation, regime)

        return selected
