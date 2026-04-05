"""Strategy H: RelativeStrengthLong - RS divergence in bear markets (v5.0)."""
from typing import Dict, List, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class RelativeStrengthLongStrategy(BaseStrategy):
    """
    Strategy H: RelativeStrengthLong v5.0
    RS divergence longs in bear/neutral markets.
    Exempt from extreme regime scalar.
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
        'min_accum_ratio': 1.1,
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

        # Accumulation ratio
        accum_ratio = data.get('accum_ratio_15d', 1.0)
        if accum_ratio < self.PARAMS['min_accum_ratio']:
            logger.debug(f"RS_REJ: {symbol} - accum_ratio {accum_ratio:.2f} < {self.PARAMS['min_accum_ratio']}")
            return False

        logger.debug(f"RS_PASS: {symbol} - RS leader in {regime}")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate RD, SH, CQ, VC per v5.0 spec."""
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
            ScoringDimension(name='RD', score=rd_score, max_score=6.0, details={}),
            ScoringDimension(name='SH', score=sh_score, max_score=4.0, details={}),
            ScoringDimension(name='CQ', score=cq_score, max_score=3.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=2.0, details={}),
        ]

    def _calculate_rd(self, data: Dict, df: pd.DataFrame) -> float:
        """
        RS Divergence - 3 components per v5.0 spec:
        1. RS percentile (0-3.0) - current RS rank vs universe
        2. Absolute divergence (0-2.0) - stock vs SPY 20d return
        3. Consistency (0-1.0) - RS percentile stability over last 10 days
        """
        rs_pct = data.get('rs_percentile', 50)
        score = 0.0

        # 1. RS percentile (0-3.0) per v5.0 spec
        if rs_pct >= 95:
            score += 3.0
        elif rs_pct >= 90:
            score += 2.5 + (rs_pct - 90) * 0.1
        elif rs_pct >= 85:
            score += 2.0 + (rs_pct - 85) * 0.1
        elif rs_pct >= 80:
            score += 1.5 + (rs_pct - 80) * 0.1

        # 2. Absolute divergence - stock vs SPY 20d return (0-2.0)
        spy_df = getattr(self, '_spy_df', None)
        if spy_df is not None and len(df) >= 20 and len(spy_df) >= 20:
            stock_ret = (df['close'].iloc[-1] / df['close'].iloc[-20] - 1)
            spy_ret = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-20] - 1)
            divergence = stock_ret - spy_ret

            if divergence >= 0.10 and spy_ret < 0:
                score += 2.0
            elif divergence >= 0.10:
                score += min(1.5 + (divergence - 0.10) * 10, 2.0)
            elif divergence >= 0.05:
                score += 0.8 + (divergence - 0.05) * 14
            elif divergence >= 0.02:
                score += 0.3 + (divergence - 0.02) * 16.67

        # 3. Consistency - RS percentile stability over last 10 days (0-1.0)
        # Per v5.0 spec: "Score 1.0 if RS percentile has been >= 75th for all of last 10 trading days"
        consistency_score = self._calculate_rs_consistency(df, spy_df)
        score += consistency_score

        return min(6.0, score)

    def _calculate_rs_consistency(self, df: pd.DataFrame, spy_df: pd.DataFrame) -> float:
        """
        Calculate RS percentile stability over last 10 trading days.

        Per v5.0 spec:
        - Calculate 3m return for each of the last 10 days
        - Rank each day's RS vs universe (approximated by checking if RS > 0)
        - Score 1.0 if RS percentile >= 75th for all 10 days
        - Otherwise score 0

        Note: True RS percentile requires universe-wide data for each historical day.
        Since we only have single-stock data here, we approximate by checking if the
        stock's 3m return was positive (outperforming a flat market) for all 10 days.
        This is a reasonable proxy since RS percentile >= 75th typically requires
        sustained positive relative performance.
        """
        if len(df) < 73:  # Need 10 days + 63 days for 3m return
            return 0.0

        if spy_df is None or len(spy_df) < 73:
            return 0.0

        days_at_75th_or_higher = 0

        for i in range(10):
            # Get data as of i days ago
            end_idx = -(i + 1)
            start_idx = -(i + 64)  # 63 trading days before end_idx

            if abs(start_idx) > len(df) or abs(start_idx) > len(spy_df):
                continue

            # Calculate 3m return as of i days ago
            stock_ret_3m = (df['close'].iloc[end_idx] / df['close'].iloc[start_idx] - 1)
            spy_ret_3m = (spy_df['close'].iloc[end_idx] / spy_df['close'].iloc[start_idx] - 1)

            # RS raw = 3m return (simplified - full calc would need 6m/12m too)
            rs_raw = stock_ret_3m

            # Approximation: RS >= 75th percentile typically means:
            # - Positive 3m return AND outperforming SPY
            # This is a heuristic since we can't calculate true percentile without universe data
            if rs_raw >= 0.05 and stock_ret_3m > spy_ret_3m:
                days_at_75th_or_higher += 1

        # Per spec: all 10 days must be >= 75th percentile for full score
        if days_at_75th_or_higher >= 10:
            return 1.0
        elif days_at_75th_or_higher >= 7:
            return 0.7
        elif days_at_75th_or_higher >= 5:
            return 0.5
        else:
            return 0.0

    def _calculate_sh(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Structure Health - per v5.0 spec (4.0 max).

        Components:
        1. EMA alignment (0-2.0 pts)
        2. 52-week high proximity (0-1.5 pts)
        3. Recent trend (0-0.5 pts)
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        score = 0.0

        # 1. EMA alignment (0-2.0 pts) per v5.0 spec
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)
        ema200 = ind.indicators.get('ema', {}).get('ema200', current_price)

        # Check full stack alignment
        full_stack = (current_price > ema21 > ema50 > ema200)
        price_above_ema50 = current_price > ema50
        ema50_above_ema200 = ema50 > ema200
        price_above_ema200 = current_price > ema200

        if full_stack:
            score += 2.0
        elif price_above_ema50 and ema50_above_ema200:
            score += 1.5
        elif price_above_ema200:
            score += 0.8
        # else: 0 points (price < EMA200)

        # 2. 52-week high proximity (0-1.5 pts) per v5.0 spec
        high_52w = df['high'].tail(252).max() if len(df) >= 252 else df['high'].max()
        distance_from_52w = (high_52w - current_price) / high_52w if high_52w > 0 else 1.0

        if distance_from_52w <= 0.05:
            score += 1.5
        elif distance_from_52w <= 0.10:
            # Linear interpolation: 5-10% = 1.0-1.5
            score += 1.0 + (0.10 - distance_from_52w) / 0.05 * 0.5
        elif distance_from_52w <= 0.15:
            # Linear interpolation: 10-15% = 0.5-1.0
            score += 0.5 + (0.15 - distance_from_52w) / 0.05 * 0.5
        # else: > 15% = 0 points

        # 3. Recent trend (0-0.5 pts)
        if len(df) >= 5:
            ret_5d = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1)
            if ret_5d > 0:
                score += 0.5

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
            stock_atr = ind.indicators.get('atr', {}).get('atr_14', 0)
            stock_atr_pct = stock_atr / current_price if current_price > 0 else 0

            spy_ind = TechnicalIndicators(spy_df)
            spy_atr = spy_ind.indicators.get('atr', {}).get('atr_14', 0)
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
        """Volume Confirmation - accumulation volume pattern."""
        accum_ratio = data.get('accum_ratio_15d', 1.0)

        score = 0.0

        # Accumulation ratio (0-2.0)
        if accum_ratio >= 1.5:
            score += 2.0
        elif accum_ratio >= 1.3:
            score += 1.5
        elif accum_ratio >= 1.1:
            score += 1.0

        # Recent volume vs average
        recent_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume > 0:
            vol_ratio = recent_volume / avg_volume
            if vol_ratio >= 1.5:
                score += 1.0
            elif vol_ratio >= 1.2:
                score += 0.5

        return min(2.0, score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """Calculate entry, stop, target for long position."""
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr14', current_price * 0.02)

        low_20d = df['low'].tail(20).min()

        entry = round(current_price, 2)
        stop = round(max(low_20d - 0.3 * atr, entry * 0.97), 2)
        risk = entry - stop
        target = round(entry + risk * 2.5, 2)

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
