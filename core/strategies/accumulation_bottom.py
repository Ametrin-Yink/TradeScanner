"""Strategy E: AccumulationBottom - Long accumulation bottoms (v5.0).

Created from:
- DoubleTopBottom long-side logic (accumulation detection)
"""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class AccumulationBottomStrategy(BaseStrategy):
    """
    Strategy E: AccumulationBottom v5.0
    Long-only accumulation bases at multi-week lows.
    Adapted from DoubleTopBottom long-side logic.
    """

    NAME = "AccumulationBottom"
    STRATEGY_TYPE = StrategyType.E
    DESCRIPTION = "AccumulationBottom v5.0 - long accumulation patterns"
    DIMENSIONS = ['TQ', 'AL', 'AS', 'VC']
    DIRECTION = 'long'

    PARAMS = {
        'min_market_cap': 2_500_000_000,
        'min_volume': 150_000,
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 180,
        'max_distance_from_60d_low': 0.10,
        'min_touches': 2,
        'rsi_max': 40,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for accumulation bottom candidates."""
        if len(df) < self.PARAMS['min_listing_days']:
            logger.debug(f"ACC_REJ: {symbol} - Insufficient data ({len(df)} < {self.PARAMS['min_listing_days']})")
            return False

        # Get pre-calculated data from phase0 if available
        data = self.phase0_data.get(symbol, {}) if hasattr(self, 'phase0_data') else {}

        # Market cap check
        market_cap = data.get('market_cap', 0)
        if market_cap < self.PARAMS['min_market_cap']:
            logger.debug(f"ACC_REJ: {symbol} - Market cap ${market_cap:,.0f} < ${self.PARAMS['min_market_cap']:,.0f}")
            return False

        # Volume check
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume < self.PARAMS['min_volume']:
            logger.debug(f"ACC_REJ: {symbol} - Avg volume {avg_volume:,.0f} < {self.PARAMS['min_volume']:,.0f}")
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Check dollar volume
        dollar_volume = current_price * df['volume'].iloc[-1]
        if dollar_volume < self.PARAMS['min_dollar_volume']:
            logger.debug(f"ACC_REJ: {symbol} - Dollar volume ${dollar_volume:,.0f} < ${self.PARAMS['min_dollar_volume']:,.0f}")
            return False

        # Check ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            logger.debug(f"ACC_REJ: {symbol} - ADR {adr_pct:.3f} < {self.PARAMS['min_atr_pct']}")
            return False

        # EMA checks - not in strong downtrend
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)

        # Check RSI not too high (oversold/accumulation zone)
        rsi = ind.indicators.get('rsi', {}).get('rsi14', 50)
        if rsi > self.PARAMS['rsi_max']:
            logger.debug(f"ACC_REJ: {symbol} - RSI {rsi:.1f} > {self.PARAMS['rsi_max']}")
            return False

        # Near 60d low
        low_60d = df['low'].tail(60).min()
        if (current_price - low_60d) / low_60d > self.PARAMS['max_distance_from_60d_low']:
            logger.debug(f"ACC_REJ: {symbol} - Distance from 60d low {(current_price - low_60d) / low_60d:.3f} > {self.PARAMS['max_distance_from_60d_low']}")
            return False

        # Check for support level with touches
        support_level = self._detect_support_level(df)
        if support_level is None:
            logger.debug(f"ACC_REJ: {symbol} - No support level detected")
            return False

        logger.debug(f"ACC_PASS: {symbol} - All filters passed (touches={support_level['touches']}, RSI={rsi:.1f})")
        return True

    def _detect_support_level(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect support level with multiple touches using local minima."""
        lows = df['low'].tail(90).values

        # Find local minima (troughs) manually
        troughs = []
        for i in range(5, len(lows) - 5):
            # Check if current point is lower than neighbors within 5-day window
            if lows[i] == min(lows[i-5:i+6]):
                troughs.append(i)

        if len(troughs) < 2:
            return None

        trough_prices = lows[troughs]

        # Group troughs that are close in price (within 2.5 ATR)
        atr = TechnicalIndicators(df).indicators.get('atr', {}).get('atr14', df['close'].iloc[-1] * 0.02)

        level_low = np.min(trough_prices)
        level_high = np.max(trough_prices[trough_prices <= level_low + atr * 2.5])

        touches = len([t for t in trough_prices if level_low <= t <= level_high])

        if touches < self.PARAMS['min_touches']:
            return None

        return {
            'low': float(level_low),
            'high': float(level_high),
            'touches': touches,
            'width_atr': float((level_high - level_low) / atr) if atr > 0 else 0
        }

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate TQ, AL, AS, VC per v5.0 spec."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # TQ: Trend Quality
        tq_score = self._calculate_tq(ind, df)

        # AL: Accumulation Level
        al_score = self._calculate_al(df)

        # AS: Accumulation Signs
        as_score = self._calculate_as(df)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df)

        return [
            ScoringDimension(name='TQ', score=tq_score, max_score=4.0, details={}),
            ScoringDimension(name='AL', score=al_score, max_score=4.0, details={}),
            ScoringDimension(name='AS', score=as_score, max_score=4.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _calculate_tq(self, ind: TechnicalIndicators, df: pd.DataFrame) -> float:
        """Trend Quality - EMA alignment and downtrend exhaustion."""
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        score = 0.0

        # EMA alignment (0-2.5)
        if current_price > ema50 and ema8 > ema21:
            score += 2.5
        elif current_price > ema50:
            score += 1.5
        elif current_price > ema50 * 0.98 and ema8 > ema21 * 0.98:
            score += 1.0

        return min(4.0, score)

    def _calculate_al(self, df: pd.DataFrame) -> float:
        """Accumulation Level quality - touches, width, proximity."""
        level = self._detect_support_level(df)
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

        # Near support (0-1.5)
        current_price = df['close'].iloc[-1]
        level_high = level['high']
        distance_pct = (current_price - level_high) / level_high
        if distance_pct < 0.01:
            score += 1.5
        elif distance_pct < 0.03:
            score += 1.0
        elif distance_pct < 0.05:
            score += 0.5

        return min(4.0, score)

    def _calculate_as(self, df: pd.DataFrame) -> float:
        """Accumulation Signs - heavy volume on down-days at support + price action strength."""
        level = self._detect_support_level(df)
        if level is None:
            return 0.0

        recent = df.tail(30)
        avg_volume = df['volume'].tail(20).mean()

        # Low-volume down-days at support (0-2.0)
        low_vol_down_days = 0
        for idx, row in recent.iterrows():
            if row['close'] < row['open'] and row['volume'] < avg_volume * 0.7:
                if abs(row['low'] - level['low']) / level['low'] < 0.02:
                    low_vol_down_days += 1

        if low_vol_down_days >= 3:
            low_vol_score = 2.0
        elif low_vol_down_days == 2:
            low_vol_score = 1.3
        elif low_vol_down_days == 1:
            low_vol_score = 0.6
        else:
            low_vol_score = 0.0

        # Price action strength (0-2.0) - detect bullish patterns in recent 10 days
        recent_10 = df.tail(10)
        price_action_signals = 0

        for idx, row in recent_10.iterrows():
            open_p = row['open']
            high_p = row['high']
            low_p = row['low']
            close_p = row['close']

            body = abs(close_p - open_p)
            lower_shadow = min(open_p, close_p) - low_p
            upper_shadow = high_p - max(open_p, close_p)

            # Check if price is near support level (within 2%)
            near_support = abs(low_p - level['low']) / level['low'] < 0.02

            if not near_support:
                continue

            # Hammer: lower shadow >= 2x body, CLV < 0.3
            clv = (close_p - low_p) / (high_p - low_p) if (high_p - low_p) > 0 else 0.5
            if body > 0 and lower_shadow >= 2 * body and clv < 0.3:
                price_action_signals += 1
                continue

            # Long lower wick: lower shadow >= 3x body
            if body > 0 and lower_shadow >= 3 * body:
                price_action_signals += 1
                continue

            # Gap reversal: gap down then closes near high
            # Gap down: open < previous close
            # Closes near high: close >= high - small threshold
            if idx > 0:
                prev_close = df.loc[df.index[df.index.get_loc(idx) - 1], 'close']
                if open_p < prev_close * 0.99 and close_p >= high_p * 0.98:
                    price_action_signals += 1
                    continue

        # Failed breakdown detection (breaks below support then closes above)
        for idx, row in recent_10.iterrows():
            if row['low'] < level['low'] and row['close'] > level['low']:
                price_action_signals += 1
                break  # Only count once

        # Score price action signals
        if price_action_signals >= 3:
            price_action_score = 2.0
        elif price_action_signals == 2:
            price_action_score = 1.5
        elif price_action_signals == 1:
            price_action_score = 0.8
        else:
            price_action_score = 0.0

        return min(4.0, low_vol_score + price_action_score)

    def _calculate_vc(self, df: pd.DataFrame) -> float:
        """Volume Confirmation - reversal surge (0-2.0) and follow-through (0-1.0)."""
        avg_volume = df['volume'].tail(20).mean()

        if avg_volume == 0:
            return 0.0

        recent = df.tail(10)
        level = self._detect_support_level(df)

        # Find best up-day volume in support zone (reversal surge) - max 2.0
        best_volume_ratio = 0.0
        reversal_day_idx = None

        for i, (idx, row) in enumerate(recent.iterrows()):
            if row['close'] > row['open']:  # Up-day
                # Check if near support zone
                if level:
                    near_support = abs(row['low'] - level['low']) / level['low'] < 0.03
                else:
                    near_support = True

                if near_support:
                    vol_ratio = row['volume'] / avg_volume
                    if vol_ratio > best_volume_ratio:
                        best_volume_ratio = vol_ratio
                        reversal_day_idx = i

        # Score reversal surge (0-2.0)
        if best_volume_ratio >= 3.0:
            surge_score = 2.0
        elif best_volume_ratio >= 2.0:
            surge_score = 1.0 + (best_volume_ratio - 2.0) / 1.0 * 1.0
        elif best_volume_ratio >= 1.5:
            surge_score = 0.5 + (best_volume_ratio - 1.5) / 0.5 * 0.5
        else:
            surge_score = 0.0

        # Follow-through score (0-1.0) - Day 2-3 volume >= 1.5x avg
        follow_through_score = 0.0
        if reversal_day_idx is not None and reversal_day_idx < len(recent) - 1:
            # Check next 2 days
            days_after = min(2, len(recent) - reversal_day_idx - 1)
            for j in range(1, days_after + 1):
                follow_idx = list(recent.index)[reversal_day_idx + j]
                follow_row = df.loc[follow_idx]
                follow_vol_ratio = follow_row['volume'] / avg_volume

                if follow_vol_ratio >= 1.5:
                    follow_through_score = 1.0
                    break
                elif follow_vol_ratio >= 1.2 and follow_through_score < 0.5:
                    follow_through_score = 0.5

        return min(3.0, surge_score + follow_through_score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """Calculate entry, stop, target for long position."""
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr14', current_price * 0.02)

        level = self._detect_support_level(df)
        support_low = level['low'] if level else df['low'].tail(20).min()

        entry = round(current_price, 2)
        stop = round(max(support_low - 0.5 * atr, entry * 0.94), 2)
        risk = entry - stop
        target = round(entry + risk * 2.5, 2)

        return entry, stop, target

    def build_match_reasons(self, symbol: str, df: pd.DataFrame,
                           dimensions: List[ScoringDimension],
                           score: float, tier: str) -> List[str]:
        """Build human-readable match reasons."""
        tq = next((d for d in dimensions if d.name == 'TQ'), None)
        al = next((d for d in dimensions if d.name == 'AL'), None)
        as_ = next((d for d in dimensions if d.name == 'AS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} AL:{al.score:.2f} AS:{as_.score:.2f} VC:{vc.score:.2f}"
        ]

        # Support level details
        level = self._detect_support_level(df)
        if level:
            reasons.append(f"Support x{level['touches']} @ {level['low']:.2f}")

        return reasons
