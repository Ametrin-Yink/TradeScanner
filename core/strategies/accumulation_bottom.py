"""Strategy E: AccumulationBottom - Long accumulation bottoms (v7.1).

Created from:
- DoubleTopBottom long-side logic (accumulation detection)
- OBV divergence for institutional accumulation detection
- Wyckoff structure scoring (spring, selling climax, volume contraction)
"""
from typing import Dict, List, Tuple, Any, Optional
import logging
import numpy as np
import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class AccumulationBottomStrategy(BaseStrategy):
    """
    Strategy E: AccumulationBottom v7.1
    Long-only accumulation bases at multi-week lows.
    """

    NAME = "AccumulationBottom"
    STRATEGY_TYPE = StrategyType.E
    DESCRIPTION = "AccumulationBottom v7.1 - long accumulation patterns"
    DIMENSIONS = ['TQ', 'AL', 'OD', 'VC', 'WY']
    DIRECTION = 'long'

    PARAMS = {
        'min_market_cap': 2_500_000_000,
        'min_volume': 150_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 180,
        'max_distance_from_60d_low': 0.10,
        'min_touches': 2,
    }

    # Regime filtering for long-only bottom strategy:
    # Bull -> full (reversals follow through); Neutral -> B-tier max; Bear -> skip
    REGIME_ALLOWANCE = {
        'bull_strong': 'S',       # Full - reversals work best in bull markets
        'bull_moderate': 'S',     # Full
        'neutral': 'B',           # B-tier max
        'bear_moderate': None,    # Skip - falling knives in bear markets
        'bear_strong': None,      # Skip
        'extreme_vix': None,      # Skip
    }

    def __init__(self, fetcher=None, db=None, config=None):
        super().__init__(fetcher=fetcher, db=db, config=config)
        self._support_cache: Dict[str, Optional[Dict]] = {}

    def _should_process_in_regime(self) -> bool:
        """Check if strategy should run in current regime.

        Skip entirely in bear markets - long-only bottom strategy needs bull/neutral backdrop.
        """
        regime = getattr(self, '_current_regime', 'neutral')
        allowance = self.REGIME_ALLOWANCE.get(regime, 'B')
        return allowance is not None

    def _get_max_tier_for_regime(self) -> str:
        """Get maximum tier allowed for current regime.

        Bull -> full; Neutral -> B-tier max; Bear -> skip (handled by _should_process)
        """
        regime = getattr(self, '_current_regime', 'neutral')
        allowance = self.REGIME_ALLOWANCE.get(regime, 'B')
        return allowance if allowance else 'C'

    def _get_support_level(self, df: pd.DataFrame) -> Optional[Dict]:
        """Get cached support level, compute once per DataFrame."""
        cache_key = id(df)
        if cache_key in self._support_cache:
            return self._support_cache[cache_key]

        result = self._detect_support_level(df)
        self._support_cache[cache_key] = result
        return result

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for accumulation bottom candidates.

        Regime: skip in bear markets, allow in bull/neutral.
        Requires: RSI < 45, within 10% of 60d low, support level, ADR > min.
        """
        # Check regime first - skip entirely in bear market
        if not self._should_process_in_regime():
            regime = getattr(self, '_current_regime', 'unknown')
            logger.debug(f"ACC_REJ: {symbol} - Skip in {regime} regime")
            return False

        if len(df) < self.PARAMS['min_listing_days']:
            logger.debug(f"ACC_REJ: {symbol} - Insufficient data ({len(df)} < {self.PARAMS['min_listing_days']})")
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Check ADR
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            logger.debug(f"ACC_REJ: {symbol} - ADR {adr_pct:.3f} < {self.PARAMS['min_atr_pct']}")
            return False

        # RSI check - must be in oversold/accumulation zone
        rsi = ind.indicators.get('rsi', {}).get('rsi', 50)
        if rsi is None or rsi > 45:
            logger.debug(f"ACC_REJ: {symbol} - RSI {rsi:.1f} > 45")
            return False

        # Near 60d low - use pre-calculated data from phase0
        phase0_data = self.phase0_data.get(symbol, {}) if hasattr(self, 'phase0_data') else {}
        low_60d = phase0_data.get('low_60d')
        if low_60d is None or low_60d <= 0:
            logger.debug(f"ACC_REJ: {symbol} - No low_60d data in phase0")
            return False
        if (current_price - low_60d) / low_60d > self.PARAMS['max_distance_from_60d_low']:
            logger.debug(f"ACC_REJ: {symbol} - Distance from 60d low {(current_price - low_60d) / low_60d:.3f} > {self.PARAMS['max_distance_from_60d_low']}")
            return False

        # Check for support level with touches
        support_level = self._get_support_level(df)
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
        Support levels are cached across filter/dimensions/entry calls.
        """
        logger.info("AccumulationBottom: Phase 0 - Using cached data for pre-filter...")

        # Clear caches for this screening run
        self._support_cache = {}

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

        # Pre-compute support levels for all prefiltered symbols (cache for reuse)
        for sym in prefiltered:
            if sym in self.market_data and self.market_data[sym] is not None:
                self._get_support_level(self.market_data[sym])

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
        """Calculate TQ, AL, OD, VC, WY per v7.1 spec."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # TQ: Trend Quality
        tq_score = self._calculate_tq(ind, df)

        # AL: Accumulation Level
        al_score = self._calculate_al(df)

        # OD: OBV Divergence (replaces AS)
        od_score = self._calculate_od(df)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df)

        # WY: Wyckoff Structure
        support_level = self._get_support_level(df)
        atr = ind.indicators.get('atr', {}).get('atr', df['close'].iloc[-1] * 0.02)
        wy_score = self._calculate_wy(df, support_level, atr)

        return [
            ScoringDimension(name='TQ', score=tq_score, max_score=4.0, details={}),
            ScoringDimension(name='AL', score=al_score, max_score=4.0, details={}),
            ScoringDimension(name='OD', score=od_score, max_score=4.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
            ScoringDimension(name='WY', score=wy_score, max_score=3.0, details={}),
        ]

    def _calculate_tq(self, ind: TechnicalIndicators, df: pd.DataFrame) -> float:
        """Trend Quality - early reversal confirmation (v7.1).

        Reward signs of downtrend exhaustion and early reversal:
        | EMA Structure | Score | Rationale |
        |---------------|-------|-----------|
        | Price>EMA21, EMA8>EMA21, still <EMA50 | 3.5 | Strong early reversal |
        | Price>EMA8, EMA8<EMA21 (price reclaiming) | 2.0 | Early sign |
        | Price<EMA8, EMA8<EMA21, <EMA50 | 0.5 | Downtrend intact |
        | Price>EMA50 | 0 | Already rallied, not a bottom |
        """
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        # Already above EMA50 - not a bottom anymore, already rallied
        if current_price > ema50:
            return 0.0

        # Price > EMA21 and EMA8 > EMA21 - strong early reversal signal
        if current_price > ema21 and ema8 > ema21:
            return 3.5

        # Price reclaimed EMA8 but still below EMA21 - early reversal sign
        if current_price > ema8 and ema8 < ema21:
            return 2.0

        # Downtrend still intact - minimal score
        return 0.5

    def _calculate_al(self, df: pd.DataFrame) -> float:
        """Accumulation Level quality - touches, interval, width (v7.0).

        Per documentation:
        | Touches | Score | Min interval | Score | Width | Score |
        |---------|-------|--------------|-------|-------|-------|
        | >=5     | 1.5   | >=14d        | 1.5   | 1-2.5xATR | 1.0 |
        | 4       | 1.2   | 7-14d        | 0.8-1.5 | 0.5-1xATR | 0.5 |
        | 3       | 0.8   | 5-7d         | 0.3-0.8 | >3xATR | 0.3 |
        | 2       | 0.3   | <5d          | 0 | | |
        """
        level = self._get_support_level(df)
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

        # Interval scoring (0-1.5)
        min_interval = level.get('min_interval_days', 0)
        if min_interval >= 14:
            score += 1.5
        elif min_interval >= 7:
            score += 0.8 + (min_interval - 7) / 7 * 0.7
        elif min_interval >= 5:
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

    def _calculate_od(self, df: pd.DataFrame) -> float:
        """OBV Divergence - institutional accumulation detection (v7.1).

        Compares OBV rate-of-change vs price rate-of-change over 30 days.
        Bullish divergence: OBV rising while price is flat or falling.

        Divergence score (0-3.0):
        | divergence (obv_roc - price_roc) | score |
        |-----------------------------------|-------|
        | > 0.30                           | 3.0   |
        | 0.15-0.30                        | 1.5-3.0 (linear) |
        | 0.05-0.15                        | 0.5-1.5 (linear) |
        | 0-0.05                           | 0 |
        | < 0                              | 0 (distribution) |

        Confirmation bonus (0-1.0):
        - Positive OBV slope over last 10 days (linear regression)
        """
        if len(df) < 60:
            return 0.0

        # Calculate OBV
        close = df['close'].values
        volume = df['volume'].values
        obv = np.zeros(len(close))

        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv[i] = obv[i-1] + volume[i]
            elif close[i] < close[i-1]:
                obv[i] = obv[i-1] - volume[i]
            else:
                obv[i] = obv[i-1]

        # 30-day rate of change
        lookback = min(30, len(close) - 1)
        obv_current = obv[-1]
        obv_past = obv[-(lookback + 1)]
        price_current = close[-1]
        price_past = close[-(lookback + 1)]

        obv_roc = (obv_current - obv_past) / abs(obv_past) if obv_past != 0 else 0
        price_roc = (price_current - price_past) / price_past if price_past > 0 else 0

        divergence = obv_roc - price_roc

        # Score divergence (0-3.0)
        if divergence > 0.30:
            div_score = 3.0
        elif divergence >= 0.15:
            div_score = 1.5 + (divergence - 0.15) / 0.15 * 1.5
        elif divergence >= 0.05:
            div_score = 0.5 + (divergence - 0.05) / 0.10 * 1.0
        else:
            div_score = 0.0

        # Confirmation bonus: OBV slope over last 10 days (0-1.0)
        if len(close) >= 10:
            recent_obv = obv[-10:]
            x = np.arange(10)
            try:
                slope, _ = np.polyfit(x, recent_obv, 1)
                # Normalize slope relative to OBV magnitude
                normalized_slope = slope / (abs(obv_current) if obv_current != 0 else 1)
                # Scale: if slope is meaningfully positive (0.5% of OBV per day or more)
                if normalized_slope > 0.005:
                    confirm_score = 1.0
                elif normalized_slope > 0.001:
                    confirm_score = 0.5
                else:
                    confirm_score = 0.0
            except (ValueError, IndexError):
                confirm_score = 0.0
        else:
            confirm_score = 0.0

        return min(4.0, div_score + confirm_score)

    def _calculate_vc(self, df: pd.DataFrame) -> float:
        """Volume Confirmation - reversal surge (0-2.0) and follow-through (0-1.0)."""
        avg_volume = df['volume'].tail(20).mean()

        if avg_volume == 0:
            return 0.0

        recent = df.tail(10)
        level = self._get_support_level(df)

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
        if best_volume_ratio >= 2.5:
            surge_score = 2.0
        elif best_volume_ratio >= 2.0:
            surge_score = 1.5 + (best_volume_ratio - 2.0) / 0.5 * 0.5
        elif best_volume_ratio >= 1.5:
            surge_score = 1.0 + (best_volume_ratio - 1.5) / 0.5 * 0.5
        elif best_volume_ratio >= 1.2:
            surge_score = 0.5 + (best_volume_ratio - 1.2) / 0.3 * 0.5
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

    def _calculate_wy(self, df: pd.DataFrame, support_level: Optional[Dict], atr: float) -> float:
        """Wyckoff Structure - spring, selling climax, volume contraction (v7.1).

        Spring detection (0-1.5):
        - Look back 30 days for false breakdown below support
        - Score based on volume on the spring bar

        Selling climax (0-1.0):
        - Look back 60 days for extreme volume + long lower wick

        Volume contraction (0-0.5):
        - Declining volume on down-days in recent 30d vs 60-30d window
        """
        if len(df) < 60:
            return 0.0

        score = 0.0

        # === Spring detection (0-1.5) ===
        if support_level is not None:
            support_low = support_level['low']
            spring_score = 0.0

            for i in range(1, min(31, len(df))):
                idx = -(i + 1)
                if idx < -len(df):
                    break
                row = df.iloc[idx]

                # False breakdown: low broke support but closed above
                if row['low'] < support_low and row['close'] > support_low:
                    # Check volume on this bar vs prior 10-day average
                    vol_on_spring = row['volume']
                    vol_avg = df.iloc[idx-10:idx]['volume'].mean() if i >= 10 else df['volume'].tail(20).mean()

                    if vol_avg > 0:
                        vol_ratio = vol_on_spring / vol_avg
                    else:
                        vol_ratio = 1.0

                    if vol_ratio < 0.8:
                        spring_score = 1.5  # Classic spring on low volume
                    elif vol_ratio < 1.2:
                        spring_score = 1.0
                    else:
                        spring_score = 0.5  # Reclaim but not clean spring

                    break  # Only score the most recent spring

            score += spring_score

        # === Selling climax detection (0-1.0) ===
        lookback_60 = min(60, len(df))
        recent_60 = df.tail(lookback_60)
        vol_20_avg = df['volume'].tail(20).mean()

        if vol_20_avg > 0:
            max_vol_idx = recent_60['volume'].idxmax()
            max_vol_row = df.loc[max_vol_idx]
            vol_ratio = max_vol_row['volume'] / vol_20_avg

            body = abs(max_vol_row['close'] - max_vol_row['open'])
            range_val = max_vol_row['high'] - max_vol_row['low']
            lower_shadow = min(max_vol_row['open'], max_vol_row['close']) - max_vol_row['low']

            if vol_ratio > 3.0 and range_val > 0 and lower_shadow >= range_val * 0.5:
                score += 1.0

        # === Volume contraction in range (0-0.5) ===
        if len(df) >= 60:
            recent_30 = df.tail(30)
            prior_30 = df.iloc[-60:-30]

            recent_down_vol = recent_30[recent_30['close'] < recent_30['open']]['volume'].mean()
            prior_down_vol = prior_30[prior_30['close'] < prior_30['open']]['volume'].mean()

            if prior_down_vol > 0 and recent_down_vol < prior_down_vol * 0.8:
                score += 0.5

        return min(3.0, score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
        """Calculate entry, stop, target for long position.

        DOCUMENTATION: "CLV >= 0.60 for long entry" (recommendation, not gate)
        """
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        level = self._get_support_level(df)
        support_low = level['low'] if level else df['low'].tail(20).min()

        # DOCUMENTATION: CLV >= 0.60 for long entry (recommendation)
        clv = (current_price - df['low'].iloc[-1]) / (df['high'].iloc[-1] - df['low'].iloc[-1])
        entry_warnings = []
        if clv < 0.60:
            entry_warnings.append(f"CLV {clv:.2f} < 0.60")
            logger.debug(f"ACC_WARN: {symbol} - CLV {clv:.2f} < 0.60")

        entry = round(current_price, 2)
        stop = round(support_low - 0.5 * atr, 2)
        risk = entry - stop
        target = round(entry + risk * 2.5, 2)

        warning = "; ".join(entry_warnings) if entry_warnings else ""
        return entry, stop, target, warning

    def build_match_reasons(self, symbol: str, df: pd.DataFrame,
                           dimensions: List[ScoringDimension],
                           score: float, tier: str) -> List[str]:
        """Build human-readable match reasons."""
        tq = next((d for d in dimensions if d.name == 'TQ'), None)
        al = next((d for d in dimensions if d.name == 'AL'), None)
        od = next((d for d in dimensions if d.name == 'OD'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        wy = next((d for d in dimensions if d.name == 'WY'), None)

        position_pct = self.calculate_position_pct(tier)

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} AL:{al.score:.2f} OD:{od.score:.2f} VC:{vc.score:.2f} WY:{wy.score:.2f}"
        ]

        # Support level details
        level = self._get_support_level(df)
        if level:
            reasons.append(f"Support x{level['touches']} @ {level['low']:.2f}")

        return reasons
