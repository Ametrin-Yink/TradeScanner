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
        'min_dollar_volume_short': 30_000_000,  # v7.0: liquidity guard for short strategies
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
        df_tail = df.tail(90).reset_index(drop=True)

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

        # Get peak indices that are within the resistance level
        level_peak_indices = [peaks[i] for i, p in enumerate(peak_prices) if level_high >= p >= level_low]
        touches = len(level_peak_indices)

        if touches < self.PARAMS['min_touches']:
            return None

        # Calculate days between touches for interval quality
        if len(level_peak_indices) >= 2:
            avg_days_between = np.mean(np.diff(level_peak_indices))
        else:
            avg_days_between = 0

        return {
            'high': float(level_high),
            'low': float(level_low),
            'touches': touches,
            'width_atr': float((level_high - level_low) / atr) if atr > 0 else 0,
            'avg_days_between': float(avg_days_between),
            'peak_indices': level_peak_indices
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

        # Interval quality (0-1.5) - days between touches
        avg_days = level.get('avg_days_between', 0)
        if avg_days >= 15:
            score += 1.5
        elif 10 <= avg_days < 15:
            # Linear interpolation from 1.0 to 1.5
            score += 1.0 + (avg_days - 10) / 5 * 0.5
        elif 7 <= avg_days < 10:
            # Linear interpolation from 0.5 to 1.0
            score += 0.5 + (avg_days - 7) / 3 * 0.5
        elif 5 <= avg_days < 7:
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
        """Distribution Signs - heavy volume on up-days at resistance + price action exhaustion."""
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

        # Score heavy volume on up-days (0-2.0)
        if heavy_vol_up_days >= 3:
            vol_score = 2.0
        elif heavy_vol_up_days == 2:
            vol_score = 1.3
        elif heavy_vol_up_days == 1:
            vol_score = 0.6
        else:
            vol_score = 0.0

        # Price action exhaustion detection (0-2.0)
        price_action_signals = self._detect_price_action_exhaustion(df, level)
        signal_count = len(price_action_signals)

        if signal_count >= 3:
            pa_score = 2.0
        elif signal_count == 2:
            pa_score = 1.5
        elif signal_count == 1:
            pa_score = 0.8
        else:
            pa_score = 0.0

        return min(4.0, vol_score + pa_score)

    def _detect_price_action_exhaustion(self, df: pd.DataFrame, level: Dict) -> List[str]:
        """Detect price action exhaustion patterns at resistance."""
        signals = []
        recent_10d = df.tail(10).reset_index(drop=True)
        level_high = level['high']

        for idx, row in recent_10d.iterrows():
            open_p = row['open']
            high_p = row['high']
            low_p = row['low']
            close_p = row['close']

            # Skip if not near resistance level
            if abs(high_p - level_high) / level_high > 0.03:
                continue

            body = abs(close_p - open_p)
            upper_shadow = high_p - max(open_p, close_p)
            lower_shadow = min(open_p, close_p) - low_p

            # Shooting star: upper shadow >= 2x body, CLV > 0.7
            if body > 0 and upper_shadow >= 2 * body:
                clv = ((close_p - low_p) - (high_p - close_p)) / (high_p - low_p) if (high_p - low_p) > 0 else 0
                if clv > 0.7:
                    signals.append(f"shooting_star_day{idx}")
                    continue

            # Long upper wick: upper shadow >= 3x body
            if body > 0 and upper_shadow >= 3 * body:
                signals.append(f"long_wick_day{idx}")
                continue

            # Failed breakout: breaks above resistance but closes below
            if high_p > level_high and close_p < level_high:
                signals.append(f"failed_breakout_day{idx}")
                continue

            # Gap fade: gap up but closes near low
            if idx > 0:
                prev_close = recent_10d.iloc[idx - 1]['close']
                gap_pct = (open_p - prev_close) / prev_close
                if gap_pct > 0.005:  # Gap up > 0.5%
                    # Close near low (within 30% of range from low)
                    day_range = high_p - low_p
                    if day_range > 0:
                        close_position = (close_p - low_p) / day_range
                        if close_position < 0.3:  # Close in lower 30% of range
                            signals.append(f"gap_fade_day{idx}")
                            continue

        return signals

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
