"""Strategy B: PullbackEntry - Pullback to EMA with 4D scoring."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType
from ..scoring_utils import safe_divide, validate_dataframe

logger = logging.getLogger(__name__)


class PullbackEntryStrategy(BaseStrategy):
    """Strategy B: PullbackEntry v7.0 - Pullback to EMA with 4D scoring."""

    NAME = "PullbackEntry"
    STRATEGY_TYPE = StrategyType.B
    DESCRIPTION = "PullbackEntry v5.0"
    DIMENSIONS = ['TI', 'RC', 'VC', 'BONUS']

    # Strategy Parameters
    PARAMS = {
        'min_data_days': 50,
        'ema21_slope_threshold': 0,  # Minimum normalized slope (S_norm > 0 per doc line 210)
        'max_retracement_range': 0.08,  # 8% max range for structure
        'ema8_penetration_tolerance': 0.985,  # 1.5% below EMA8 allowed
        'volume_dry_threshold': 0.7,  # <70% of 20d avg
        'volume_surge_threshold': 1.5,  # >150% of 20d avg
        'gap_veto_threshold': 0.8,  # 0.8 ATR gap = veto
        'atr_initial_stop': 1.2,  # Initial stop: 1.2x ATR
        'position_tiers': {
            'S': {'min_score': 12, 'position_pct': 0.20, 'label': 'Apex'},
            'A': {'min_score': 9, 'position_pct': 0.10, 'label': 'Strong'},
            'B': {'min_score': 7, 'position_pct': 0.05, 'label': 'Speculative'},
            'C': {'min_score': 0, 'position_pct': 0.00, 'label': 'Reject'}
        },
        'sector_etfs': {  # v5.0: Sector ETF mapping for bonus calculation
            'Technology': 'XLK',
            'Financials': 'XLF',
            'Energy': 'XLE',
            'Industrials': 'XLI',
            'Consumer Staples': 'XLP',
            'Consumer Discretionary': 'XLY',
            'Materials': 'XLB',
            'Utilities': 'XLU',
            'Health Care': 'XLV',
            'Biotechnology': 'XBI',
            'Semiconductors': 'SMH',
            'Software': 'IGV',
            'Transportation': 'IYT',
        }
    }

    def __init__(self, fetcher=None, db=None):
        """Initialize strategy with market ATR cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.market_atr_median = 0.0
        self.sector_counts = {}
        self.stock_info = {}

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter using cached data.

        v7.1: Uses phase0_data for fast pre-filtering, only fetches DataFrames
        for symbols that pass the pre-filter.
        """
        # Phase 0: Use cached phase0_data for fast pre-filter
        logger.info("PullbackEntry: Using Phase 0 cached data for pre-filter...")

        phase0_data = getattr(self, 'phase0_data', {})
        if not phase0_data:
            logger.warning("PullbackEntry: No phase0_data available, falling back to full scan")
            return self._screen_full_scan(symbols, max_candidates)

        # Phase 0.5: Pre-filter using cached EMA21 data
        logger.info("PullbackEntry: Phase 0.5 - Pre-filtering by EMA21 trend (cached)...")
        prefiltered_symbols = []

        for symbol in symbols:
            if symbol not in phase0_data:
                continue
            data = phase0_data[symbol]

            try:
                current_price = data.get('current_price', 0)
                ema21 = data.get('ema21', 0)

                # Skip invalid data
                if current_price <= 0 or ema21 <= 0:
                    continue

                # v7.0: Check price above EMA21 (line 211)
                if current_price <= ema21:
                    continue

                # v7.0: Check S_norm > 0 (line 210, 225)
                # S_norm = (EMA21_today − EMA21_5d) / ATR14
                ema21_slope_norm = data.get('ema21_slope_norm', 0)
                if ema21_slope_norm > 0:
                    # Uptrend confirmed - fetch full data for this symbol
                    prefiltered_symbols.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"PullbackEntry: {len(prefiltered_symbols)}/{len(symbols)} passed EMA21 trend pre-filter")

        if not prefiltered_symbols:
            logger.info("PullbackEntry: No symbols passed pre-filter")
            return []

        # Now fetch data only for pre-filtered symbols
        return self._process_prefiltered_symbols(prefiltered_symbols, max_candidates)

    def _process_prefiltered_symbols(self, symbols: List[str], max_candidates: int) -> List[StrategyMatch]:
        """Process pre-filtered symbols - fetch data and calculate ATR median."""
        logger.info("PullbackEntry: Processing pre-filtered symbols...")

        all_atrs = []
        symbol_data = {}

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_data_days']:
                    continue

                ind = TechnicalIndicators(df)
                ind.calculate_all()

                atr = ind.indicators.get('atr', {}).get('atr', 0)
                if atr > 0:
                    all_atrs.append(atr)

                symbol_data[symbol] = {'df': df, 'ind': ind}
            except Exception as e:
                logger.debug(f"Error processing {symbol}: {e}")
                continue

        if not all_atrs:
            logger.warning("PullbackEntry: No valid ATR data found")
            return []

        self.market_atr_median = sorted(all_atrs)[len(all_atrs) // 2]
        logger.info(f"PullbackEntry: Market ATR median = {self.market_atr_median:.2f}, "
                    f"Processing {len(symbol_data)} symbols")

        # Get industry data for sector context
        try:
            if self.fetcher:
                self.stock_info = self.fetcher.fetch_batch_stock_info(list(symbol_data.keys()))
                self.sector_counts = {}
                for info in self.stock_info.values():
                    sector = info.get('sector', 'Unknown')
                    self.sector_counts[sector] = self.sector_counts.get(sector, 0) + 1
        except Exception as e:
            logger.warning(f"Could not fetch sector data: {e}")
            self.stock_info = {}
            self.sector_counts = {}

        # Cache market data for use in filter/calculate_dimensions
        self.market_data = {sym: data['df'] for sym, data in symbol_data.items()}

        # Call parent screen method
        matches = super().screen(list(symbol_data.keys()), max_candidates=max_candidates)

        # Sort by confidence and limit to 5 per tier for diversity
        scored_candidates = []
        for match in matches:
            scored_candidates.append({
                'match': match,
                'score': match.technical_snapshot.get('score', 0),
                'tier': match.technical_snapshot.get('tier', 'C')
            })

        scored_candidates.sort(key=lambda x: x['score'], reverse=True)

        # Limit 5 per tier
        tier_limits = {'S': 5, 'A': 5, 'B': 5}
        tier_current = {'S': 0, 'A': 0, 'B': 0}

        filtered_matches = []
        for cand in scored_candidates:
            tier = cand['tier']
            if tier in tier_current and tier_current[tier] >= tier_limits[tier]:
                continue
            tier_current[tier] = tier_current.get(tier, 0) + 1
            filtered_matches.append(cand['match'])

        return filtered_matches

    def _screen_full_scan(self, symbols: List[str], max_candidates: int) -> List[StrategyMatch]:
        """Fallback: Full scan without phase0_data (original behavior)."""
        logger.info("PullbackEntry: Calculating market statistics (fallback)...")

        all_atrs = []
        symbol_data = {}

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < self.PARAMS['min_data_days']:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            atr = ind.indicators.get('atr', {}).get('atr', 0)
            if atr > 0:
                all_atrs.append(atr)

            symbol_data[symbol] = {'df': df, 'ind': ind}

        if not all_atrs:
            logger.warning("PullbackEntry: No valid ATR data found")
            return []

        self.market_atr_median = sorted(all_atrs)[len(all_atrs) // 2]
        logger.info(f"PullbackEntry: Market ATR median = {self.market_atr_median:.2f}, "
                    f"Processing {len(symbol_data)} symbols")

        # Phase 0.5: Pre-filter by EMA21 trend (price > EMA21 and slope > 0)
        logger.info("PullbackEntry: Phase 0.5 - Pre-filtering by EMA21 trend...")
        prefiltered_symbols = []
        symbols_to_remove = []

        for symbol, data in list(symbol_data.items()):
            try:
                df = data['df']
                ind = data['ind']

                current_price = df['close'].iloc[-1]
                ema21 = ind.indicators.get('ema', {}).get('ema21', 0)

                ema21_5d_ago = df['close'].ewm(span=21).mean().iloc[-6] if len(df) >= 6 else ema21 * 0.99
                ema_slope = ema21 - ema21_5d_ago if ema21 and ema21_5d_ago else 0

                if current_price > ema21 and ema_slope > 0:
                    prefiltered_symbols.append(symbol)
                else:
                    symbols_to_remove.append(symbol)
            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                symbols_to_remove.append(symbol)
                continue

        for symbol in symbols_to_remove:
            symbol_data.pop(symbol, None)

        logger.info(f"PullbackEntry: {len(prefiltered_symbols)}/{len(symbol_data) + len(prefiltered_symbols)} passed EMA21 trend pre-filter")

        # Get industry data for sector context
        try:
            if self.fetcher:
                self.stock_info = self.fetcher.fetch_batch_stock_info(list(symbol_data.keys()))
                self.sector_counts = {}
                for info in self.stock_info.values():
                    sector = info.get('sector', 'Unknown')
                    self.sector_counts[sector] = self.sector_counts.get(sector, 0) + 1
        except Exception as e:
            logger.warning(f"Could not fetch sector data: {e}")
            self.stock_info = {}
            self.sector_counts = {}

        self.market_data = {sym: data['df'] for sym, data in symbol_data.items()}

        matches = super().screen(list(symbol_data.keys()), max_candidates=max_candidates)

        scored_candidates = []
        for match in matches:
            scored_candidates.append({
                'match': match,
                'score': match.technical_snapshot.get('score', 0),
                'tier': match.technical_snapshot.get('tier', 'C')
            })

        scored_candidates.sort(key=lambda x: x['score'], reverse=True)

        tier_limits = {'S': 5, 'A': 5, 'B': 5}
        tier_current = {'S': 0, 'A': 0, 'B': 0}

        filtered_matches = []
        for cand in scored_candidates:
            tier = cand['tier']
            if tier in tier_current and tier_current[tier] >= tier_limits[tier]:
                continue
            tier_current[tier] = tier_current.get(tier, 0) + 1
            filtered_matches.append(cand['match'])

        return filtered_matches

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        Filter symbols based on PullbackEntry criteria with Phase 0 fast pre-filter.
        """
        # Validate DataFrame before processing
        if not validate_dataframe(df, min_rows=self.PARAMS.get('min_data_days', 50)):
            logger.debug(f"Pullback_REJ: {symbol} - Invalid DataFrame")
            return False

        # Phase 0: Fast pre-filter using cached data (O(1) checks before expensive calculations)
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        current_price = df['close'].iloc[-1]

        # Skip penny stocks and extreme prices
        if current_price < 2.0 or current_price > 3000.0:
            return False

        # Skip low volume stocks (avg volume < 100K)
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume < 100000:
            return False

        # Skip insufficient data
        if len(df) < self.PARAMS['min_data_days']:
            return False

        # MISMATCH FIX 3: Market cap filter (doc line 212): Market cap ≥ $2B
        market_cap = self.stock_info.get(symbol, {}).get('market_cap', 0)
        if market_cap > 0 and market_cap < 2e9:
            logger.debug(f"Pullback_REJ: {symbol} - Market cap ${market_cap/1e9:.2f}B < $2B")
            return False

        # Use pre-calculated EMA21 slope from phase0_data
        ema21_slope_norm = data.get('ema21_slope_norm')
        if ema21_slope_norm is None or ema21_slope_norm < self.PARAMS['ema21_slope_threshold']:
            logger.debug(f"Pullback_REJ: {symbol} - EMA21 slope {ema21_slope_norm:.2f} < threshold")
            return False

        # v7.0: Price > EMA21 (doc line 211)
        ema21 = data.get('ema21', 0)
        if ema21 <= 0 or current_price <= ema21:
            logger.debug(f"Pullback_REJ: {symbol} - Price {current_price:.2f} <= EMA21 {ema21:.2f}")
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # Calculate TI score for filtering (uses slope internally)
        ti_data = ind.calculate_normalized_ema_slope(self.market_atr_median)
        ti_score = ti_data['score']

        # Filter out weak trends
        if ti_score == 0:
            return False

        # Filter out poor structure
        rc_data = ind.calculate_retracement_structure()
        if rc_data['total_score'] <= 0:
            return False

        # MISMATCH FIX 2: Gap-down is scoring component (doc line 240), not binary filter
        # Removed: gap veto filter - gap is now scored in RC dimension (0 pts if > 0.8×ATR, 1.0 if < 0.8×ATR)

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """
        Calculate 4-dimensional scoring (TI, RS, VC, Bonus).

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            List of ScoringDimension objects
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        dimensions = []

        # Dimension 1: Trend Intensity (TI) - 0-5 points
        ti_data = ind.calculate_normalized_ema_slope(self.market_atr_median)
        ti_score = ti_data['score']

        # Calculate EMA21 touch count (deduct for multiple touches) - VECTORIZED
        ema21 = ind.indicators.get('ema', {}).get('ema21', 0)
        touch_count = 0
        if ema21 > 0:
            # Vectorized: Count how many times price crossed below EMA21 in last 20 days
            last_20 = df.tail(20)
            touched = (last_20['low'] <= ema21) & (last_20['close'] > ema21 * 0.99)
            touch_count = touched.sum()

        # Deduct TI score for multiple touches (first touch is best)
        # MISMATCH FIX 4: Cap penalty at 1.0 (doc line 227), not 1.5
        touch_deduction = min(1.0, (touch_count - 1) * 0.5) if touch_count > 1 else 0
        ti_score = max(0, ti_score - touch_deduction)

        dimensions.append(ScoringDimension(
            name='TI',
            score=ti_score,
            max_score=5.0,
            details={
                'slope_norm': ti_data.get('slope_norm', 0),
                'slope_raw': ti_data.get('slope_raw', 0),
                'ema21_today': ti_data.get('ema21_today', 0),
                'ema21_t5': ti_data.get('ema21_t5', 0),
                'atr14': ti_data.get('atr14', 0),
                'ema21_touch_count': touch_count,
                'touch_deduction': touch_deduction
            }
        ))

        # Dimension 2: Retracement Structure (RC) - 0-5 points
        rc_data = ind.calculate_retracement_structure()
        rc_score = rc_data['total_score']
        dimensions.append(ScoringDimension(
            name='RC',
            score=rc_score,
            max_score=5.0,
            details={
                'tightness_score': rc_data.get('tightness_score', 0),
                'support_score': rc_data.get('support_score', 0),
                'gap_score': rc_data.get('gap_score', 0),  # MISMATCH FIX 2: Gap-down scoring
                'price_range_pct': rc_data.get('price_range_pct', 0),
                'ema8_current': rc_data.get('ema8_current', 0),
                'low_min': rc_data.get('low_min', 0)
            }
        ))

        # Dimension 3: Volume Confirmation (VC) - 0-5 points
        vc_data = ind.calculate_volume_confirmation()
        vc_score = vc_data['total_score']
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'v_dry': vc_data.get('v_dry', 0),
                'dry_score': vc_data.get('dry_score', 0),
                'v_surge': vc_data.get('v_surge', 0),
                'surge_score': vc_data.get('surge_score', 0),
                'vol_today': vc_data.get('vol_today', 0),
                'vol_20d_avg': vc_data.get('vol_20d_avg', 0)
            }
        ))

        # Dimension 4: Environment Bonus - +2/-10 points (v7.0: momentum persistence replaces gap veto)
        bonus_score = 0

        # v5.0: Sector leadership bonus (0-1.0) based on sector ETF performance
        sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')
        sector_leadership_score = self._calculate_sector_leadership(sector)
        bonus_score += sector_leadership_score

        # v7.0: Momentum persistence vs SPY (0-1.0) - replaces gap veto bonus
        # Rewards presence of relative strength, not absence of badness
        momentum_persistence_score = self._calculate_momentum_persistence(symbol, df)
        bonus_score += momentum_persistence_score

        dimensions.append(ScoringDimension(
            name='BONUS',
            score=bonus_score,
            max_score=2.0,
            details={
                'sector': sector,
                'sector_leadership_score': sector_leadership_score,
                'momentum_persistence_score': momentum_persistence_score,
                'stock_5d_return': self._calculate_momentum_persistence_details(symbol, df).get('stock_5d_return', 0),
                'spy_5d_return': self._calculate_momentum_persistence_details(symbol, df).get('spy_5d_return', 0),
                'outperformance_pct': self._calculate_momentum_persistence_details(symbol, df).get('outperformance_pct', 0)
            }
        ))

        return dimensions

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, and target prices with 4-stage exit system.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            dimensions: Dimension scores
            score: Total score
            tier: Tier (S/A/B/C)

        Returns:
            Tuple of (entry_price, stop_loss, take_profit)
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        entry_price = round(current_price, 2)

        # Dynamic stop loss: Platform low or EMA21 - ATR
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price * 0.95)
        platform_low = df['low'].tail(5).min()
        stop_candidates = [
            platform_low,
            ema21 - atr,
            entry_price - atr * self.PARAMS['atr_initial_stop']
        ]
        stop_loss = round(min(stop_candidates), 2)

        # Risk for position sizing reference
        risk = entry_price - stop_loss

        # Reference target (3R)
        target = round(entry_price + risk * 3, 2)

        return entry_price, stop_loss, target

    def build_match_reasons(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> List[str]:
        """Build human-readable match reasons."""
        ti = next((d for d in dimensions if d.name == 'TI'), None)
        rc = next((d for d in dimensions if d.name == 'RC'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        position_pct = self.calculate_position_pct(tier)

        reasons = [
            f"Score: {score:.0f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TI:{ti.score if ti else 0} RC:{rc.score if rc else 0} "
            f"VC:{vc.score if vc else 0} B:{bonus.score if bonus else 0}"
        ]

        # Add TI detail
        if ti and 'slope_norm' in ti.details:
            reasons.append(f"EMA21 slope: {ti.details['slope_norm']:.2f}")

        # Add RC detail
        if rc and 'price_range_pct' in rc.details:
            reasons.append(f"Range: {rc.details['price_range_pct']:.1f}%")

        # Add VC detail
        if vc and 'v_dry' in vc.details:
            reasons.append(f"Vol dry: {vc.details['v_dry']:.2f}x")

        # Add sector info
        if bonus and bonus.details.get('sector') and bonus.details['sector'] != 'Unknown':
            reasons.append(f"Sector: {bonus.details['sector']}")

        return reasons

    def build_snapshot(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Dict[str, Any]:
        """
        Build technical snapshot with 4-stage exit logic.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            dimensions: Dimension scores
            score: Total score
            tier: Tier (S/A/B/C)

        Returns:
            Dict with technical snapshot data
        """
        snapshot = super().build_snapshot(symbol, df, dimensions, score, tier)

        # Get indicators for exit calculations
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # Entry price
        entry_price = round(current_price, 2)

        # Calculate stop loss
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price * 0.95)
        platform_low = df['low'].tail(5).min()
        stop_candidates = [
            platform_low,
            ema21 - atr,
            entry_price - atr * self.PARAMS['atr_initial_stop']
        ]
        stop_loss = round(min(stop_candidates), 2)

        risk = entry_price - stop_loss

        # 4-Stage Exit System
        # Stage 1: Initial stop (already in stop_loss)

        # Stage 2: Lock-profit at Entry + 0.5R when profit = 2.5R
        lock_profit_trigger = entry_price + risk * 2.5
        lock_profit_stop = entry_price + risk * 0.5

        # Stage 3: Trend exit: EMA10 or Chandelier 3x ATR
        ema10 = ind.indicators.get('ema', {}).get('ema10')
        chandelier_stop = ind.calculate_chandelier_exit(
            entry_price, entry_price, atr, 3.0
        )

        # MISMATCH FIX 5: Stage 4 trailing uses EMA5 (doc line 263), not EMA8
        ema5 = ind.indicators.get('ema', {}).get('ema5')

        # Stage 4: Acceleration exit: Close below EMA5 when >20% from EMA21
        ema21_val = ind.indicators.get('ema', {}).get('ema21', current_price)
        acceleration_trigger = ema21_val * 1.20

        # Add 4-stage exit system to snapshot
        snapshot.update({
            'lock_profit_trigger': lock_profit_trigger,
            'lock_profit_stop': lock_profit_stop,
            'chandelier_stop': chandelier_stop,
            'acceleration_trigger': acceleration_trigger,
            'ema5': ema5,  # MISMATCH FIX 5: Stage 4 trailing uses EMA5
            'ema10': ema10,
            'atr': atr,
            'dynamic_exit_notes': (
                'Initial:1.2xATR | Lock:+2.5R->+0.5R | '
                'Trend:EMA10/3xATR | Accel:EMA5 when>20%'
            )
        })

        # Add dimension-specific details
        ti = next((d for d in dimensions if d.name == 'TI'), None)
        rc = next((d for d in dimensions if d.name == 'RC'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        if ti:
            snapshot['ema21_slope_norm'] = ti.details.get('slope_norm', 0)

        if rc:
            snapshot['retracement_range_pct'] = rc.details.get('price_range_pct', 0)

        if vc:
            snapshot['volume_dry_ratio'] = vc.details.get('v_dry', 0)
            snapshot['volume_surge_ratio'] = vc.details.get('v_surge', 0)

        if bonus:
            snapshot['sector'] = bonus.details.get('sector', 'Unknown')
            snapshot['sector_leadership_score'] = bonus.details.get('sector_leadership_score', 0)
            snapshot['gap_estimate_pct'] = bonus.details.get('gap_estimate_pct', 0)

        return snapshot

    def _calculate_sector_leadership(self, sector: str) -> float:
        """
        Calculate sector leadership score (0-1.0) based on sector ETF performance.

        Scoring:
        - RS >= 90th AND > EMA50: 1.0
        - RS >= 80th AND > EMA50: 0.7
        - RS >= 80th but < EMA50: 0.3
        - Otherwise: 0

        Uses pre-calculated ETF data from etf_cache (Phase 0).

        Args:
            sector: Stock's sector name

        Returns:
            Leadership score 0-1.0
        """
        if sector == 'Unknown' or sector not in self.PARAMS['sector_etfs']:
            return 0.0

        etf_symbol = self.PARAMS['sector_etfs'][sector]

        # Use pre-calculated ETF data from database
        etf_data = self.db.get_etf_cache(etf_symbol) if hasattr(self, 'db') else None
        if not etf_data:
            return 0.0

        # Get pre-calculated metrics
        rs_percentile = etf_data.get('rs_percentile', 0)
        above_ema50 = etf_data.get('above_ema50', False)

        # Score based on RS percentile and EMA50 alignment
        if rs_percentile >= 90 and above_ema50:
            return 1.0
        elif rs_percentile >= 80 and above_ema50:
            return 0.7
        elif rs_percentile >= 80:
            return 0.3
        else:
            return 0.0

    def _calculate_momentum_persistence(self, symbol: str, df: pd.DataFrame) -> float:
        """
        Calculate momentum persistence vs SPY (0-1.0 pts).

        Measures stock's 5d return relative to SPY's 5d return.
        Rewards presence of relative strength during pullback.

        Uses pre-calculated SPY data from etf_cache (Phase 0).

        Scoring:
        - Outperformance > 2%: +1.0
        - Outperformance > 1%: +0.5
        - Otherwise: 0

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            Momentum persistence score 0-1.0
        """
        if len(df) < 5:
            return 0.0

        # Stock 5d return (safe division)
        close_5d_ago = df['close'].iloc[-5] if len(df) >= 5 else df['close'].iloc[-1]
        close_latest = df['close'].iloc[-1]
        stock_return = safe_divide(close_latest - close_5d_ago, close_5d_ago, default=0.0)

        # SPY 5d return from pre-calculated data
        spy_data = self.db.get_etf_cache('SPY') if hasattr(self, 'db') else None
        if not spy_data:
            return 0.0

        spy_return = spy_data.get('ret_5d', 0) / 100  # Convert from percentage

        # Outperformance
        outperformance = stock_return - spy_return

        # Score based on outperformance
        if outperformance > 0.02:
            return 1.0
        elif outperformance > 0.01:
            return 0.5
        else:
            return 0.0

    def _calculate_momentum_persistence_details(self, symbol: str, df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate momentum persistence details for reporting.

        Uses pre-calculated SPY data from etf_cache (Phase 0).

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            Dict with stock_5d_return, spy_5d_return, outperformance_pct
        """
        if len(df) < 5:
            return {'stock_5d_return': 0.0, 'spy_5d_return': 0.0, 'outperformance_pct': 0.0}

        # Stock 5d return (safe division)
        close_5d_ago = df['close'].iloc[-5] if len(df) >= 5 else df['close'].iloc[-1]
        close_latest = df['close'].iloc[-1]
        stock_return = safe_divide(close_latest - close_5d_ago, close_5d_ago, default=0.0)

        # SPY 5d return from pre-calculated data
        spy_data = self.db.get_etf_cache('SPY') if hasattr(self, 'db') else None
        if not spy_data:
            return {'stock_5d_return': stock_return, 'spy_5d_return': 0.0, 'outperformance_pct': 0.0}

        spy_return = spy_data.get('ret_5d', 0) / 100  # Convert from percentage

        # Outperformance
        outperformance = stock_return - spy_return

        return {
            'stock_5d_return': stock_return,
            'spy_5d_return': spy_return,
            'outperformance_pct': outperformance
        }
