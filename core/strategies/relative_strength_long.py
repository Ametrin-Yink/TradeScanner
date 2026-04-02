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

        # SH: Support Hold
        sh_score = self._calculate_sh(df)

        # CQ: Compression Quality
        cq_score = self._calculate_cq(df)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df, data)

        return [
            ScoringDimension(name='RD', score=rd_score, max_score=4.0, details={}),
            ScoringDimension(name='SH', score=sh_score, max_score=4.0, details={}),
            ScoringDimension(name='CQ', score=cq_score, max_score=4.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _calculate_rd(self, data: Dict, df: pd.DataFrame) -> float:
        """RS Divergence - RS percentile and trend."""
        rs_pct = data.get('rs_percentile', 50)

        score = 0.0

        # RS percentile (0-2.5)
        if rs_pct >= 95:
            score += 2.5
        elif rs_pct >= 90:
            score += 2.0
        elif rs_pct >= 85:
            score += 1.5
        elif rs_pct >= 80:
            score += 1.0

        # RS trend improvement (0-1.5)
        # Would need historical RS data for full implementation
        # For now, placeholder based on current percentile
        if rs_pct >= 90:
            score += 1.5
        elif rs_pct >= 85:
            score += 1.0

        return min(4.0, score)

    def _calculate_sh(self, df: pd.DataFrame) -> float:
        """Support Hold - holding support while market declines."""
        current_price = df['close'].iloc[-1]
        low_20d = df['low'].tail(20).min()

        score = 0.0

        # Near support (0-2.5)
        distance_from_low = (current_price - low_20d) / low_20d
        if distance_from_low < 0.01:
            score += 2.5
        elif distance_from_low < 0.03:
            score += 2.0
        elif distance_from_low < 0.05:
            score += 1.5
        elif distance_from_low < 0.08:
            score += 1.0

        # Price holding while SPY declining (0-1.5)
        # Check if price is flat/up while SPY is down
        spy_df = getattr(self, '_spy_df', None)
        if spy_df is not None and len(spy_df) >= 5:
            spy_return_5d = (spy_df['close'].iloc[-1] / spy_df['close'].iloc[-5] - 1)
            price_return_5d = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1)

            if spy_return_5d < -0.02 and price_return_5d > -0.01:
                score += 1.5
            elif spy_return_5d < -0.01 and price_return_5d > -0.01:
                score += 1.0

        return min(4.0, score)

    def _calculate_cq(self, df: pd.DataFrame) -> float:
        """Compression Quality - price tightening near support."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        score = 0.0

        # EMA compression (0-2.5)
        if current_price > ema8 * 0.99 and current_price < ema50 * 1.01:
            score += 2.5
        elif current_price > ema21 * 0.98 and current_price < ema50 * 1.02:
            score += 1.5
        elif current_price < ema50 * 1.05:
            score += 1.0

        # ADR declining (0-1.5)
        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < 0.02:
            score += 1.5
        elif adr_pct < 0.03:
            score += 1.0
        elif adr_pct < 0.04:
            score += 0.5

        return min(4.0, score)

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

        return min(3.0, score)

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
