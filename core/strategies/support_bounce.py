"""Strategy E: 支撑回踩买入 (Support Rebound Buy) - Near support with volume contraction."""
from ..scoring_utils import calculate_clv
from typing import Dict, List, Optional, Tuple, Any
import logging
from datetime import datetime

import pandas as pd

from ..indicators import TechnicalIndicators
from ..support_resistance import SupportResistanceCalculator
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class SupportBounceStrategy(BaseStrategy):
    """
    Strategy C: SupportBounce v5.0
    - Removed SPY > EMA200 hard gate (regime-adaptive position sizing instead)
    - Depth range 2-10% for support distance
    - Continuous 1-5 day reclaim scoring for RB dimension
    """

    NAME = "SupportBounce"
    STRATEGY_TYPE = StrategyType.C  # Changed from UPTHRUST_REBOUND
    DESCRIPTION = "SupportBounce v5.0 - regime-adaptive false breakdown"
    DIMENSIONS = ['SQ', 'VD', 'RB']
    DIRECTION = 'long'

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'max_distance_from_support': 0.10,  # v7.0: Max 10% depth from support
        'min_touches_60d': 3,  # v7.0: ≥3 touches in 60d OR ≥2 in 30d
        'min_touches_30d': 2,  # v7.0: alternative shorter lookback
        'target_r_multiplier': 2.0,  # v7.0: 2.5R (2.0R in bear)
        'support_tolerance_atr': 0.5,  # Support level ± 0.5 ATR
        'time_stop_days': 5,
        'time_stop_clv_min': 0.4,
        'range_existence_bonus': 0.5,
        'max_reclaim_days': 5,
        'sector_etfs': {  # Sector ETF mapping
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
        """Initialize with sector ETF data cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.sector_etf_data = {}
        self.stock_info = {}

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter.
        - Support exists and within 10% (v5.0: removed SPY > EMA200 gate, depth range 2-10%)
        """
        # v5.0: SPY > EMA200 gate removed - regime-adaptive position sizing instead
        logger.info("SupportBounce: Phase 0 - Support Bounce v5.0 (no SPY gate)")

        # Pre-filter by support existence and distance
        prefiltered = []
        logger.info("SupportBounce: Phase 0.5 - Pre-filtering by support...")

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    logger.debug(f"U&R_REJ: {symbol} - Insufficient data")
                    continue

                current_price = df['close'].iloc[-1]

                # Calculate S/R with tolerance
                calc = SupportResistanceCalculator(df)
                sr_levels = calc.calculate_all()
                supports = sr_levels.get('support', [])

                if not supports:
                    logger.debug(f"SupportBounce_REJ: {symbol} - No support levels found")
                    continue

                # Find nearest support
                supports_below = [s for s in supports if s < current_price]
                if not supports_below:
                    logger.debug(f"SupportBounce_REJ: {symbol} - No support below price {current_price:.2f}")
                    continue

                nearest_support = max(supports_below)
                distance_pct = (current_price - nearest_support) / current_price

                # v7.0: Max depth 10% (no minimum - doc only requires within ±15% of EMA50)
                max_depth = self.PARAMS['max_distance_from_support']
                if distance_pct > max_depth:
                    logger.debug(f"SupportBounce_REJ: {symbol} - Depth {distance_pct:.2%} > {max_depth:.0%}")
                    continue

                # v7.0: Check touch count (≥3 in 60d OR ≥2 in 30d)
                touches_60d = calc.count_touches(nearest_support, lookback=60)
                touches_30d = calc.count_touches(nearest_support, lookback=30)
                min_touches_60d = self.PARAMS['min_touches_60d']
                min_touches_30d = self.PARAMS['min_touches_30d']

                if touches_60d < min_touches_60d and touches_30d < min_touches_30d:
                    logger.debug(f"SupportBounce_REJ: {symbol} - Insufficient touches (60d={touches_60d}, 30d={touches_30d})")
                    continue

                logger.debug(f"SupportBounce_PASS: {symbol} - Support at {nearest_support:.2f}, depth {distance_pct:.2%}, touches_60d={touches_60d}, touches_30d={touches_30d}")
                prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"SupportBounce: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Load sector ETF data for comparison
        self._load_sector_etf_data()

        # Load stock info for sector alpha
        try:
            if self.fetcher:
                self.stock_info = self.fetcher.fetch_batch_stock_info(prefiltered)
        except Exception as e:
            logger.warning(f"Could not load stock info: {e}")
            self.stock_info = {}

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)

    def _load_sector_etf_data(self):
        """Load sector ETF data for Sector Alpha comparison."""
        try:
            for etf in self.PARAMS['sector_etfs'].values():
                df = self._get_data(etf)
                if df is not None and len(df) > 50:
                    self.sector_etf_data[etf] = df
        except Exception as e:
            logger.warning(f"Could not load sector ETF data: {e}")

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for SupportBounce candidates per v7.0 spec."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        current_price = df['close'].iloc[-1]

        # Calculate S/R
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        supports = sr_levels.get('support', [])
        if not supports:
            return False

        # Find nearest support (highest support below price)
        supports_below = [s for s in supports if s < current_price]
        if not supports_below:
            return False

        nearest_support = max(supports_below)
        distance_pct = abs(current_price - nearest_support) / current_price

        # v7.0: Max depth 10% (no minimum depth gate)
        max_depth = self.PARAMS['max_distance_from_support']
        if distance_pct > max_depth:
            return False

        # v7.0: Support touch requirement - ≥3 touches in 60d OR ≥2 touches in 30d
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        support_touches = self._calculate_support_touches(df, nearest_support, atr)
        touch_dates = support_touches.get('touch_dates', [])

        # Count touches in 60d and 30d windows
        touches_60d = len([d for d in touch_dates if d <= 60])
        touches_30d = len([d for d in touch_dates if d <= 30])

        # v7.0: Require ≥3 in 60d OR ≥2 in 30d (recency matters more)
        if not (touches_60d >= 3 or touches_30d >= 2):
            logger.debug(f"{symbol}: v7.0 touch requirement failed (60d:{touches_60d}, 30d:{touches_30d})")
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring with three expert defenses."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.99
        distance_pct = abs(current_price - nearest_support) / current_price

        # Get support touches and recency
        support_touches = self._calculate_support_touches(df, nearest_support, atr)
        recency_weight = self._calculate_recency_weight(support_touches['last_touch_days'])

        # Volume and CLV data for veto check
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)
        vol_ma20 = volume_data.get('vol_ma20', df['volume'].mean())

        # Calculate CLV (Close Location Value)
        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])

        # Defense 2: Volume Trap Veto
        is_falling_knife = (volume_ratio > self.PARAMS['volume_veto_threshold'] and
                           clv < self.PARAMS['clv_veto_threshold'])

        # Defense 3: Sector Alpha Bonus
        sector_alpha = self._calculate_sector_alpha(symbol, current_price, atr)

        dimensions = []

        # Dimension 1: Support Quality (SQ) - 6 points max with range bonus
        sq_score, sq_details = self._calculate_sq_with_range_bonus(df, ind)
        # Add sector alpha bonus if present
        if sector_alpha > 0:
            sq_score += sector_alpha
            sq_details['sector_alpha'] = sector_alpha
        sq_score = min(4.0, sq_score)
        dimensions.append(ScoringDimension(
            name='SQ',
            score=sq_score,
            max_score=4.0,
            details=sq_details
        ))

        # Dimension 2: Volume Dryness (VD) - 5 points max
        # Veto: return empty if falling knife detected
        if is_falling_knife:
            logger.debug(f"{symbol}: Volume trap veto (Vol:{volume_ratio:.2f}x, CLV:{clv:.2f})")
            return []

        vd_score, vd_details = self._calculate_vd(volume_ratio, df)
        dimensions.append(ScoringDimension(
            name='VD',
            score=vd_score,
            max_score=5.0,
            details=vd_details
        ))

        # Dimension 3: Rebound Setup (RB) - 6 points max
        rb_score, rb_details = self._calculate_rb(ind, df, clv, symbol)
        dimensions.append(ScoringDimension(
            name='RB',
            score=rb_score,
            max_score=6.0,
            details=rb_details
        ))

        return dimensions


    def _check_time_stop(self, symbol: str, entry_date: datetime,
                         df: pd.DataFrame) -> bool:
        """
        Time stop check - 5 days without rebound exit.
        Also check 5-day CLV avg > 0.4.
        """
        # Get post-entry data
        entry_idx = df.index.get_indexer([entry_date], method='nearest')[0]
        if entry_idx < 0 or entry_idx + 5 >= len(df):
            return False

        post_entry = df.iloc[entry_idx:entry_idx+5]

        # Check if rebounded within 5 days
        entry_price = df['close'].iloc[entry_idx]
        max_price = post_entry['close'].max()

        if max_price > entry_price:
            return False  # Rebounded, no stop

        # 5 days no rebound, check CLV avg
        clv_values = []
        for _, row in post_entry.iterrows():
            high, low, close = row['high'], row['low'], row['close']
            if high != low:
                clv = (close - low) / (high - low)
                clv_values.append(clv)

        if clv_values and sum(clv_values) / len(clv_values) >= self.PARAMS['time_stop_clv_min']:
            return False  # High CLV avg, no stop

        return True  # Trigger time stop

    def _detect_resistance_level(self, df: pd.DataFrame) -> Optional[float]:
        """Detect clear resistance level above current price."""
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        resistances = sr_levels.get('resistance', [])

        if not resistances:
            return None

        current_price = df['close'].iloc[-1]
        resistances_above = [r for r in resistances if r > current_price]

        if not resistances_above:
            return None

        return min(resistances_above)

    def _detect_support_level(self, df: pd.DataFrame) -> Optional[float]:
        """Detect clear support level below current price."""
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        if not supports:
            return None

        current_price = df['close'].iloc[-1]
        supports_below = [s for s in supports if s < current_price]

        if not supports_below:
            return None

        return max(supports_below)

    def _calculate_sq_with_range_bonus(self, df: pd.DataFrame, ind: TechnicalIndicators) -> Tuple[float, Dict]:
        """
        Calculate SQ dimension with range existence bonus.
        """
        # Base SQ calculation
        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.99
        distance_pct = abs(current_price - nearest_support) / current_price

        # Get support touches and recency
        support_touches = self._calculate_support_touches(df, nearest_support, atr)
        recency_weight = self._calculate_recency_weight(support_touches['last_touch_days'])

        sq_score, sq_details = self._calculate_sq(
            distance_pct, support_touches, recency_weight,
            0.0, atr, ind, df
        )

        # Check if clear resistance level exists (range)
        resistance = self._detect_resistance_level(df)
        if resistance is not None:
            support = self._detect_support_level(df)
            if support is not None:
                range_width = (resistance - support) / support
                if 0.05 < range_width < 0.20:  # Reasonable range
                    sq_score += self.PARAMS['range_existence_bonus']
                    sq_details['range_bonus'] = self.PARAMS['range_existence_bonus']
                    sq_details['range_width'] = range_width

        return min(6.0, sq_score), sq_details

    def _calculate_support_touches(self, df: pd.DataFrame, support_level: float, atr: float) -> Dict:
        """
        Calculate support touches within tolerance (±0.5 ATR).

        v7.0: Now tracks touch_dates list for recency-based filtering.
        Returns touch_dates as list of days ago for each touch.
        """
        tolerance = atr * self.PARAMS['support_tolerance_atr']
        touches = 0
        last_touch_idx = None
        bounce_strengths = []
        touch_dates = []  # v7.0: Track days ago for each touch

        # Look back 90 days (about 63 trading days)
        lookback = min(63, len(df) - 1)

        for i in range(1, lookback + 1):
            idx = -(i + 1)
            if idx < -len(df):
                break

            low = df['low'].iloc[idx]
            close = df['close'].iloc[idx]
            open_price = df['open'].iloc[idx]
            prev_close = df['close'].iloc[idx - 1] if idx - 1 >= -len(df) else close

            # Check if price touched support
            if abs(low - support_level) <= tolerance or low <= support_level + tolerance:
                touches += 1
                last_touch_idx = i
                touch_dates.append(i)  # v7.0: Record this touch

                # Calculate bounce strength (close vs open after touch)
                if close > open_price:
                    strength = (close - open_price) / open_price * 100
                    bounce_strengths.append(min(strength, 5.0))  # Cap at 5%

        avg_bounce = sum(bounce_strengths) / len(bounce_strengths) if bounce_strengths else 0

        return {
            'touches': touches,
            'last_touch_days': last_touch_idx if last_touch_idx else 90,
            'avg_bounce_strength': avg_bounce,
            'bounce_count': len(bounce_strengths),
            'touch_dates': touch_dates,  # v7.0: Return touch dates list
        }

    def _calculate_recency_weight(self, days_since_touch: int) -> float:
        """Calculate recency weight with time decay."""
        if days_since_touch <= 30:
            return 1.0
        elif days_since_touch <= 60:
            return 0.7
        elif days_since_touch <= 90:
            return 0.5
        else:
            return 0.3

    def _calculate_sector_alpha(self, symbol: str, current_price: float, atr: float) -> float:
        """Check if sector ETF is also near support (Defense 3)."""
        if not self.stock_info or symbol not in self.stock_info:
            return 0.0

        sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')
        if sector == 'Unknown' or sector not in self.PARAMS['sector_etfs']:
            return 0.0

        etf_symbol = self.PARAMS['sector_etfs'][sector]
        if etf_symbol not in self.sector_etf_data:
            return 0.0

        etf_df = self.sector_etf_data[etf_symbol]
        if len(etf_df) < 20:
            return 0.0

        etf_price = etf_df['close'].iloc[-1]

        # Calculate ETF support levels
        calc = SupportResistanceCalculator(etf_df)
        etf_sr = calc.calculate_all()
        etf_supports = etf_sr.get('support', [])

        if not etf_supports:
            return 0.0

        # Find nearest ETF support
        etf_supports_below = [s for s in etf_supports if s < etf_price]
        if not etf_supports_below:
            return 0.0

        nearest_etf_support = max(etf_supports_below)
        etf_atr = atr  # Use same ATR scale for comparison
        etf_distance = abs(etf_price - nearest_etf_support) / etf_price

        # ETF within 3% of support = sector tailwind (+1 bonus)
        if etf_distance < self.PARAMS['max_distance_from_support']:
            return 1.0

        return 0.0

    def _calculate_sq(
        self,
        distance_pct: float,
        support_touches: Dict,
        recency_weight: float,
        sector_alpha: float,
        atr: float,
        ind: TechnicalIndicators,
        df: pd.DataFrame
    ) -> Tuple[float, Dict]:
        """
        Support Quality (SQ) - 6 points max.
        Touch frequency + Recency + Bounce strength + Distance + Sector Alpha.
        """
        details = {
            'distance_pct': distance_pct,
            'touches': support_touches['touches'],
            'recency_weight': recency_weight,
            'last_touch_days': support_touches['last_touch_days'],
            'avg_bounce_strength': support_touches['avg_bounce_strength'],
            'bounce_count': support_touches['bounce_count'],
            'sector_alpha': sector_alpha
        }

        sq_score = 0.0

        # 1. Touch frequency (0-1.5 pts)
        touches = support_touches['touches']
        if touches >= 3:
            sq_score += 1.5
        elif touches == 2:
            sq_score += 1.0
        elif touches == 1:
            sq_score += 0.5

        # 2. Recency weight applied to touch score
        sq_score = round(sq_score * recency_weight, 2)

        # 3. Bounce strength (0-1.5 pts)
        avg_bounce = support_touches['avg_bounce_strength']
        if avg_bounce >= 2.0:
            sq_score += 1.5
        elif avg_bounce >= 1.0:
            sq_score += 1.0
        elif avg_bounce > 0:
            sq_score += 0.5

        # 4. Support distance quality (0-1.5 pts)
        if distance_pct < 0.005:
            sq_score += 1.5
        elif distance_pct < 0.01:
            sq_score += 1.2
        elif distance_pct < 0.02:
            sq_score += 1.0
        elif distance_pct < 0.03:
            sq_score += 0.5

        # 5. Sector Alpha bonus (0-1 pt)
        sq_score += sector_alpha

        return round(min(6.0, sq_score), 2), details

    def _calculate_vd(self, volume_ratio: float, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        Volume Dynamics (VD) - 5 points max.
        3-phase pattern: Climax -> Dry-up -> Surge
        - Phase 1: Climax (0-1.5 pts): Volume >= 3x avg20d
        - Phase 2: Dry-up (0-1.5 pts): Volume < 0.6x avg
        - Phase 3: Surge (0-2.0 pts): Volume on reclaim >= 2x avg
        """
        details = {
            'volume_ratio': volume_ratio,
            'phase1_climax': 0.0,
            'phase2_dryup': 0.0,
            'phase3_surge': 0.0,
            'vd_dry_up': False
        }

        vd_score = 0.0
        vol_ma20 = df['volume'].iloc[-20:].mean() if len(df) >= 20 else df['volume'].mean()

        # Phase 1: Climax detection (look back up to 5 days)
        climax_score = 0.0
        climax_found = False
        for i in range(1, min(6, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break
            day_vol = df['volume'].iloc[idx]
            day_avg = df['volume'].iloc[max(-len(df), idx-20):idx].mean() if idx >= -len(df) + 20 else vol_ma20
            if day_avg > 0:
                day_ratio = day_vol / day_avg
                if day_ratio >= 4.0:
                    climax_score = 1.5
                    climax_found = True
                    details['climax_day'] = i
                    details['climax_ratio'] = day_ratio
                    break
                elif day_ratio >= 3.0:
                    # Linear interpolation: 3x = 1.0, 4x = 1.5
                    climax_score = 1.0 + (day_ratio - 3.0) * 0.5
                    climax_found = True
                    details['climax_day'] = i
                    details['climax_ratio'] = day_ratio
                    break

        details['phase1_climax'] = round(climax_score, 2)
        vd_score += climax_score

        # Phase 2: Dry-up detection (current volume)
        dryup_score = 0.0
        if volume_ratio < 0.4:
            dryup_score = 1.5
            details['vd_dry_up'] = True
        elif volume_ratio < 0.6:
            # Linear interpolation: 0.4x = 1.5, 0.6x = 1.0
            dryup_score = 1.5 - (volume_ratio - 0.4) * 2.5
            details['vd_dry_up'] = True

        details['phase2_dryup'] = round(dryup_score, 2)
        vd_score += dryup_score

        # Phase 3: Surge detection (volume on reclaim >= 2x avg)
        surge_score = 0.0
        # Look for recent surge after dry-up (last 3 days)
        for i in range(1, min(4, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break
            day_vol = df['volume'].iloc[idx]
            day_avg = df['volume'].iloc[max(-len(df), idx-20):idx].mean() if idx >= -len(df) + 20 else vol_ma20
            if day_avg > 0:
                day_ratio = day_vol / day_avg
                if day_ratio >= 3.0:
                    surge_score = 2.0
                    details['surge_day'] = i
                    details['surge_ratio'] = day_ratio
                    break
                elif day_ratio >= 2.0:
                    # Linear interpolation: 2x = 1.0, 3x = 2.0
                    surge_score = 1.0 + (day_ratio - 2.0)
                    details['surge_day'] = i
                    details['surge_ratio'] = day_ratio
                    break

        details['phase3_surge'] = round(surge_score, 2)
        vd_score += surge_score

        return round(min(5.0, vd_score), 2), details

    def _calculate_rb(self, ind: TechnicalIndicators, df: pd.DataFrame, clv: float, symbol: str = '') -> Tuple[float, Dict]:
        """
        Rebound Setup (RB) - 6 points max.

        v5.0: Continuous 1-5 day reclaim scoring based on days since false breakdown.
        v7.0: Changes:
          - Add depth ≥2% hard gate (depth<2% returns 0 score)
          - Remove 4-5 day reclaim scoring (expired)

        Scoring:
        - 1 day = full points (2.0)
        - 2-3 days = medium points (1.0-1.5)
        - 4-5 days = EXPIRED (v7.0: removed 0.5 pts)
        - Plus sector alignment (0-1.0 pts)
        """
        today = df.iloc[-1]
        current_price = today['close']
        high = today['high']
        low = today['low']
        open_price = today['open']

        # Calculate shadow ratios
        total_range = high - low
        lower_shadow = min(open_price, current_price) - low if min(open_price, current_price) > low else 0
        upper_shadow = high - max(open_price, current_price) if high > max(open_price, current_price) else 0

        # Calculate days since false breakdown (reclaim)
        days_since_breakdown = self._calculate_days_since_breakdown(df)

        # v7.0: Calculate depth from support for hard gate
        current_price = df['close'].iloc[-1]
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])
        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.99
        depth_pct = abs(current_price - nearest_support) / current_price

        # Calculate sector alignment score
        sector_alignment = self._calculate_sector_alignment(symbol)

        details = {
            'clv': clv,
            'lower_shadow_pct': 0,
            'has_hammer': False,
            'prior_halt': False,
            'days_since_breakdown': days_since_breakdown,
            'depth_pct': depth_pct,
            'sector_alignment': sector_alignment
        }

        rb_score = 0.0

        # v7.0: Hard gate - depth must be ≥2%
        if depth_pct < 0.02:
            details['depth_gate_failed'] = True
            details['reclaim_score'] = 'depth_too_shallow'
            return 0.0, details

        # v5.0/v7.0: Continuous reclaim scoring based on days since breakdown
        # v7.0: 4-5 day reclaims now EXPIRED (removed 0.5 pts scoring)
        if days_since_breakdown <= 1:
            rb_score += 2.0  # 1 day = full reclaim score
            details['reclaim_score'] = 'full'
        elif days_since_breakdown <= 3:
            # Linear interpolation: 2 days = 1.5, 3 days = 1.0
            rb_score += 2.0 - (days_since_breakdown - 1) * 0.5
            details['reclaim_score'] = 'medium'
        elif days_since_breakdown <= 5:
            # v7.0: 4-5 days = EXPIRED (removed 0.5 pts scoring)
            details['reclaim_score'] = 'expired'
        else:
            details['reclaim_score'] = 'expired'

        if total_range > 0:
            lower_shadow_pct = lower_shadow / total_range
            details['lower_shadow_pct'] = lower_shadow_pct

            # Lower shadow bonus (0-1 pt)
            if lower_shadow_pct >= 0.6:
                rb_score += 1.0
                details['has_hammer'] = True
            elif lower_shadow_pct >= 0.4:
                rb_score += 0.7
            elif lower_shadow_pct >= 0.3:
                rb_score += 0.4

        # CLV position bonus (0-1 pt) - higher is better
        if clv >= 0.7:
            rb_score += 1.0
        elif clv >= 0.5:
            rb_score += 0.7
        elif clv >= 0.4:
            rb_score += 0.4

        # Sector alignment bonus (0-1.0 pts)
        rb_score += sector_alignment

        return round(min(6.0, rb_score), 2), details

    def _calculate_sector_alignment(self, symbol: str) -> float:
        """
        Calculate sector alignment score based on sector ETF vs EMA50.
        Returns 0-1.0 points:
        - Above EMA50 by >2%: +1.0
        - Within EMA50±2%: +0.5
        - Below EMA50 by >2%: 0
        """
        if not self.stock_info or not symbol or symbol not in self.stock_info:
            return 0.0

        sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')
        if sector == 'Unknown' or sector not in self.PARAMS['sector_etfs']:
            return 0.0

        etf_symbol = self.PARAMS['sector_etfs'][sector]
        if etf_symbol not in self.sector_etf_data:
            return 0.0

        etf_df = self.sector_etf_data[etf_symbol]
        if len(etf_df) < 50:
            return 0.0

        etf_price = etf_df['close'].iloc[-1]
        etf_ema50 = etf_df['close'].ewm(span=50).mean().iloc[-1]

        if etf_ema50 == 0:
            return 0.0

        etf_vs_ema_pct = (etf_price - etf_ema50) / etf_ema50

        # Above EMA50 by >2%: +1.0
        if etf_vs_ema_pct > 0.02:
            return 1.0
        # Within EMA50±2%: +0.5
        elif abs(etf_vs_ema_pct) <= 0.02:
            return 0.5
        # Below EMA50 by >2%: 0
        else:
            return 0.0

    def _calculate_days_since_breakdown(self, df: pd.DataFrame) -> int:
        """
        Calculate days since false breakdown below support.
        Returns number of days since price broke below support and rebounded.
        """
        if len(df) < 10:
            return 999  # Not enough data

        current_price = df['close'].iloc[-1]

        # Calculate support levels
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        if not supports:
            return 999

        # Find nearest support below current price
        supports_below = [s for s in supports if s < current_price]
        if not supports_below:
            return 999

        nearest_support = max(supports_below)

        # Look back up to 10 days to find false breakdown
        lookback_days = min(10, len(df) - 1)
        breakdown_day = None

        for i in range(1, lookback_days + 1):
            idx = -(i + 1)  # Go back i days from today
            if idx < -len(df):
                break

            low = df['low'].iloc[idx]
            close = df['close'].iloc[idx]

            # Check if price broke below support (low < support)
            # and then closed back above (close > support) - false breakdown
            if low < nearest_support and close > nearest_support:
                breakdown_day = i
                break
            # Or price is now below support level but close reclaimed it
            elif low < nearest_support:
                # Check if subsequent days reclaimed
                for j in range(1, i):
                    check_idx = -(j + 1)
                    if check_idx >= -len(df):
                        check_close = df['close'].iloc[check_idx]
                        if check_close > nearest_support:
                            breakdown_day = j
                            break
                if breakdown_day:
                    break

        return breakdown_day if breakdown_day else 999

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """Calculate entry, stop, and target prices."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.98

        entry = round(current_price, 2)
        stop = round(nearest_support - atr * 0.5, 2)  # Support minus 0.5 ATR buffer
        target = round(current_price + atr * self.PARAMS['target_r_multiplier'], 2)

        return entry, stop, target

    def build_match_reasons(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> List[str]:
        """Build human-readable match reasons."""
        sq = next((d for d in dimensions if d.name == 'SQ'), None)
        vd = next((d for d in dimensions if d.name == 'VD'), None)
        rb = next((d for d in dimensions if d.name == 'RB'), None)

        position_pct = self.calculate_position_pct(tier)

        sq_details = sq.details if sq else {}
        vd_details = vd.details if vd else {}
        rb_details = rb.details if rb else {}

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"SQ:{sq.score:.2f} VD:{vd.score:.2f} RB:{rb.score:.2f}"
        ]

        # SQ details
        touches = sq_details.get('touches', 0)
        recency_weight = sq_details.get('recency_weight', 0)
        sector_alpha = sq_details.get('sector_alpha', 0)
        if sector_alpha > 0:
            reasons.append(f"Support x{touches} (w:{recency_weight}, +{sector_alpha}α)")
        else:
            reasons.append(f"Support x{touches} (w:{recency_weight})")

        # VD details
        vol_ratio = vd_details.get('volume_ratio', 0)
        contraction_days = vd_details.get('contraction_days', 0)
        reasons.append(f"Vol {vol_ratio:.1f}x, {contraction_days}d dry")

        # RB details
        reclaim_days = rb_details.get('days_since_breakdown')
        if reclaim_days and reclaim_days <= 5:
            reasons.append(f"Reclaim d{reclaim_days} ({rb_details.get('reclaim_score', 'unknown')})")
        if rb_details.get('has_hammer'):
            reasons.append("Hammer candle + bounce")

        return reasons
