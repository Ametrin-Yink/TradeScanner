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


class UpthrustReboundStrategy(BaseStrategy):
    """Strategy E: 支撑回踩买入 - 支撑位假跌破后反弹，区间存在加分（合并原Range多头）"""

    NAME = "SupportBounce"
    STRATEGY_TYPE = StrategyType.UPTHRUST_REBOUND
    DESCRIPTION = "SupportBounce v2.0 - Support level false breakdown rebound, range existence bonus"
    DIMENSIONS = ['SQ', 'VD', 'RB']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'max_distance_from_support': 0.03,  # Relaxed from 1% to 3%
        'target_r_multiplier': 2.0,  # Changed from 2.5 to 2.0
        'support_tolerance_atr': 0.5,  # Support level ± 0.5 ATR
        'volume_veto_threshold': 1.5,  # Volume > 1.5x MA20 for veto
        'clv_veto_threshold': 0.3,  # CLV < 0.3 for veto
        'time_stop_days': 5,  # Changed from 3 to 5
        'time_stop_clv_min': 0.4,  # CLV avg > 0.4
        'range_existence_bonus': 0.5,  # Range existence bonus from F
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

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter.
        - SPY > EMA200 (no rebound in downtrend)
        - Support exists and within 3%
        """
        # Phase 0: Check SPY trend
        logger.info("U&R: Phase 0 - Checking SPY trend...")
        spy_df = getattr(self, '_spy_df', None)
        if spy_df is None:
            spy_df = self._get_data('SPY')
        if spy_df is not None and len(spy_df) >= 200:
            spy_current = spy_df['close'].iloc[-1]
            spy_ema200 = spy_df['close'].ewm(span=200).mean().iloc[-1]

            if spy_current <= spy_ema200:
                logger.info("U&R: SPY below EMA200, skipping (no rebound in downtrend)")
                return []

        # Pre-filter by support existence and distance
        prefiltered = []
        logger.info("U&R: Phase 0.5 - Pre-filtering by support...")

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    continue

                current_price = df['close'].iloc[-1]

                # Calculate S/R with tolerance
                calc = SupportResistanceCalculator(df)
                sr_levels = calc.calculate_all()
                supports = sr_levels.get('support', [])

                if not supports:
                    continue

                # Find nearest support
                supports_below = [s for s in supports if s < current_price]
                if not supports_below:
                    continue

                nearest_support = max(supports_below)
                distance_pct = (current_price - nearest_support) / current_price

                # Relaxed threshold: < 3%
                if distance_pct < self.PARAMS['max_distance_from_support']:
                    prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"U&R: {len(prefiltered)}/{len(symbols)} passed pre-filter")

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
        return super().screen(prefiltered)

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
        """Filter for U&R candidates with volume veto check."""
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

        if distance_pct > self.PARAMS['max_distance_from_support']:
            return False

        # Defense 2: Volume Trap Veto (Falling Knife Detection)
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        # Calculate CLV
        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])

        # Veto if high volume with low CLV (accelerating decline)
        if volume_ratio > self.PARAMS['volume_veto_threshold'] and clv < self.PARAMS['clv_veto_threshold']:
            logger.debug(f"{symbol}: Volume trap veto (Vol:{volume_ratio:.2f}x, CLV:{clv:.2f})")
            return False

        # Check volume contraction (normal U&R requires dry volume)
        if volume_ratio > 0.9:
            return False

        return True

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
        sq_score = min(6.0, sq_score)
        dimensions.append(ScoringDimension(
            name='SQ',
            score=sq_score,
            max_score=6.0,
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

        # Dimension 3: Rebound Setup (RB) - 4 points max
        rb_score, rb_details = self._calculate_rb(ind, df, clv)
        dimensions.append(ScoringDimension(
            name='RB',
            score=rb_score,
            max_score=4.0,
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
        """Calculate support touches within tolerance (±0.5 ATR)."""
        tolerance = atr * self.PARAMS['support_tolerance_atr']
        touches = 0
        last_touch_idx = None
        bounce_strengths = []

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

                # Calculate bounce strength (close vs open after touch)
                if close > open_price:
                    strength = (close - open_price) / open_price * 100
                    bounce_strengths.append(min(strength, 5.0))  # Cap at 5%

        avg_bounce = sum(bounce_strengths) / len(bounce_strengths) if bounce_strengths else 0

        return {
            'touches': touches,
            'last_touch_days': last_touch_idx if last_touch_idx else 90,
            'avg_bounce_strength': avg_bounce,
            'bounce_count': len(bounce_strengths)
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
        Volume Dryness (VD) - 5 points max.
        Contraction degree + Contraction duration.
        """
        details = {
            'volume_ratio': volume_ratio,
            'contraction_days': 0,
            'vd_dry_up': False
        }

        vd_score = 0.0

        # Volume contraction degree (0-3 pts)
        if volume_ratio < 0.5:
            vd_score += 3.0
            details['vd_dry_up'] = True
        elif volume_ratio < 0.65:
            vd_score += 2.5
        elif volume_ratio < 0.8:
            vd_score += 2.0
        elif volume_ratio < 1.0:
            vd_score += 1.0
        else:
            vd_score += 0.5

        # Contraction duration bonus (0-2 pts)
        contraction_days = 0
        for i in range(1, min(10, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break
            vol_ratio_hist = df['volume'].iloc[idx] / df['volume'].iloc[idx-20:idx].mean() if idx >= -len(df) + 20 else 1.0
            if vol_ratio_hist < 0.8:
                contraction_days += 1
            else:
                break

        details['contraction_days'] = contraction_days

        if contraction_days >= 3:
            vd_score += 2.0
        elif contraction_days == 2:
            vd_score += 1.5
        elif contraction_days == 1:
            vd_score += 0.5

        return round(min(5.0, vd_score), 2), details

    def _calculate_rb(self, ind: TechnicalIndicators, df: pd.DataFrame, clv: float) -> Tuple[float, Dict]:
        """
        Rebound Setup (RB) - 4 points max.
        Long lower shadow + CLV position + Prior day halt.
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

        details = {
            'clv': clv,
            'lower_shadow_pct': 0,
            'has_hammer': False,
            'prior_halt': False
        }

        rb_score = 0.0

        if total_range > 0:
            lower_shadow_pct = lower_shadow / total_range
            details['lower_shadow_pct'] = lower_shadow_pct

            # 1. Long lower shadow (0-1.5 pts)
            if lower_shadow_pct >= 0.6:
                rb_score += 1.5
                details['has_hammer'] = True
            elif lower_shadow_pct >= 0.4:
                rb_score += 1.0
            elif lower_shadow_pct >= 0.3:
                rb_score += 0.5

        # 2. CLV position (0-1.5 pts) - higher is better
        if clv >= 0.7:
            rb_score += 1.5
        elif clv >= 0.5:
            rb_score += 1.0
        elif clv >= 0.4:
            rb_score += 0.5

        # 3. Prior day halt pattern (0-1 pt)
        if len(df) >= 2:
            prev = df.iloc[-2]
            prev_range = prev['high'] - prev['low']
            if prev_range > 0:
                prev_clv = (prev['close'] - prev['low']) / prev_range
                # Prior day closed near low, today bouncing
                if prev_clv < 0.3 and clv > 0.5:
                    rb_score += 1.0
                    details['prior_halt'] = True

        return round(min(4.0, rb_score), 2), details

    def _calculate_sr(self, distance_pct: float, sr_levels: Dict) -> float:
        """Support Quality dimension (0-5)."""
        sr_score = 0.0

        # Proximity to support (closer is better)
        if distance_pct < 0.005:
            sr_score += 3.0
        elif distance_pct < 0.01:
            sr_score += 2.0 + (0.01 - distance_pct) / 0.005
        else:
            sr_score += max(0, 1.0 - (distance_pct - 0.01) / 0.01)

        # Number of support levels
        supports = sr_levels.get('support', [])
        if len(supports) >= 3:
            sr_score += 1.5
        elif len(supports) >= 2:
            sr_score += 1.0
        else:
            sr_score += 0.5

        # Support strength (if available)
        all_levels = sr_levels.get('all_levels', [])
        tested_levels = [l for l in all_levels if l.get('touches', 0) >= 2]
        if len(tested_levels) >= 2:
            sr_score += 0.5

        return round(min(5.0, sr_score), 2)

    def _calculate_vc(self, volume_ratio: float) -> float:
        """Volume Contraction dimension (0-5)."""
        vc_score = 0.0

        # Volume contraction (lower is better for entry)
        if volume_ratio < 0.5:
            vc_score += 3.0
        elif volume_ratio < 0.7:
            vc_score += 2.0 + (0.7 - volume_ratio) / 0.2
        elif volume_ratio < 0.8:
            vc_score += 1.0 + (0.8 - volume_ratio) / 0.1
        else:
            vc_score += max(0, 0.5 - (volume_ratio - 0.8) / 0.2 * 0.5)

        # Dry-up bonus
        if volume_ratio < 0.6:
            vc_score += 2.0
        elif volume_ratio < 0.8:
            vc_score += 1.0

        return round(min(5.0, vc_score), 2)

    def _calculate_tc(self, ind: TechnicalIndicators, price: float) -> float:
        """Trend Context dimension (0-5)."""
        tc_score = 0.0

        # ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct > 0.03:
            tc_score += 2.0
        elif adr_pct > 0.02:
            tc_score += 1.0

        # Trend
        if ind.is_uptrend():
            tc_score += 2.0
        else:
            tc_score += 0.5

        # EMA proximity
        ema = ind.indicators.get('ema', {})
        ema21 = ema.get('ema21', price)
        if price > ema21:
            tc_score += 1.0

        return round(min(5.0, tc_score), 2)

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
        if rb_details.get('has_hammer'):
            reasons.append("Hammer candle + bounce")
        if rb_details.get('prior_halt'):
            reasons.append("Halt-rebound pattern")

        return reasons
