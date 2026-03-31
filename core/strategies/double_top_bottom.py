"""Strategy G: DTSS v2.1 - Distribution Top / Accumulation Bottom with expert suggestions."""
from ..scoring_utils import calculate_clv, check_rsi_divergence, calculate_test_interval, calculate_institutional_intensity
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class DoubleTopBottomStrategy(BaseStrategy):
    """
    Strategy G: DTSS v2.1 - Distribution Top / Accumulation Bottom.

    Expert suggestions implemented:
    A. Left/Right side grading (TS dimension)
    B. Test interval > 10 days (PL dimension)
    C. Exhaustion gap detection (VC dimension)
    D. Institutional intensity factor (VC dimension)
    """

    NAME = "DoubleTopBottom"
    STRATEGY_TYPE = StrategyType.DTSS
    DESCRIPTION = "DoubleTopBottom v2.1 - Distribution top / accumulation bottom with left/right side grading"
    DIMENSIONS = ['PL', 'TS', 'VC']

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 60,
        'max_distance_from_level': 0.03,  # 3% from 60d high/low
        'target_r_multiplier': 3.0,
        'support_tolerance_atr': 0.5,
        'min_test_interval_days': 10,  # Expert suggestion B: quality test interval
        'volume_veto_threshold': 1.5,
        'breakout_threshold_atr': 0.5,
        'time_decay_days': 3,
        'profit_efficiency_threshold': 1.5,
        'efficiency_penalty': 2.0,
        'left_side_max_tier': 'B',  # Expert suggestion A: left side position limit
        'exhaustion_gap_threshold': 0.01,  # 1% gap
        'institutional_intensity_threshold': 1.5,  # Expert suggestion D
    }

    def __init__(self, fetcher=None, db=None):
        """Initialize with market direction cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.market_direction = 'neutral'  # 'long', 'short', 'neutral'
        self.spy_return_1d = 0.0

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen symbols with Phase 0 market direction detection.
        """
        # Phase 0: Determine market direction
        logger.info("DTSS: Phase 0 - Determining market direction...")
        self._detect_market_direction()

        if self.market_direction == 'neutral':
            logger.info("DTSS: Market neutral, no trading")
            return []

        logger.info(f"DTSS: Market direction = {self.market_direction.upper()}")

        # Phase 0.5: Pre-filter by trend and level existence
        prefiltered = []
        logger.info(f"DTSS: Phase 0.5 - Pre-filtering for {self.market_direction} mode...")

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

        logger.info(f"DTSS: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered)

    def _detect_market_direction(self):
        """
        Detect market direction based on SPY trend.
        Short: SPY < EMA50 or SPY < open - 1%
        Long: SPY > EMA50 or SPY > open + 1%
        """
        try:
            # Use cached SPY data from screener if available
            spy_df = getattr(self, '_spy_df', None)
            if spy_df is None:
                spy_df = self._get_data('SPY')

            if spy_df is None or len(spy_df) < 50:
                self.market_direction = 'neutral'
                return

            current = spy_df['close'].iloc[-1]
            ema50 = spy_df['close'].ewm(span=50).mean().iloc[-1]
            open_price = spy_df['open'].iloc[-1]
            atr = spy_df['close'].rolling(14).apply(lambda x: (x.max() - x.min())).iloc[-1]

            # Short mode: distribution environment
            if current < ema50 or current < open_price * 0.99:
                self.market_direction = 'short'
            # Long mode: accumulation environment
            elif current > ema50 or current > open_price * 1.01:
                self.market_direction = 'long'
            else:
                self.market_direction = 'neutral'

        except Exception as e:
            logger.warning(f"Could not detect market direction: {e}")
            self.market_direction = 'neutral'

    def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
        """Pre-filter symbol based on market direction."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        price_metrics = ind.indicators.get('price_metrics', {})

        if self.market_direction == 'short':
            # Distribution top mode
            high_60d = price_metrics.get('high_60d')
            if high_60d is None:
                return False

            distance = abs(high_60d - current_price) / current_price
            if distance > self.PARAMS['max_distance_from_level']:
                return False

            # Check for weakness
            ema = ind.indicators.get('ema', {})
            ema8 = ema.get('ema8', current_price)
            ema21 = ema.get('ema21', current_price)

            weakness = ema8 < ema21 or current_price < ema8
            if not weakness:
                return False

        else:  # long mode
            # Accumulation bottom mode
            low_60d = price_metrics.get('low_60d')
            if low_60d is None:
                return False

            distance = abs(current_price - low_60d) / current_price
            if distance > self.PARAMS['max_distance_from_level']:
                return False

            # Check for strength
            ema = ind.indicators.get('ema', {})
            ema8 = ema.get('ema8', current_price)
            ema21 = ema.get('ema21', current_price)

            strength = ema8 > ema21 or current_price > ema8
            if not strength:
                return False

        return True

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter with veto checks."""
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

        price_metrics = ind.indicators.get('price_metrics', {})

        if self.market_direction == 'short':
            high_60d = price_metrics.get('high_60d')
            if high_60d is None:
                return False

            # Veto: breakout above 60d high with volume
            if volume_ratio > self.PARAMS['volume_veto_threshold'] and \
               current_price > high_60d + self.PARAMS['breakout_threshold_atr'] * atr:
                logger.debug(f"{symbol}: Breakout veto (short)")
                return False

        else:  # long mode
            low_60d = price_metrics.get('low_60d')
            if low_60d is None:
                return False

            # Veto: breakdown below 60d low with volume
            if volume_ratio > self.PARAMS['volume_veto_threshold'] and \
               current_price < low_60d - self.PARAMS['breakout_threshold_atr'] * atr:
                logger.debug(f"{symbol}: Breakdown veto (long)")
                return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring with expert suggestions."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        price_metrics = ind.indicators.get('price_metrics', {})

        dimensions = []

        if self.market_direction == 'short':
            level_60d = price_metrics.get('high_60d', current_price)
            distance_pct = abs(level_60d - current_price) / current_price

            # Calculate test info with interval (Expert suggestion B)
            test_info = self._calculate_test_info(df, level_60d, atr, 'high')

            # Dimension 1: PL - Proximity to Level (5 pts)
            pl_score, pl_details = self._calculate_pl(distance_pct, test_info)
            dimensions.append(ScoringDimension(
                name='PL',
                score=pl_score,
                max_score=5.0,
                details=pl_details
            ))

            # Dimension 2: TS - Trend Structure with left/right grading (Expert suggestion A)
            ts_score, ts_details = self._calculate_ts_short(ind, df, current_price)
            dimensions.append(ScoringDimension(
                name='TS',
                score=ts_score,
                max_score=6.0,
                details=ts_details
            ))

            # Dimension 3: VC - Volume with exhaustion gap & institutional intensity (Expert C & D)
            vc_score, vc_details = self._calculate_vc_short(ind, df, current_price, level_60d)
            dimensions.append(ScoringDimension(
                name='VC',
                score=vc_score,
                max_score=4.0,
                details=vc_details
            ))

        else:  # long mode
            level_60d = price_metrics.get('low_60d', current_price)
            distance_pct = abs(current_price - level_60d) / current_price

            # Calculate test info with interval
            test_info = self._calculate_test_info(df, level_60d, atr, 'low')

            # Dimension 1: PL
            pl_score, pl_details = self._calculate_pl(distance_pct, test_info)
            dimensions.append(ScoringDimension(
                name='PL',
                score=pl_score,
                max_score=5.0,
                details=pl_details
            ))

            # Dimension 2: TS with left/right grading
            ts_score, ts_details = self._calculate_ts_long(ind, df, current_price)
            dimensions.append(ScoringDimension(
                name='TS',
                score=ts_score,
                max_score=6.0,
                details=ts_details
            ))

            # Dimension 3: VC
            vc_score, vc_details = self._calculate_vc_long(ind, df, current_price, level_60d)
            dimensions.append(ScoringDimension(
                name='VC',
                score=vc_score,
                max_score=4.0,
                details=vc_details
            ))

        # Check profit efficiency (Devil detail)
        total_score = sum(d.score for d in dimensions)
        entry = current_price
        stop = self._calculate_stop(df, dimensions)
        target1 = self._calculate_target1(df, dimensions)

        if target1 and stop and abs(entry - stop) > 0:
            profit_potential = abs(target1 - entry) / abs(entry - stop)
            if profit_potential < self.PARAMS['profit_efficiency_threshold']:
                total_score -= self.PARAMS['efficiency_penalty']
                logger.debug(f"{symbol}: Efficiency penalty applied (R:R={profit_potential:.2f})")

        return dimensions

    def _calculate_test_info(self, df: pd.DataFrame, level: float, atr: float, level_type: str) -> Dict:
        """
        Calculate test information with interval constraint (Expert suggestion B).
        """
        tolerance = atr * self.PARAMS['support_tolerance_atr']
        tests = []
        last_test_idx = None

        lookback = min(90, len(df) - 1)

        for i in range(1, lookback + 1):
            idx = -(i + 1)
            if idx < -len(df):
                break

            row = df.iloc[idx]

            # Check if price touched the level
            touched = False
            if level_type == 'high':
                # Near 60d high
                if abs(row['high'] - level) <= tolerance or row['high'] >= level - tolerance:
                    if row['close'] < level:  # Rejected
                        touched = True
            else:  # low
                # Near 60d low
                if abs(row['low'] - level) <= tolerance or row['low'] <= level + tolerance:
                    if row['close'] > level:  # Bounced
                        touched = True

            if touched:
                # Expert suggestion B: min 10 days between quality tests
                if last_test_idx is None or (last_test_idx - i) >= self.PARAMS['min_test_interval_days']:
                    tests.append({
                        'idx': i,
                        'days_since': i
                    })
                    last_test_idx = i

        # Calculate average interval
        intervals = []
        if len(tests) >= 2:
            for i in range(1, len(tests)):
                intervals.append(tests[i-1]['idx'] - tests[i]['idx'])

        avg_interval = sum(intervals) / len(intervals) if intervals else 0

        return {
            'test_count': len(tests),
            'avg_interval': avg_interval,
            'max_interval': max(intervals) if intervals else 0
        }

    def _calculate_pl(self, distance_pct: float, test_info: Dict) -> Tuple[float, Dict]:
        """
        Proximity to Level dimension (0-5) with test interval (Expert suggestion B).
        """
        details = {
            'distance_pct': distance_pct,
            'test_count': test_info['test_count'],
            'avg_interval': test_info['avg_interval']
        }

        pl_score = 0.0

        # Distance scoring
        if distance_pct < 0.01:
            pl_score += 3.0
        elif distance_pct < 0.02:
            pl_score += 2.0
        elif distance_pct < 0.03:
            pl_score += 1.0

        # Test interval scoring (Expert suggestion B)
        avg_interval = test_info['avg_interval']
        if avg_interval > 10:
            pl_score += 1.5  # High quality validation
        elif avg_interval > 5:
            pl_score += 1.0
        elif test_info['test_count'] >= 2:
            pl_score += 0.5  # Short interval, lower quality

        return round(min(5.0, pl_score), 2), details

    def _calculate_ts_short(self, ind: TechnicalIndicators, df: pd.DataFrame, price: float) -> Tuple[float, Dict]:
        """
        Trend Structure for short with stricter confirmation.
        Right side (confirmed): EMA8 < EMA21 < EMA50 + RSI divergence = max 6 pts
        Without RSI divergence: max 4 pts (stricter confirmation)
        Left side (early): EMA still bullish BUT distribution signs = 3 pts (Tier B max)
        """
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', price)
        ema21 = ema.get('ema21', price)
        ema50 = ema.get('ema50', price)

        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi', 50)

        # Calculate RSI divergence - REQUIRED for max score
        rsi_divergence = check_rsi_divergence(df, 'bearish')

        details = {
            'side': 'unknown',
            'ema8': ema8,
            'ema21': ema21,
            'ema50': ema50,
            'rsi': rsi,
            'rsi_divergence': rsi_divergence
        }

        ts_score = 0.0
        has_death_cross = ema8 < ema21
        full_bearish_alignment = ema8 < ema21 < ema50

        # Right side: Confirmed bearish alignment with death cross
        if full_bearish_alignment:
            if rsi_divergence:
                # Full confirmation: death cross + RSI divergence
                ts_score += 3.0  # Increased base for full confirmation
                details['side'] = 'right'
            else:
                # Death cross but no divergence - partial credit
                ts_score += 2.0
                details['side'] = 'right'  # Still right side technically
        # Left side: Early distribution (EMA still bullish but divergence present)
        elif ema8 > ema21 > ema50 and rsi_divergence:
            ts_score += 2.0  # Left side base
            details['side'] = 'left'
        # Transition: Partial death cross (ema8 < ema21 but not below ema50)
        elif has_death_cross:
            ts_score += 1.5
            details['side'] = 'transition'
        # No clear signal
        else:
            details['side'] = 'unknown'

        # Price below EMA8 (bearish position)
        if price < ema8:
            ts_score += 2.0

        # EMA21 slope
        ema21_slope = ind.calculate_stable_ema_slope(period=21, comparison_days=3)
        slope_val = ema21_slope.get('slope', 0)
        if slope_val < -0.002:  # -0.2%
            ts_score += 1.5
        elif slope_val < 0:
            ts_score += 0.5

        # RSI in distribution zone (45-60)
        if 45 < rsi < 60:
            ts_score += 1.0

        # Stricter confirmation: Without RSI divergence, cap at 4.0 points
        if not rsi_divergence:
            ts_score = min(ts_score, 4.0)

        # Expert suggestion A: Left side gets max 3 points
        if details['side'] == 'left':
            ts_score = min(ts_score, 3.0)

        return round(min(6.0, ts_score), 2), details

    def _calculate_ts_long(self, ind: TechnicalIndicators, df: pd.DataFrame, price: float) -> Tuple[float, Dict]:
        """Trend Structure for long with left/right grading."""
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', price)
        ema21 = ema.get('ema21', price)
        ema50 = ema.get('ema50', price)

        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi', 50)

        # Calculate RSI divergence
        rsi_divergence = check_rsi_divergence(df, 'bullish')

        details = {
            'side': 'unknown',
            'ema8': ema8,
            'ema21': ema21,
            'ema50': ema50,
            'rsi': rsi,
            'rsi_divergence': rsi_divergence
        }

        ts_score = 0.0

        # Right side: Confirmed bullish alignment
        if ema8 > ema21 > ema50:
            ts_score += 2.0
            details['side'] = 'right'
        # Left side: Early accumulation
        elif ema8 < ema21 < ema50 and rsi_divergence:
            ts_score += 2.0
            details['side'] = 'left'
        elif ema8 > ema21:
            ts_score += 1.5
            details['side'] = 'transition'

        # Price above EMA8
        if price > ema8:
            ts_score += 2.0

        # EMA21 slope
        ema21_slope = ind.calculate_stable_ema_slope(period=21, comparison_days=3)
        slope_val = ema21_slope.get('slope', 0)
        if slope_val > 0.002:  # +0.2%
            ts_score += 1.5
        elif slope_val > 0:
            ts_score += 0.5

        # RSI in accumulation zone
        if 40 < rsi < 55:
            ts_score += 1.0

        # Left side gets max 3 points
        if details['side'] == 'left':
            ts_score = min(ts_score, 3.0)

        return round(min(6.0, ts_score), 2), details

    def _check_rsi_divergence(self, df: pd.DataFrame, direction: str) -> bool:
        """Check for RSI divergence."""
        if len(df) < 30:
            return False

        # Calculate RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        if direction == 'bearish':
            # Bearish divergence: price higher high, RSI lower high
            recent_slice = df.tail(10)
            recent_high_idx = recent_slice['high'].idxmax()
            recent_high = df.loc[recent_high_idx, 'high']
            recent_rsi = rsi.loc[recent_high_idx]

            prev_start = max(0, len(df) - 30)
            prev_end = len(df) - 10
            if prev_start >= prev_end:
                return False

            prev_period = df.iloc[prev_start:prev_end]
            prev_rsi_period = rsi.iloc[prev_start:prev_end]

            if len(prev_period) < 5:
                return False

            prev_high = prev_period['high'].max()
            prev_rsi_high = prev_rsi_period.max()

            return recent_high > prev_high and recent_rsi < prev_rsi_high
        else:
            # Bullish divergence: price lower low, RSI higher low
            recent_slice = df.tail(10)
            recent_low_idx = recent_slice['low'].idxmin()
            recent_low = df.loc[recent_low_idx, 'low']
            recent_rsi = rsi.loc[recent_low_idx]

            prev_start = max(0, len(df) - 30)
            prev_end = len(df) - 10
            if prev_start >= prev_end:
                return False

            prev_period = df.iloc[prev_start:prev_end]
            prev_rsi_period = rsi.iloc[prev_start:prev_end]

            if len(prev_period) < 5:
                return False

            prev_low = prev_period['low'].min()
            prev_rsi_low = prev_rsi_period.min()

            return recent_low < prev_low and recent_rsi > prev_rsi_low

    def _calculate_vc_short(self, ind: TechnicalIndicators, df: pd.DataFrame, price: float, high_60d: float) -> Tuple[float, Dict]:
        """
        Volume Confirmation for short with exhaustion gap & institutional intensity (Expert C & D).
        """
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        # Calculate CLV for institutional intensity (Expert suggestion D)
        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])
        institutional_intensity = volume_ratio * abs(clv - 0.5)

        # Check exhaustion gap (Expert suggestion C)
        exhaustion_gap = self._check_exhaustion_gap(df, high_60d, 'short')

        details = {
            'volume_ratio': volume_ratio,
            'clv': clv,
            'institutional_intensity': institutional_intensity,
            'exhaustion_gap': exhaustion_gap
        }

        vc_score = 0.0

        # Volume spike
        if volume_ratio > 1.5:
            vc_score += 2.0
        elif volume_ratio > 1.2:
            vc_score += 1.0

        # Expert suggestion C: Exhaustion gap
        if exhaustion_gap:
            vc_score += 2.0

        # Expert suggestion D: Institutional intensity
        if institutional_intensity > self.PARAMS['institutional_intensity_threshold']:
            vc_score += 1.5
        elif institutional_intensity > 1.0:
            vc_score += 1.0

        return round(min(4.0, vc_score), 2), details

    def _calculate_vc_long(self, ind: TechnicalIndicators, df: pd.DataFrame, price: float, low_60d: float) -> Tuple[float, Dict]:
        """Volume Confirmation for long."""
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        # Institutional intensity
        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])
        institutional_intensity = volume_ratio * abs(clv - 0.5)

        # Exhaustion gap
        exhaustion_gap = self._check_exhaustion_gap(df, low_60d, 'long')

        details = {
            'volume_ratio': volume_ratio,
            'clv': clv,
            'institutional_intensity': institutional_intensity,
            'exhaustion_gap': exhaustion_gap
        }

        vc_score = 0.0

        # Volume
        if volume_ratio > 1.3:
            vc_score += 2.0
        elif volume_ratio > 1.0:
            vc_score += 1.0

        # Exhaustion gap
        if exhaustion_gap:
            vc_score += 2.0

        # Institutional intensity
        if institutional_intensity > self.PARAMS['institutional_intensity_threshold']:
            vc_score += 1.5
        elif institutional_intensity > 1.0:
            vc_score += 1.0

        return round(min(4.0, vc_score), 2), details


    def _check_exhaustion_gap(self, df: pd.DataFrame, level: float, direction: str) -> bool:
        """
        Check for exhaustion gap (Expert suggestion C).
        Short: Gap up to level + close < open + volume spike
        Long: Gap down to level + close > open + volume spike
        """
        if len(df) < 2:
            return False

        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        gap_threshold = self.PARAMS['exhaustion_gap_threshold']

        if direction == 'short':
            # Gap up
            gap_up = today['open'] > yesterday['high'] * (1 + gap_threshold)
            # Near 60d high
            near_high = today['high'] >= level * 0.995
            # Close below open (rejection)
            rejection = today['close'] < today['open']
            # Volume spike
            volume_spike = today['volume'] > df['volume'].tail(20).mean() * 1.5

            return gap_up and near_high and rejection and volume_spike
        else:
            # Gap down
            gap_down = today['open'] < yesterday['low'] * (1 - gap_threshold)
            # Near 60d low
            near_low = today['low'] <= level * 1.005
            # Close above open (rejection)
            rejection = today['close'] > today['open']
            # Volume spike
            volume_spike = today['volume'] > df['volume'].tail(20).mean() * 1.5

            return gap_down and near_low and rejection and volume_spike

    def _calculate_stop(self, df: pd.DataFrame, dimensions: List[ScoringDimension]) -> Optional[float]:
        """Calculate stop price."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        price_metrics = ind.indicators.get('price_metrics', {})

        if self.market_direction == 'short':
            high_60d = price_metrics.get('high_60d', current_price)
            return high_60d + atr * 0.5
        else:
            low_60d = price_metrics.get('low_60d', current_price)
            return low_60d - atr * 0.5

    def _calculate_target1(self, df: pd.DataFrame, dimensions: List[ScoringDimension]) -> Optional[float]:
        """Calculate first target."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        price_metrics = ind.indicators.get('price_metrics', {})

        if self.market_direction == 'short':
            high_60d = price_metrics.get('high_60d', current_price)
            return high_60d - atr  # First target: 1 ATR below high
        else:
            low_60d = price_metrics.get('low_60d', current_price)
            return low_60d + atr  # First target: 1 ATR above low

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
        price_metrics = ind.indicators.get('price_metrics', {})

        entry = round(current_price, 2)

        if self.market_direction == 'short':
            high_60d = price_metrics.get('high_60d', current_price * 1.03)
            stop = round(high_60d + atr * 0.5, 2)
            target = round(high_60d - atr * self.PARAMS['target_r_multiplier'], 2)
        else:
            low_60d = price_metrics.get('low_60d', current_price * 0.97)
            stop = round(low_60d - atr * 0.5, 2)
            target = round(low_60d + atr * self.PARAMS['target_r_multiplier'], 2)

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
        pl = next((d for d in dimensions if d.name == 'PL'), None)
        ts = next((d for d in dimensions if d.name == 'TS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        pl_details = pl.details if pl else {}
        ts_details = ts.details if ts else {}
        vc_details = vc.details if vc else {}

        side = ts_details.get('side', 'unknown')
        side_label = f"{side.upper()}" if side != 'unknown' else ""

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%) {side_label}",
            f"PL:{pl.score:.2f} TS:{ts.score:.2f} VC:{vc.score:.2f}",
            f"Direction: {self.market_direction.upper()}",
            f"Tests: {pl_details.get('test_count', 0)} (avg {pl_details.get('avg_interval', 0):.0f}d)",
        ]

        if vc_details.get('exhaustion_gap'):
            reasons.append("Exhaustion gap!")

        if vc_details.get('institutional_intensity', 0) > 1.5:
            reasons.append(f"Inst intensity: {vc_details['institutional_intensity']:.2f}")

        if ts_details.get('rsi_divergence'):
            reasons.append("RSI divergence")

        return reasons

    def calculate_position_pct(self, tier: str) -> float:
        """
        Override to implement left/right side position limit (Expert suggestion A).
        Left side (TS <= 3) max Tier B (5%).
        """
        # This is called after dimensions are calculated, but we don't have access here
        # The actual limiting should be done in selector.py based on TS details
        # For now, return standard values
        base_pct = super().calculate_position_pct(tier)
        return base_pct
