"""Strategy D: DistributionTop - Short distribution tops (v5.0).

Created from:
- DoubleTopBottom short-side logic (distribution detection)
- RangeShort sector-weak pattern
"""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class DistributionTopStrategy(BaseStrategy):
    """
    Strategy D: DistributionTop v5.0
    Short-only distribution tops at multi-week highs.
    Combines DoubleTopBottom short logic + RangeShort sector-weak pattern.
    """

    NAME = "DistributionTop"
    STRATEGY_TYPE = StrategyType.D
    DESCRIPTION = "DistributionTop v5.0 - short distribution patterns"
    DIMENSIONS = ['TQ', 'RL', 'DS', 'VC']
    DIRECTION = 'short'

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 60,
        'max_distance_from_60d_high': 0.08,
        'max_distance_from_ema50': 1.05,
        'ema_alignment_tolerance': 1.02,
        'min_touches': 2,
        'min_test_interval_days': 5,
        'breakout_threshold_atr': 0.3,
        'volume_veto_threshold': 1.5,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for distribution top candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Check dollar volume
        dollar_volume = current_price * df['volume'].iloc[-1]
        if dollar_volume < self.PARAMS['min_dollar_volume']:
            return False

        # Check ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            return False

        # EMA checks
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        # Price not strongly extended above EMA50
        if current_price > ema50 * self.PARAMS['max_distance_from_ema50']:
            return False

        # EMA alignment - not in strong uptrend
        if ema8 > ema21 * self.PARAMS['ema_alignment_tolerance']:
            return False

        # Near 60d high
        high_60d = df['high'].tail(60).max()
        if (high_60d - current_price) / high_60d > self.PARAMS['max_distance_from_60d_high']:
            return False

        # Check for resistance level with touches
        resistance_level = self._detect_resistance_level(df)
        if resistance_level is None:
            return False

        return True

    def _detect_resistance_level(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect resistance level with multiple touches using local maxima."""
        highs = df['high'].tail(90).values

        # Find local maxima (peaks) manually
        peaks = []
        for i in range(5, len(highs) - 5):
            # Check if current point is higher than neighbors within 5-day window
            if highs[i] == max(highs[i-5:i+6]):
                peaks.append(i)

        if len(peaks) < 2:
            return None

        peak_prices = highs[peaks]

        # Group peaks that are close in price (within 2.5 ATR)
        atr = TechnicalIndicators(df).indicators.get('atr', {}).get('atr14', df['close'].iloc[-1] * 0.02)

        level_high = np.max(peak_prices)
        level_low = np.min(peak_prices[peak_prices >= level_high - atr * 2.5])

        touches = len([p for p in peak_prices if level_high >= p >= level_low])

        if touches < self.PARAMS['min_touches']:
            return None

        return {
            'high': float(level_high),
            'low': float(level_low),
            'touches': touches,
            'width_atr': float((level_high - level_low) / atr) if atr > 0 else 0
        }

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate TQ, RL, DS, VC per v5.0 spec."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # TQ: Trend Quality
        tq_score = self._calculate_tq(ind, df)

        # RL: Resistance Level
        rl_score = self._calculate_rl(df)

        # DS: Distribution Signs
        ds_score = self._calculate_ds(df)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df)

        return [
            ScoringDimension(name='TQ', score=tq_score, max_score=4.0, details={}),
            ScoringDimension(name='RL', score=rl_score, max_score=4.0, details={}),
            ScoringDimension(name='DS', score=ds_score, max_score=4.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _calculate_tq(self, ind: TechnicalIndicators, df: pd.DataFrame) -> float:
        """Trend Quality - EMA alignment and sector weakness."""
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        score = 0.0

        # EMA alignment (0-2.5)
        if current_price < ema50 and ema8 < ema21:
            score += 2.5
        elif current_price < ema50:
            score += 1.5
        elif current_price > ema50 and ema8 < ema21:
            score += 1.0

        return min(4.0, score)

    def _calculate_rl(self, df: pd.DataFrame) -> float:
        """Resistance Level quality - touches, interval, width."""
        level = self._detect_resistance_level(df)
        if level is None:
            return 0.0

        score = 0.0

        # Touch count (0-1.5)
        touches = level['touches']
        if touches >= 5:
            score += 1.5
        elif touches == 4:
            score += 1.2
        elif touches == 3:
            score += 0.8
        elif touches == 2:
            score += 0.3

        # Width (0-1.0) - tighter is better
        width_atr = level['width_atr']
        if 1.0 <= width_atr <= 2.5:
            score += 1.0
        elif 0.5 <= width_atr < 1.0:
            score += 0.5
        elif width_atr > 3.0:
            score += 0.3

        return min(4.0, score)

    def _calculate_ds(self, df: pd.DataFrame) -> float:
        """Distribution Signs - heavy volume on up-days at resistance."""
        level = self._detect_resistance_level(df)
        if level is None:
            return 0.0

        recent = df.tail(30)
        avg_volume = df['volume'].tail(20).mean()

        heavy_vol_up_days = 0
        for idx, row in recent.iterrows():
            if row['close'] > row['open'] and row['volume'] > avg_volume * 1.5:
                if abs(row['high'] - level['high']) / level['high'] < 0.02:
                    heavy_vol_up_days += 1

        if heavy_vol_up_days >= 3:
            return 2.0
        elif heavy_vol_up_days == 2:
            return 1.3
        elif heavy_vol_up_days == 1:
            return 0.6
        return 0.0

    def _calculate_vc(self, df: pd.DataFrame) -> float:
        """Volume Confirmation - breakdown surge and follow-through."""
        recent_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()

        if avg_volume == 0:
            return 0.0

        volume_ratio = recent_volume / avg_volume

        if volume_ratio >= 2.5:
            return 2.0
        elif volume_ratio >= 1.8:
            return 1.3 + (volume_ratio - 1.8) / 0.7 * 0.7
        elif volume_ratio >= 1.2:
            return 0.5 + (volume_ratio - 1.2) / 0.6 * 0.8
        return 0.0

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """Calculate entry, stop, target for short position."""
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        level = self._detect_resistance_level(df)
        resistance_high = level['high'] if level else df['high'].tail(20).max()

        entry = round(current_price, 2)
        stop = round(min(resistance_high + 0.5 * atr, entry * 1.04), 2)
        risk = stop - entry
        target = round(entry - risk * 2.5, 2)

        return entry, stop, target

    def build_match_reasons(self, symbol: str, df: pd.DataFrame,
                           dimensions: List[ScoringDimension],
                           score: float, tier: str) -> List[str]:
        """Build human-readable match reasons."""
        tq = next((d for d in dimensions if d.name == 'TQ'), None)
        rl = next((d for d in dimensions if d.name == 'RL'), None)
        ds = next((d for d in dimensions if d.name == 'DS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} RL:{rl.score:.2f} DS:{ds.score:.2f} VC:{vc.score:.2f}"
        ]

        # Resistance level details
        level = self._detect_resistance_level(df)
        if level:
            reasons.append(f"Resistance x{level['touches']} @ {level['high']:.2f}")

        return reasons
