"""Strategy F: Range Support - Range bottom support with multiple tests."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from ..support_resistance import SupportResistanceCalculator
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class RangeSupportStrategy(BaseStrategy):
    """Strategy F: Range Support - Uptrend with support tested 3+ times."""

    NAME = "RangeSupport"
    STRATEGY_TYPE = StrategyType.RANGE_SUPPORT
    DESCRIPTION = "Range bottom support entry with multiple tests in uptrend"
    DIMENSIONS = ['TQ', 'SR', 'TC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 60,
        'min_touches': 3,
        'max_distance_from_support': 0.03,
        'target_r_multiplier': 3.0,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for range support candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        # Must be in uptrend
        if not ind.is_uptrend():
            return False

        current_price = df['close'].iloc[-1]

        # Calculate S/R with focus on trading ranges
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        # Find levels with multiple touches
        all_levels = sr_levels.get('all_levels', [])
        range_levels = [l for l in all_levels if l.get('touches', 0) >= self.PARAMS['min_touches']]

        if not range_levels:
            return False

        # Find support level near current price
        for level_info in range_levels:
            level_price = level_info['price']
            if current_price > level_price:
                distance_pct = (current_price - level_price) / current_price
                if distance_pct <= self.PARAMS['max_distance_from_support']:
                    return True

        return False

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        all_levels = sr_levels.get('all_levels', [])

        # Find the best level
        best_level = None
        best_distance = float('inf')

        for level_info in all_levels:
            if level_info.get('touches', 0) >= self.PARAMS['min_touches']:
                level_price = level_info['price']
                if current_price > level_price:
                    distance_pct = (current_price - level_price) / current_price
                    if distance_pct < best_distance:
                        best_distance = distance_pct
                        best_level = level_info

        if best_level is None:
            return []

        level_price = best_level['price']
        touches = best_level.get('touches', 0)
        distance_pct = best_distance

        dimensions = []

        # Dimension 1: Trend Quality (TQ)
        tq_score = self._calculate_tq(ind, current_price)
        dimensions.append(ScoringDimension(
            name='TQ',
            score=tq_score,
            max_score=5.0,
            details={
                'is_uptrend': ind.is_uptrend()
            }
        ))

        # Dimension 2: Support Quality (SR)
        sr_score = self._calculate_sr(best_level, distance_pct)
        dimensions.append(ScoringDimension(
            name='SR',
            score=sr_score,
            max_score=5.0,
            details={
                'support_level': level_price,
                'touches': touches,
                'distance_pct': distance_pct
            }
        ))

        # Dimension 3: Trend Context (TC)
        tc_score = self._calculate_tc(ind, current_price)
        dimensions.append(ScoringDimension(
            name='TC',
            score=tc_score,
            max_score=5.0,
            details={}
        ))

        return dimensions

    def _calculate_tq(self, ind: TechnicalIndicators, price: float) -> float:
        """Trend Quality dimension (0-5)."""
        tq_score = 0.0

        # Strong uptrend
        if ind.is_uptrend():
            tq_score += 2.5

        # EMA alignment
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', price)
        ema21 = ema.get('ema21', price)
        ema50 = ema.get('ema50', price)

        if ema8 > ema21 > ema50:
            tq_score += 2.5
        elif ema21 > ema50:
            tq_score += 1.5

        return round(min(5.0, tq_score), 2)

    def _calculate_sr(self, level_info: Dict, distance_pct: float) -> float:
        """Support Quality dimension (0-5)."""
        sr_score = 0.0
        touches = level_info.get('touches', 0)

        # Number of touches
        if touches >= 5:
            sr_score += 3.0
        elif touches >= 3:
            sr_score += 2.0 + (touches - 3) / 2.0
        else:
            sr_score += touches * 0.5

        # Proximity (closer is better)
        if distance_pct < 0.01:
            sr_score += 2.0
        elif distance_pct < 0.02:
            sr_score += 1.5
        elif distance_pct < 0.03:
            sr_score += 1.0
        else:
            sr_score += 0.5

        return round(min(5.0, sr_score), 2)

    def _calculate_tc(self, ind: TechnicalIndicators, price: float) -> float:
        """Trend Context dimension (0-5)."""
        tc_score = 0.0

        # ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct > 0.04:
            tc_score += 2.0
        elif adr_pct > 0.03:
            tc_score += 1.5
        elif adr_pct > 0.02:
            tc_score += 1.0

        # Volume health
        volume_data = ind.indicators.get('volume', {})
        volume_sma = volume_data.get('volume_sma', 0)
        if volume_sma > 2_000_000:
            tc_score += 2.0
        elif volume_sma > 1_000_000:
            tc_score += 1.0

        # EMA slope
        ema50_slope = ind.calculate_stable_ema_slope(period=50, comparison_days=3)
        if ema50_slope.get('is_uptrend'):
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

        sr = next((d for d in dimensions if d.name == 'SR'), None)
        support_level = sr.details.get('support_level', current_price * 0.97) if sr else current_price * 0.97

        entry = round(current_price, 2)
        stop = round(support_level - atr, 2)
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
        tq = next((d for d in dimensions if d.name == 'TQ'), None)
        sr = next((d for d in dimensions if d.name == 'SR'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)

        position_pct = self.calculate_position_pct(tier)

        sr_details = sr.details if sr else {}
        touches = sr_details.get('touches', 0)

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} SR:{sr.score:.2f} TC:{tc.score:.2f}",
            f"Support tested {touches} times",
            "Uptrend confirmed",
            "Range bottom entry"
        ]
