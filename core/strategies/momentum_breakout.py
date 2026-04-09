"""Strategy A1: MomentumBreakout - Confirmed breakout patterns."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType
from ..scoring_utils import safe_divide, validate_dataframe
from ..constants import SECTOR_ETFS

logger = logging.getLogger(__name__)


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Strategy A1: MomentumBreakout v5.0 - Confirmed breakout.
    - Multi-pattern CQ (VCP, HTF, flat, ascending, loose)
    - TC promoted to primary gate (RS >= 50th)
    - Bonus pool (+3 max, clamped to 15)
    """

    NAME = "MomentumBreakout"
    STRATEGY_TYPE = StrategyType.A1
    DESCRIPTION = "MomentumBreakout v5.0 - confirmed breakout"
    DIMENSIONS = ['TC', 'CQ', 'BS', 'VC']

    # Strategy Parameters
    PARAMS = {
        'min_dollar_volume': 50_000_000,      # $50M minimum
        'min_atr_pct': 0.015,                  # 1.5% minimum ATR
        'min_listing_days': 60,                # 60 days minimum
        'platform_lookback': (15, 60),         # 15-60 day platform (relaxed from 15-30)
        'rs_bonus_threshold': 0.85,            # RS>85 percentile bonus
        'platform_max_range': 0.12,            # <12% range
        'concentration_threshold': 0.50,       # 50% days in +/-2.5% band
        'volume_contraction_vs_platform': 0.70, # Last 5d < 70% of platform avg
        'breakout_pct': 0.02,                  # >2% above platform high
        'clv_threshold': 0.75,                 # CLV >= 0.75
        'breakout_volume_vs_20d_sma': 2.0,     # Volume > 2.0x 20d SMA
        'max_distance_from_50ema': 0.20,       # Within 20% of 50EMA
        'max_distance_from_52w_high': 0.10,    # Within 10% of 52-week high
        'energy_ratio_cap': 3.0,               # Cap energy ratio at 3.0
        'rs_percentile_min': 80,               # RS > 80 percentile (kept intentionally different from Momentum)
        'min_rs_percentile': 50,               # TC is primary gate
        'max_raw_score': 20.0,
        'bonus_max': 1.5,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter with TC primary gate and basic requirements.

        v7.0 Fix: VCP pattern is scored in CQ dimension, not a hard gate.
        Per spec: "CQ: VCP/flag/flat/ascending/loose pattern detection" (0-4 points)

        Hard gates:
        - RS >= 50th percentile (TC gate)
        - Price > EMA200
        - 3-month return >= -20%
        - Avg 20d volume >= 100K
        - Market cap >= $2B
        """
        # Validate DataFrame before processing
        if not validate_dataframe(df, min_rows=self.PARAMS.get('min_listing_days', 60)):
            logger.debug(f"MB_REJ: {symbol} - Invalid DataFrame")
            return False

        # TC hard gate - RS >= 50th percentile (must be done first)
        data = getattr(self, 'phase0_data', {}).get(symbol, {})
        rs_pct = data.get('rs_percentile', 0)

        if rs_pct < self.PARAMS['min_rs_percentile']:
            logger.debug(f"MB_REJ: {symbol} - RS {rs_pct:.1f} < {self.PARAMS['min_rs_percentile']} (TC gate)")
            return False

        if len(df) < self.PARAMS['min_listing_days']:
            logger.debug(f"MB_REJ: {symbol} - Insufficient data: {len(df)} < {self.PARAMS['min_listing_days']}")
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Layer 0: Tier 1 Pre-Filters (from documentation)
        # Market cap >= $2B
        stock_info = self.db.get_stock_info_full(symbol) if self.db else None
        if stock_info:
            market_cap = stock_info.get('market_cap', 0)
            if market_cap < 2e9:
                logger.debug(f"MB_REJ: {symbol} - Market cap {market_cap:.0f} < $2B")
                return False

        # Price > EMA200
        ema200 = ind.indicators.get('ema', {}).get('ema200')
        if ema200 is None or current_price <= ema200:
            if ema200 is None:
                logger.debug(f"MB_REJ: {symbol} - EMA200 is None")
            else:
                logger.debug(f"MB_REJ: {symbol} - Price {current_price:.2f} <= EMA200 {ema200:.2f}")
            return False

        # 3-month return >= -20%
        ret_3m = data.get('ret_3m')
        if ret_3m is None:
            # Fallback calculation if not in phase0_data
            if len(df) >= 63:
                price_3m = df['close'].iloc[-63]
                ret_3m = (current_price - price_3m) / price_3m if price_3m > 0 else 0
            else:
                ret_3m = 0
        if ret_3m < -0.20:
            logger.debug(f"MB_REJ: {symbol} - 3m return {ret_3m:.2%} < -20%")
            return False

        # Avg 20d volume >= 100K
        avg_volume_20d = df['volume'].tail(20).mean()
        if avg_volume_20d < 100_000:
            logger.debug(f"MB_REJ: {symbol} - Avg 20d volume {avg_volume_20d:.0f} < 100K")
            return False

        # v7.0 Fix: VCP pattern is NOT a hard gate - all patterns valid, scored in CQ
        # Pattern detection happens in calculate_dimensions() for CQ scoring

        logger.debug(f"MB_PASS: {symbol} - Basic filters passed (VCP scored in CQ)")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 4-dimensional scoring with multi-pattern CQ.

        v7.0 Fix: Handle None platform gracefully - use 60d range as fallback.
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Detect VCP platform - may return None if no valid pattern
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        # v7.0 Fix: Create fallback platform data if detection failed
        if not platform:
            high_60d = df['high'].tail(60).max()
            low_60d = df['low'].tail(60).min()
            platform = {
                'is_valid': True,
                'platform_high': high_60d,
                'platform_low': low_60d,
                'platform_range_pct': (high_60d - low_60d) / high_60d if high_60d > 0 else 0.15,
                'platform_days': 60,
                'concentration_ratio': 0.30,
                'volume_contraction_ratio': 1.0,
                'contraction_quality': 0.3,
            }

        platform_high = platform['platform_high']
        breakout_pct = (current_price - platform_high) / platform_high
        platform_range_pct = platform['platform_range_pct']
        clv = ind.calculate_clv()
        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        ema50_distance = ind.distance_from_ema50()
        metrics_52w = ind.calculate_52w_metrics()

        dimensions = []

        # Dimension 1: Trend Context (TC) - PROMOTED to first position
        tc_score = self._calculate_tc(ema50_distance, metrics_52w, clv, df, symbol)
        dimensions.append(ScoringDimension(
            name='TC',
            score=tc_score,
            max_score=5.0,
            details={
                'rs_percentile': getattr(self, 'phase0_data', {}).get(symbol, {}).get('rs_percentile', 50),
                'distance_from_52w_high': metrics_52w['distance_from_high'],
                'ema50_distance': ema50_distance['distance_pct'],
            }
        ))

        # Dimension 2: Consolidation Quality (CQ) - Multi-pattern support
        pattern_type, cq_score = self._detect_consolidation_pattern(ind, df, platform)
        dimensions.append(ScoringDimension(
            name='CQ',
            score=cq_score,
            max_score=4.0,
            details={
                'pattern_type': pattern_type,
                'platform_range_pct': platform_range_pct,
                'concentration_ratio': platform['concentration_ratio'],
                'contraction_quality': platform.get('contraction_quality', 0.5)
            }
        ))

        # Dimension 3: Breakout Strength (BS)
        # v7.0 Fix: Pass volume_ratio for direct volume scoring
        bs_score = self._calculate_bs(breakout_pct, platform_range_pct, volume_ratio)
        dimensions.append(ScoringDimension(
            name='BS',
            score=bs_score,
            max_score=4.0,
            details={
                'breakout_pct': breakout_pct,
                'volume_ratio': volume_ratio
            }
        ))

        # Dimension 4: Volume Confirmation (VC)
        vc_score = self._calculate_vc(platform, volume_ratio, clv)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=4.0,
            details={
                'volume_ratio': volume_ratio,
                'volume_contraction': platform['volume_contraction_ratio'],
                'clv': clv
            }
        ))

        return dimensions

    def _detect_consolidation_pattern(self, ind: TechnicalIndicators, df: pd.DataFrame, platform: Dict) -> Tuple[str, float]:
        """
        Multi-pattern CQ detection: VCP, HTF, flat base, ascending base, loose base.
        Returns (pattern_type, score) tuple.

        v7.0 Fix: Aligned with documentation requirements.
        - VCP: 15-60d, range<12%, >50% days ±2.5%, vol<70%, ≥2 waves
        - High tight flag: +30% in ≤8w, pullback 8-30%, flag 2-6w
        - Flat base: Range<15%, EMA21 slope<0.3×ATR/5d, 3-15w
        - Ascending: ≥3 higher lows, range 10-25%, 4-12w
        - Loose: Range<20%, ≥10d
        """
        if not platform or not platform.get('is_valid'):
            return 'none', 0.0

        platform_range_pct = platform['platform_range_pct']
        concentration_ratio = platform['concentration_ratio']
        contraction_quality = platform.get('contraction_quality', 0.5)
        volume_contraction = platform.get('volume_contraction_ratio', 1.0)
        platform_days = platform['platform_days']

        # Calculate trend within platform (for ascending/flat detection)
        platform_start = -platform_days
        platform_end = 0
        if len(df) < platform_days:
            return 'loose', max(0.0, min(2.5, concentration_ratio * 3.0))

        platform_data = df.iloc[platform_start:platform_end]
        if len(platform_data) < 10:
            return 'loose', 0.5

        # Linear regression slope
        x = np.arange(len(platform_data))
        y = platform_data['close'].values
        slope = np.polyfit(x, y, 1)[0] if len(x) > 1 else 0
        slope_pct = slope / np.mean(y) if np.mean(y) > 0 else 0

        # Calculate ATR for slope comparison
        atr = ind.indicators.get('atr', {}).get('atr', y.mean() * 0.02)
        atr_5d = atr * 5  # Approximate 5-day ATR

        # Count higher lows for ascending pattern
        higher_lows = 0
        for i in range(5, len(platform_data)):
            if platform_data['low'].iloc[i] > platform_data['low'].iloc[i-5]:
                higher_lows += 1

        # Count waves for VCP (using the method from PreBreakoutCompressionStrategy)
        wave_count = self._count_contraction_waves(df, platform)

        # Pattern Detection Logic (first match wins)
        pattern_type = 'loose'
        base_score = 2.5

        # VCP: 15-60d, range<12%, >50% days ±2.5%, vol<70%, ≥2 waves
        if (15 <= platform_days <= 60 and
            platform_range_pct < 0.12 and
            concentration_ratio > 0.50 and
            volume_contraction < 0.70 and
            wave_count >= 2):
            pattern_type = 'VCP'
            base_score = 3.0  # Base score, can reach 4.0 with bonuses

        # High Tight Flag: Prior +30% in ≤8w, pullback 8-30%, flag 2-6w
        elif self._is_high_tight_flag(df, platform_data, platform_days):
            pattern_type = 'high_tight_flag'
            base_score = 2.2  # 0.61-0.72 × 3.0 ≈ 1.8-2.2

        # Flat Base: Range<15%, EMA21 slope<0.3×ATR/5d, 3-15w (21-105d)
        elif (21 <= platform_days <= 105 and
              platform_range_pct < 0.15 and
              abs(slope_pct) < (0.3 * atr_5d / y.mean()) if y.mean() > 0 else abs(slope_pct) < 0.001):
            pattern_type = 'flat_base'
            base_score = 2.0  # 0.55-0.75 × 3.0 ≈ 1.65-2.25

        # Ascending: ≥3 higher lows, range 10-25%, 4-12w (28-84d)
        elif (28 <= platform_days <= 84 and
              higher_lows >= 3 and
              0.10 <= platform_range_pct <= 0.25):
            pattern_type = 'ascending'
            base_score = 2.2  # 0.62 × 3.0 ≈ 1.86

        # Loose: Range<20%, ≥10d
        elif platform_range_pct < 0.20 and platform_days >= 10:
            pattern_type = 'loose'
            base_score = 0.45  # 0.15-0.40 × 3.0 ≈ 0.45-1.2

        # Apply duration bonus per documentation
        # 3-10w = 1.0, 2-3w = 0.4-1.0, 10-15w = 0.5-1.0, <2w = 0.2, >15w = 0.3
        duration_bonus = 0.0
        platform_weeks = platform_days / 7
        if 3 <= platform_weeks <= 10:
            duration_bonus = 1.0
        elif 2 <= platform_weeks < 3:
            duration_bonus = 0.4 + (platform_weeks - 2) * 0.6  # 0.4-1.0
        elif 10 < platform_weeks <= 15:
            duration_bonus = 1.0 - (platform_weeks - 10) * 0.1  # 1.0-0.5
        elif platform_weeks < 2:
            duration_bonus = 0.2
        elif platform_weeks > 15:
            duration_bonus = 0.3

        # Calculate CQ score: cq_base = pattern_score × 3.0, then add duration_bonus
        cq_base = base_score
        final_score = cq_base + duration_bonus

        # Additional quality bonuses
        # Tightness bonus
        if platform_range_pct < 0.08:
            final_score += 0.5
        elif platform_range_pct < 0.04:
            final_score += 0.8

        # Concentration bonus
        if concentration_ratio > 0.70:
            final_score += 0.3
        elif concentration_ratio > 0.60:
            final_score += 0.2

        # Wave count bonus for VCP
        if pattern_type == 'VCP' and wave_count >= 3:
            final_score += 0.5

        return pattern_type, round(min(4.0, final_score), 2)

    def _is_high_tight_flag(self, df: pd.DataFrame, platform_data: pd.DataFrame, platform_days: int) -> bool:
        """
        Check if pattern is a high tight flag.

        Requirements:
        - Prior advance: +30% in ≤8 weeks (56 days)
        - Pullback: 8-30% from high
        - Flag duration: 2-6 weeks (14-42 days)
        """
        if len(df) < 100:
            return False

        # Find the high before the flag
        flag_high = platform_data['high'].max()
        flag_low = platform_data['low'].min()

        # Calculate pullback from high
        pullback = (flag_high - flag_low) / flag_high

        # Check pullback range (8-30%)
        if not (0.08 <= pullback <= 0.30):
            return False

        # Check flag duration (2-6 weeks = 14-42 days)
        if not (14 <= platform_days <= 42):
            return False

        # Check prior advance (+30% in ≤8 weeks before flag)
        pre_flag_start = -platform_days - 56
        pre_flag_end = -platform_days
        if len(df) < abs(pre_flag_start):
            return False

        pre_flag_data = df.iloc[pre_flag_start:pre_flag_end]
        if len(pre_flag_data) < 10:
            return False

        # Calculate advance from start of period to flag start
        advance_start = pre_flag_data['close'].iloc[0]
        advance_end = pre_flag_data['close'].iloc[-1]
        advance_pct = (advance_end - advance_start) / advance_start if advance_start > 0 else 0

        return advance_pct >= 0.30

    def _count_contraction_waves(self, df: pd.DataFrame, platform: Dict) -> int:
        """
        Count contraction waves in platform period.

        A wave = local peak (swing high) where subsequent peak < prior peak.
        Ideal VCP shows 3+ progressively smaller waves.

        Args:
            df: DataFrame with OHLCV data
            platform: Platform detection result dict

        Returns:
            Number of contraction waves detected (0-5 typical)
        """
        platform_days = platform.get('platform_days', 30)
        if len(df) < platform_days:
            return 0

        platform_df = df.tail(platform_days).reset_index(drop=True)

        # Find local peaks (swing highs) using 5-day window
        peaks = []
        for i in range(5, len(platform_df) - 5):
            window_highs = platform_df['high'].iloc[i-5:i+6]
            if platform_df['high'].iloc[i] == window_highs.max():
                peaks.append(platform_df['high'].iloc[i])

        # Count waves: each successive lower high = 1 contraction wave
        waves = 0
        for i in range(1, len(peaks)):
            if peaks[i] < peaks[i-1]:
                waves += 1

        return waves

    # Sector ETF mapping for sector leadership bonus
    # Sector ETF mapping for sector leadership bonus (shared constant)

    def _calculate_bonus(self, dimensions: List[ScoringDimension], df: pd.DataFrame, symbol: str) -> float:
        """
        Calculate bonus points for A1 (confirmed breakout).
        Max bonus is capped at 1.5 (VCP structure bonus moved to A2's CP dimension).

        Bonus pool:
        - Sector leadership: 0.5 max (sector ETF RS >= 80th AND sector ETF > EMA50)
        - Earnings catalyst: 0.5 max (7-21 days to earnings)
        - Accumulation divergence: 0.5 max (OBV rising while price flat)
        """
        bonus = 0.0
        ind = TechnicalIndicators(df)

        # NOTE: VCP structure bonus (2.0 max) removed for A1 - this is now A2's primary value
        # A1 focuses on confirmed breakouts, A2 focuses on compression setups

        # Bonus 1: Sector leadership (0.5 max)
        sector_bonus = self._calculate_sector_leadership_bonus(symbol)
        bonus += sector_bonus

        # Bonus 2: Earnings catalyst (0.5 max)
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        days_to_earnings = data.get('days_to_earnings')
        if days_to_earnings is not None and 7 <= days_to_earnings <= 21:
            bonus += 0.5

        # Bonus 3: Accumulation divergence (0.5 max)
        accum_bonus = self._calculate_accumulation_divergence(df)
        bonus += accum_bonus

        return min(bonus, self.PARAMS['bonus_max'])

    def _calculate_sector_leadership_bonus(self, symbol: str) -> float:
        """
        Calculate sector leadership bonus (0.5 max).
        Requires: Sector ETF RS >= 80th percentile AND Sector ETF > EMA50.
        """
        try:
            # Get stock's sector from database
            stock_info = self.db.get_stock_info_full(symbol)
            if not stock_info:
                return 0.0

            sector = stock_info.get('sector', '')
            if not sector or sector not in self.SECTOR_ETFS:
                return 0.0

            etf_symbol = self.SECTOR_ETFS[sector]

            # Get ETF data from market_data cache
            etf_df = self.market_data.get(etf_symbol)
            if etf_df is None or len(etf_df) < 50:
                return 0.0

            # Check ETF > EMA50
            ema50 = etf_df['close'].ewm(span=50).mean().iloc[-1]
            current_price = etf_df['close'].iloc[-1]
            if current_price <= ema50:
                return 0.0

            # Check ETF RS >= 80th percentile
            if len(etf_df) >= 252:
                price_3m = etf_df['close'].iloc[-63] if len(etf_df) >= 63 else etf_df['close'].iloc[0]
                price_6m = etf_df['close'].iloc[-126] if len(etf_df) >= 126 else etf_df['close'].iloc[0]
                price_12m = etf_df['close'].iloc[-252] if len(etf_df) >= 252 else etf_df['close'].iloc[0]

                ret_3m = (current_price - price_3m) / price_3m
                ret_6m = (current_price - price_6m) / price_6m
                ret_12m = (current_price - price_12m) / price_12m

                rs_score = 0.4 * ret_3m + 0.3 * ret_6m + 0.3 * ret_12m

                # RS >= 80th percentile threshold (approximate using RS score > 0.3)
                if rs_score > 0.3:
                    return 0.5

            return 0.0
        except Exception:
            return 0.0

    def _calculate_accumulation_divergence(self, df: pd.DataFrame) -> float:
        """
        Calculate accumulation divergence bonus (0.5 max).
        OBV rising while price flat during base (linear regression divergence).
        """
        try:
            if len(df) < 30:
                return 0.0

            # Calculate OBV (On-Balance Volume)
            obv = [0]
            for i in range(1, len(df)):
                if df['close'].iloc[i] > df['close'].iloc[i-1]:
                    obv.append(obv[-1] + df['volume'].iloc[i])
                elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                    obv.append(obv[-1] - df['volume'].iloc[i])
                else:
                    obv.append(obv[-1])

            # Use last 20 days for base period
            base_period = min(20, len(df) // 2)
            if base_period < 10:
                return 0.0

            price_values = df['close'].tail(base_period).values
            obv_values = obv[-base_period:]

            # Linear regression on price (x = time, y = price)
            x = np.arange(base_period)
            price_slope, _ = np.polyfit(x, price_values, 1)

            # Linear regression on OBV
            obv_slope, _ = np.polyfit(x, obv_values, 1)

            # Normalize OBV slope by average volume for comparison
            avg_volume = df['volume'].tail(base_period).mean()
            normalized_obv_slope = obv_slope / avg_volume if avg_volume > 0 else 0

            # Divergence: OBV rising (positive slope) while price relatively flat (small slope)
            price_change_pct = abs(price_slope) / np.mean(price_values) if np.mean(price_values) > 0 else 0
            obv_rising = normalized_obv_slope > 0.01  # OBV has meaningful upward trend

            # Price is "flat" if change is less than 5% over the period
            price_flat = price_change_pct < 0.05

            if obv_rising and price_flat:
                return 0.5

            return 0.0
        except Exception:
            return 0.0

    def calculate_score(self, dimensions: List[ScoringDimension], df: pd.DataFrame = None, symbol: str = None) -> Tuple[float, str]:
        """
        Calculate final score with bonus pool, normalized to 0-15 scale.
        A1 max raw score: 18.5 (5+4+4+4+1.5 bonus) -> normalized to 0-15 scale.
        """
        from .base_strategy import normalize_score

        base_score = sum(d.score for d in dimensions)

        # Calculate bonus if df and symbol available
        bonus = 0.0
        if df is not None and symbol is not None:
            bonus = self._calculate_bonus(dimensions, df, symbol)

        raw_score = base_score + bonus

        # Normalize to 0-15 scale using STRATEGY_MAX_SCORES
        normalized_score = normalize_score(raw_score, self.NAME)

        # Cap at 15.0
        final_score = min(normalized_score, 15.0)

        # Determine tier based on final score
        if final_score >= self.TIER_S_MIN:
            tier = 'S'
        elif final_score >= self.TIER_A_MIN:
            tier = 'A'
        elif final_score >= self.TIER_B_MIN:
            tier = 'B'
        else:
            tier = 'C'

        logger.debug(f"MB Score: base={base_score:.1f} bonus={bonus:.1f} raw={raw_score:.1f} norm={normalized_score:.2f} final={final_score:.2f} tier={tier}")

        return final_score, tier

    def _calculate_bs(self, breakout_pct: float, platform_range_pct: float, volume_ratio: float = None) -> float:
        """
        Breakout Strength dimension (0-4.0).

        v7.0 Fix: Use direct volume ratio scoring instead of energy_ratio.

        Components:
        1. Breakout % above pivot (0-2.5 pts)
        2. Volume / avg20d (0-1.5 pts) - direct volume ratio, not energy_ratio

        Documentation table:
        | Breakout % | Score | Vol/avg20d | Score |
        |-----------|-------|------------|-------|
        | ≥5%       | 2.5   | ≥3.0×      | 1.5   |
        | 3-5%      | 2.0-2.5 | 2-3×    | 1.0-1.5 |
        | 2-3%      | 1.5-2.0 | 1.5-2×  | 0.5-1.0 |
        | 1-2%      | 0.5-1.5 | 1-1.5×  | 0-0.5 |
        | <1%       | 0-0.5 | <1×       | 0     |
        """
        bs_score = 0.0

        # Component 1: Breakout % above pivot (0-2.5 pts)
        if breakout_pct >= 0.05:
            bs_score += 2.5
        elif breakout_pct >= 0.03:
            # 3%–5%: 2.0–2.5 (interpolate)
            bs_score += 2.0 + (breakout_pct - 0.03) / 0.02 * 0.5
        elif breakout_pct >= 0.02:
            # 2%–3%: 1.5–2.0 (interpolate)
            bs_score += 1.5 + (breakout_pct - 0.02) / 0.01 * 0.5
        elif breakout_pct >= 0.01:
            # 1%–2%: 0.5–1.5 (interpolate)
            bs_score += 0.5 + (breakout_pct - 0.01) / 0.01 * 1.0
        elif breakout_pct > 0:
            # < 1%: 0–0.5 (interpolate)
            bs_score += breakout_pct / 0.01 * 0.5

        # Component 2: Volume ratio scoring (0-1.5 pts)
        # v7.0 Fix: Use direct volume ratio instead of energy_ratio
        vol_ratio = volume_ratio if volume_ratio is not None else 1.0

        if vol_ratio >= 3.0:
            bs_score += 1.5
        elif vol_ratio >= 2.0:
            # 2-3x: 1.0-1.5 (interpolate)
            bs_score += 1.0 + (vol_ratio - 2.0) * 0.5
        elif vol_ratio >= 1.5:
            # 1.5-2x: 0.5-1.0 (interpolate)
            bs_score += 0.5 + (vol_ratio - 1.5) * 1.0
        elif vol_ratio >= 1.0:
            # 1-1.5x: 0-0.5 (interpolate)
            bs_score += (vol_ratio - 1.0) * 1.0
        # <1x: 0 points

        return round(min(4.0, bs_score), 2)

    def _calculate_vc(self, platform: Dict, volume_ratio: float, clv: float) -> float:
        """
        Volume Confirmation dimension (0-4.0) - v5.0 aligned with documentation.
        Includes CLV component (0-0.5 pts) moved from TC.
        """
        vc_score = 0.0
        vol_contract = platform['volume_contraction_ratio']

        # 1. Base volume behavior - last 5d of base / avg20d before base (0-2.0 pts)
        if vol_contract < 0.50:
            vc_score += 2.0
        elif vol_contract < 0.65:
            vc_score += 1.5 + (0.65 - vol_contract) / 0.15 * 0.5  # 1.5-2.0
        elif vol_contract < 0.80:
            vc_score += 0.8 + (0.80 - vol_contract) / 0.15 * 0.7  # 0.8-1.5
        elif vol_contract < 1.00:
            vc_score += 0.2 + (1.00 - vol_contract) / 0.20 * 0.6  # 0.2-0.8
        else:
            # v7.0 Fix I-01: Active-base stocks get neutral minimum (0.2), not penalty
            vc_score += 0.2

        # 2. Breakout volume - breakout day / avg20d (0-1.5 pts)
        if volume_ratio >= 3.0:
            vc_score += 1.5
        elif volume_ratio >= 2.0:
            vc_score += 1.0 + (volume_ratio - 2.0) / 1.0 * 0.5  # 1.0-1.5
        elif volume_ratio >= 1.5:
            vc_score += 0.5 + (volume_ratio - 1.5) / 0.5 * 0.5  # 0.5-1.0
        elif volume_ratio >= 1.0:
            vc_score += 0 + (volume_ratio - 1.0) / 0.5 * 0.5  # 0-0.5
        else:
            vc_score += 0  # < 1.0x

        # 3. CLV on breakout bar (0-0.5 pts) - MOVED FROM TC
        if clv >= 0.85:
            vc_score += 0.5
        elif clv >= 0.65:
            vc_score += 0 + (clv - 0.65) / 0.20 * 0.5  # 0-0.5
        # < 0.65: 0 points

        return round(min(4.0, vc_score), 2)

    def _calculate_tc(self, ema50_dist: Dict, metrics_52w: Dict, clv: float, df: pd.DataFrame, symbol: str) -> float:
        """
        Trend Context dimension (0-5) - v5.0 aligned with documentation.
        """
        tc_score = 0.0
        current_price = df['close'].iloc[-1]
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # 1. RS Strength (0-2.0 pts) - percentile-based from phase0_data
        data = getattr(self, 'phase0_data', {}).get(symbol, {})
        rs_pct = data.get('rs_percentile', 50)

        if rs_pct >= 90:
            tc_score += 2.0
        elif rs_pct >= 75:
            tc_score += 1.5 + (rs_pct - 75) / 15 * 0.5  # 1.5-2.0
        elif rs_pct >= 60:
            tc_score += 1.0 + (rs_pct - 60) / 15 * 0.5  # 1.0-1.5
        elif rs_pct >= 50:
            tc_score += 0.5 + (rs_pct - 50) / 10 * 0.5  # 0.5-1.0
        # else: 0, but this shouldn't happen due to pre-filter

        # 2. EMA Structure (0-2.0 pts) - 3 conditions from documentation
        ema50 = ind.indicators.get('ema', {}).get('ema50')
        ema200 = ind.indicators.get('ema', {}).get('ema200')

        if ema50 and current_price > ema50 * 1.05:
            tc_score += 1.0  # Price > EMA50 * 1.05
        if ema200 and current_price > ema200:
            tc_score += 0.5  # Price > EMA200
        if ema50 and ema200 and ema50 > ema200:
            tc_score += 0.5  # EMA50 > EMA200

        # 3. 52-Week High Proximity (0-1.0 pts) - per documentation
        dist_52w = metrics_52w['distance_from_high']
        if dist_52w <= 0.05:  # <= 5%
            tc_score += 1.0
        elif dist_52w <= 0.15:  # 5-15%
            tc_score += 1.0 - (dist_52w - 0.05) / 0.10  # 1.0-0.0 linear
        # > 15%: 0 points

        return round(min(5.0, tc_score), 2)

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, and target prices.

        v7.0 Fix: Validate A1 entry conditions:
        - Price > pivot × 1.01
        - Volume > 1.5× avg20d
        - CLV ≥ 0.65
        """
        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        current_price = df['close'].iloc[-1]
        platform_low = platform['platform_low'] if platform else df['low'].tail(20).min()
        platform_high = platform['platform_high'] if platform else df['high'].tail(20).max()
        pivot = platform_high

        # Get pattern type from CQ dimension
        cq_dim = next((d for d in dimensions if d.name == 'CQ'), None)
        pattern_type = cq_dim.details.get('pattern_type', 'vcp') if cq_dim else 'vcp'

        # Get volume and CLV from VC dimension
        vc_dim = next((d for d in dimensions if d.name == 'VC'), None)
        volume_ratio = vc_dim.details.get('volume_ratio', 0) if vc_dim else 0
        clv = vc_dim.details.get('clv', 0) if vc_dim else 0

        # v7.0 Fix: Validate entry conditions
        # Entry (A1): Price>pivot×1.01, Vol>1.5×, CLV≥0.65
        entry_conditions_met = True

        # Check price > pivot × 1.01
        if current_price < pivot * 1.01:
            entry_conditions_met = False
            logger.debug(f"MB_ENTRY_REJ: {symbol} - Price {current_price:.2f} < pivot×1.01 {pivot*1.01:.2f}")

        # Check volume > 1.5× avg20d
        if volume_ratio < 1.5:
            entry_conditions_met = False
            logger.debug(f"MB_ENTRY_REJ: {symbol} - Volume ratio {volume_ratio:.2f} < 1.5×")

        # Check CLV ≥ 0.65
        if clv < 0.65:
            entry_conditions_met = False
            logger.debug(f"MB_ENTRY_REJ: {symbol} - CLV {clv:.2f} < 0.65")

        # If entry conditions not met, return invalid entry
        if not entry_conditions_met:
            # Return current price as entry but with stop at entry (no trade)
            entry = round(current_price, 2)
            stop = entry  # No valid stop, indicates invalid setup
            target = entry  # No valid target
            return entry, stop, target

        entry = round(current_price, 2)

        # Pattern-specific stop loss calculation
        if pattern_type in ('vcp', 'flat_base', 'ascending'):
            stop = platform_low * 0.98
        elif pattern_type == 'high_tight_flag':
            # High tight flag: use flag low (platform low) with 1.5% buffer
            stop = platform_low * 0.985
        else:  # loose base or unknown
            atr = ind.indicators.get('atr', {}).get('atr_14', entry * 0.02)
            stop = entry - 1.5 * atr

        # Apply 8% stop floor: never more than 8% below entry
        stop = max(stop, entry * 0.92)
        stop = round(stop, 2)

        risk = entry - stop

        # Target: 3R baseline, 4R for S-tier
        if tier == 'S':
            target = round(entry + risk * 4, 2)  # 4R for S-tier
        else:
            target = round(entry + risk * 3, 2)  # 3R baseline

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
        tc = next((d for d in dimensions if d.name == 'TC'), None)
        cq = next((d for d in dimensions if d.name == 'CQ'), None)
        bs = next((d for d in dimensions if d.name == 'BS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        pattern_type = cq.details.get('pattern_type', 'VCP') if cq else 'VCP'

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TC:{tc.score:.2f} CQ:{cq.score:.2f} BS:{bs.score:.2f} VC:{vc.score:.2f}",
            f"{pattern_type.upper()} {platform['platform_days']}d (±{platform['platform_range_pct']*100:.1f}%)",
            f"Breakout +{bs.details.get('breakout_pct', 0)*100:.1f}% | Vol {vc.details.get('volume_ratio', 0):.1f}x",
            f"50EMA: {tc.details.get('ema50_distance', 0)*100:.1f}% | 52w: {tc.details.get('distance_from_52w_high', 0)*100:.1f}%"
        ]

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter.
        - 52-week high proximity <25%
        - RS > 80 percentile (avoid mediocre stocks that just follow market)
        Uses shared phase0_data from screener if available.
        """
        prefiltered = []

        # Phase 0.1: Use phase0_data from screener if available
        phase0_data = getattr(self, 'phase0_data', None)
        if phase0_data:
            logger.info("MomentumBreakout: Phase 0.1 - Using phase0_data from screener")
            rs_scores = []
            for symbol in symbols:
                if symbol in phase0_data:
                    data = phase0_data[symbol]
                    rs_scores.append({
                        'symbol': symbol,
                        'rs': data.get('rs_raw', 0),
                        'percentile': data.get('rs_percentile', 50),
                        'distance_52w': data.get('distance_from_52w_high', 0),
                        'df': self._get_data(symbol)
                    })
        else:
            logger.info("MomentumBreakout: Phase 0.1 - Calculating RS scores (no phase0_data)...")
            rs_scores = []
            for symbol in symbols:
                try:
                    df = self._get_data(symbol)
                    if df is None or len(df) < self.PARAMS['min_listing_days']:
                        continue

                    current_price = df['close'].iloc[-1]

                    # Calculate returns
                    price_3m = df['close'].iloc[-63] if len(df) >= 63 else df['close'].iloc[0]
                    price_6m = df['close'].iloc[-126] if len(df) >= 126 else df['close'].iloc[0]
                    price_12m = df['close'].iloc[-252] if len(df) >= 252 else df['close'].iloc[0]

                    ret_3m = (current_price - price_3m) / price_3m
                    ret_6m = (current_price - price_6m) / price_6m
                    ret_12m = (current_price - price_12m) / price_12m

                    # RS score
                    rs_raw = 0.4 * ret_3m + 0.3 * ret_6m + 0.3 * ret_12m
                    rs_scores.append({'symbol': symbol, 'rs': rs_raw, 'df': df})
                except Exception as e:
                    logger.debug(f"Error calculating RS for {symbol}: {e}")
                    continue

            # Calculate RS percentile if not using phase0_data
            if not rs_scores:
                return []
            all_rs = [s['rs'] for s in rs_scores]
            for item in rs_scores:
                below = sum(1 for r in all_rs if r < item['rs'])
                item['percentile'] = (below / len(all_rs)) * 100

        # Phase 0.2: Pre-filter by RS > threshold only (A1: confirmed breakout)
        # v7.0: Removed 52-week high filter - breaks can happen from any base
        logger.info(f"A1 MomentumBreakout: Phase 0.2 - Pre-filtering by RS > {self.PARAMS['rs_percentile_min']} (no 52w filter)...")
        for item in rs_scores:
            try:
                if item['percentile'] < self.PARAMS['rs_percentile_min']:
                    continue

                # A1: No 52-week high filter - confirmed breakouts can happen from any base
                # Breakout confirmation is done in filter() via platform detection
                prefiltered.append(item['symbol'])
            except Exception as e:
                logger.debug(f"Error pre-filtering {item['symbol']}: {e}")
                continue

        logger.info(f"A1 MomentumBreakout: {len(prefiltered)}/{len(symbols)} passed RS>{self.PARAMS['rs_percentile_min']} pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)

