"""Strategy A: VCP-EP (Volatility Contraction Pattern - Episodic Pivot)."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class MomentumBreakoutStrategy(BaseStrategy):
    """Strategy A: VCP-EP - Captures demand burst after supply exhaustion."""

    NAME = "MomentumBreakout"
    STRATEGY_TYPE = StrategyType.EP
    DESCRIPTION = "MomentumBreakout v2.0 - VCP platform + volume breakout, RS>85 percentile bonus"
    DIMENSIONS = ['PQ', 'BS', 'VC', 'TC']

    # VCP-EP Parameters
    PARAMS = {
        'min_dollar_volume': 50_000_000,      # $50M minimum
        'min_atr_pct': 0.015,                  # 1.5% minimum ATR
        'min_listing_days': 60,                # 60 days minimum
        'platform_lookback': (15, 60),         # 15-60 day platform (relaxed from 15-30)
        'rs_bonus_threshold': 0.85,            # RS>85 percentile bonus
        'platform_max_range': 0.12,            # <12% range
        'concentration_threshold': 0.50,       # 50% days in ±2.5% band
        'volume_contraction_vs_platform': 0.70, # Last 5d < 70% of platform avg
        'breakout_pct': 0.02,                  # >2% above platform high
        'clv_threshold': 0.75,                 # CLV >= 0.75
        'breakout_volume_vs_20d_sma': 2.0,     # Volume > 2.0x 20d SMA
        'max_distance_from_50ema': 0.20,       # Within 20% of 50EMA
        'max_distance_from_52w_high': 0.10,    # Within 10% of 52-week high
        'energy_ratio_cap': 3.0,               # Cap energy ratio at 3.0
        'rs_percentile_min': 80,               # RS > 80 percentile (kept intentionally different from Momentum)
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """5-layer filtering system."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Layer 1: Liquidity
        dollar_volume = current_price * df['volume'].iloc[-1]
        if dollar_volume < self.PARAMS['min_dollar_volume']:
            return False

        adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
        if adr_pct < self.PARAMS['min_atr_pct']:
            return False

        # Layer 2: 50EMA deadzone filter
        ema50_distance = ind.distance_from_ema50()
        if ema50_distance['distance_pct'] > self.PARAMS['max_distance_from_50ema']:
            return False

        ema50_slope = ind.calculate_stable_ema_slope(period=50, comparison_days=3)
        if not ema50_slope['is_uptrend']:
            return False

        # Layer 3: 52-week high proximity
        metrics_52w = ind.calculate_52w_metrics()
        if metrics_52w['distance_from_high'] is None:
            return False
        if metrics_52w['distance_from_high'] > self.PARAMS['max_distance_from_52w_high']:
            return False

        # Layer 4: VCP Platform Detection
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        if platform is None or not platform.get('is_valid'):
            return False

        if platform['volume_contraction_ratio'] > self.PARAMS['volume_contraction_vs_platform']:
            return False

        # Layer 5: EP Breakout Confirmation
        platform_high = platform['platform_high']
        breakout_pct = (current_price - platform_high) / platform_high

        if breakout_pct < self.PARAMS['breakout_pct']:
            return False

        clv = ind.calculate_clv()
        if clv < self.PARAMS['clv_threshold']:
            return False

        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        if volume_ratio < self.PARAMS['breakout_volume_vs_20d_sma']:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 4-dimensional scoring."""
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

        # Dimension 1: Platform Quality (PQ)
        pq_score = self._calculate_pq(platform, platform_range_pct)
        dimensions.append(ScoringDimension(
            name='PQ',
            score=pq_score,
            max_score=5.0,
            details={
                'platform_range_pct': platform_range_pct,
                'concentration_ratio': platform['concentration_ratio'],
                'contraction_quality': platform.get('contraction_quality', 0.5)
            }
        ))

        # Dimension 2: Breakout Strength (BS)
        bs_score = self._calculate_bs(breakout_pct, platform_range_pct)
        dimensions.append(ScoringDimension(
            name='BS',
            score=bs_score,
            max_score=5.0,
            details={
                'breakout_pct': breakout_pct,
                'energy_ratio': breakout_pct / platform_range_pct if platform_range_pct > 0 else 1.0
            }
        ))

        # Dimension 3: Volume Confirmation (VC)
        vc_score = self._calculate_vc(platform, volume_ratio)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'volume_ratio': volume_ratio,
                'volume_contraction': platform['volume_contraction_ratio']
            }
        ))

        # Dimension 4: Trend Context (TC)
        tc_score = self._calculate_tc(ema50_distance, metrics_52w, clv)

        # Add RS bonus to TC score (from Momentum strategy)
        rs_bonus = self._calculate_rs_bonus(df)
        tc_score = min(5.0, tc_score + rs_bonus)

        dimensions.append(ScoringDimension(
            name='TC',
            score=tc_score,
            max_score=5.0,
            details={
                'ema50_distance': ema50_distance['distance_pct'],
                'distance_from_52w_high': metrics_52w['distance_from_high'],
                'clv': clv,
                'rs_bonus': rs_bonus
            }
        ))

        return dimensions

    def _calculate_pq(self, platform: Dict, platform_range_pct: float) -> float:
        """Platform Quality dimension (0-5)."""
        pq_score = 0.0

        # Tightness
        if platform_range_pct < 0.04:
            pq_score += 2.0
        elif platform_range_pct < 0.08:
            pq_score += 2.0 - (platform_range_pct - 0.04) / 0.04
        elif platform_range_pct < 0.12:
            pq_score += 1.0 - (platform_range_pct - 0.08) / 0.04
        else:
            pq_score += max(0.0, 0.5 - (platform_range_pct - 0.12) / 0.08 * 0.5)

        # Concentration
        conc_ratio = platform['concentration_ratio']
        if conc_ratio > 0.70:
            pq_score += 1.5
        elif conc_ratio > 0.50:
            pq_score += 0.5 + (conc_ratio - 0.50) / 0.20
        else:
            pq_score += max(0.0, (conc_ratio - 0.30) / 0.20 * 0.5)

        # Contraction Quality (建议#1)
        contraction_quality = platform.get('contraction_quality', 0.5)
        if contraction_quality >= 0.8:
            pq_score += 1.5
        elif contraction_quality >= 0.5:
            pq_score += 0.5 + (contraction_quality - 0.5) / 0.3 * 1.0
        else:
            pq_score += max(0.0, contraction_quality / 0.5 * 0.5)

        return round(min(5.0, pq_score), 2)

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

    def _calculate_vc(self, platform: Dict, volume_ratio: float) -> float:
        """Volume Confirmation dimension (0-5)."""
        vc_score = 0.0
        vol_contract = platform['volume_contraction_ratio']

        # Contraction
        if vol_contract < 0.50:
            vc_score += 2.0
        elif vol_contract < 0.70:
            vc_score += 2.0 - (vol_contract - 0.50) / 0.20
        else:
            vc_score += max(0.0, 1.0 - (vol_contract - 0.70) / 0.20)

        # Expansion
        if volume_ratio > 3.0:
            vc_score += 3.0
        elif volume_ratio > 2.0:
            vc_score += 2.0 + (volume_ratio - 2.0)
        else:
            vc_score += max(0.0, volume_ratio / 2.0 * 2.0)

        return round(min(5.0, vc_score), 2)

    def _calculate_tc(self, ema50_dist: Dict, metrics_52w: Dict, clv: float) -> float:
        """Trend Context dimension (0-5)."""
        tc_score = 0.0
        ema_dist = ema50_dist['distance_pct']

        # EMA proximity
        if ema_dist < 0.05:
            tc_score += 2.0
        elif ema_dist < 0.10:
            tc_score += 2.0 - (ema_dist - 0.05) / 0.05
        else:
            tc_score += max(0.0, 1.0 - (ema_dist - 0.10) / 0.05)

        # 52w high proximity
        dist_52w = metrics_52w['distance_from_high']
        if dist_52w < 0.03:
            tc_score += 2.0
        elif dist_52w < 0.05:
            tc_score += 2.0 - (dist_52w - 0.03) / 0.02
        else:
            tc_score += max(0.0, 1.0 - (dist_52w - 0.05) / 0.02)

        # CLV bonus
        if clv > 0.85:
            tc_score += 1.0
        elif clv > 0.65:
            tc_score += (clv - 0.65) / 0.20

        return round(min(5.0, tc_score), 2)

    def _calculate_rs_bonus(self, df: pd.DataFrame) -> float:
        """
        Calculate RS bonus score (0-1 points) for TC dimension.
        Merged from original Momentum strategy.
        """
        if len(df) < 252:
            return 0.0

        close = df['close']
        current_price = close.iloc[-1]

        # Calculate RS components
        price_3m = close.iloc[-63] if len(close) >= 63 else close.iloc[0]
        price_6m = close.iloc[-126] if len(close) >= 126 else close.iloc[0]
        price_12m = close.iloc[-252] if len(close) >= 252 else close.iloc[0]

        rs_3m = (current_price - price_3m) / price_3m
        rs_6m = (current_price - price_6m) / price_6m
        rs_12m = (current_price - price_12m) / price_12m

        rs_score = rs_3m * 0.4 + rs_6m * 0.3 + rs_12m * 0.3

        # Convert to 0-1 bonus
        if rs_score > 0.5:
            return 1.0
        elif rs_score > 0.3:
            return 0.5 + (rs_score - 0.3) / 0.2 * 0.5
        else:
            return max(0.0, rs_score / 0.3 * 0.5)

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

        entry = round(current_price, 2)
        stop = round(platform_low * 0.98, 2)  # Platform low - 2% buffer
        risk = entry - stop
        target = round(entry + risk * 3, 2)  # 3R

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
        pq = next((d for d in dimensions if d.name == 'PQ'), None)
        bs = next((d for d in dimensions if d.name == 'BS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)

        position_pct = self.calculate_position_pct(tier)

        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"PQ:{pq.score:.2f} BS:{bs.score:.2f} VC:{vc.score:.2f} TC:{tc.score:.2f}",
            f"VCP {platform['platform_days']}d (±{platform['platform_range_pct']*100:.1f}%)",
            f"Breakout +{bs.details.get('breakout_pct', 0)*100:.1f}% | Vol {vc.details.get('volume_ratio', 0):.1f}x",
            f"50EMA: {tc.details.get('ema50_distance', 0)*100:.1f}% | 52w: {tc.details.get('distance_from_52w_high', 0)*100:.1f}%"
        ]

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter.
        - 52-week high proximity <25%
        - RS > 80 percentile (avoid mediocre stocks that just follow market)
        """
        prefiltered = []

        # Phase 0.1: Calculate RS for all symbols first
        logger.info("VCP-EP: Phase 0.1 - Calculating RS scores...")
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

        # Calculate RS percentile
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
                if item['percentile'] < self.PARAMS['rs_percentile_min']:  # RS > threshold
                    continue

                df = item['df']
                ind = TechnicalIndicators(df)
                metrics_52w = ind.calculate_52w_metrics()

                # Relaxed pre-filter: <25% from 52w high
                if metrics_52w['distance_from_high'] is not None:
                    if metrics_52w['distance_from_high'] < 0.25:
                        prefiltered.append(item['symbol'])
            except Exception as e:
                logger.debug(f"Error pre-filtering {item['symbol']}: {e}")
                continue

        logger.info(f"VCP-EP: {len(prefiltered)}/{len(symbols)} passed RS>80 + 52w high pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered)
