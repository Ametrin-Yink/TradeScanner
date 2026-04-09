"""Strategy A2: PreBreakoutCompression - Anticipatory breakout setups."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType
from .momentum_breakout import MomentumBreakoutStrategy
from ..scoring_utils import safe_divide, validate_dataframe

logger = logging.getLogger(__name__)


class PreBreakoutCompressionStrategy(MomentumBreakoutStrategy):
    """
    Strategy A2: PreBreakoutCompression - Anticipatory breakout setups.

    Shares A1's slot budget but uses CP dimension instead of BS.
    Scores lower by design (no confirmed breakout), typically B-tier.

    Key difference from A1:
    - A1: Confirmed breakout (price > pivot, RS>80)
    - A2: Pre-breakout compression (price within 5% of pivot, RS>50)

    Dimensions: ['TC', 'CQ', 'CP', 'VC']
    - TC: Trend Context (same as A1)
    - CQ: Consolidation Quality (same as A1)
    - CP: Compression Score (NEW - volume/range contraction)
    - VC: Volume Confirmation (dry-up detection)
    """

    NAME = "PreBreakoutCompression"
    STRATEGY_TYPE = StrategyType.A2
    DESCRIPTION = "PreBreakoutCompression - anticipatory VCP compression setups"
    DIMENSIONS = ['TC', 'CQ', 'CP', 'VC']  # CP replaces BS

    # Inherit most params from A1, but adjust for pre-breakout
    PARAMS = {
        **MomentumBreakoutStrategy.PARAMS,
        'breakout_pct': 0.0,
        'bonus_max': 1.5,
    }

    def calculate_score(self, dimensions: List[ScoringDimension], df: pd.DataFrame = None, symbol: str = None) -> Tuple[float, str]:
        """A2 uses base class normalization (not A1's bonus-based scoring)."""
        return BaseStrategy.calculate_score(self, dimensions, df, symbol)

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """A2 filter: consolidation near highs, not yet broken out."""
        data = getattr(self, 'phase0_data', {}).get(symbol, {})
        rs_pct = data.get('rs_percentile', 0)

        if rs_pct < self.PARAMS['min_rs_percentile']:
            logger.debug(f"A2_REJ: {symbol} - RS {rs_pct:.1f} < {self.PARAMS['min_rs_percentile']} (TC gate)")
            return False

        if len(df) < self.PARAMS['min_listing_days']:
            logger.debug(f"A2_REJ: {symbol} - Insufficient data: {len(df)} < {self.PARAMS['min_listing_days']}")
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        ema200 = ind.indicators.get('ema', {}).get('ema200')
        if ema200 is None or current_price <= ema200:
            logger.debug(f"A2_REJ: {symbol} - Price {current_price:.2f} <= EMA200 {ema200:.2f}")
            return False

        ret_3m = data.get('ret_3m')
        if ret_3m is None:
            if len(df) >= 63:
                price_3m = df['close'].iloc[-63]
                ret_3m = (current_price - price_3m) / price_3m if price_3m > 0 else 0
            else:
                ret_3m = 0
        if ret_3m < -0.20:
            logger.debug(f"A2_REJ: {symbol} - 3m return {ret_3m:.2%} < -20%")
            return False

        high_60d = df['high'].tail(60).max()
        low_60d = df['low'].tail(60).min()

        if high_60d <= 0 or low_60d <= 0:
            logger.debug(f"A2_REJ: {symbol} - Invalid 60d high/low")
            return False

        distance_from_high = (high_60d - current_price) / high_60d
        if distance_from_high > 0.05:
            logger.debug(f"A2_REJ: {symbol} - Too far from 60d high: {distance_from_high:.1%}")
            return False

        range_60d = high_60d - low_60d
        position_in_range = (current_price - low_60d) / range_60d if range_60d > 0 else 0
        if position_in_range < 0.40:
            logger.debug(f"A2_REJ: {symbol} - In lower {position_in_range:.0%} of 60d range")
            return False

        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        if platform and platform.get('platform_high'):
            distance_from_pivot = (current_price - platform['platform_high']) / platform['platform_high']
            if distance_from_pivot > 0.03:
                logger.debug(f"A2_REJ: {symbol} - Distance from pivot {distance_from_pivot:.1%} > 3%")
                return False

        logger.debug(f"A2_PASS: {symbol} - Consolidation near highs (dist:{distance_from_high:.1%}, pos:{position_in_range:.0%})")
        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 4 dimensions with CP instead of BS."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

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
            pattern_type = 'loose'
        else:
            range_pct = platform.get('platform_range_pct', 0.15)
            conc = platform.get('concentration_ratio', 0.3)
            if range_pct < 0.08 and conc > 0.60:
                pattern_type = 'VCP'
            elif range_pct < 0.05 and platform.get('platform_days', 60) <= 20:
                pattern_type = 'HTF'
            elif range_pct < 0.10 and conc > 0.55:
                pattern_type = 'flat'
            else:
                pattern_type = 'loose'

        platform_high = platform['platform_high']
        platform_range_pct = platform['platform_range_pct']
        breakout_pct = (current_price - platform_high) / platform_high
        clv = ind.calculate_clv()
        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        ema50_distance = ind.distance_from_ema50()
        metrics_52w = ind.calculate_52w_metrics()

        dimensions = []

        dimensions.append(ScoringDimension(
            name='TC',
            score=self._calculate_tc(ema50_distance, metrics_52w, clv, df, symbol),
            max_score=5.0,
            details={
                'rs_percentile': getattr(self, 'phase0_data', {}).get(symbol, {}).get('rs_percentile', 50),
                'distance_from_52w_high': metrics_52w['distance_from_high'],
                'ema50_distance': ema50_distance['distance_pct'],
            }
        ))

        _, cq_score = self._detect_consolidation_pattern(ind, df, platform)
        dimensions.append(ScoringDimension(
            name='CQ',
            score=cq_score,
            max_score=4.0,
            details={
                'pattern_type': pattern_type,
                'platform_range_pct': platform_range_pct,
                'concentration_ratio': platform['concentration_ratio'],
                'contraction_quality': platform.get('contraction_quality', 0.3)
            }
        ))

        cp_score = self._calculate_cp(df=df, platform=platform)
        dimensions.append(ScoringDimension(
            name='CP',
            score=cp_score,
            max_score=4.0,
            details={
                'volume_contraction': platform['volume_contraction_ratio'],
                'range_contraction': platform_range_pct,
                'distance_from_pivot': breakout_pct,
            }
        ))

        vc_score = self._calculate_vc_a2(df, platform)
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

    def _calculate_vc_a2(self, df: pd.DataFrame, platform: Dict) -> float:
        """A2 VC Dimension - dry-up only, max 4.0."""
        vc_score = 0.0

        vol_5d = df['volume'].tail(5).mean()
        vol_20d = df['volume'].tail(20).mean()
        dry_up_ratio = vol_5d / vol_20d if vol_20d > 0 else 1.0

        if dry_up_ratio < 0.50:
            vc_score += 3.0
        elif dry_up_ratio < 0.65:
            vc_score += 2.0
        elif dry_up_ratio < 0.80:
            vc_score += 1.0

        clv_values = []
        for i in range(5):
            if len(df) > i:
                row = df.iloc[-(i+1)]
                if row['high'] > row['low']:
                    clv = ((row['close'] - row['low']) - (row['high'] - row['close'])) / (row['high'] - row['low'])
                    clv_values.append(clv)

        if clv_values:
            avg_clv = sum(clv_values) / len(clv_values)
            if avg_clv >= 0.70:
                vc_score += 1.0

        return min(4.0, vc_score)

    def _calculate_cp(self, df: pd.DataFrame, platform: Dict) -> float:
        """Compression Score (CP) - Max 4.0."""
        cp_score = 0.0

        vol_5d = df['volume'].tail(5).mean()
        vol_20d = df['volume'].tail(20).mean()
        vol_contract = vol_5d / vol_20d if vol_20d > 0 else 1.0

        if vol_contract < 0.50:
            cp_score += 1.5
        elif vol_contract < 0.65:
            cp_score += 0.8
        elif vol_contract < 0.80:
            cp_score += 0.3

        high_5d = df['high'].tail(5).max()
        low_5d = df['low'].tail(5).min()
        range_5d = high_5d - low_5d

        atr_20d = df['high'].tail(20).max() - df['low'].tail(20).min()

        range_ratio = range_5d / atr_20d if atr_20d > 0 else 1.0

        if range_ratio < 0.50:
            cp_score += 1.5
        elif range_ratio < 0.70:
            cp_score += 0.8

        wave_count = self._count_contraction_waves(df, platform)
        if wave_count >= 3:
            cp_score += 1.0
        elif wave_count >= 2:
            cp_score += 0.5

        platform_high = platform['platform_high']
        current_price = df['close'].iloc[-1]
        distance = abs(current_price - platform_high) / platform_high

        if distance < 0.015:
            cp_score += 1.0
        elif distance < 0.03:
            cp_score += 0.5 + (0.03 - distance) / 0.015 * 0.5

        return min(4.0, cp_score)

    def _count_contraction_waves(self, df: pd.DataFrame, platform: Dict) -> int:
        """Count contraction waves in platform period."""
        platform_days = platform.get('platform_days', 30)
        if len(df) < platform_days:
            return 0

        platform_df = df.tail(platform_days).reset_index(drop=True)

        peaks = []
        for i in range(5, len(platform_df) - 5):
            window_highs = platform_df['high'].iloc[i-5:i+6]
            if platform_df['high'].iloc[i] == window_highs.max():
                peaks.append(platform_df['high'].iloc[i])

        waves = 0
        for i in range(1, len(peaks)):
            if peaks[i] < peaks[i-1]:
                waves += 1

        return waves

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """Calculate entry, stop, and target prices for pre-breakout setup."""
        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        current_price = df['close'].iloc[-1]
        platform_low = platform['platform_low'] if platform else df['low'].tail(20).min()
        platform_high = platform['platform_high'] if platform else df['high'].tail(20).max()

        entry = round(current_price, 2)
        stop = platform_low * 0.97
        stop = max(stop, entry * 0.92)
        stop = round(stop, 2)

        risk = entry - stop

        if tier == 'S':
            target = round(entry + risk * 4, 2)
        else:
            target = round(entry + risk * 3, 2)

        return entry, stop, target

    def build_match_reasons(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> List[str]:
        """Build human-readable match reasons for A2."""
        tc = next((d for d in dimensions if d.name == 'TC'), None)
        cq = next((d for d in dimensions if d.name == 'CQ'), None)
        cp = next((d for d in dimensions if d.name == 'CP'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        ind = TechnicalIndicators(df)
        platform = ind.detect_vcp_platform(
            lookback_range=self.PARAMS['platform_lookback'],
            max_range_pct=self.PARAMS['platform_max_range'],
            concentration_threshold=self.PARAMS['concentration_threshold']
        )

        pattern_type = cq.details.get('pattern_type', 'VCP') if cq else 'VCP'
        distance_from_pivot = cp.details.get('distance_from_pivot', 0) * 100

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TC:{tc.score:.2f} CQ:{cq.score:.2f} CP:{cp.score:.2f} VC:{vc.score:.2f}",
            f"{pattern_type.upper()} {platform['platform_days']}d compression (+/-{platform['platform_range_pct']*100:.1f}%)",
            f"Distance from pivot: {distance_from_pivot:.1f}% | Vol {vc.details.get('volume_ratio', 0):.1f}x",
            f"50EMA: {tc.details.get('ema50_distance', 0)*100:.1f}% | 52w: {tc.details.get('distance_from_52w_high', 0)*100:.1f}%"
        ]

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """Screen all symbols with Phase 0 pre-filter for A2."""
        prefiltered = []

        phase0_data = getattr(self, 'phase0_data', None)
        if phase0_data:
            logger.info("PreBreakoutCompression: Phase 0.1 - Using phase0_data from screener")
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
            logger.info("PreBreakoutCompression: Phase 0.1 - Calculating RS scores (no phase0_data)...")
            rs_scores = []
            for symbol in symbols:
                try:
                    df = self._get_data(symbol)
                    if df is None or len(df) < self.PARAMS['min_listing_days']:
                        continue

                    current_price = df['close'].iloc[-1]

                    if len(df) >= 63:
                        price_3m = df['close'].iloc[-63]
                        rs_raw = (current_price / price_3m - 1) * 100
                    else:
                        rs_raw = 0

                    rs_scores.append({'symbol': symbol, 'rs': rs_raw, 'df': df})
                except Exception as e:
                    logger.debug(f"Error calculating RS for {symbol}: {e}")
                    continue

            if not rs_scores:
                return []
            all_rs = [s['rs'] for s in rs_scores]
            for item in rs_scores:
                below = sum(1 for r in all_rs if r < item['rs'])
                item['percentile'] = (below / len(all_rs)) * 100

        logger.info(f"A2 PreBreakoutCompression: Phase 0.2 - Pre-filtering by RS > 50 (no 52w filter)...")
        for item in rs_scores:
            try:
                if item['percentile'] < 50:
                    continue

                prefiltered.append(item['symbol'])
            except Exception as e:
                logger.debug(f"Error pre-filtering {item['symbol']}: {e}")
                continue

        logger.info(f"A2 PreBreakoutCompression: {len(prefiltered)}/{len(symbols)} passed RS>50 pre-filter")

        return super().screen(prefiltered, max_candidates=max_candidates)
