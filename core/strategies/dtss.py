"""Strategy G: DTSS - Distribution Top Sell Signal (Short)."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class DTSSStrategy(BaseStrategy):
    """Strategy G: DTSS - Distribution Top Sell Signal (Short strategy).

    Short strategy: Within 3% of 60-day high + showing weakness.
    """

    NAME = "DTSS"
    STRATEGY_TYPE = StrategyType.DTSS
    DESCRIPTION = "Distribution Top Sell Signal - Short strategy near highs with weakness"
    DIMENSIONS = ['PQ', 'WS', 'VC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 60,
        'max_distance_from_high': 0.03,
        'target_r_multiplier': 3.0,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for DTSS candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        current_price = df['close'].iloc[-1]
        price_metrics = ind.indicators.get('price_metrics', {})
        high_60d = price_metrics.get('high_60d')

        if high_60d is None:
            return False

        # Check if near 60-day high (within 3%)
        distance_from_high = abs(high_60d - current_price) / current_price
        if distance_from_high > self.PARAMS['max_distance_from_high']:
            return False

        # Check for weakness signs
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8')
        ema21 = ema.get('ema21')

        if ema8 is None or ema21 is None:
            return False

        # Weakness: EMA8 crossing below EMA21 or price below both
        weakness = ema8 < ema21 or current_price < ema8

        if not weakness:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        price_metrics = ind.indicators.get('price_metrics', {})
        high_60d = price_metrics.get('high_60d', current_price)
        distance_from_high = abs(high_60d - current_price) / current_price

        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', current_price)
        ema21 = ema.get('ema21', current_price)

        volume_data = ind.indicators.get('volume', {})
        volume_spike = volume_data.get('volume_spike', False)
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        dimensions = []

        # Dimension 1: Proximity Quality (PQ)
        pq_score = self._calculate_pq(distance_from_high)
        dimensions.append(ScoringDimension(
            name='PQ',
            score=pq_score,
            max_score=5.0,
            details={
                'high_60d': high_60d,
                'distance_from_high': distance_from_high
            }
        ))

        # Dimension 2: Weakness Signals (WS)
        ws_score = self._calculate_ws(ema8, ema21, current_price)
        dimensions.append(ScoringDimension(
            name='WS',
            score=ws_score,
            max_score=5.0,
            details={
                'ema8': ema8,
                'ema21': ema21,
                'ema_bearish': ema8 < ema21,
                'price_below_ema8': current_price < ema8
            }
        ))

        # Dimension 3: Volume Confirmation (VC)
        vc_score = self._calculate_vc(volume_spike, volume_ratio)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'volume_spike': volume_spike,
                'volume_ratio': volume_ratio
            }
        ))

        return dimensions

    def _calculate_pq(self, distance_pct: float) -> float:
        """Proximity Quality dimension (0-5) - closer to high is better for short."""
        pq_score = 0.0

        # Near the high is good for short
        if distance_pct < 0.01:
            pq_score += 3.0
        elif distance_pct < 0.02:
            pq_score += 2.5
        elif distance_pct < 0.03:
            pq_score += 2.0
        else:
            pq_score += 1.0

        # Bonus for extreme proximity
        if distance_pct < 0.005:
            pq_score += 2.0
        elif distance_pct < 0.015:
            pq_score += 1.0

        return round(min(5.0, pq_score), 2)

    def _calculate_ws(self, ema8: float, ema21: float, price: float) -> float:
        """Weakness Signals dimension (0-5)."""
        ws_score = 0.0

        # EMA crossover (bearish)
        if ema8 < ema21:
            ema_diff = (ema21 - ema8) / ema21
            if ema_diff > 0.02:
                ws_score += 3.0
            elif ema_diff > 0.01:
                ws_score += 2.0 + (ema_diff - 0.01) / 0.01
            else:
                ws_score += 1.0 + ema_diff / 0.01

        # Price below EMA8
        if price < ema8:
            price_diff = (ema8 - price) / ema8
            if price_diff > 0.01:
                ws_score += 2.0
            else:
                ws_score += price_diff / 0.01 * 2.0

        return round(min(5.0, ws_score), 2)

    def _calculate_vc(self, volume_spike: bool, volume_ratio: float) -> float:
        """Volume Confirmation dimension (0-5)."""
        vc_score = 0.0

        # Volume spike on decline
        if volume_spike:
            vc_score += 3.0
        elif volume_ratio > 1.5:
            vc_score += 2.0 + min(1.0, (volume_ratio - 1.5) / 1.0)
        elif volume_ratio > 1.2:
            vc_score += 1.0 + (volume_ratio - 1.2) / 0.3

        # Above average volume
        if volume_ratio > 1.0:
            vc_score += 1.0
        elif volume_ratio > 0.8:
            vc_score += 0.5

        return round(min(5.0, vc_score), 2)

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """Calculate entry, stop, and target prices for short."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        price_metrics = ind.indicators.get('price_metrics', {})
        high_60d = price_metrics.get('high_60d', current_price * 1.03)

        entry = round(current_price, 2)
        stop = round(high_60d + atr, 2)
        target = round(current_price - atr * self.PARAMS['target_r_multiplier'], 2)

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
        pq = next((d for d in dimensions if d.name == 'PQ'), None)
        ws = next((d for d in dimensions if d.name == 'WS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        pq_details = pq.details if pq else {}
        ws_details = ws.details if ws else {}
        vc_details = vc.details if vc else {}

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"PQ:{pq.score:.2f} WS:{ws.score:.2f} VC:{vc.score:.2f}",
            f"Near 60d high ({pq_details.get('distance_from_high', 0)*100:.1f}%)",
            f"Weakness: EMA8<EMA21: {ws_details.get('ema_bearish', False)}",
            f"Volume spike: {vc_details.get('volume_spike', False)}"
        ]
