"""Strategy G: EarningsGap - Post-earnings gap continuation (v7.0)."""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class EarningsGapStrategy(BaseStrategy):
    """
    Strategy G: EarningsGap v7.0
    Post-earnings gap continuation (long or short).
    """

    NAME = "EarningsGap"
    STRATEGY_TYPE = StrategyType.G
    DESCRIPTION = "EarningsGap v5.0 - post-earnings continuation"
    DIMENSIONS = ['GS', 'QC', 'TC', 'VC']
    DIRECTION = 'both'

    PARAMS = {
        'min_market_cap': 2_000_000_000,  # v7.0: $2B per docs (line 524)
        'min_gap_pct': 0.05,
        'max_days_post_earnings': 5,
        'min_dollar_volume_gap_day': 100e6,
        'min_rs_percentile': 50,
        'max_consolidation_days': 10,
        'min_price': 10.0,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for earnings gap candidates."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # v7.0: Market cap ≥ $2B (doc line 524)
        market_cap = data.get('market_cap', 0)
        if market_cap < self.PARAMS['min_market_cap']:
            logger.debug(f"EG_REJ: {symbol} - Market cap ${market_cap:,.0f} < ${self.PARAMS['min_market_cap']:,.0f}")
            return False

        # Check earnings timing with gap-size-dependent window
        days_to_earnings = data.get('days_to_earnings')
        gap_1d_pct = data.get('gap_1d_pct', 0)

        if days_to_earnings is None or days_to_earnings > 0:
            logger.debug(f"EG_REJ: {symbol} - not post-earnings: {days_to_earnings}")
            return False

        # v7.0: Gap-size-dependent eligibility window
        days_post_earnings = abs(days_to_earnings)
        gap_size = abs(gap_1d_pct)

        # Determine max days eligible by gap size
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

        # Check minimum price
        if current_price < self.PARAMS['min_price']:
            logger.debug(f"EG_REJ: {symbol} - price too low: ${current_price:.2f}")
            return False

        logger.debug(f"EG_PASS: {symbol} - gap {gap_1d_pct:.2%}, days {days_to_earnings}")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate GS, QC, TC, VC per v7.0 spec."""
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})

        # GS: Gap Strength
        gs_score = self._calculate_gs(data, df)

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

    def _calculate_gs(self, data: Dict, df: pd.DataFrame) -> float:
        """
        Gap Strength (GS) - 0-5.0 max per v7.0 spec.

        Components:
        1. Base Gap % score (1.0-3.0 pts)
        2. Gap type bonus (0-2.0 pts):
           - Beat/miss vs est: +1.0
           - Guidance change: +1.0
           - One-time event: +0.5
        """
        gap_pct = data.get('gap_1d_pct', 0)
        gap_direction = data.get('gap_direction', 'none')

        # Component 1: Base Gap % score per v7.0 spec
        # | Gap % | Long | Short |
        # |-------|------|-------|
        # | ≥10%  | 3.0  | 2.5   |
        # | 7-10% | 2.0-3.0 | 2.0-2.5 |
        # | 5-7%  | 1.0-2.0 | 1.5-2.0 |
        abs_gap_pct = abs(gap_pct)

        if gap_direction == 'up':  # Long
            if abs_gap_pct >= 0.10:
                base_score = 3.0
            elif abs_gap_pct >= 0.07:
                # 7-10%: 2.0-3.0 (interpolate)
                base_score = 2.0 + (abs_gap_pct - 0.07) / 0.03 * 1.0
            elif abs_gap_pct >= 0.05:
                # 5-7%: 1.0-2.0 (interpolate)
                base_score = 1.0 + (abs_gap_pct - 0.05) / 0.02 * 1.0
            else:
                base_score = 0.0
        else:  # Short (gap down)
            if abs_gap_pct >= 0.10:
                base_score = 2.5
            elif abs_gap_pct >= 0.07:
                # 7-10%: 2.0-2.5 (interpolate)
                base_score = 2.0 + (abs_gap_pct - 0.07) / 0.03 * 0.5
            elif abs_gap_pct >= 0.05:
                # 5-7%: 1.5-2.0 (interpolate)
                base_score = 1.5 + (abs_gap_pct - 0.05) / 0.02 * 0.5
            else:
                base_score = 0.0

        # Component 2: Earnings-specific bonuses (max 2.5 pts)
        # - Beat/miss vs est: +1.0
        # - Guidance change: +1.0
        # - One-time event: +0.5
        bonus_score = 0.0

        if data.get('earnings_beat', False):
            bonus_score += 1.0

        if data.get('guidance_change', False):
            bonus_score += 1.0

        if data.get('one_time_event', False):
            bonus_score += 0.5

        total = base_score + bonus_score
        return min(5.0, total)

    def _calculate_qc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Quality of Consolidation (QC) - 0-4.0 max per v7.0 spec.

        Components:
        1. Days since gap score (0-2.0 pts)
        2. Consolidation range score (0-1.5 pts)

        | Days since gap | Score |
        |----------------|-------|
        | 1-2 | 2.0 |
        | 3-4 | 1.5 |
        | 5+ | 0.5 |

        | Consolidation range | Score |
        |---------------------|-------|
        | <3% | 1.5 |
        | 3-5% | 1.0 |
        | 5-8% | 0.5 |
        | >8% | 0 |
        """
        # Component 1: Days since gap score
        days_post_earnings = data.get('days_post_earnings', 1)

        if days_post_earnings <= 2:
            days_score = 2.0
        elif days_post_earnings <= 4:
            days_score = 1.5
        else:
            days_score = 0.5

        # Component 2: Consolidation range score
        # Calculate the consolidation range (high - low) as % of gap open
        gap_pct = data.get('gap_1d_pct', 0)
        current_price = df['close'].iloc[-1]

        # Get consolidation high and low (excluding gap day)
        if len(df) > 1:
            consolidation_df = df.iloc[:-1]  # Exclude gap day
            consolidation_high = consolidation_df['high'].max()
            consolidation_low = consolidation_df['low'].min()
        else:
            consolidation_high = df['high'].iloc[-1]
            consolidation_low = df['low'].iloc[-1]

        # Calculate consolidation range as percentage
        gap_open = df['open'].iloc[-1]
        consolidation_range_pct = (consolidation_high - consolidation_low) / gap_open

        if consolidation_range_pct < 0.03:
            range_score = 1.5
        elif consolidation_range_pct < 0.05:
            range_score = 1.0
        elif consolidation_range_pct < 0.08:
            range_score = 0.5
        else:
            range_score = 0.0

        total = days_score + range_score
        return min(4.0, total)

    def _calculate_tc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Trend Context (TC) - 0-3.0 max per v7.0 spec.

        | Pre-earnings trend | Score |
        |--------------------|-------|
        | Aligned with gap direction | 2.0 |
        | Neutral | 1.0 |
        | Counter-trend | 0.5 |

        Sector alignment bonus: +1.0 if sector ETF confirms gap direction
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
                base_score = 2.0  # Aligned
            elif current_price > ema21:
                base_score = 1.5  # Partially aligned
            elif current_price > ema50:
                base_score = 1.0  # Neutral
            else:
                base_score = 0.5  # Counter-trend
        else:  # Down gap - want bearish alignment
            if current_price < ema8 < ema21:
                base_score = 2.0  # Aligned
            elif current_price < ema21:
                base_score = 1.5  # Partially aligned
            elif current_price < ema50:
                base_score = 1.0  # Neutral
            else:
                base_score = 0.5  # Counter-trend

        # Sector alignment bonus: +1.0 if sector ETF confirms gap direction
        sector_bonus = 0.0
        if data.get('sector_aligned', False):
            sector_bonus = 1.0

        total = base_score + sector_bonus
        return min(3.0, total)

    def _calculate_vc(self, df: pd.DataFrame, data: Dict) -> float:
        """
        Volume Confirmation (VC) - 0-3.0 max per v7.0 spec.

        | Gap day vol / avg20d | Score | Consolidation vol | Score |
        |----------------------|-------|-------------------|-------|
        | >5× | 2.0 | Below average | 1.0 |
        | 3-5× | 1.5 | Average | 0.5 |
        | 2-3× | 1.0 | Above average | 0 |
        | <2× | 0 | | |
        """
        # Gap day volume ratio - main component (max 2.0)
        gap_volume_ratio = data.get('gap_volume_ratio', 1.0)

        if gap_volume_ratio > 5.0:
            volume_score = 2.0
        elif gap_volume_ratio >= 3.0:
            volume_score = 1.5
        elif gap_volume_ratio >= 2.0:
            volume_score = 1.0
        else:
            volume_score = 0.0

        # Consolidation volume score (max 1.0)
        # Compare consolidation volume to average
        if len(df) > 1:
            consolidation_volume = df['volume'].iloc[:-1].mean()
            avg_volume = df['volume'].tail(20).mean()

            if avg_volume > 0:
                consolidation_vol_ratio = consolidation_volume / avg_volume

                if consolidation_vol_ratio < 0.8:  # Below average
                    consolidation_vol_score = 1.0
                elif consolidation_vol_ratio <= 1.2:  # Average
                    consolidation_vol_score = 0.5
                else:  # Above average
                    consolidation_vol_score = 0.0
            else:
                consolidation_vol_score = 0.5  # Default if can't calculate
        else:
            consolidation_vol_score = 0.5  # Default

        total = volume_score + consolidation_vol_score
        return min(3.0, total)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, target based on gap direction per v7.0 spec.

        **Entry (Long)**: Break of consolidation high; Vol≥1.5×avg20d
        **Entry (Short)**: Break of consolidation low; Vol≥1.5×avg20d
        **Stop (Long)**: max(consolidation_low−0.5×ATR, gap_open×0.95)
        **Stop (Short)**: min(consolidation_high+0.5×ATR, gap_open×1.05)
        **Target**: entry ± 2.5 × (entry − stop)
        """
        current_price = df['close'].iloc[-1]
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        gap_pct = data.get('gap_1d_pct', 0)

        ind = TechnicalIndicators(df)
        ind.calculate_all()
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # Calculate consolidation levels (excluding gap day)
        if len(df) > 1:
            consolidation_df = df.iloc[:-1]  # Exclude gap day
            consolidation_high = consolidation_df['high'].max()
            consolidation_low = consolidation_df['low'].min()
        else:
            consolidation_high = df['high'].iloc[-1]
            consolidation_low = df['low'].iloc[-1]

        gap_open = df['open'].iloc[-1]

        if gap_pct > 0:  # Long setup
            # Entry: break of consolidation high
            entry = round(consolidation_high, 2)

            # Stop: max(consolidation_low−0.5×ATR, gap_open×0.95)
            stop_consolidation = consolidation_low - 0.5 * atr
            stop_gap_buffer = gap_open * 0.95
            stop = round(max(stop_consolidation, stop_gap_buffer), 2)

            # Target: entry + 2.5 × (entry - stop)
            risk = entry - stop
            target = round(entry + risk * 2.5, 2)
        else:  # Short setup
            # Entry: break of consolidation low
            entry = round(consolidation_low, 2)

            # Stop: min(consolidation_high+0.5×ATR, gap_open×1.05)
            stop_consolidation = consolidation_high + 0.5 * atr
            stop_gap_buffer = gap_open * 1.05
            stop = round(min(stop_consolidation, stop_gap_buffer), 2)

            # Target: entry - 2.5 × (stop - entry)
            risk = stop - entry
            target = round(entry - risk * 2.5, 2)

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
