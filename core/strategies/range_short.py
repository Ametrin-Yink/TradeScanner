"""Strategy F: Range Resistance Short - Short at resistance in bearish/neutral markets."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from ..support_resistance import SupportResistanceCalculator
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class RangeShortStrategy(BaseStrategy):
    """
    Strategy F: Range Resistance Short
    - Short-only: Short at resistance in bearish/neutral markets
    - Devil details: width constraint, relative weakness, time decay, stability filter, profit efficiency
    """

    NAME = "RangeShort"
    STRATEGY_TYPE = StrategyType.RANGE_SUPPORT
    DESCRIPTION = "RangeShort - Short-only at resistance in bearish/neutral markets"
    DIMENSIONS = ['TQ', 'RL', 'VC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 60,
        'min_touches': 3,
        'max_distance_from_level': 0.03,  # 3% from resistance
        'target_r_multiplier': 2.5,
        'support_tolerance_atr': 0.5,  # ±0.5 ATR for touch detection
        'min_test_interval_days': 3,  # Stability filter: min 3 days between tests
        'min_range_width_atr_multiple': 1.5,  # Width constraint
        'time_decay_days': 5,  # Time decay threshold
        'time_decay_return_pct': 0.01,  # 1% return threshold
        'profit_efficiency_threshold': 1.5,  # Profit potential threshold
        'efficiency_penalty': 2.0,  # Score penalty for bad entry
        'volume_veto_threshold': 1.5,
        'breakout_threshold_atr': 0.3,  # 0.3 ATR for breakout detection
    }

    def __init__(self, fetcher=None, db=None):
        """Initialize with SPY return cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.spy_return_1d = 0.0

    def _is_short_environment(self, spy_df: pd.DataFrame) -> bool:
        """
        Check if market environment is suitable for shorting.
        Returns True if SPY < EMA200 OR SPY is flat (|SPY_return_1d| < 0.3%)
        """
        if spy_df is None or len(spy_df) < 200:
            return False

        current = spy_df['close'].iloc[-1]
        prev_close = spy_df['close'].iloc[-2] if len(spy_df) > 1 else current
        ema200 = spy_df['close'].ewm(span=200).mean().iloc[-1]

        self.spy_return_1d = (current - prev_close) / prev_close

        # Short environment: bearish trend OR flat market
        is_bearish = current < ema200
        is_flat = abs(self.spy_return_1d) < 0.003  # 0.3%

        return is_bearish or is_flat

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen symbols with Phase 0 market environment check.
        """
        # Phase 0: Check if short environment
        logger.info("RangeSupport: Phase 0 - Checking short environment...")

        spy_df = getattr(self, '_spy_df', None)
        if spy_df is None:
            spy_df = self._get_data('SPY')

        if not self._is_short_environment(spy_df):
            logger.info("RangeSupport: Not a short environment, skipping")
            return []

        logger.info(f"RangeSupport: Short environment confirmed (SPY return: {self.spy_return_1d*100:.2f}%)")

        # Phase 0.5: Pre-filter by trend and level existence
        prefiltered = []
        logger.info("RangeSupport: Phase 0.5 - Pre-filtering for short mode...")

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    continue

                if self._prefilter_symbol(symbol, df):
                    prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"RangeSupport: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered)

    def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
        """Pre-filter symbol for short mode only with relaxed criteria."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        ema = ind.indicators.get('ema', {})
        ema21 = ema.get('ema21', current_price)
        ema50 = ema.get('ema50', current_price)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        # RELAXED: Must be below EMA50 (don't require EMA21 in between)
        # Original: if not (current_price < ema21 < ema50):
        if current_price >= ema50:
            logger.debug(f"RS_REJ: {symbol} - Price {current_price:.2f} >= EMA50 {ema50:.2f}")
            return False

        # Must have resistance near price
        resistances = sr_levels.get('resistance', [])
        if not resistances:
            logger.debug(f"RS_REJ: {symbol} - No resistance levels")
            return False

        resistances_above = [r for r in resistances if r > current_price]
        if not resistances_above:
            logger.debug(f"RS_REJ: {symbol} - No resistance above price {current_price:.2f}")
            return False

        nearest_resistance = min(resistances_above)
        distance_pct = (nearest_resistance - current_price) / current_price

        if distance_pct > self.PARAMS['max_distance_from_level']:
            logger.debug(f"RS_REJ: {symbol} - Resistance too far: {distance_pct:.2%} > {self.PARAMS['max_distance_from_level']:.2%}")
            return False

        # RELAXED: Check width constraint
        supports = sr_levels.get('support', [])
        if supports:
            nearest_support = max(s for s in supports if s < current_price) if any(s < current_price for s in supports) else nearest_resistance * 0.9
            range_width = (nearest_resistance - nearest_support) / nearest_support
            atr_pct = ind.indicators.get('atr', {}).get('atr_pct', 0.02)

            # RELAXED: From 1.5x to 1.0x ATR multiple
            if range_width < self.PARAMS['min_range_width_atr_multiple'] * 0.67 * atr_pct:
                logger.debug(f"RS_REJ: {symbol} - Range too narrow: {range_width:.3f}")
                return False

        logger.debug(f"RS_PASS: {symbol} - Resistance at {nearest_resistance:.2f}, distance {distance_pct:.2%}")
        return True

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter with veto checks for short mode."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        # Find nearest resistance
        resistances = sr_levels.get('resistance', [])
        if not resistances:
            return False

        resistances_above = [r for r in resistances if r > current_price]
        if not resistances_above:
            return False

        nearest_resistance = min(resistances_above)

        # Veto: breakout above resistance with volume
        if volume_ratio > self.PARAMS['volume_veto_threshold'] and current_price > nearest_resistance + self.PARAMS['breakout_threshold_atr'] * atr:
            logger.debug(f"{symbol}: Resistance breakout veto")
            return False

        # Check time decay
        if self._check_time_decay(df, nearest_resistance, atr, 'short'):
            logger.debug(f"{symbol}: Time decay at resistance")
            return False

        return True

    def _check_time_decay(self, df: pd.DataFrame, level: float, atr: float, direction: str) -> bool:
        """
        Check for time decay (Devil Detail C).
        If price stays at level for >5 days with minimal movement, level is weakening.
        """
        tolerance = atr * 0.3
        consecutive_days = 0
        first_day_open = None

        for i in range(1, min(20, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break

            row = df.iloc[idx]

            # Check if high is near resistance
            if abs(row['high'] - level) <= tolerance or row['high'] >= level - tolerance:
                consecutive_days += 1
                if first_day_open is None:
                    first_day_open = row['open']
            else:
                break

        if consecutive_days > self.PARAMS['time_decay_days'] and first_day_open is not None:
            current_close = df['close'].iloc[-1]
            level_return = abs(current_close - first_day_open) / first_day_open

            if level_return < self.PARAMS['time_decay_return_pct']:
                return True

        return False

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring with devil details for short mode."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        dimensions = []

        # Find the relevant resistance level
        level_info = None
        level_price = None

        resistances = sr_levels.get('resistance', [])
        if resistances:
            resistances_above = [r for r in resistances if r > current_price]
            if resistances_above:
                level_price = min(resistances_above)
                level_info = self._calculate_level_info(df, level_price, atr, 'resistance')

        if level_info is None:
            return []

        # Dimension 1: TQ - Trend Quality (5 pts) - short alignment only
        tq_score, tq_details = self._calculate_tq(ind, current_price)
        dimensions.append(ScoringDimension(
            name='TQ',
            score=tq_score,
            max_score=5.0,
            details=tq_details
        ))

        # Dimension 2: RL - Range Level Quality (6 pts)
        rl_score, rl_details = self._calculate_rl(level_info, current_price)
        dimensions.append(ScoringDimension(
            name='RL',
            score=rl_score,
            max_score=6.0,
            details=rl_details
        ))

        # Check width constraint veto
        if rl_score < -5:
            logger.debug(f"{symbol}: Range width veto (RL={rl_score})")
            return []

        # Dimension 3: VC - Volume Confirmation (4 pts)
        vc_score, vc_details = self._calculate_vc(ind, df, symbol)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=4.0,
            details=vc_details
        ))

        # Devil Detail D: Profit efficiency check
        total_score = tq_score + rl_score + vc_score
        entry = current_price
        stop = level_price + atr * 0.5
        target1 = self._calculate_target1(df, level_info, current_price)

        if target1 and entry != stop:
            # For short positions: stop > entry, target1 < entry
            if stop > entry:
                profit_potential = (entry - target1) / (stop - entry)
            else:
                profit_potential = (target1 - entry) / (entry - stop)
            if profit_potential < self.PARAMS['profit_efficiency_threshold']:
                total_score -= self.PARAMS['efficiency_penalty']
                logger.debug(f"{symbol}: Efficiency penalty applied (R:R={profit_potential:.2f})")

        return dimensions

    def _calculate_level_info(self, df: pd.DataFrame, level: float, atr: float, level_type: str) -> Dict:
        """Calculate level information with stability filter (Devil Detail A)."""
        tolerance = atr * self.PARAMS['support_tolerance_atr']
        touches = 0
        last_touch_idx = None
        bounce_returns = []
        recent_30d_touches = 0

        lookback = min(90, len(df) - 1)

        for i in range(1, lookback + 1):
            idx = -(i + 1)
            if idx < -len(df):
                break

            row = df.iloc[idx]

            # Check if price touched the level
            touched = False
            if level_type == 'resistance':
                if abs(row['high'] - level) <= tolerance or row['high'] >= level - tolerance:
                    if row['close'] < level:  # Rejected
                        touched = True

            if touched:
                # Stability filter: min 3 days between tests
                if last_touch_idx is None or (last_touch_idx - i) >= self.PARAMS['min_test_interval_days']:
                    touches += 1
                    last_touch_idx = i

                    # Check if within last 30 days
                    if i <= 30:
                        recent_30d_touches += 1

                    # Calculate drop strength
                    if i > 3:  # Need 3 days after to measure
                        post_idx = idx + 3
                        if post_idx < 0:
                            post_low = df['low'].iloc[post_idx]
                            close = row['close']

                            drop_ret = (close - post_low) / close
                            bounce_returns.append(min(drop_ret, 0.05))  # Cap at 5%

        avg_bounce = sum(bounce_returns) / len(bounce_returns) if bounce_returns else 0

        return {
            'level_price': level,
            'level_type': level_type,
            'touches': touches,
            'recent_30d_touches': recent_30d_touches,
            'avg_bounce_return': avg_bounce,
            'bounce_count': len(bounce_returns)
        }

    def _calculate_tq(self, ind: TechnicalIndicators, price: float) -> Tuple[float, Dict]:
        """Trend Quality dimension (0-5) for short mode."""
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', price)
        ema21 = ema.get('ema21', price)
        ema50 = ema.get('ema50', price)

        details = {
            'ema_alignment': False,
            'price_vs_ema21': price < ema21,
            'ema21_slope': 0
        }

        tq_score = 0.0

        # EMA alignment for short
        if ema8 < ema21 < ema50:
            tq_score += 2.0
            details['ema_alignment'] = True
        elif ema21 < ema50:
            tq_score += 1.5

        # Price vs EMA21
        if price < ema21:
            tq_score += 1.5

        # EMA21 slope
        ema21_slope = ind.calculate_stable_ema_slope(period=21, comparison_days=3)
        slope_val = ema21_slope.get('slope', 0)
        details['ema21_slope'] = slope_val

        if slope_val < 0:
            tq_score += 1.5

        return round(min(5.0, tq_score), 2), details

    def _calculate_rl(self, level_info: Dict, current_price: float) -> Tuple[float, Dict]:
        """Range Level Quality dimension (0-6) with width constraint."""
        touches = level_info['touches']
        recent_30d = level_info['recent_30d_touches']
        avg_bounce = level_info['avg_bounce_return']

        details = {
            'touches': touches,
            'recent_30d_touches': recent_30d,
            'avg_bounce_return': avg_bounce,
            'width_veto': False
        }

        rl_score = 0.0

        # Number of touches (0-3 pts)
        if touches >= 5:
            rl_score += 3.0
        elif touches >= 3:
            rl_score += 2.0 + (touches - 3) / 2.0
        else:
            rl_score += touches * 0.5

        # Recent 30d frequency (0-1.5 pts)
        if recent_30d >= 3:
            rl_score += 1.5
        elif recent_30d == 2:
            rl_score += 1.0
        elif recent_30d == 1:
            rl_score += 0.5

        # Return strength (0-1.5 pts)
        if avg_bounce >= 0.02:  # 2%
            rl_score += 1.5
        elif avg_bounce >= 0.01:  # 1%
            rl_score += 1.0
        elif avg_bounce > 0:
            rl_score += 0.5

        return round(min(6.0, rl_score), 2), details

    def _calculate_vc(self, ind: TechnicalIndicators, df: pd.DataFrame, symbol: str) -> Tuple[float, Dict]:
        """Volume Confirmation dimension (0-4) with relative weakness for short."""
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        details = {
            'volume_ratio': volume_ratio,
            'relative_weakness': 0.0
        }

        vc_score = 0.0

        # Relative weakness (Devil Detail B)
        stock_return = df['close'].iloc[-1] / df['close'].iloc[-2] - 1 if len(df) > 1 else 0

        # Relative weakness calculation
        relative_weakness = self.spy_return_1d - stock_return
        details['relative_weakness'] = relative_weakness

        # If SPY up but stock not moving = distribution
        if self.spy_return_1d > 0.01 and stock_return < 0.003:
            vc_score += 2.0
        elif self.spy_return_1d > 0.005 and stock_return < 0.002:
            vc_score += 1.5

        # Volume confirmation
        if volume_ratio > 1.3:
            vc_score += 1.0
        elif volume_ratio > 1.0:
            vc_score += 0.5

        return round(min(4.0, vc_score), 2), details

    def _calculate_target1(self, df: pd.DataFrame, level_info: Dict, current_price: float) -> Optional[float]:
        """Calculate first target (mid-range)."""
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()

        level_price = level_info['level_price']

        # Find opposite level (support for short)
        supports = sr_levels.get('support', [])
        if supports:
            supports_below = [s for s in supports if s < current_price]
            if supports_below:
                opposite = max(supports_below)
                return (level_price + opposite) / 2

        # Fallback to 20-day SMA
        return df['close'].tail(20).mean()

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

        # Get level price from RL dimension
        rl = next((d for d in dimensions if d.name == 'RL'), None)
        level_price = rl.details.get('level_price', current_price) if rl else current_price

        entry = round(current_price, 2)
        stop = round(level_price + atr * 0.5, 2)  # Above resistance
        target = round(level_price - atr * self.PARAMS['target_r_multiplier'], 2)

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
        rl = next((d for d in dimensions if d.name == 'RL'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        rl_details = rl.details if rl else {}
        vc_details = vc.details if vc else {}

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} RL:{rl.score:.2f} VC:{vc.score:.2f}",
            f"Level tested {rl_details.get('touches', 0)}x ({rl_details.get('recent_30d_touches', 0)} in 30d)",
        ]

        if rl_details.get('avg_bounce_return', 0) > 0:
            reasons.append(f"Avg drop: {rl_details['avg_bounce_return']*100:.1f}%")

        if vc_details.get('relative_weakness', 0) > 0:
            reasons.append(f"Weak vs SPY: {vc_details['relative_weakness']*100:.1f}%")

        return reasons
