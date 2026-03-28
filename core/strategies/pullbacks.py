"""Strategy D: Pullbacks - Buying pullbacks from 20-day high."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class PullbacksStrategy(BaseStrategy):
    """Strategy D: Buying pullbacks - 1-5% pullback from 20-day high, above EMA50."""

    NAME = "Pullbacks"
    STRATEGY_TYPE = StrategyType.PULLBACKS
    DESCRIPTION = "Buying pullbacks from 20-day high while maintaining EMA50 support"
    DIMENSIONS = ['TQ', 'PD', 'TC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'pullback_min': 0.01,
        'pullback_max': 0.05,
        'pullback_days': 5,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for pullback candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        current_price = df['close'].iloc[-1]

        # Must be above EMA50
        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50')
        if ema50 is None or current_price <= ema50:
            return False

        # Check 20-day high
        price_metrics = ind.indicators.get('price_metrics', {})
        high_20d = price_metrics.get('high_20d')
        distance_from_high = price_metrics.get('distance_from_high')

        if high_20d is None or distance_from_high is None:
            return False

        # Must be in pullback (1-5% below high)
        pullback_pct = abs(distance_from_high)
        if pullback_pct < self.PARAMS['pullback_min'] or pullback_pct > self.PARAMS['pullback_max']:
            return False

        # Check pullback duration (price making lower highs)
        recent_highs = df['high'].tail(self.PARAMS['pullback_days']).values
        is_pullback = all(recent_highs[i] >= recent_highs[i+1] for i in range(len(recent_highs)-1))

        if not is_pullback:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring with CLV hard filter."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # CLV Hard Filter: CLV < 0.4 indicates accelerating decline (not just pullback)
        today = df.iloc[-1]
        high = today['high']
        low = today['low']
        close = today['close']

        if high > low:
            clv = (close - low) / (high - low)
        else:
            clv = 0.5

        if clv < 0.4:
            # CLV too low - price closed near low, likely still falling
            logger.debug(f"{symbol}: CLV {clv:.2f} < 0.4, filtering out (accelerating decline)")
            return []

        current_price = df['close'].iloc[-1]
        price_metrics = ind.indicators.get('price_metrics', {})
        high_20d = price_metrics.get('high_20d', current_price)
        distance_from_high = price_metrics.get('distance_from_high', 0)
        pullback_pct = abs(distance_from_high)

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price)
        ema21 = ema.get('ema21', current_price)

        dimensions = []

        # Dimension 1: Trend Quality (TQ)
        tq_score = self._calculate_tq(ind, ema50, ema21, current_price)
        dimensions.append(ScoringDimension(
            name='TQ',
            score=tq_score,
            max_score=5.0,
            details={
                'ema50': ema50,
                'ema21': ema21,
                'price_above_ema50': current_price > ema50
            }
        ))

        # Dimension 2: Pullback Depth (PD)
        pd_score = self._calculate_pd(pullback_pct)
        dimensions.append(ScoringDimension(
            name='PD',
            score=pd_score,
            max_score=5.0,
            details={
                'pullback_pct': pullback_pct,
                'high_20d': high_20d
            }
        ))

        # Dimension 3: Trend Context (TC)
        tc_score = self._calculate_tc(ind, current_price)
        dimensions.append(ScoringDimension(
            name='TC',
            score=tc_score,
            max_score=5.0,
            details={
                'distance_from_20d_high': distance_from_high
            }
        ))

        return dimensions

    def _calculate_tq(self, ind: TechnicalIndicators, ema50: float, ema21: float, price: float) -> float:
        """Trend Quality dimension (0-5)."""
        tq_score = 0.0

        # Price above EMA50
        if price > ema50:
            distance = (price - ema50) / ema50
            if distance < 0.05:
                tq_score += 2.0
            elif distance < 0.10:
                tq_score += 1.5
            else:
                tq_score += 1.0

        # EMA alignment (EMA21 > EMA50)
        if ema21 > ema50:
            tq_score += 2.0
        else:
            tq_score += 1.0

        # Uptrend check
        if ind.is_uptrend():
            tq_score += 1.0

        return round(min(5.0, tq_score), 2)

    def _calculate_pd(self, pullback_pct: float) -> float:
        """Pullback Depth dimension (0-5)."""
        # Optimal pullback is 2-4%
        if 0.02 <= pullback_pct <= 0.04:
            return 5.0
        elif 0.01 <= pullback_pct < 0.02:
            return 3.0 + (pullback_pct - 0.01) / 0.01 * 2.0
        elif 0.04 < pullback_pct <= 0.05:
            return 5.0 - (pullback_pct - 0.04) / 0.01 * 2.0
        else:
            return 2.0

    def _calculate_tc(self, ind: TechnicalIndicators, price: float) -> float:
        """Trend Context dimension (0-5)."""
        tc_score = 0.0

        # Volume confirmation
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)
        if volume_ratio < 0.8:
            tc_score += 2.0
        elif volume_ratio < 1.0:
            tc_score += 1.0

        # ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct > 0.03:
            tc_score += 2.0
        elif adr_pct > 0.02:
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

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price * 0.95)

        price_metrics = ind.indicators.get('price_metrics', {})
        high_20d = price_metrics.get('high_20d', current_price * 1.05)

        entry = round(current_price, 2)
        stop = round(ema50 - atr, 2)
        target = round(high_20d, 2)

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
        pd = next((d for d in dimensions if d.name == 'PD'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)

        position_pct = self.calculate_position_pct(tier)

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        price_metrics = ind.indicators.get('price_metrics', {})
        pullback_pct = abs(price_metrics.get('distance_from_high', 0))

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} PD:{pd.score:.2f} TC:{tc.score:.2f}",
            f"Pullback {pullback_pct*100:.1f}% from 20d high",
            "Above EMA50 support",
            "Descending highs pattern"
        ]
