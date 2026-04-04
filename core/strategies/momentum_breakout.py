"""Strategy A: VCP-EP (Volatility Contraction Pattern - Episodic Pivot)."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Strategy A: MomentumBreakout v5.0
    - Multi-pattern CQ (VCP, HTF, flat, ascending, loose)
    - TC promoted to primary gate (RS >= 50th)
    - Bonus pool (+3 max, clamped to 15)
    """

    NAME = "MomentumBreakout"
    STRATEGY_TYPE = StrategyType.A  # Changed from EP
    DESCRIPTION = "MomentumBreakout v5.0 - multi-pattern momentum"
    DIMENSIONS = ['TC', 'CQ', 'BS', 'VC']

    # VCP-EP Parameters
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
        # v5.0: TC promoted to primary gate
        'min_rs_percentile': 50,               # NEW: TC is now primary gate
        'max_raw_score': 20.0,                  # NEW: Allow raw scores up to 20
        'bonus_max': 3.0,                       # NEW: Bonus pool max
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """5-layer filtering system with diagnostic logging + TC primary gate."""
        # NEW: TC hard gate - RS >= 50th percentile (must be done first)
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
        # Price > EMA200
        ema200 = ind.indicators.get('ema', {}).get('ema_200')
        if ema200 is None or current_price <= ema200:
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

        # Layer 1: Liquidity
        dollar_volume = current_price * df['volume'].iloc[-1]
        if dollar_volume < self.PARAMS['min_dollar_volume']:
            logger.debug(f"MB_REJ: {symbol} - Low dollar volume: ${dollar_volume/1e6:.1f}M < ${self.PARAMS['min_dollar_volume']/1e6:.0f}M")
            return False

        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            logger.debug(f"MB_REJ: {symbol} - Low ADR: {adr_pct:.3f} < {self.PARAMS['min_atr_pct']}")
            return False

        # Layer 2: 50EMA deadzone filter
        ema50_distance = ind.distance_from_ema50()
        if ema50_distance['distance_pct'] > self.PARAMS['max_distance_from_50ema']:
            logger.debug(f"MB_REJ: {symbol} - Far from 50EMA: {ema50_distance['distance_pct']:.3f} > {self.PARAMS['max_distance_from_50ema']}")
            return False

        ema50_slope = ind.calculate_stable_ema_slope(period=50, comparison_days=3)
        if not ema50_slope['is_uptrend']:
            logger.debug(f"MB_REJ: {symbol} - EMA50 not in uptrend")
            return False

        # Layer 3: 52-week high proximity
        metrics_52w = ind.calculate_52w_metrics()
        if metrics_52w['distance_from_high'] is None:
            logger.debug(f"MB_REJ: {symbol} - Cannot calculate 52w metrics")
            return False
        if metrics_52w['distance_from_high'] > self.PARAMS['max_distance_from_52w_high']:
            logger.debug(f"MB_REJ: {symbol} - Far from 52w high: {metrics_52w['distance_from_high']:.3f} > {self.PARAMS['max_distance_from_52w_high']}")
            return False

        # Layer 4: VCP Platform Detection
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        if platform is None or not platform.get('is_valid'):
            logger.debug(f"MB_REJ: {symbol} - No valid VCP platform detected")
            return False

        if platform['volume_contraction_ratio'] > self.PARAMS['volume_contraction_vs_platform']:
            logger.debug(f"MB_REJ: {symbol} - Poor volume contraction: {platform['volume_contraction_ratio']:.2f} > {self.PARAMS['volume_contraction_vs_platform']}")
            return False

        # Layer 5: EP Breakout Confirmation
        platform_high = platform['platform_high']
        breakout_pct = (current_price - platform_high) / platform_high

        if breakout_pct < self.PARAMS['breakout_pct']:
            logger.debug(f"MB_REJ: {symbol} - Breakout too small: {breakout_pct:.3f} < {self.PARAMS['breakout_pct']}")
            return False

        clv = ind.calculate_clv()
        if clv < self.PARAMS['clv_threshold']:
            logger.debug(f"MB_REJ: {symbol} - CLV too low: {clv:.3f} < {self.PARAMS['clv_threshold']}")
            return False

        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        if volume_ratio < self.PARAMS['breakout_volume_vs_20d_sma']:
            logger.debug(f"MB_REJ: {symbol} - Volume ratio too low: {volume_ratio:.2f}x < {self.PARAMS['breakout_volume_vs_20d_sma']}x")
            return False

        logger.debug(f"MB_PASS: {symbol} - All 5 layers + TC gate passed! Breakout:{breakout_pct:.2%}, Vol:{volume_ratio:.1f}x")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 4-dimensional scoring with multi-pattern CQ."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        if not platform:
            return []

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
        bs_score = self._calculate_bs(breakout_pct, platform_range_pct)
        dimensions.append(ScoringDimension(
            name='BS',
            score=bs_score,
            max_score=4.0,
            details={
                'breakout_pct': breakout_pct,
                'energy_ratio': breakout_pct / platform_range_pct if platform_range_pct > 0 else 1.0
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
        """
        if not platform or not platform.get('is_valid'):
            return 'none', 0.0

        platform_range_pct = platform['platform_range_pct']
        concentration_ratio = platform['concentration_ratio']
        contraction_quality = platform.get('contraction_quality', 0.5)
        platform_days = platform['platform_days']

        # Calculate trend within platform (for ascending/flat detection)
        platform_start = -platform_days - 5  # Slight offset
        platform_end = -5
        if len(df) < abs(platform_start) + 5:
            return 'loose', max(0.0, min(2.5, concentration_ratio * 3.0))

        platform_data = df.iloc[platform_start:platform_end]
        if len(platform_data) < 10:
            return 'loose', 0.5

        # Linear regression slope
        x = np.arange(len(platform_data))
        y = platform_data['close'].values
        slope = np.polyfit(x, y, 1)[0] if len(x) > 1 else 0
        slope_pct = slope / np.mean(y) if np.mean(y) > 0 else 0

        # Pattern Detection Logic
        pattern_type = 'loose'
        base_score = 2.5

        # VCP: Tight range + high concentration + good contraction
        if (platform_range_pct < 0.08 and
            concentration_ratio > 0.60 and
            contraction_quality > 0.70):
            pattern_type = 'VCP'
            base_score = 4.0
        # HTF: Very tight, short duration
        elif (platform_range_pct < 0.05 and
              platform_days <= 20 and
              concentration_ratio > 0.70):
            pattern_type = 'HTF'
            base_score = 4.5
        # Flat Base: Low slope + tight range
        elif (abs(slope_pct) < 0.0005 and
              platform_range_pct < 0.10 and
              concentration_ratio > 0.55):
            pattern_type = 'flat'
            base_score = 3.5
        # Ascending Base: Positive slope + tight range
        elif (slope_pct > 0.0005 and
              platform_range_pct < 0.10 and
              concentration_ratio > 0.50):
            pattern_type = 'ascending'
            base_score = 3.0
        # Loose Base: Wide range or poor concentration
        else:
            pattern_type = 'loose'
            base_score = max(0.5, min(2.0, concentration_ratio * 3.0))

        # Apply bonus/penalty based on pattern quality
        final_score = base_score

        # Tightness bonus
        if platform_range_pct < 0.04:
            final_score += 0.5
        elif platform_range_pct > 0.10:
            final_score -= 0.5

        # Concentration bonus
        if concentration_ratio > 0.70:
            final_score += 0.3
        elif concentration_ratio < 0.40:
            final_score -= 0.3

        # Contraction quality bonus
        if contraction_quality > 0.80:
            final_score += 0.2

        return pattern_type, round(min(5.0, final_score), 2)

    def _calculate_bonus(self, dimensions: List[ScoringDimension], df: pd.DataFrame, symbol: str) -> float:
        """
        Calculate bonus points from confluence factors.
        Max bonus is capped at 3.0.
        """
        bonus = 0.0
        ind = TechnicalIndicators(df)

        # Bonus 1: Exceptional pattern quality
        cq_dim = next((d for d in dimensions if d.name == 'CQ'), None)
        if cq_dim and cq_dim.details.get('pattern_type') in ['VCP', 'HTF']:
            if cq_dim.score >= 4.5:
                bonus += 1.0
            elif cq_dim.score >= 4.0:
                bonus += 0.5

        # Bonus 2: High RS percentile (already passed TC gate, bonus for exceptional RS)
        data = getattr(self, 'phase0_data', {}).get(symbol, {})
        rs_pct = data.get('rs_percentile', 50)
        if rs_pct >= 90:
            bonus += 1.0
        elif rs_pct >= 80:
            bonus += 0.5

        # Bonus 3: Strong volume confirmation
        vc_dim = next((d for d in dimensions if d.name == 'VC'), None)
        if vc_dim:
            vol_ratio = vc_dim.details.get('volume_ratio', 0)
            if vol_ratio >= 4.0:
                bonus += 0.5
            elif vol_ratio >= 3.0:
                bonus += 0.25

        # Bonus 4: Multi-timeframe alignment (simplified check)
        try:
            if len(df) >= 50:
                ema20 = df['close'].ewm(span=20).mean().iloc[-1]
                ema50 = df['close'].ewm(span=50).mean().iloc[-1]
                current = df['close'].iloc[-1]
                if current > ema20 > ema50:
                    bonus += 0.25
        except Exception:
            pass

        return min(bonus, self.PARAMS['bonus_max'])

    def calculate_score(self, dimensions: List[ScoringDimension], df: pd.DataFrame = None, symbol: str = None) -> Tuple[float, str]:
        """
        Calculate final score with bonus pool.
        Raw scores can exceed 15, clamped to 15 for tier calculation.
        """
        base_score = sum(d.score for d in dimensions)

        # Calculate bonus if df and symbol available
        bonus = 0.0
        if df is not None and symbol is not None:
            bonus = self._calculate_bonus(dimensions, df, symbol)

        raw_score = base_score + bonus

        # Clamp to 15 for tier calculation
        clamped_score = min(raw_score, 15.0)

        # Determine tier based on clamped score
        if clamped_score >= self.TIER_S_MIN:
            tier = 'S'
        elif clamped_score >= self.TIER_A_MIN:
            tier = 'A'
        elif clamped_score >= self.TIER_B_MIN:
            tier = 'B'
        else:
            tier = 'C'

        logger.debug(f"MB Score: base={base_score:.1f} bonus={bonus:.1f} raw={raw_score:.1f} clamped={clamped_score:.1f} tier={tier}")

        return clamped_score, tier

    def _calculate_bs(self, breakout_pct: float, platform_range_pct: float) -> float:
        """Breakout Strength dimension (0-5)."""
        bs_score = 0.0

        # Breakout %
        if breakout_pct > 0.04:
            bs_score += 3.0
        elif breakout_pct > 0.02:
            bs_score += 2.0 + (breakout_pct - 0.02) / 0.02
        else:
            bs_score += max(0.0, breakout_pct / 0.02 * 2.0)

        # Energy ratio
        raw_energy = breakout_pct / platform_range_pct if platform_range_pct > 0 else 1.0
        energy_ratio = min(raw_energy, self.PARAMS['energy_ratio_cap'])

        if energy_ratio > 2.0:
            bs_score += 2.0
        elif energy_ratio > 1.0:
            bs_score += 1.0 + (energy_ratio - 1.0)
        else:
            bs_score += max(0.0, energy_ratio)

        return round(min(5.0, bs_score), 2)

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
            vc_score += 0  # > 1.00

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
        ema50 = ind.indicators.get('ema', {}).get('ema_50')
        ema200 = ind.indicators.get('ema', {}).get('ema_200')

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
        """Calculate entry, stop, and target prices."""
        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        current_price = df['close'].iloc[-1]
        platform_low = platform['platform_low'] if platform else df['low'].tail(20).min()
        platform_high = platform['platform_high'] if platform else df['high'].tail(20).max()

        # Get pattern type from CQ dimension
        cq_dim = next((d for d in dimensions if d.name == 'CQ'), None)
        pattern_type = cq_dim.details.get('pattern_type', 'vcp') if cq_dim else 'vcp'

        entry = round(current_price, 2)

        # Pattern-specific stop loss calculation
        if pattern_type in ('vcp', 'flat', 'ascending'):
            stop = platform_low * 0.98
        elif pattern_type == 'HTF':
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

        # Phase 0.2: Pre-filter by 52w high and RS > threshold
        logger.info(f"VCP-EP: Phase 0.2 - Pre-filtering by 52w high and RS > {self.PARAMS['rs_percentile_min']}...")
        for item in rs_scores:
            try:
                if item['percentile'] < self.PARAMS['rs_percentile_min']:
                    continue

                # Use pre-calculated distance_52w from phase0_data if available
                distance_52w = item.get('distance_52w')
                if distance_52w is None:
                    # Fallback: calculate 52w metrics
                    df = item['df']
                    if df is None:
                        continue
                    ind = TechnicalIndicators(df)
                    metrics_52w = ind.calculate_52w_metrics()
                    distance_52w = metrics_52w.get('distance_from_high', 1.0)

                # Relaxed pre-filter: <25% from 52w high
                if distance_52w < 0.25:
                    prefiltered.append(item['symbol'])
            except Exception as e:
                logger.debug(f"Error pre-filtering {item['symbol']}: {e}")
                continue

        logger.info(f"MomentumBreakout: {len(prefiltered)}/{len(symbols)} passed RS>{self.PARAMS['rs_percentile_min']} + 52w high pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)
