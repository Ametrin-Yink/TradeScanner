"""Strategy E: Upthrust & Rebound (U&R) - Near support with volume contraction."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from ..support_resistance import SupportResistanceCalculator
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class UpthrustReboundStrategy(BaseStrategy):
    """Strategy E: Upthrust & Rebound - Price within 1% of support + volume contraction."""

    NAME = "U&R"
    STRATEGY_TYPE = StrategyType.UPTHRUST_REBOUND
    DESCRIPTION = "Upthrust and Rebound near support level with volume contraction"
    DIMENSIONS = ['SR', 'VC', 'TC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'max_distance_from_support': 0.01,
        'target_r_multiplier': 2.5,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for U&R candidates."""
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

        # Check volume contraction
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        if volume_ratio > 0.8:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.99
        distance_pct = abs(current_price - nearest_support) / current_price

        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        dimensions = []

        # Dimension 1: Support Quality (SR)
        sr_score = self._calculate_sr(distance_pct, sr_levels)
        dimensions.append(ScoringDimension(
            name='SR',
            score=sr_score,
            max_score=5.0,
            details={
                'nearest_support': nearest_support,
                'distance_pct': distance_pct,
                'num_supports': len(supports)
            }
        ))

        # Dimension 2: Volume Contraction (VC)
        vc_score = self._calculate_vc(volume_ratio)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'volume_ratio': volume_ratio
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
        stop = round(nearest_support - atr, 2)
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
        sr = next((d for d in dimensions if d.name == 'SR'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)

        position_pct = self.calculate_position_pct(tier)

        sr_details = sr.details if sr else {}
        vc_details = vc.details if vc else {}

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"SR:{sr.score:.2f} VC:{vc.score:.2f} TC:{tc.score:.2f}",
            f"Near support ({sr_details.get('distance_pct', 0)*100:.1f}%)",
            f"Volume contraction ({vc_details.get('volume_ratio', 0):.1f}x)",
            "U&R setup"
        ]
