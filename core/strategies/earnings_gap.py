"""Strategy G: EarningsGap - Post-earnings gap continuation (v7.0)."""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class EarningsGapStrategy(BaseStrategy):
    """
    Strategy G: EarningsGap v7.0
    Post-earnings gap continuation (long or short).

    Based on Episodic Pivot methodology (Qullamaggie/Bonde):
    - Large gap on earnings with institutional volume participation
    - Tight consolidation after the gap
    - Entry on breakout of consolidation range
    """

    NAME = "EarningsGap"
    STRATEGY_TYPE = StrategyType.G
    DESCRIPTION = "EarningsGap v7.0 - post-earnings continuation"
    DIMENSIONS = ['GS', 'QC', 'TC', 'VC']
    DIRECTION = 'both'

    PARAMS = {
        'min_gap_pct': 0.05,
        'max_consolidation_days': 10,
        'min_gap_volume_ratio': 2.0,
        'min_rs_percentile_long': 50,
        'min_rs_percentile_short': 50,
    }

    def _find_gap_day_index(self, df: pd.DataFrame) -> int:
        """Find the most recent earnings gap day within lookback window.

        Returns the integer position (0-based from start of df) of the
        most recent day with a gap >= min_gap_pct. Falls back to the
        last day if no qualifying gap is found.
        """
        gaps = (df['open'] / df['close'].shift(1) - 1).abs()
        lookback = self.PARAMS.get('max_consolidation_days', 10) + 1
        recent = gaps.tail(lookback)
        threshold = self.PARAMS.get('min_gap_pct', 0.05)
        candidates = recent[recent >= threshold]
        if len(candidates) == 0:
            return len(df) - 1
        # Return integer position within df
        return df.index.get_loc(candidates.index[-1])

    def _get_consolidation_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Get DataFrame of all days AFTER the gap day."""
        gap_idx = self._find_gap_day_index(df)
        return df.iloc[gap_idx + 1:]

    def _get_gap_open(self, df: pd.DataFrame) -> float:
        """Get the open price of the actual gap day."""
        gap_idx = self._find_gap_day_index(df)
        return df['open'].iloc[gap_idx]

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for earnings gap candidates."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # Check earnings timing
        days_to_earnings = data.get('days_to_earnings')
        gap_1d_pct = data.get('gap_1d_pct', 0)

        if days_to_earnings is None or days_to_earnings >= 0:
            logger.debug(f"EG_REJ: {symbol} - not post-earnings: {days_to_earnings}")
            return False

        # v7.0: Gap-size-dependent eligibility window
        days_post_earnings = abs(days_to_earnings)
        gap_size = abs(gap_1d_pct)

        if gap_size >= 0.10:
            max_days = 5
        elif gap_size >= 0.07:
            max_days = 3
        else:
            max_days = 2

        if days_post_earnings > max_days or days_post_earnings < 1:
            logger.debug(f"EG_REJ: {symbol} - Outside eligibility window (gap={gap_size:.1%}, days={days_post_earnings}, max={max_days})")
            return False

        # Check gap size
        if abs(gap_1d_pct) < self.PARAMS['min_gap_pct']:
            logger.debug(f"EG_REJ: {symbol} - gap too small: {gap_1d_pct:.2%}")
            return False

        # Check gap-day volume (institutions must participate)
        gap_vol_ratio = data.get('gap_volume_ratio', 1.0)
        if gap_vol_ratio < self.PARAMS['min_gap_volume_ratio']:
            logger.debug(f"EG_REJ: {symbol} - gap volume too low: {gap_vol_ratio:.1f}x")
            return False

        # Check RS percentile (direction-dependent)
        rs_pct = data.get('rs_percentile', 0)
        gap_direction = data.get('gap_direction', 'none')

        if gap_direction == 'up':
            if rs_pct < self.PARAMS['min_rs_percentile_long']:
                logger.debug(f"EG_REJ: {symbol} - RS too low for long: {rs_pct}")
                return False
        elif gap_direction == 'down':
            if rs_pct > (100 - self.PARAMS['min_rs_percentile_short']):
                logger.debug(f"EG_REJ: {symbol} - RS too high for short: {rs_pct}")
                return False
        else:
            logger.debug(f"EG_REJ: {symbol} - no gap direction: {gap_direction}")
            return False

        logger.debug(f"EG_PASS: {symbol} - gap {gap_1d_pct:.2%}, days {days_to_earnings}, vol {gap_vol_ratio:.1f}x")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate GS, QC, TC, VC per v7.0 spec."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        gs_score = self._calculate_gs(data, df)
        qc_score = self._calculate_qc(df, data)
        tc_score = self._calculate_tc(df, data)
        vc_score = self._calculate_vc(df, data)

        return [
            ScoringDimension(name='GS', score=gs_score, max_score=5.0, details={}),
            ScoringDimension(name='QC', score=qc_score, max_score=4.0, details={}),
            ScoringDimension(name='TC', score=tc_score, max_score=3.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _calculate_gs(self, data: Dict, df: pd.DataFrame) -> float:
        """
        Gap Strength (GS) - 0-5.0 max.

        Components:
        1. Base Gap % score (1.0-3.0 pts) - long, slightly less for short
        2. Earnings surprise bonus (0-1.0 pts) - scaled if pct available
        3. Guidance change: +1.0
        4. One-time event: +0.5
        """
        gap_pct = data.get('gap_1d_pct', 0)
        gap_direction = data.get('gap_direction', 'none')
        abs_gap_pct = abs(gap_pct)

        # Component 1: Base Gap % score
        if gap_direction == 'up':  # Long
            if abs_gap_pct >= 0.10:
                base_score = 3.0
            elif abs_gap_pct >= 0.07:
                base_score = 2.0 + (abs_gap_pct - 0.07) / 0.03 * 1.0
            elif abs_gap_pct >= 0.05:
                base_score = 1.0 + (abs_gap_pct - 0.05) / 0.02 * 1.0
            else:
                base_score = 0.0
        else:  # Short (gap down)
            if abs_gap_pct >= 0.10:
                base_score = 2.5
            elif abs_gap_pct >= 0.07:
                base_score = 2.0 + (abs_gap_pct - 0.07) / 0.03 * 0.5
            elif abs_gap_pct >= 0.05:
                base_score = 1.5 + (abs_gap_pct - 0.05) / 0.02 * 0.5
            else:
                base_score = 0.0

        # Component 2: Earnings surprise magnitude bonus (direction-aware)
        surprise_pct = data.get('earnings_surprise_pct')
        if surprise_pct is not None:
            if gap_direction == 'up':
                # Longs rewarded for beats, not misses
                surprise_bonus = min(1.0, max(0, surprise_pct) / 0.20)
            else:
                # Shorts rewarded for misses, not beats
                surprise_bonus = min(1.0, max(0, -surprise_pct) / 0.20)
        elif data.get('earnings_beat', False):
            # Fallback: binary beat flag
            surprise_bonus = 1.0
        else:
            surprise_bonus = 0.0

        # Component 3: Guidance change
        guidance_bonus = 1.0 if data.get('guidance_change', False) else 0.0

        # Component 4: One-time event
        event_bonus = 0.5 if data.get('one_time_event', False) else 0.0

        total = base_score + surprise_bonus + guidance_bonus + event_bonus
        return min(5.0, total)

    def _calculate_qc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Quality of Consolidation (QC) - 0-4.0 max.

        Components:
        1. Consolidation range tightness (0-2.5 pts)
        2. Consolidation volume trend (0-1.5 pts)

        No days-score component: time decay is handled by the eligibility
        window filter, avoiding double-counting.

        | Consolidation range | Score |
        |---------------------|-------|
        | <3%                 | 2.5   |
        | 3-5%                | 1.5   |
        | 5-8%                | 0.8   |
        | >8%                 | 0     |

        | Consolidation vol vs avg20d | Score |
        |-----------------------------|-------|
        | <0.8x                       | 1.5   |
        | 0.8-1.2x                    | 0.8   |
        | >1.2x                       | 0     |
        """
        consolidation = self._get_consolidation_df(df)
        if len(consolidation) < 1:
            # Same-day: no consolidation yet, give partial credit
            return 1.5

        # Component 1: Range tightness
        consol_high = consolidation['high'].max()
        consol_low = consolidation['low'].min()
        gap_open = self._get_gap_open(df)
        consol_range_pct = (consol_high - consol_low) / gap_open if gap_open > 0 else 0

        if consol_range_pct < 0.03:
            range_score = 2.5
        elif consol_range_pct < 0.05:
            range_score = 1.5
        elif consol_range_pct < 0.08:
            range_score = 0.8
        else:
            range_score = 0.0

        # Component 2: Volume trend during consolidation
        consol_vol = consolidation['volume'].mean()
        avg_vol = df['volume'].tail(20).mean()
        vol_ratio = consol_vol / avg_vol if avg_vol > 0 else 1.0

        if vol_ratio < 0.8:
            vol_score = 1.5
        elif vol_ratio <= 1.2:
            vol_score = 0.8
        else:
            vol_score = 0.0

        total = range_score + vol_score
        return min(4.0, total)

    def _calculate_tc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Trend Context (TC) - 0-3.0 max.

        | Pre-earnings trend         | Score |
        |----------------------------|-------|
        | Aligned with gap direction | 2.0   |
        | Neutral                    | 1.0   |
        | Counter-trend              | 0.5   |

        Sector alignment bonus:
        - sector_aligned True: +1.0
        - sector_aligned False but data available: +0.0
        - sector data unavailable: +0.5 (neutral default)
        """
        gap_pct = data.get('gap_1d_pct', 0)

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        if gap_pct > 0:  # Up gap - want bullish alignment
            if current_price > ema8 > ema21:
                base_score = 2.0
            elif current_price > ema21:
                base_score = 1.5
            elif current_price > ema50:
                base_score = 1.0
            else:
                base_score = 0.5
        else:  # Down gap - want bearish alignment
            if current_price < ema8 < ema21:
                base_score = 2.0
            elif current_price < ema21:
                base_score = 1.5
            elif current_price < ema50:
                base_score = 1.0
            else:
                base_score = 0.5

        # Sector alignment bonus
        has_sector_data = 'sector_aligned' in data
        if data.get('sector_aligned', False):
            sector_bonus = 1.0
        elif has_sector_data:
            sector_bonus = 0.0  # Data available, but not aligned
        else:
            sector_bonus = 0.5  # No data, neutral default

        total = base_score + sector_bonus
        return min(3.0, total)

    def _calculate_vc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Volume Confirmation (VC) - 0-3.0 max.

        | Gap day vol / avg20d | Score | Consolidation vol | Score |
        |----------------------|-------|-------------------|-------|
        | >5x                  | 2.0   | Below average     | 1.0   |
        | 3-5x                 | 1.5   | Average           | 0.5   |
        | 2-3x                 | 1.0   | Above average     | 0     |
        | <2x                  | 0     |                   |       |
        """
        gap_volume_ratio = data.get('gap_volume_ratio', 1.0)

        if gap_volume_ratio > 5.0:
            volume_score = 2.0
        elif gap_volume_ratio >= 3.0:
            volume_score = 1.5
        elif gap_volume_ratio >= 2.0:
            volume_score = 1.0
        else:
            volume_score = 0.0

        # Consolidation volume score
        consolidation = self._get_consolidation_df(df)
        if len(consolidation) >= 1:
            consolidation_volume = consolidation['volume'].mean()
            avg_volume = df['volume'].tail(20).mean()

            if avg_volume > 0:
                consol_vol_ratio = consolidation_volume / avg_volume
                if consol_vol_ratio < 0.8:
                    consolidation_vol_score = 1.0
                elif consol_vol_ratio <= 1.2:
                    consolidation_vol_score = 0.5
                else:
                    consolidation_vol_score = 0.0
            else:
                consolidation_vol_score = 0.5
        else:
            consolidation_vol_score = 0.5

        total = volume_score + consolidation_vol_score
        return min(3.0, total)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, target based on gap direction.

        **Entry (Long)**: Break of consolidation high
        **Entry (Short)**: Break of consolidation low
        **Stop (Long)**: max(consolidation_low - 0.5*ATR, gap_open * 0.95)
        **Stop (Short)**: min(consolidation_high + 0.5*ATR, gap_open * 1.05)
        **Target**: entry +/- 2.5 * (entry - stop)
        """
        current_price = df['close'].iloc[-1]
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        gap_pct = data.get('gap_1d_pct', 0)

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        consolidation = self._get_consolidation_df(df)
        if len(consolidation) >= 1:
            consolidation_high = consolidation['high'].max()
            consolidation_low = consolidation['low'].min()
        else:
            consolidation_high = df['high'].iloc[-1]
            consolidation_low = df['low'].iloc[-1]

        gap_open = self._get_gap_open(df)

        if gap_pct > 0:  # Long setup
            entry = round(consolidation_high, 2)
            stop_consolidation = consolidation_low - 0.5 * atr
            stop_gap_buffer = gap_open * 0.95
            stop = round(max(stop_consolidation, stop_gap_buffer), 2)
            risk = entry - stop
            target = round(entry + risk * 2.5, 2)
        else:  # Short setup
            entry = round(consolidation_low, 2)
            stop_consolidation = consolidation_high + 0.5 * atr
            stop_gap_buffer = gap_open * 1.05
            stop = round(min(stop_consolidation, stop_gap_buffer), 2)
            risk = stop - entry
            target = round(entry - risk * 2.5, 2)

        return entry, stop, target, ""

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
        gap_vol_ratio = data.get('gap_volume_ratio', 1.0)

        direction = "Up" if gap_pct > 0 else "Down"

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"GS:{gs.score:.2f} QC:{qc.score:.2f} TC:{tc.score:.2f} VC:{vc.score:.2f}",
            f"{direction} gap {abs(gap_pct)*100:.1f}% | {abs(days_to_earnings)} days post-earnings | Vol {gap_vol_ratio:.1f}x",
            f"Consolidation quality: {qc.score:.1f}/4.0 | Volume confirm: {vc.score:.1f}/3.0"
        ]
