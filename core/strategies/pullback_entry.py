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

    def __init__(self, fetcher=None, db=None, config=None):
        """Initialize strategy with market ATR cache."""
        super().__init__(fetcher=fetcher, db=db, config=config)
        self.market_atr_median = 0.0
        self.sector_counts = {}
        self.stock_info = {}

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter using cached data.

        v7.2: Consolidated screening — shared batch preparation and finalization.
        """
        phase0_data = getattr(self, 'phase0_data', {})

        if phase0_data:
            # Phase 0.5: Pre-filter using cached EMA21 data
            logger.info("PullbackEntry: Phase 0.5 - Pre-filtering by EMA21 trend (cached)...")
            prefiltered_symbols = []

            for symbol in symbols:
                data = phase0_data.get(symbol, {})
                try:
                    current_price = data.get('current_price', 0)
                    ema21 = data.get('ema21', 0)
                    ema21_slope_norm = data.get('ema21_slope_norm', 0)

                    if current_price > 0 and ema21 > 0 and current_price > ema21 and ema21_slope_norm > 0:
                        prefiltered_symbols.append(symbol)
                except Exception as e:
                    logger.debug(f"Error pre-filtering {symbol}: {e}")
                    continue

            logger.info(f"PullbackEntry: {len(prefiltered_symbols)}/{len(symbols)} passed EMA21 trend pre-filter")
            if not prefiltered_symbols:
                return []

            symbol_data = self._batch_prepare_symbols(prefiltered_symbols)
        else:
            # Fallback: no phase0_data, scan all symbols
            logger.warning("PullbackEntry: No phase0_data, falling back to full scan")
            symbol_data = self._batch_prepare_symbols(symbols)

        if not symbol_data:
            return []

        matches = super().screen(list(symbol_data.keys()), max_candidates=max_candidates)
        return self._finalize_screening(matches, max_candidates)

    def _batch_prepare_symbols(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch DataFrames, compute indicators, market ATR median, and sector info."""
        logger.info(f"PullbackEntry: Batch preparing {len(symbols)} symbols...")

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
            return {}

        self.market_atr_median = sorted(all_atrs)[len(all_atrs) // 2]
        logger.info(f"PullbackEntry: Market ATR median = {self.market_atr_median:.2f}, "
                    f"Processing {len(symbol_data)} symbols")

        # Fetch sector info
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

        # Cache market data for filter/calculate_dimensions
        self.market_data = {sym: data['df'] for sym, data in symbol_data.items()}
        return symbol_data

    def _finalize_screening(self, matches: List[StrategyMatch], max_candidates: int) -> List[StrategyMatch]:
        """Sort by score and limit candidates per tier for diversity."""
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
        Filter symbols based on PullbackEntry criteria.

        Phase 0 already filters: market cap >= $2B, price $2-$3000, volume >= 100K
        Phase 0.5 already filters: price > EMA21, ema21_slope_norm > 0

        This filter only checks:
        1. DataFrame validity + minimum rows (strategy-specific: 50 days)
        2. Price within EMA21 tolerance band (allows pullback wicks below EMA21)
        """
        # Validate DataFrame
        if not validate_dataframe(df, min_rows=self.PARAMS.get('min_data_days', 50)):
            logger.debug(f"Pullback_REJ: {symbol} - Invalid DataFrame")
            return False

        current_price = df['close'].iloc[-1]
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # Price within EMA21 tolerance band (pullbacks can wick slightly below EMA21)
        ema21 = data.get('ema21', 0)
        ema21_tolerance = ema21 * 0.98  # 2% tolerance
        if ema21 <= 0 or current_price < ema21_tolerance:
            logger.debug(f"Pullback_REJ: {symbol} - Price {current_price:.2f} < EMA21*0.98 {ema21_tolerance:.2f}")
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """
        Calculate 4-dimensional scoring (TI, RC, VC, BONUS).

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

        # Dimension 2: Retracement Structure (RC) — 0-8 points
        rc_data = ind.calculate_retracement_structure()
        rc_score = rc_data['total_score']
        dimensions.append(ScoringDimension(
            name='RC',
            score=rc_score,
            max_score=8.0,
            details={
                'tightness_score': rc_data.get('tightness_score', 0),
                'support_score': rc_data.get('support_score', 0),
                'gap_score': rc_data.get('gap_score', 0),
                'depth_score': rc_data.get('depth_score', 0),
                'pullback_depth_pct': rc_data.get('pullback_depth_pct', 0),
                'reversal_score': rc_data.get('reversal_score', 0),
                'reversal_signals': rc_data.get('reversal_signals', {}),
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
                'distribution_penalty': vc_data.get('distribution_penalty', 0),
                'is_distribution_day': vc_data.get('is_distribution_day', False),
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

        # Cache details once instead of calling 3 times
        momentum_details = self._calculate_momentum_persistence_details(symbol, df)
        bonus_score += momentum_persistence_score

        dimensions.append(ScoringDimension(
            name='BONUS',
            score=bonus_score,
            max_score=2.0,
            details={
                'sector': sector,
                'sector_leadership_score': sector_leadership_score,
                'momentum_persistence_score': momentum_persistence_score,
                'stock_5d_return': momentum_details.get('stock_5d_return', 0),
                'spy_5d_return': momentum_details.get('spy_5d_return', 0),
                'outperformance_pct': momentum_details.get('outperformance_pct', 0)
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
