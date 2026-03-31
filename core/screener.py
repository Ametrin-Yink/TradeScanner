"""Strategy screener - thin orchestrator using plugin architecture."""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd

from core.fetcher import DataFetcher
from core.strategies import (
    create_strategy,
    get_all_strategies,
    StrategyType,
    StrategyMatch,
)
from core.indicators import TechnicalIndicators
from data.db import Database

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ['StrategyScreener', 'StrategyType', 'StrategyMatch']


class StrategyScreener:
    """Screen stocks using 8 trading strategies via plugin architecture."""

    # Dynamic allocation: total 30 candidates distributed by market regime
    TOTAL_CANDIDATES_TARGET = 30

    # Phase 0 pre-calculation thresholds (universal for all strategies)
    MIN_PRICE = 2.0
    MAX_PRICE = 3000.0
    MIN_VOLUME = 100000  # 100K daily average
    MIN_ADR_PCT = 0.03  # 3% minimum ADR - for backward compat

    # Strategy group mapping for dynamic allocation
    STRATEGY_GROUPS = {
        StrategyType.EP: 'breakout_momentum',
        StrategyType.MOMENTUM: 'breakout_momentum',
        StrategyType.SHORYUKEN: 'trend_pullback',
        StrategyType.PULLBACKS: 'trend_pullback',
        StrategyType.UPTHRUST_REBOUND: 'rebound_range',
        StrategyType.RANGE_SUPPORT: 'rebound_range',
        StrategyType.DTSS: 'rebound_range',
        StrategyType.PARABOLIC: 'extreme_reversal',
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

        # Initialize all strategy plugins
        self._strategies = {}
        for strategy_type in StrategyType:
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

        This runs ONCE before any strategy screening and computes:
        1. Basic filters: price ($2-3000), volume (>100K)
        2. Technical indicators: ATR, ADR, EMAs
        3. RS scores: 3m/6m/12m returns + percentile ranking
        4. SPY data: 5-day return for relative strength
        5. 52-week metrics: distance from high

        Returns:
            Dict mapping symbol to pre-calculated data
        """
        logger.info(f"Phase 0: Starting universal pre-calculation for {len(symbols)} symbols...")

        # Get SPY data first (for RS calculations)
        self._spy_data = self._get_data('SPY')
        if self._spy_data is not None and len(self._spy_data) >= 5:
            spy_current = self._spy_data['close'].iloc[-1]
            spy_5d_ago = self._spy_data['close'].iloc[-5]
            self._spy_return_5d = (spy_current - spy_5d_ago) / spy_5d_ago
            logger.info(f"Phase 0: SPY 5-day return = {self._spy_return_5d:.2%}")

        phase0_data = {}
        rs_scores = []
        passed_basic = 0

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < 60:  # Absolute minimum for any calculation
                continue
            if len(df) < self.MIN_HISTORY_DAYS:
                logger.debug(f"Phase 0: {symbol} has {len(df)} days (< {self.MIN_HISTORY_DAYS}), limited indicators")

            try:
                current_price = df['close'].iloc[-1]
                avg_volume = df['volume'].tail(20).mean()

                # Phase 0.1: Basic filters (price and volume)
                if not (self.MIN_PRICE <= current_price <= self.MAX_PRICE):
                    continue
                if avg_volume < self.MIN_VOLUME:
                    continue

                passed_basic += 1

                # Phase 0.2: Calculate technical indicators
                ind = TechnicalIndicators(df)
                ind.calculate_all()

                # Phase 0.3: Calculate RS metrics only for periods with sufficient data
                returns = {}
                if len(df) >= 63:
                    price_3m_ago = df['close'].iloc[-63]
                    returns['3m'] = (current_price - price_3m_ago) / price_3m_ago
                if len(df) >= 126:
                    price_6m_ago = df['close'].iloc[-126]
                    returns['6m'] = (current_price - price_6m_ago) / price_6m_ago
                if len(df) >= 252:
                    price_12m_ago = df['close'].iloc[-252]
                    returns['12m'] = (current_price - price_12m_ago) / price_12m_ago

                # 5-day return (most stocks should have this)
                price_5d_ago = df['close'].iloc[-5] if len(df) >= 5 else df['close'].iloc[0]
                ret_5d = (current_price - price_5d_ago) / price_5d_ago

                # Weighted average of available returns (reweights if some missing)
                weights = {'3m': 0.4, '6m': 0.3, '12m': 0.3}
                total_weight = sum(weights.get(k, 0) for k in returns.keys())
                if total_weight > 0:
                    rs_raw = sum(returns.get(k, 0) * weights[k] for k in returns) / total_weight
                else:
                    rs_raw = 0.0

                # Extract available returns (0.0 if not enough data)
                ret_3m = returns.get('3m', 0.0)
                ret_6m = returns.get('6m', 0.0)
                ret_12m = returns.get('12m', 0.0)

                # Phase 0.4: 52-week metrics
                metrics_52w = ind.calculate_52w_metrics()

                # Store pre-calculated data
                phase0_data[symbol] = {
                    'df': df,
                    'ind': ind,
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
                    'high_50d': df['high'].tail(50).max(),
                    'volume_sma20': df['volume'].tail(20).mean(),
                    'data_days': len(df),  # Metadata for strategy filtering
                }

                rs_scores.append({'symbol': symbol, 'rs': rs_raw})

            except Exception as e:
                logger.warning(f"Phase 0: Error processing {symbol}: {e}")
                continue

        logger.info(f"Phase 0: {passed_basic}/{len(symbols)} symbols passed basic filters")

        # Phase 0.5: Calculate RS percentiles - O(n log n) using sorting
        if rs_scores:
            # Sort by RS value
            sorted_scores = sorted(rs_scores, key=lambda x: x['rs'])
            n = len(sorted_scores)

            # Calculate percentile based on position in sorted array
            for i, item in enumerate(sorted_scores):
                # Use (i+1)/n to avoid 0 percentile for lowest stock
                # This ensures even the lowest RS stock gets some percentile > 0
                percentile = ((i + 1) / n) * 100
                if item['symbol'] in phase0_data:
                    phase0_data[item['symbol']]['rs_percentile'] = min(99.9, percentile)

        logger.info(f"Phase 0: Pre-calculation complete for {len(phase0_data)} symbols")
        return phase0_data

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

    def _allocate_candidates(
        self,
        all_candidates: List[StrategyMatch],
        group_slots: Dict[str, int]
    ) -> List[StrategyMatch]:
        """
        Allocate 30 candidates from global pool based on group slots.

        Phase 2: Dynamic allocation from global candidate pool.

        Args:
            all_candidates: All candidates from all strategies (global pool)
            group_slots: Target slots per strategy group (e.g., {'breakout_momentum': 15, ...})

        Returns:
            List of 30 selected StrategyMatch objects
        """
        from collections import defaultdict

        # Group candidates by strategy group
        group_candidates = defaultdict(list)

        for candidate in all_candidates:
            # Find which group this strategy belongs to
            strategy_type = None
            for st, group in self.STRATEGY_GROUPS.items():
                if st.value == candidate.strategy:
                    strategy_type = st
                    break

            if strategy_type:
                group = self.STRATEGY_GROUPS[strategy_type]
                group_candidates[group].append(candidate)

        selected = []
        selected_symbols_strategies = set()  # Track (symbol, strategy) pairs

        # Phase 2.1: Select from each group according to slots (minimum diversity)
        for group, slots in group_slots.items():
            candidates = group_candidates.get(group, [])

            # Sort by score descending
            candidates.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

            # Select top N for this group
            for candidate in candidates:
                if len(selected) >= self.TOTAL_CANDIDATES_TARGET:
                    break
                key = (candidate.symbol, candidate.strategy)
                if key not in selected_symbols_strategies:
                    selected.append(candidate)
                    selected_symbols_strategies.add(key)

            selected_from_group = len([s for s in selected if s in candidates])
            logger.info(f"[{group}] Selected {selected_from_group}/{len(candidates)} candidates (target: {slots})")

        # Phase 2.2: If underfilled, add from underrepresented groups first
        if len(selected) < self.TOTAL_CANDIDATES_TARGET:
            needed = self.TOTAL_CANDIDATES_TARGET - len(selected)

            # Calculate how underfilled each group is
            group_fill_ratio = {}
            for group, slots in group_slots.items():
                group_count = len([c for c in selected
                                  if c.strategy in [st.value for st, g in self.STRATEGY_GROUPS.items() if g == group]])
                group_fill_ratio[group] = group_count / slots if slots > 0 else 1.0

            # Sort groups by fill ratio (most underfilled first)
            underfilled_groups = sorted(group_fill_ratio.keys(), key=lambda g: group_fill_ratio[g])

            # Add from underfilled groups first
            for group in underfilled_groups:
                if len(selected) >= self.TOTAL_CANDIDATES_TARGET:
                    break

                candidates = [c for c in group_candidates.get(group, [])
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

    def load_earnings_calendar(self, symbols: Optional[List[str]] = None):
        """Load earnings calendar for EP strategy."""
        self.earnings_calendar = self.fetcher.fetch_earnings_calendar(symbols)
        logger.info(f"Loaded {len(self.earnings_calendar)} earnings dates")

    def _get_data(self, symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol.

        Uses 1 year (1y) by default to ensure sufficient data for all strategies,
        including Momentum which requires 200 days for EMA200 calculation.
        """
        if symbol in self.market_data:
            return self.market_data[symbol]
        return self.fetcher.fetch_stock_data(symbol, period=period, interval="1d")

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
        except:
            return False

    def screen_all(
        self,
        symbols: List[str],
        market_data: Optional[Dict[str, pd.DataFrame]] = None,
        batch_size: int = 100,  # Phase C: Stream processing batch size
        strategy_weighting: Optional[Dict[str, float]] = None  # Dynamic strategy allocation
    ) -> List[StrategyMatch]:
        """
        Screen all symbols using all 8 strategy plugins with unified Phase 0.

        Phase 0: Universal pre-calculation (price/volume/RS/SPY) - runs ONCE
        Phase 1: Strategy screening (global collection, no slot limits)
        Phase 2: Dynamic allocation (30 slots by market regime weights)

        Args:
            symbols: List of stock symbols to screen
            market_data: Optional pre-loaded market data cache (must have 280+ days)
            batch_size: Number of symbols to process per batch (default 100)
            strategy_weighting: Market-derived weights for strategy allocation
                {'breakout_momentum': 0.5, 'trend_pullback': 0.3, 'rebound_range': 0.15, 'extreme_reversal': 0.05}

        Returns:
            List of StrategyMatch (30 total, dynamically allocated across strategy groups)
        """
        import gc

        self.market_data = market_data or {}

        # Default equal weighting if not provided
        if strategy_weighting is None:
            strategy_weighting = {
                'breakout_momentum': 0.25,
                'trend_pullback': 0.25,
                'rebound_range': 0.25,
                'extreme_reversal': 0.25
            }

        # Step 6-7: Calculate group slots for dynamic allocation (30 total)
        # This is used LATER to select from global candidate pool
        group_slots = {}
        for group, weight in strategy_weighting.items():
            group_slots[group] = max(2, int(self.TOTAL_CANDIDATES_TARGET * weight))  # Minimum 2 per group

        # Ensure total is 30 (adjust largest group if needed)
        total_slots = sum(group_slots.values())
        if total_slots != self.TOTAL_CANDIDATES_TARGET:
            diff = self.TOTAL_CANDIDATES_TARGET - total_slots
            group_slots['breakout_momentum'] = group_slots.get('breakout_momentum', 8) + diff

        # Load earnings if not already loaded
        if not self.earnings_calendar:
            self.load_earnings_calendar(symbols)

        # ============================================================
        # PHASE 0: Universal Pre-Calculation (runs ONCE for all strategies)
        # ============================================================
        logger.info("=" * 60)
        logger.info("PHASE 0: Universal Pre-Calculation")
        logger.info("=" * 60)

        self._phase0_data = self._run_phase0_precalculation(symbols, self.market_data)

        # Share Phase 0 data, market data, and earnings with all strategies
        import copy
        for strategy in self._strategies.values():
            strategy.market_data = copy.copy(self.market_data)
            strategy.phase0_data = copy.copy(self._phase0_data)
            strategy.spy_return_5d = self._spy_return_5d
            strategy._spy_df = self._spy_data  # Share SPY dataframe
            if hasattr(strategy, 'earnings_calendar'):
                strategy.earnings_calendar = copy.copy(self.earnings_calendar)

        # ============================================================
        # PHASE 1: Strategy-specific screening (using Phase 0 data)
        # Collect ALL candidates globally, no slot limits at this stage
        # ============================================================
        logger.info("=" * 60)
        logger.info("PHASE 1: Strategy Screening (Global Collection)")
        logger.info("=" * 60)

        all_candidates = []  # Global pool of all candidates from all strategies
        phase1_stats = {}  # Statistics for each strategy

        # Get symbols that passed Phase 0 (already filtered by price/volume)
        phase0_symbols = list(self._phase0_data.keys())
        total_symbols = len(phase0_symbols)
        num_batches = (total_symbols + batch_size - 1) // batch_size

        for strategy_type, strategy in self._strategies.items():
            start_time = time.time()
            logger.info(f"\n{'='*60}")
            logger.info(f"[START] {strategy_type.value} Strategy Screening")
            logger.info(f"{'='*60}")
            logger.info(f"Total symbols to screen: {total_symbols}")
            logger.info(f"Batch size: {batch_size}, Total batches: {num_batches}")

            try:
                strategy_candidates = []
                processed_count = 0
                passed_filter_count = 0

                for batch_idx in range(num_batches):
                    batch_start = batch_idx * batch_size
                    batch_end = min(batch_start + batch_size, total_symbols)
                    batch_symbols = phase0_symbols[batch_start:batch_end]
                    processed_count += len(batch_symbols)

                    # Progress logging every 10% or every 10 batches
                    progress_pct = (batch_idx + 1) / num_batches * 100
                    if batch_idx % max(1, num_batches // 10) == 0 or batch_idx % 10 == 0:
                        logger.info(f"[{strategy_type.value}] Progress: {processed_count}/{total_symbols} "
                                    f"({progress_pct:.1f}%) - Batch {batch_idx+1}/{num_batches}")

                    # Process this batch using strategy's screen method
                    batch_candidates = strategy.screen(batch_symbols)

                    if batch_candidates:
                        passed_filter_count += len(batch_candidates)
                        strategy_candidates.extend(batch_candidates)
                        logger.debug(f"[{strategy_type.value}] Batch {batch_idx+1}: "
                                     f"{len(batch_candidates)} candidates")

                    del batch_symbols
                    if batch_idx % 5 == 0:
                        gc.collect()

                # Calculate tier distribution for this strategy
                tier_counts = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
                score_sum = 0
                score_max = 0
                score_min = float('inf')

                for candidate in strategy_candidates:
                    tier = candidate.technical_snapshot.get('tier', 'C')
                    score = candidate.technical_snapshot.get('score', 0)
                    tier_counts[tier] = tier_counts.get(tier, 0) + 1
                    score_sum += score
                    score_max = max(score_max, score)
                    score_min = min(score_min, score)

                avg_score = score_sum / len(strategy_candidates) if strategy_candidates else 0
                elapsed = time.time() - start_time

                # Store stats
                phase1_stats[strategy_type.value] = {
                    'screened': total_symbols,
                    'passed_filter': passed_filter_count,
                    'final_candidates': len(strategy_candidates),
                    'tier_distribution': tier_counts,
                    'avg_score': avg_score,
                    'score_range': f"{score_min:.1f}-{score_max:.1f}" if strategy_candidates else "N/A",
                    'elapsed_seconds': elapsed
                }

                # Collect ALL candidates from this strategy (no slot limit yet)
                if strategy_candidates:
                    all_candidates.extend(strategy_candidates)

                # Strategy completion summary
                logger.info(f"\n{'='*60}")
                logger.info(f"[COMPLETE] {strategy_type.value} Strategy Screening")
                logger.info(f"{'='*60}")
                logger.info(f"Screened: {total_symbols} symbols")
                logger.info(f"Passed filter: {passed_filter_count} symbols")
                logger.info(f"Final candidates: {len(strategy_candidates)} symbols")
                logger.info(f"Tier distribution: S={tier_counts['S']}, A={tier_counts['A']}, "
                            f"B={tier_counts['B']}, C={tier_counts['C']}")
                logger.info(f"Score range: {score_min:.1f}-{score_max:.1f}, Average: {avg_score:.2f}")
                logger.info(f"Time elapsed: {elapsed:.2f}s ({total_symbols/elapsed:.1f} symbols/sec)")

                if 'strategy_candidates' in locals():
                    del strategy_candidates
                gc.collect()

            except Exception as e:
                logger.error(f"Error in {strategy_type.value} screening: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # Phase 1 complete summary
        logger.info(f"\n{'='*60}")
        logger.info(f"PHASE 1 COMPLETE: {len(all_candidates)} total candidates from all strategies")
        logger.info(f"{'='*60}")

        # Print summary table
        logger.info("\nStrategy Screening Summary:")
        logger.info(f"{'Strategy':<15} {'Screened':>10} {'Passed':>8} {'Final':>8} {'S':>4} {'A':>4} {'B':>4} {'C':>4} {'AvgScore':>10} {'Time':>8}")
        logger.info("-" * 90)
        for strategy_name, stats in phase1_stats.items():
            tier_dist = stats['tier_distribution']
            logger.info(f"{strategy_name:<15} {stats['screened']:>10} {stats['passed_filter']:>8} "
                        f"{stats['final_candidates']:>8} {tier_dist['S']:>4} {tier_dist['A']:>4} "
                        f"{tier_dist['B']:>4} {tier_dist['C']:>4} {stats['avg_score']:>10.2f} "
                        f"{stats['elapsed_seconds']:>7.1f}s")

        # ============================================================
        # PHASE 2: Dynamic Allocation from Global Pool
        # Select 30 candidates based on group slots allocation
        # ============================================================
        logger.info("=" * 60)
        logger.info("PHASE 2: Dynamic Allocation (30 slots)")
        logger.info("=" * 60)

        selected_candidates = self._allocate_candidates(all_candidates, group_slots)

        logger.info(f"=" * 60)
        logger.info(f"TOTAL: {len(selected_candidates)} candidates selected")
        logger.info(f"=" * 60)

        return selected_candidates
