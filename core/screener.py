"""Strategy screener - thin orchestrator using plugin architecture."""
import copy
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

        # Preload Tier 3 ETF data into memory
        self._tier3_data: Dict[str, pd.DataFrame] = {}
        tier3_symbols = ['SPY', 'QQQ', 'IWM', '^VIX', 'VIXY', 'UVXY',
                         'XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY',
                         'XLB', 'XLU', 'XLV', 'XBI', 'SMH', 'IGV',
                         'IYT', 'KRE', 'XRT']
        for sym in tier3_symbols:
            try:
                df = self.db.get_tier3_cache(sym)
                if df is not None and not df.empty:
                    self._tier3_data[sym] = df
            except Exception:
                pass

        # Preload Tier 1 cache into memory
        self._tier1_cache_all: Dict[str, Dict] = {}
        try:
            self._tier1_cache_all = self.db.get_all_tier1_cache()
        except Exception:
            pass

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
                        'ema8': cache_entry.get('ema8', 0),
                        'ema21': cache_entry.get('ema21', 0),
                        'ema50': cache_entry.get('ema50', 0),
                        'ema200': cache_entry.get('ema200', 0),
                        'high_60d': cache_entry.get('high_60d', 0),
                        'low_60d': cache_entry.get('low_60d', 0),
                        'volume_sma20': cache_entry.get('volume_sma', 0),
                        'volume_ratio': cache_entry.get('volume_ratio', 1.0),
                        'data_days': cache_entry.get('data_days', len(df)),
                        'rsi_14': cache_entry.get('rsi_14', 50),
                        # v7.0 Strategy G earnings data
                        'earnings_beat': cache_entry.get('earnings_beat', False),
                        'guidance_change': cache_entry.get('guidance_change', False),
                        'one_time_event': cache_entry.get('one_time_event', False),
                        'days_to_earnings': cache_entry.get('days_to_earnings'),
                        'days_since_earnings': cache_entry.get('days_since_earnings'),
                        'earnings_date': cache_entry.get('earnings_date'),
                        'gap_1d_pct': cache_entry.get('gap_1d_pct', 0),
                        'gap_direction': cache_entry.get('gap_direction', 'none'),
                        'gap_volume_ratio': cache_entry.get('gap_volume_ratio', 1.0),
                        # v7.0 Strategy G eligibility
                        'g_max_days': cache_entry.get('g_max_days'),
                        'days_post_earnings': cache_entry.get('days_post_earnings'),
                        'g_eligible': cache_entry.get('g_eligible', False),
                        # v7.1: Sector alignment
                        'sector_aligned': cache_entry.get('sector_aligned', False),
                        # v7.1: All missing keys from Tier 1 cache
                        'rsi_14': cache_entry.get('rsi_14', 50),
                        'rs_consecutive_days_80': cache_entry.get('rs_consecutive_days_80', 0),
                        'accum_ratio_15d': cache_entry.get('accum_ratio_15d', 1.0),
                        'consecutive_down_days': cache_entry.get('consecutive_down_days', 0),
                        'resistances': [float(x) for x in cache_entry.get('resistances', [])],
                        'supports': [float(x) for x in cache_entry.get('supports', [])],
                        'nearest_resistance_distance_pct': cache_entry.get('nearest_resistance_distance_pct', 999.0),
                        'nearest_support_distance_pct': cache_entry.get('nearest_support_distance_pct', 999.0),
                        'ema21_slope_norm': cache_entry.get('ema21_slope_norm', 0),
                        'pullback_from_high_pct': cache_entry.get('pullback_from_high_pct', 0),
                        'distance_to_ema8_pct': cache_entry.get('distance_to_ema8_pct', 0),
                        'sector': cache_entry.get('sector', ''),
                        'vcp_detected': cache_entry.get('vcp_detected', False),
                        'vcp_tightness': cache_entry.get('vcp_tightness', 0.12),
                        'vcp_volume_ratio': cache_entry.get('vcp_volume_ratio', 1.0),
                        'earnings_surprise_pct': cache_entry.get('earnings_surprise_pct'),
                    }

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

                # Fetch earnings data from already-loaded Tier 1 cache
                cache_entry = cached_tier1.get(symbol, {})

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
                    'rs_percentile': 50,  # Will be updated after percentile calculation
                    'distance_from_52w_high': metrics_52w.get('distance_from_high', 1.0),
                    'ema8': ind.indicators.get('ema', {}).get('ema8', 0),
                    'ema21': ind.indicators.get('ema', {}).get('ema21', 0),
                    'ema50': ind.indicators.get('ema', {}).get('ema50', 0),
                    'ema200': ind.indicators.get('ema', {}).get('ema200', 0),
                    'high_60d': float(df['high'].tail(60).max()),
                    'low_60d': float(df['low'].tail(60).min()),
                    'volume_sma20': float(df['volume'].tail(20).mean()),
                    'volume_ratio': ind.indicators.get('volume', {}).get('volume_ratio', 1.0),
                    'data_days': len(df),
                    'rsi_14': ind.indicators.get('rsi', {}).get('rsi', 50),
                    # v7.0 Strategy G earnings data (from Tier 1 cache)
                    'earnings_beat': cache_entry.get('earnings_beat', False),
                    'guidance_change': cache_entry.get('guidance_change', False),
                    'one_time_event': cache_entry.get('one_time_event', False),
                    'days_to_earnings': cache_entry.get('days_to_earnings'),
                    'days_since_earnings': cache_entry.get('days_since_earnings'),
                    'earnings_date': cache_entry.get('earnings_date'),
                    'gap_1d_pct': cache_entry.get('gap_1d_pct', 0),
                    'gap_direction': cache_entry.get('gap_direction', 'none'),
                    'gap_volume_ratio': cache_entry.get('gap_volume_ratio', 1.0),
                    # v7.0 Strategy G eligibility
                    'g_max_days': cache_entry.get('g_max_days'),
                    'days_post_earnings': cache_entry.get('days_post_earnings'),
                    'g_eligible': cache_entry.get('g_eligible', False),
                    # v7.1: Sector alignment
                    'sector_aligned': cache_entry.get('sector_aligned', False),
                    # v7.1: All missing keys from Tier 1 cache
                    'rsi_14': ind.indicators.get('rsi', {}).get('rsi', 50),
                    'rs_consecutive_days_80': cache_entry.get('rs_consecutive_days_80', 0),
                    'accum_ratio_15d': cache_entry.get('accum_ratio_15d', 1.0),
                    'consecutive_down_days': self._calc_consecutive_down_days(df),
                    'resistances': cache_entry.get('resistances', []),
                    'supports': cache_entry.get('supports', []),
                    'nearest_resistance_distance_pct': cache_entry.get('nearest_resistance_distance_pct', 999.0),
                    'nearest_support_distance_pct': cache_entry.get('nearest_support_distance_pct', 999.0),
                    'ema21_slope_norm': self._calc_ema21_slope_norm(ind, df),
                    'pullback_from_high_pct': self._calc_pullback_pct(df),
                    'distance_to_ema8_pct': self._calc_distance_to_ema8(df, ind),
                    'sector': cache_entry.get('sector', ''),
                    'vcp_detected': cache_entry.get('vcp_detected', False),
                    'vcp_tightness': cache_entry.get('vcp_tightness', 0.12),
                    'vcp_volume_ratio': cache_entry.get('vcp_volume_ratio', 1.0),
                    'earnings_surprise_pct': cache_entry.get('earnings_surprise_pct'),
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

        Uses preloaded _tier1_cache_all from __init__ to avoid per-symbol queries.

        Args:
            symbols: List of symbols to load

        Returns:
            Dict mapping symbol to cached Tier 1 data
        """
        all_cache = getattr(self, '_tier1_cache_all', {})
        if not all_cache:
            try:
                all_cache = self.db.get_all_tier1_cache()
            except Exception:
                return {}

        today = datetime.now().date()
        max_age_days = 2
        cached = {}

        for symbol in symbols:
            data = all_cache.get(symbol)
            if not data:
                continue
            cache_date_str = data.get('cache_date')
            if not cache_date_str:
                continue
            try:
                cache_date = datetime.fromisoformat(cache_date_str).date()
                days_old = (today - cache_date).days
                if 0 <= days_old <= max_age_days:
                    cached[symbol] = data
            except (ValueError, TypeError):
                pass

        return cached

    def _load_tier3_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Load Tier 3 market data from cache.

        Args:
            symbol: Symbol to load (e.g., SPY, VIX)

        Returns:
            DataFrame or None
        """
        if symbol in self._tier3_data:
            logger.debug(f"Loaded Tier 3 from memory for {symbol}: {len(self._tier3_data[symbol])} rows")
            return self._tier3_data[symbol]

        try:
            df = self.db.get_tier3_cache(symbol)
            if df is not None and not df.empty:
                self._tier3_data[symbol] = df  # Cache in memory
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

        Fallback: if < 30 after normal allocation, round-robin fill from
        remaining candidates of all strategies until 30.
        """
        from collections import defaultdict

        SECTOR_MAX = 4

        # Group candidates by strategy letter, sorted by score
        by_strategy = defaultdict(list)
        for c in all_candidates:
            letter = STRATEGY_NAME_TO_LETTER.get(c.strategy, '')
            if letter:
                by_strategy[letter].append(c)
        for letter in by_strategy:
            by_strategy[letter].sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

        # Step 1: select top N per strategy from allocation
        selected_by_letter = {}
        for letter, slots in allocation.items():
            selected_by_letter[letter] = by_strategy.get(letter, [])[:slots]

        total_selected = sum(len(v) for v in selected_by_letter.values())
        logger.info(f"Initial allocation: {total_selected} candidates from strategy slots")

        # Step 2: round-robin fill if < 30
        if total_selected < 30:
            selected_symbols = set()
            for letter, cands in selected_by_letter.items():
                for c in cands:
                    selected_symbols.add(c.symbol)

            # Build remaining pools per strategy (unselected candidates)
            remaining = {}
            for letter, cands in by_strategy.items():
                pool = [c for c in cands if c.symbol not in selected_symbols]
                if pool:
                    remaining[letter] = pool

            # Round-robin across strategies, one from each per pass
            added = 0
            while added < 30 - total_selected and remaining:
                any_added = False
                for letter in list(remaining.keys()):
                    if added >= 30 - total_selected:
                        break
                    pool = remaining[letter]
                    candidate = pool.pop(0)
                    # Skip duplicates
                    if candidate.symbol in selected_symbols:
                        continue
                    if not pool:
                        del remaining[letter]
                    selected_symbols.add(candidate.symbol)
                    selected_by_letter[letter].append(candidate)
                    added += 1
                    any_added = True
                if not any_added:
                    break

            logger.info(f"Round-robin fill: +{added} candidates, total {total_selected + added}")

        # Step 3: flatten, deduplicate (keep best score), sector cap
        sector_counts = defaultdict(int)
        best_by_symbol = {}

        for letter, candidates in selected_by_letter.items():
            for c in candidates:
                symbol = c.symbol
                sector = c.technical_snapshot.get('sector', 'Unknown')
                current_score = c.technical_snapshot.get('score', 0)

                if sector != 'Unknown' and sector_counts[sector] >= SECTOR_MAX:
                    logger.debug(f"Skipping {symbol} ({sector}): sector at cap")
                    continue

                if symbol not in best_by_symbol:
                    best_by_symbol[symbol] = c
                    if sector != 'Unknown':
                        sector_counts[sector] += 1
                else:
                    existing_score = best_by_symbol[symbol].technical_snapshot.get('score', 0)
                    if current_score > existing_score:
                        old_sector = best_by_symbol[symbol].technical_snapshot.get('sector', 'Unknown')
                        if old_sector != 'Unknown':
                            sector_counts[old_sector] -= 1
                        best_by_symbol[symbol] = c
                        if sector != 'Unknown':
                            sector_counts[sector] += 1

        final = list(best_by_symbol.values())
        final.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)
        final = final[:30]

        # Backfill if dedup reduced us below 30
        if len(final) < 30:
            selected_symbols = set(c.symbol for c in final)
            sector_counts_final = defaultdict(int)
            for c in final:
                sector = c.technical_snapshot.get('sector', 'Unknown')
                if sector != 'Unknown':
                    sector_counts_final[sector] += 1

            # Build remaining pool sorted by score
            remaining_pool = []
            for letter, cands in by_strategy.items():
                for c in cands:
                    if c.symbol not in selected_symbols:
                        remaining_pool.append(c)
            remaining_pool.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

            for c in remaining_pool:
                if len(final) >= 30:
                    break
                if c.symbol in selected_symbols:
                    continue
                sector = c.technical_snapshot.get('sector', 'Unknown')
                if sector != 'Unknown' and sector_counts_final.get(sector, 0) >= SECTOR_MAX:
                    continue
                final.append(c)
                selected_symbols.add(c.symbol)
                if sector != 'Unknown':
                    sector_counts_final[sector] += 1

        final.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)
        final = final[:30]

        # Recompute sector counts for logging
        sector_final = defaultdict(int)
        for c in final:
            sector = c.technical_snapshot.get('sector', 'Unknown')
            if sector != 'Unknown':
                sector_final[sector] += 1

        logger.info(f"Final: {len(final)} unique candidates")
        logger.info(f"Sector distribution: {dict(sector_final)}")

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

    def _calc_consecutive_down_days(self, df: pd.DataFrame) -> int:
        """Count consecutive down days at end of series (Strategy F)."""
        count = 0
        for i in range(1, min(10, len(df))):
            if df['close'].iloc[-i] < df['close'].iloc[-i - 1]:
                count += 1
            else:
                break
        return count

    def _calc_ema21_slope_norm(self, ind, df: pd.DataFrame) -> float:
        """Calculate normalized EMA21 slope (Strategy B)."""
        ema21 = ind.indicators.get('ema', {}).get('ema21', 0)
        atr = ind.indicators.get('atr', {}).get('atr', 1)
        ema21_5d_ago = df['close'].ewm(span=21).mean().iloc[-6] if len(df) >= 6 else ema21 * 0.99
        return (ema21 - ema21_5d_ago) / atr if atr > 0 else 0

    def _calc_pullback_pct(self, df: pd.DataFrame) -> float:
        """Calculate pullback from 20d high (Strategy B)."""
        current_price = df['close'].iloc[-1]
        high_20d = df['high'].tail(20).max()
        return (high_20d - current_price) / high_20d if high_20d > 0 else 0

    def _calc_distance_to_ema8(self, df: pd.DataFrame, ind) -> float:
        """Calculate distance to EMA8 (Strategy B)."""
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        return abs(current_price - ema8) / ema8 if ema8 > 0 else 0

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
            List of StrategyMatch (max 30 total, distributed per table)
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
        # Screen extra to ensure round-robin/backfill has enough candidates to reach 30
        EXTRA_SCREEN = 10
        all_candidates = []
        for stype, strategy in active_strategies.items():
            letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
            max_slots = allocation.get(letter, 0)
            screen_count = max_slots + EXTRA_SCREEN
            candidates = strategy.screen(symbols, max_candidates=screen_count)
            all_candidates.extend(candidates)
            logger.info(f"{strategy.NAME}: {len(candidates)} candidates (max {max_slots} slots, screened {screen_count})")

        # Phase 2: Allocate by table (strict, no backfill)
        selected = self._allocate_by_table(all_candidates, allocation, regime)

        return selected
