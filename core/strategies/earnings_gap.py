"""Strategy G: EarningsGap - Post-earnings gap continuation (v5.0)."""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class EarningsGapStrategy(BaseStrategy):
    """
    Strategy G: EarningsGap v5.0
    Post-earnings gap continuation (long or short).
    """

    NAME = "EarningsGap"
    STRATEGY_TYPE = StrategyType.G
    DESCRIPTION = "EarningsGap v5.0 - post-earnings continuation"
    DIMENSIONS = ['GS', 'QC', 'TC', 'VC']
    DIRECTION = 'both'

    PARAMS = {
        'min_gap_pct': 0.05,
        'max_days_post_earnings': 5,
        'min_dollar_volume_gap_day': 100e6,
        'min_rs_percentile': 50,
        'max_consolidation_days': 10,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for earnings gap candidates."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # Check earnings timing
        days_to_earnings = data.get('days_to_earnings')
        if days_to_earnings is None or days_to_earnings > 0 or days_to_earnings < -self.PARAMS['max_days_post_earnings']:
            logger.debug(f"EG_REJ: {symbol} - not in earnings window: {days_to_earnings}")
            return False

        # Check gap size
        gap_1d_pct = data.get('gap_1d_pct', 0)
        if abs(gap_1d_pct) < self.PARAMS['min_gap_pct']:
            logger.debug(f"EG_REJ: {symbol} - gap too small: {gap_1d_pct:.2%}")
            return False

        # Check RS percentile
        rs_pct = data.get('rs_percentile', 0)
        if rs_pct < self.PARAMS['min_rs_percentile']:
            logger.debug(f"EG_REJ: {symbol} - RS too low: {rs_pct}")
            return False

        # Check dollar volume
        current_price = df['close'].iloc[-1]
        avg_volume = df['volume'].tail(5).mean()
        dollar_volume = current_price * avg_volume
        if dollar_volume < self.PARAMS['min_dollar_volume_gap_day']:
            logger.debug(f"EG_REJ: {symbol} - dollar volume too low")
            return False

        logger.debug(f"EG_PASS: {symbol} - gap {gap_1d_pct:.2%}, days {days_to_earnings}")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate GS, QC, TC, VC per v5.0 spec."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # GS: Gap Size
        gs_score = self._calculate_gs(data)

        # QC: Quality of Continuation
        qc_score = self._calculate_qc(df, data)

        # TC: Trend Confirmation
        tc_score = self._calculate_tc(df, data)

        # VC: Volume Confirmation
        vc_score = self._calculate_vc(df, data)

        return [
            ScoringDimension(name='GS', score=gs_score, max_score=5.0, details={}),
            ScoringDimension(name='QC', score=qc_score, max_score=4.0, details={}),
            ScoringDimension(name='TC', score=tc_score, max_score=3.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _calculate_gs(self, data: Dict) -> float:
        """Gap Size - larger gaps score higher."""
        gap_pct = abs(data.get('gap_1d_pct', 0))

        if gap_pct >= 0.20:
            return 4.0
        elif gap_pct >= 0.15:
            return 3.5 + (gap_pct - 0.15) / 0.05 * 0.5
        elif gap_pct >= 0.10:
            return 2.5 + (gap_pct - 0.10) / 0.05 * 1.0
        elif gap_pct >= 0.05:
            return 1.0 + (gap_pct - 0.05) / 0.05 * 1.5
        return 0.0

    def _calculate_qc(self, df: pd.DataFrame, data: Dict) -> float:
        """Quality of Continuation - holding gap, low consolidation."""
        current_price = df['close'].iloc[-1]
        gap_pct = data.get('gap_1d_pct', 0)

        if gap_pct == 0:
            return 0.0

        # Determine gap zone
        prev_close = current_price / (1 + gap_pct)
        gap_open = current_price  # Approximation

        # For up gaps: holding above gap
        # For down gaps: holding below gap
        if gap_pct > 0:  # Up gap
            # Calculate gap fill percentage
            gap_low = prev_close
            gap_high = gap_open
            gap_range = gap_high - gap_low

            if gap_range > 0:
                fill_pct = (gap_high - current_price) / gap_range
                if fill_pct <= 0.25:
                    return 4.0
                elif fill_pct <= 0.50:
                    return 3.0
                elif fill_pct <= 0.75:
                    return 2.0
                else:
                    return 1.0
        else:  # Down gap
            gap_high = prev_close
            gap_low = gap_open
            gap_range = gap_high - gap_low

            if gap_range > 0:
                fill_pct = (current_price - gap_low) / gap_range
                if fill_pct <= 0.25:
                    return 4.0
                elif fill_pct <= 0.50:
                    return 3.0
                elif fill_pct <= 0.75:
                    return 2.0
                else:
                    return 1.0

        return 0.0

    def _calculate_tc(self, df: pd.DataFrame, data: Dict) -> float:
        """Trend Confirmation - EMA alignment in gap direction."""
        gap_pct = data.get('gap_1d_pct', 0)

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        score = 0.0

        if gap_pct > 0:  # Up gap - want bullish alignment
            if current_price > ema8 > ema21:
                score += 2.5
            elif current_price > ema21:
                score += 1.5
            elif current_price > ema50:
                score += 0.5

            # RS percentile bonus
            rs_pct = data.get('rs_percentile', 50)
            if rs_pct >= 80:
                score += 1.5
            elif rs_pct >= 60:
                score += 1.0
        else:  # Down gap - want bearish alignment
            if current_price < ema8 < ema21:
                score += 2.5
            elif current_price < ema21:
                score += 1.5
            elif current_price < ema50:
                score += 0.5

            # RS percentile (inverse - weak RS for shorts)
            rs_pct = data.get('rs_percentile', 50)
            if rs_pct <= 30:
                score += 1.5
            elif rs_pct <= 40:
                score += 1.0

        return min(4.0, score)

    def _calculate_vc(self, df: pd.DataFrame, data: Dict) -> float:
        """Volume Confirmation - elevated volume on gap day."""
        # Volume on gap day
        gap_volume_ratio = data.get('gap_volume_ratio', 1.0)

        score = 0.0

        if gap_volume_ratio >= 3.0:
            score += 2.0
        elif gap_volume_ratio >= 2.0:
            score += 1.5
        elif gap_volume_ratio >= 1.5:
            score += 1.0
        elif gap_volume_ratio >= 1.2:
            score += 0.5

        # Current volume vs average
        recent_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume > 0:
            current_ratio = recent_volume / avg_volume
            if current_ratio >= 1.5:
                score += 1.0
            elif current_ratio >= 1.0:
                score += 0.5

        return min(3.0, score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """Calculate entry, stop, target based on gap direction."""
        current_price = df['close'].iloc[-1]
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        gap_pct = data.get('gap_1d_pct', 0)

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        atr = ind.indicators.get('atr', {}).get('atr14', current_price * 0.02)

        entry = round(current_price, 2)

        if gap_pct > 0:  # Long continuation
            # Stop below gap zone
            prev_close = entry / (1 + gap_pct)
            stop = round(prev_close - 0.3 * atr, 2)
            risk = entry - stop
            target = round(entry + risk * 2.0, 2)
        else:  # Short continuation
            # Stop above gap zone
            prev_close = entry / (1 + gap_pct)
            stop = round(prev_close + 0.3 * atr, 2)
            risk = stop - entry
            target = round(entry - risk * 2.0, 2)

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
        gs = next((d for d in dimensions if d.name == 'GS'), None)
        qc = next((d for d in dimensions if d.name == 'QC'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        gap_pct = data.get('gap_1d_pct', 0)
        days_to_earnings = data.get('days_to_earnings', 0)

        direction = "Up" if gap_pct > 0 else "Down"

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"GS:{gs.score:.2f} QC:{qc.score:.2f} TC:{tc.score:.2f} VC:{vc.score:.2f}",
            f"{direction} gap {abs(gap_pct)*100:.1f}% | {abs(days_to_earnings)} days post-earnings",
            f"Gap holding quality: {qc.score:.1f}/4.0 | Volume confirm: {vc.score:.1f}/3.0"
        ]
