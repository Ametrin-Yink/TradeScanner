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
        'min_atr_pct': 0.015,
        'min_listing_days': 180,
        'max_distance_from_60d_low': 0.10,
        'min_touches': 2,
    }

    # Regime filtering per documentation:
    # "Bull → skip; Neutral → B-tier max; Bear → full; Extreme VIX → A-tier min"
    REGIME_ALLOWANCE = {
        'bull_strong': None,      # Skip entirely
        'bull_moderate': None,    # Skip entirely
        'neutral': 'B',           # B-tier max
        'bear_moderate': 'S',     # Full (no restriction)
        'bear_strong': 'S',       # Full (no restriction)
        'extreme_vix': 'A',       # A-tier min
    }

    def _should_process_in_regime(self) -> bool:
        """Check if strategy should run in current regime.

        DOCUMENTATION: "Bull → skip"
        """
        regime = getattr(self, '_current_regime', 'neutral')
        allowance = self.REGIME_ALLOWANCE.get(regime, 'B')
        return allowance is not None

    def _get_max_tier_for_regime(self) -> str:
        """Get maximum tier allowed for current regime.

        DOCUMENTATION:
        - Neutral → B-tier max
        - Extreme VIX → A-tier min (meaning A and S allowed)
        - Bear → full (no restriction)
        """
        regime = getattr(self, '_current_regime', 'neutral')
        allowance = self.REGIME_ALLOWANCE.get(regime, 'B')
        return allowance if allowance else 'C'

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for accumulation bottom candidates.

        DOCUMENTATION: "Bull → skip; Neutral → B-tier max; Bear → full; Extreme VIX → A-tier min"
        """
        # Check regime first - skip entirely in bull market
        if not self._should_process_in_regime():
            regime = getattr(self, '_current_regime', 'unknown')
            logger.debug(f"ACC_REJ: {symbol} - Skip in {regime} regime")
            return False

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

        # Check ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            logger.debug(f"ACC_REJ: {symbol} - ADR {adr_pct:.3f} < {self.PARAMS['min_atr_pct']}")
            return False

        # EMA checks - not in strong downtrend
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)

        # Near 60d low - use pre-calculated data from phase0
        low_60d = data.get('low_60d')
        if low_60d is None or low_60d <= 0:
            logger.debug(f"ACC_REJ: {symbol} - No low_60d data in phase0")
            return False
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

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter using cached data.

        v7.1: Uses phase0_data for fast pre-filter (price near 60d low, RSI low),
        only fetches DataFrames for symbols that pass the pre-filter.
        """
        logger.info("AccumulationBottom: Phase 0 - Using cached data for pre-filter...")

        phase0_data = getattr(self, 'phase0_data', {})
        prefiltered = []

        # Phase 0.5: Pre-filter using cached data
        logger.info("AccumulationBottom: Phase 0.5 - Pre-filtering by 60d low proximity and RSI...")

        for symbol in symbols:
            try:
                # Use phase0_data for fast pre-filter
                if phase0_data and symbol in phase0_data:
                    data = phase0_data[symbol]
                    current_price = data.get('current_price', 0)
                    low_60d = data.get('low_60d', 0)
                    rsi = data.get('rsi_14', 50)

                    # Pre-filter: price within 15% of 60d low (accumulation zone)
                    if low_60d > 0 and current_price > 0:
                        distance_from_low = (current_price - low_60d) / low_60d
                        if distance_from_low > 0.15:
                            logger.debug(f"AccumBottom_REJ: {symbol} - Price {distance_from_low:.1%} above 60d low")
                            continue

                    # Pre-filter: RSI < 45 (oversold/accumulation zone)
                    if rsi > 45:
                        logger.debug(f"AccumBottom_REJ: {symbol} - RSI {rsi:.1f} too high")
                        continue

                # Fetch full data for detailed analysis
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    continue

                # Run full filter
                if self.filter(symbol, df):
                    prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"AccumulationBottom: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Cache market data for use in filter/calculate_dimensions
        self.market_data = {sym: self._get_data(sym) for sym in prefiltered}

        # Call base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)

    def _detect_support_level(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect support level with multiple touches using local minima.

        Returns dict with: low, high, touches, width_atr, min_interval_days
        """
        lows = df['low'].tail(90).values
        dates = df.index[-90:]

        # Find local minima (troughs) manually
        troughs = []
        for i in range(5, len(lows) - 5):
            # Check if current point is lower than neighbors within 5-day window
            if lows[i] == min(lows[i-5:i+6]):
                troughs.append((i, lows[i], dates[i]))

        if len(troughs) < 2:
            return None

        trough_prices = np.array([t[1] for t in troughs])
        trough_dates = [t[2] for t in troughs]

        # Group troughs that are close in price (within 2.5 ATR)
        atr = TechnicalIndicators(df).indicators.get('atr', {}).get('atr', df['close'].iloc[-1] * 0.02)

        level_low = np.min(trough_prices)
        level_high = np.max(trough_prices[trough_prices <= level_low + atr * 2.5])

        # Get touches within the level
        touches_in_level = [(i, p, d) for i, (idx, p, d) in enumerate(troughs)
                           if level_low <= p <= level_high]
        touches = len(touches_in_level)

        # Calculate minimum interval between touches
        min_interval_days = 0
        if len(touches_in_level) >= 2:
            for j in range(1, len(touches_in_level)):
                prev_date = touches_in_level[j-1][2]
                curr_date = touches_in_level[j][2]
                interval = (curr_date - prev_date).days
                if j == 1 or interval < min_interval_days:
                    min_interval_days = interval

        if touches < self.PARAMS['min_touches']:
            return None

        return {
            'low': float(level_low),
            'high': float(level_high),
            'touches': touches,
            'width_atr': float((level_high - level_low) / atr) if atr > 0 else 0,
            'min_interval_days': min_interval_days
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
        """Trend Quality - EMA alignment for downtrend exhaustion (v7.0).

        Per documentation:
        | EMA Structure | Score |
        |---------------|-------|
        | Price<EMA50 AND EMA8<EMA21 | 2.5 |
        | Price<EMA200, EMA8 crossing EMA21 | 2.0 |
        | Price<EMA50 only | 1.5 |
        | Price>EMA50 | 0 |
        """
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)
        ema200 = ind.indicators.get('ema', {}).get('ema200', current_price)

        score = 0.0

        # DOCUMENTATION: Price<EMA50 AND EMA8<EMA21 = 2.5 (downtrend exhaustion)
        if current_price < ema50 and ema8 < ema21:
            score += 2.5
        # DOCUMENTATION: Price<EMA50 only = 1.5
        elif current_price < ema50:
            score += 1.5
        # DOCUMENTATION: Price<EMA200, EMA8 crossing EMA21 = 2.0
        elif current_price < ema200 and abs(ema8 - ema21) / ema21 < 0.01:
            score += 2.0
        # DOCUMENTATION: Price>EMA50 = 0 (not valid for accumulation bottom)
        # No score added for uptrend

        return min(4.0, score)

    def _calculate_al(self, df: pd.DataFrame) -> float:
        """Accumulation Level quality - touches, interval, width (v7.0).

        Per documentation:
        | Touches | Score | Min interval | Score | Width | Score |
        |---------|-------|--------------|-------|-------|-------|
        | >=5     | 1.5   | >=14d        | 1.5   | 1-2.5×ATR | 1.0 |
        | 4       | 1.2   | 7-14d        | 0.8-1.5 | 0.5-1×ATR | 0.5 |
        | 3       | 0.8   | 5-7d         | 0.3-0.8 | >3×ATR | 0.3 |
        | 2       | 0.3   | <5d          | 0 | | |
        """
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

        # Interval scoring (0-1.5) - NEW per v7.0
        min_interval = level.get('min_interval_days', 0)
        if min_interval >= 14:
            score += 1.5
        elif min_interval >= 7:
            # Interpolate: 7d=0.8, 14d=1.5
            score += 0.8 + (min_interval - 7) / 7 * 0.7
        elif min_interval >= 5:
            # Interpolate: 5d=0.3, 7d=0.8
            score += 0.3 + (min_interval - 5) / 2 * 0.5
        # <5d = 0

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
        """Accumulation Signs - up-day volume ratio + price action strength (v7.0).

        Per documentation:
        | Up-day vol ratio (up-day vol / avg20d) | Score |
        |----------------------------------------|-------|
        | >2.0×                                  | 2.0   |
        | 1.5-2.0×                               | 1.5-2.0 |
        | 1.2-1.5×                               | 0.8-1.5 |
        | 1.0-1.2×                               | 0.3-0.8 |

        Price action (cap 2.0): hammer/bullish engulfing=+1.0, failed breakdown=+1.0,
        higher lows=+0.5, tight range=+0.5
        """
        level = self._detect_support_level(df)
        if level is None:
            return 0.0

        recent = df.tail(30)
        avg_volume = df['volume'].tail(20).mean()

        if avg_volume == 0:
            return 0.0

        # DOCUMENTATION: Up-day vol ratio (up-day vol / avg20d)
        # Calculate total up-day volume and ratio
        up_day_volume = 0
        up_day_count = 0
        for idx, row in recent.iterrows():
            if row['close'] > row['open']:  # Up-day
                up_day_volume += row['volume']
                up_day_count += 1

        # Average up-day volume ratio
        if up_day_count > 0:
            avg_up_day_vol_ratio = (up_day_volume / up_day_count) / avg_volume
        else:
            avg_up_day_vol_ratio = 0

        # Score up-day volume ratio (0-2.0)
        if avg_up_day_vol_ratio > 2.0:
            vol_ratio_score = 2.0
        elif avg_up_day_vol_ratio >= 1.5:
            vol_ratio_score = 1.5 + (avg_up_day_vol_ratio - 1.5) / 0.5 * 0.5
        elif avg_up_day_vol_ratio >= 1.2:
            vol_ratio_score = 0.8 + (avg_up_day_vol_ratio - 1.2) / 0.3 * 0.7
        elif avg_up_day_vol_ratio >= 1.0:
            vol_ratio_score = 0.3 + (avg_up_day_vol_ratio - 1.0) / 0.2 * 0.5
        else:
            vol_ratio_score = 0.0

        # Price action strength (0-2.0) - detect bullish patterns in recent 10 days
        recent_10 = df.tail(10)
        price_action_signals = 0

        for i, (idx, row) in enumerate(recent_10.iterrows()):
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

            # Bullish engulfing: current body engulfs previous body
            if i > 0:
                prev_row = recent_10.iloc[i-1]
                prev_body = abs(prev_row['close'] - prev_row['open'])
                if close_p > open_p and prev_row['close'] < prev_row['open']:
                    if open_p < prev_row['close'] and close_p > prev_row['open']:
                        price_action_signals += 1
                        continue

            # Long lower wick: lower shadow >= 3x body
            if body > 0 and lower_shadow >= 3 * body:
                price_action_signals += 1
                continue

            # Gap reversal: gap down then closes near high
            if i > 0:
                prev_close = recent_10.iloc[i-1]['close']
                if open_p < prev_close * 0.99 and close_p >= high_p * 0.98:
                    price_action_signals += 1
                    continue

        # Failed breakdown detection (breaks below support then closes above)
        for idx, row in recent_10.iterrows():
            if row['low'] < level['low'] and row['close'] > level['low']:
                price_action_signals += 1
                break  # Only count once

        # Score price action signals (cap 2.0 per documentation)
        if price_action_signals >= 3:
            price_action_score = 2.0
        elif price_action_signals == 2:
            price_action_score = 1.5
        elif price_action_signals == 1:
            price_action_score = 0.8
        else:
            price_action_score = 0.0

        return min(4.0, vol_ratio_score + price_action_score)

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
                            score: float, tier: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Calculate entry, stop, target for long position.

        DOCUMENTATION: "CLV ≥ 0.60 for long entry"
        """
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        level = self._detect_support_level(df)
        support_low = level['low'] if level else df['low'].tail(20).min()

        # DOCUMENTATION: CLV ≥ 0.60 for long entry
        clv = (current_price - df['low'].iloc[-1]) / (df['high'].iloc[-1] - df['low'].iloc[-1])
        if clv < 0.60:
            logger.debug(f"ACC_REJ: {symbol} - CLV {clv:.2f} < 0.60")
            return None, None, None

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
