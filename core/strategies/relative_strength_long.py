"""Strategy H: RelativeStrengthLong - RS divergence in bear/neutral markets (v7.0)."""
from typing import Dict, List, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class RelativeStrengthLongStrategy(BaseStrategy):
    """
    Strategy H: RelativeStrengthLong v7.0
    RS divergence longs in bear/neutral markets.
    Exempt from extreme regime scalar.

    Mismatches fixed (v7.0):
    1. RD max score: 6.0 → 4.0
    2. RD scoring: RS percentile + SPY divergence bonus (capped at 4.0)
    3. SH dimension: Replaced EMA alignment + 52w high with SPY down-day evaluation
    4. Regime exit: Added Stage 3 trailing stop when SPY crosses above EMA21
    5. Stop loss: Changed to max(EMA50×0.99, entry×0.93)
    6. Pre-filter: Removed accum_ratio hard gate (now only scored in VC)
    """

    NAME = "RelativeStrengthLong"
    STRATEGY_TYPE = StrategyType.H
    DESCRIPTION = "RelativeStrengthLong v5.0 - RS leaders in bear markets"
    DIMENSIONS = ['RD', 'SH', 'CQ', 'VC']
    DIRECTION = 'long'

    # Exempt from extreme regime scalar reduction
    EXTREME_EXEMPT = True

    PARAMS = {
        'min_rs_percentile': 80,
        'min_market_cap': 3e9,
        'min_volume': 200000,
        'max_distance_from_52w_high': 0.15,
        # Note: accum_ratio is scored in VC dimension, not a hard pre-filter
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Hard gate: Only in bear/neutral regimes. RS >= 80th."""
        # Get regime from screener context
        regime = getattr(self, '_current_regime', 'neutral')
        if regime not in ['bear_moderate', 'bear_strong', 'extreme_vix', 'neutral']:
            logger.debug(f"RS_REJ: {symbol} - not in bear/neutral regime: {regime}")
            return False

        data = self.phase0_data.get(symbol, {}) if hasattr(self, 'phase0_data') else {}

        # RS percentile gate
        rs_pct = data.get('rs_percentile', 0)
        if rs_pct < self.PARAMS['min_rs_percentile']:
            logger.debug(f"RS_REJ: {symbol} - RS percentile {rs_pct:.1f} < {self.PARAMS['min_rs_percentile']}")
            return False

        # Market cap
        market_cap = data.get('market_cap', 0)
        if market_cap < self.PARAMS['min_market_cap']:
            logger.debug(f"RS_REJ: {symbol} - market cap too low")
            return False

        # Volume
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume < self.PARAMS['min_volume']:
            logger.debug(f"RS_REJ: {symbol} - volume too low")
            return False

        # Distance from 52w high
        high_52w = df['high'].tail(252).max() if len(df) >= 252 else df['high'].max()
        current_price = df['close'].iloc[-1]
        distance_from_high = (high_52w - current_price) / high_52w
        if distance_from_high > self.PARAMS['max_distance_from_52w_high']:
            logger.debug(f"RS_REJ: {symbol} - too far from 52w high: {distance_from_high:.2%}")
            return False

        logger.debug(f"RS_PASS: {symbol} - RS leader in {regime}")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate RD, SH, CQ, VC per v7.0 spec."""
        data = self.phase0_data.get(symbol, {}) if hasattr(self, 'phase0_data') else {}

        # RD: RS Divergence
        rd_score = self._calculate_rd(data, df)

        # SH: Support Hold (updated to use data param for 52w high)
        sh_score = self._calculate_sh(df, data)

        # CQ: Compression Quality
        cq_score = self._calculate_cq(df)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df, data)

        return [
            ScoringDimension(name='RD', score=rd_score, max_score=4.0, details={}),
            ScoringDimension(name='SH', score=sh_score, max_score=4.0, details={}),
            ScoringDimension(name='CQ', score=cq_score, max_score=3.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=2.0, details={}),
        ]

    def _calculate_rd(self, data: Dict, df: pd.DataFrame) -> float:
        """
        RS Divergence - per v7.0 spec (max 4.0, including bonus).

        Documentation structure:
        | RS_pct | Score | Stock 10d return − SPY 10d return | Bonus |
        |--------|-------|-----------------------------------|-------|
        | ≥95th | 4.0 | >+10% | +1.5 |
        | 90-95th | 3.0-4.0 | +5-10% | +1.0-1.5 |
        | 85-90th | 2.0-3.0 | +2-5% | +0.5-1.0 |
        | 80-85th | 1.0-2.0 | <+2% | 0 |

        Note: RD capped at 4.0 after bonus.
        """
        rs_pct = data.get('rs_percentile', 50)
        base_score = 0.0

        # RS percentile base score (0-3.0)
        if rs_pct >= 95:
            base_score = 3.0
        elif rs_pct >= 90:
            base_score = 2.0 + (rs_pct - 90) * 0.2  # 2.0-3.0 for 90-95th
        elif rs_pct >= 85:
            base_score = 1.0 + (rs_pct - 85) * 0.2  # 1.0-2.0 for 85-90th
        elif rs_pct >= 80:
            base_score = 0.0 + (rs_pct - 80) * 0.2  # 0.0-1.0 for 80-85th
        else:
            return 0.0  # Below 80th percentile

        # SPY divergence bonus (0-1.5) based on 10d return differential
        spy_df = getattr(self, '_spy_df', None)
        bonus = 0.0
        if spy_df is not None and len(df) >= 10 and len(spy_df) >= 10:
            stock_ret_10d = (df['close'].iloc[-1] / df['close'].iloc[-10] - 1)
            spy_ret_10d = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-10] - 1)
            divergence = stock_ret_10d - spy_ret_10d

            if divergence > 0.10:
                bonus = 1.5
            elif divergence >= 0.05:
                bonus = 1.0 + (divergence - 0.05) * 10  # 1.0-1.5 for +5-10%
            elif divergence >= 0.02:
                bonus = 0.5 + (divergence - 0.02) * 16.67  # 0.5-1.0 for +2-5%
            # else: <+2% = 0 bonus

        # Cap at 4.0 after bonus
        return min(4.0, base_score + bonus)

    def _calculate_sh(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Support Hold - per v7.0 spec (max 4.0).

        Evaluated during SPY down-days in last 10d:
        | Condition | Score |
        |-----------|-------|
        | Held above EMA8 during SPY weakness | 1.5 |
        | Held above EMA21 | 1.0 |
        | No SPY down-days in 10d (baseline) | 1.0 |
        | Brief EMA21 break, reclaimed same day | 0.5 |
        | Closed below EMA21 | 0 |
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)

        spy_df = getattr(self, '_spy_df', None)
        if spy_df is None or len(spy_df) < 11 or len(df) < 11:
            # Can't evaluate without sufficient data - return baseline
            return 1.0

        # Identify SPY down-days in last 10 days
        spy_down_days = []
        for i in range(1, 11):
            idx = -i
            prev_idx = -(i + 1)
            if abs(idx) <= len(spy_df) and abs(prev_idx) <= len(spy_df):
                spy_close = spy_df['close'].iloc[idx]
                spy_prev_close = spy_df['close'].iloc[prev_idx]
                if spy_close < spy_prev_close:
                    spy_down_days.append(i - 1)  # 0-indexed days ago

        # No SPY down-days in 10d = baseline score
        if not spy_down_days:
            return 1.0

        # Evaluate stock behavior during SPY down-days
        score = 0.0
        held_above_ema8_count = 0
        held_above_ema21_count = 0
        broke_ema21_but_reclaimed = False

        for days_ago in spy_down_days:
            idx = -(days_ago + 1)
            if abs(idx) > len(df):
                continue

            stock_low = df['low'].iloc[idx]
            stock_close = df['close'].iloc[idx]
            prev_close = df['close'].iloc[idx - 1] if idx > 0 else stock_close

            # Check if held above EMA8 during SPY weakness
            if stock_low >= ema8:
                held_above_ema8_count += 1

            # Check if held above EMA21
            if stock_low >= ema21:
                held_above_ema21_count += 1
            elif stock_close >= ema21:
                # Broke EMA21 intraday but reclaimed by close
                broke_ema21_but_reclaimed = True

        # Calculate score based on behavior
        num_down_days = len(spy_down_days)

        # Held above EMA8 during SPY weakness: 1.5 points
        if held_above_ema8_count == num_down_days:
            score += 1.5
        elif held_above_ema8_count > 0:
            score += 1.5 * (held_above_ema8_count / num_down_days)

        # Held above EMA21: 1.0 points
        if held_above_ema21_count == num_down_days:
            score += 1.0
        elif held_above_ema21_count > 0:
            score += 1.0 * (held_above_ema21_count / num_down_days)

        # Brief EMA21 break, reclaimed same day: 0.5 points
        if broke_ema21_but_reclaimed and held_above_ema21_count < num_down_days:
            score = max(score, 0.5)

        # Closed below EMA21 on any down-day: 0 points for that day
        closed_below_ema21 = any(
            df['close'].iloc[-(d + 1)] < ema21
            for d in spy_down_days
            if abs(-(d + 1)) <= len(df)
        )
        if closed_below_ema21:
            # Reduce score if closed below EMA21
            score = min(score, 0.5)

        return min(4.0, score)

    def _calculate_cq(self, df: pd.DataFrame) -> float:
        """
        Compression Quality - per v5.0 spec (3.0 max).

        Components:
        1. Volatility vs SPY (0-1.5 pts) - relative ATR
        2. Base quality during SPY weakness (0-1.5 pts) - price range % in last 10d
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        score = 0.0

        # 1. Volatility vs SPY (0-1.5 pts) per v5.0 spec
        spy_df = getattr(self, '_spy_df', None)
        if spy_df is not None and len(spy_df) >= 20:
            stock_atr = ind.indicators.get('atr', {}).get('atr', 0)
            stock_atr_pct = stock_atr / current_price if current_price > 0 else 0

            spy_ind = TechnicalIndicators(spy_df)
            spy_atr = spy_ind.indicators.get('atr', {}).get('atr', 0)
            spy_price = spy_df['close'].iloc[-1]
            spy_atr_pct = spy_atr / spy_price if spy_price > 0 else 0

            if spy_atr_pct > 0:
                rel_vol = stock_atr_pct / spy_atr_pct
                if rel_vol < 0.8:
                    score += 1.5
                elif rel_vol < 1.2:
                    # Linear interpolation: 0.8-1.2 = 1.5-0.8
                    score += 1.5 - (rel_vol - 0.8) / 0.4 * 0.7
                elif rel_vol < 1.8:
                    # Linear interpolation: 1.2-1.8 = 0.8-0.2
                    score += 0.8 - (rel_vol - 1.2) / 0.6 * 0.6
                # else: > 1.8 = 0 points

        # 2. Base quality during SPY weakness (0-1.5 pts)
        # Measure stock's price range % during last 10d
        if len(df) >= 10:
            recent_10d = df.tail(10)
            high_10d = recent_10d['high'].max()
            low_10d = recent_10d['low'].min()
            price_range_pct = (high_10d - low_10d) / low_10d if low_10d > 0 else 1.0

            if price_range_pct < 0.05:
                score += 1.5
            elif price_range_pct < 0.08:
                # Linear interpolation: 5-8% = 1.5-1.0
                score += 1.5 - (price_range_pct - 0.05) / 0.03 * 0.5
            elif price_range_pct < 0.12:
                # Linear interpolation: 8-12% = 1.0-0.5
                score += 1.0 - (price_range_pct - 0.08) / 0.04 * 0.5
            # else: > 12% = 0 points

        return min(3.0, score)

    def _calculate_vc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Volume Confirmation - per v7.0 spec (max 2.0).

        accum_ratio = sum(vol, up-days, 15d) / sum(vol, down-days, 15d)

        | accum_ratio | Score |
        |-------------|-------|
        | >2.0 | 2.0 |
        | 1.5–2.0 | 1.5–2.0 |
        | 1.2–1.5 | 0.8–1.5 |
        | 1.0–1.2 | 0.3–0.8 |
        | <1.0 | 0 |
        """
        accum_ratio = data.get('accum_ratio_15d', 1.0)

        score = 0.0

        # Accumulation ratio scoring per v7.0 spec
        if accum_ratio > 2.0:
            score = 2.0
        elif accum_ratio >= 1.5:
            # 1.5-2.0 = 1.5-2.0
            score = 1.5 + (accum_ratio - 1.5) * 0.5
        elif accum_ratio >= 1.2:
            # 1.2-1.5 = 0.8-1.5
            score = 0.8 + (accum_ratio - 1.2) / 0.3 * 0.7
        elif accum_ratio >= 1.0:
            # 1.0-1.2 = 0.3-0.8
            score = 0.3 + (accum_ratio - 1.0) / 0.2 * 0.5
        # else: <1.0 = 0

        return min(2.0, score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, target for long position per v7.0 spec.

        Entry: RS≥80th 5+ days, Price>EMA21 positive slope, Vol≥1.2×avg20d; prefer SPY down-day
        Stop: max(EMA50×0.99, entry×0.93)
        Target: entry + 3.0 × (entry − stop)
        Regime exit: If SPY crosses above EMA21 (bear→neutral), move to Stage 3 trailing stop
        """
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # Get indicators
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        entry = round(current_price, 2)

        # Stop loss per v7.0: max(EMA50×0.99, entry×0.93)
        ema50_stop = ema50 * 0.99
        entry_stop = entry * 0.93
        stop = round(max(ema50_stop, entry_stop), 2)

        # Check regime exit condition (SPY above EMA21 = bear→neutral signal)
        spy_df = getattr(self, '_spy_df', None)
        regime_exit_active = False
        if spy_df is not None and len(spy_df) >= 21:
            spy_ema21 = spy_df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
            spy_close = spy_df['close'].iloc[-1]
            if spy_close > spy_ema21:
                # SPY above EMA21: regime transitioning from bear to neutral
                # Move to Stage 3 trailing stop (tighter stop)
                regime_exit_active = True
                # Stage 3: Use tighter stop (EMA21 or recent low)
                ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
                low_10d = df['low'].tail(10).min()
                stage3_stop = round(max(ema21 * 0.99, low_10d), 2)
                # Use the tighter of original stop or Stage 3 stop
                stop = min(stop, stage3_stop)

        # Target per v7.0: 3.0× risk (not 2.5×)
        risk = entry - stop
        target = round(entry + risk * 3.0, 2)

        return entry, stop, target

    def build_match_reasons(self, symbol: str, df: pd.DataFrame,
                           dimensions: List[ScoringDimension],
                           score: float, tier: str) -> List[str]:
        """Build human-readable match reasons."""
        rd = next((d for d in dimensions if d.name == 'RD'), None)
        sh = next((d for d in dimensions if d.name == 'SH'), None)
        cq = next((d for d in dimensions if d.name == 'CQ'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        data = self.phase0_data.get(symbol, {}) if hasattr(self, 'phase0_data') else {}
        rs_pct = data.get('rs_percentile', 0)
        accum_ratio = data.get('accum_ratio_15d', 1.0)

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"RD:{rd.score:.2f} SH:{sh.score:.2f} CQ:{cq.score:.2f} VC:{vc.score:.2f}",
            f"RS percentile: {rs_pct:.0f}th",
            f"Accumulation ratio: {accum_ratio:.2f}",
            f"Support hold score: {sh.score:.2f}"
        ]
