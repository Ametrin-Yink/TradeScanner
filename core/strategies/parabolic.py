"""Strategy H: Parabolic - Parabolic short setup."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class ParabolicStrategy(BaseStrategy):
    """Strategy H: Parabolic - Short extreme overextensions.

    RSI>80 + price > 50EMA + 5*ATR + 2+ gaps in 5 days.
    """

    NAME = "Parabolic"
    STRATEGY_TYPE = StrategyType.PARABOLIC
    DESCRIPTION = "Parabolic short - Extreme overextension reversal"
    DIMENSIONS = ['MO', 'EX', 'VC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'rsi_threshold': 80,
        'ema_atr_multiplier': 5.0,
        'min_gaps': 2,
        'lookback_days': 5,
        'stop_atr_multiplier': 2.0,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for parabolic candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi')

        if rsi is None or rsi <= self.PARAMS['rsi_threshold']:
            return False

        current_price = df['close'].iloc[-1]
        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50')
        atr = ind.indicators.get('atr', {}).get('atr')

        if ema50 is None or atr is None:
            return False

        # Price should be significantly above 50EMA
        if current_price <= ema50 + self.PARAMS['ema_atr_multiplier'] * atr:
            return False

        # Check for gaps
        price_metrics = ind.indicators.get('price_metrics', {})
        gaps = price_metrics.get('gaps_5d', 0)

        if gaps < self.PARAMS['min_gaps']:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi', 50)

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        price_metrics = ind.indicators.get('price_metrics', {})
        gaps = price_metrics.get('gaps_5d', 0)

        # Distance from EMA
        distance_from_ema = (current_price - ema50) / ema50
        atr_multiple = distance_from_ema / (atr / current_price) if atr > 0 else 0

        dimensions = []

        # Dimension 1: Momentum Overextension (MO)
        mo_score = self._calculate_mo(rsi, atr_multiple)
        dimensions.append(ScoringDimension(
            name='MO',
            score=mo_score,
            max_score=5.0,
            details={
                'rsi': rsi,
                'atr_multiple': atr_multiple
            }
        ))

        # Dimension 2: Extension Level (EX)
        ex_score = self._calculate_ex(distance_from_ema, gaps)
        dimensions.append(ScoringDimension(
            name='EX',
            score=ex_score,
            max_score=5.0,
            details={
                'distance_from_ema_pct': distance_from_ema,
                'gaps_5d': gaps
            }
        ))

        # Dimension 3: Volume Confirmation (VC)
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)
        volume_spike = volume_data.get('volume_spike', False)

        vc_score = self._calculate_vc(volume_ratio, volume_spike)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'volume_ratio': volume_ratio,
                'volume_spike': volume_spike
            }
        ))

        return dimensions

    def _calculate_mo(self, rsi: float, atr_multiple: float) -> float:
        """Momentum Overextension dimension (0-5)."""
        mo_score = 0.0

        # RSI overbought
        if rsi > 85:
            mo_score += 3.0
        elif rsi > 80:
            mo_score += 2.0 + (rsi - 80) / 5.0
        else:
            mo_score += max(0, (rsi - 70) / 10.0)

        # Distance from EMA in ATR terms
        if atr_multiple > 10:
            mo_score += 2.0
        elif atr_multiple > 7:
            mo_score += 1.5 + (atr_multiple - 7) / 3.0 * 0.5
        elif atr_multiple > 5:
            mo_score += 1.0 + (atr_multiple - 5) / 2.0 * 0.5
        else:
            mo_score += max(0, (atr_multiple - 3) / 2.0)

        return round(min(5.0, mo_score), 2)

    def _calculate_ex(self, distance_pct: float, gaps: int) -> float:
        """Extension Level dimension (0-5)."""
        ex_score = 0.0

        # Distance from EMA
        if distance_pct > 0.20:
            ex_score += 3.0
        elif distance_pct > 0.15:
            ex_score += 2.0 + (distance_pct - 0.15) / 0.05
        elif distance_pct > 0.10:
            ex_score += 1.0 + (distance_pct - 0.10) / 0.05
        else:
            ex_score += max(0, distance_pct / 0.10)

        # Gaps
        if gaps >= 4:
            ex_score += 2.0
        elif gaps >= 3:
            ex_score += 1.5
        elif gaps >= 2:
            ex_score += 1.0

        return round(min(5.0, ex_score), 2)

    def _calculate_vc(self, volume_ratio: float, volume_spike: bool) -> float:
        """Volume Confirmation dimension (0-5)."""
        vc_score = 0.0

        # Volume spike
        if volume_spike:
            vc_score += 3.0
        elif volume_ratio > 2.0:
            vc_score += 2.0 + min(1.0, (volume_ratio - 2.0) / 2.0)
        elif volume_ratio > 1.5:
            vc_score += 1.0 + (volume_ratio - 1.5) / 0.5

        # Elevated volume
        if volume_ratio > 1.2:
            vc_score += 1.5
        elif volume_ratio > 1.0:
            vc_score += 0.5 + (volume_ratio - 1.0) / 0.2 * 1.0

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

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price * 0.95)

        entry = round(current_price, 2)
        stop = round(current_price + atr * self.PARAMS['stop_atr_multiplier'], 2)
        target = round(ema50, 2)

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
        mo = next((d for d in dimensions if d.name == 'MO'), None)
        ex = next((d for d in dimensions if d.name == 'EX'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        mo_details = mo.details if mo else {}
        ex_details = ex.details if ex else {}

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"MO:{mo.score:.2f} EX:{ex.score:.2f} VC:{vc.score:.2f}",
            f"RSI: {mo_details.get('rsi', 0):.1f}",
            f"Gaps in 5d: {ex_details.get('gaps_5d', 0)}",
            "Parabolic extension"
        ]
