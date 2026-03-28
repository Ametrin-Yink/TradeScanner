"""Strategy B: Momentum Breakout.

Core Philosophy: Capture confirmed breakouts of the strongest stocks after volatility contraction.

Three-Layer Filter:
1. Universe Selection: RS > 85 percentile (top 15% strength)
2. Setup Detection: 200EMA uptrend + within 5% of 50d high + volatility squeeze
3. Entry Trigger: Close above 50d high + volume confirmation

Dynamic Trailing Stop: Chandelier Exit (3x ATR) -> 21EMA -> 10EMA
"""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class MomentumStrategy(BaseStrategy):
    """Strategy B: Momentum Breakout - Capture confirmed breakouts of strongest stocks."""

    NAME = "Momentum"
    STRATEGY_TYPE = StrategyType.MOMENTUM
    DESCRIPTION = "Momentum Breakout - Capture breakouts of strong stocks after squeeze"
    DIMENSIONS = ['RS', 'SQ', 'VC', 'TC']

    # Momentum Parameters
    PARAMS = {
        'rs_percentile_threshold': 85,       # Top 15%
        'require_200ema_uptrend': True,      # Long-term trend
        'max_distance_from_50d_high': 0.05,  # Within 5% of 50d high
        'squeeze_contraction': 0.80,         # Range < 80% of previous
        'breakout_pct': 0.01,                # Close > 50d high + 1%
        'volume_ratio': 1.8,                 # Volume > 1.8x 20d SMA
        'atr_multiplier': 3.0,               # Chandelier Exit: 3x ATR
        'min_data_days': 200,                # Need 200 days for RS calculation
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        3-phase filtering system for momentum breakout.
        Note: RS percentile filtering is done at batch level in screen() method.
        """
        if len(df) < self.PARAMS['min_data_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Phase 2: Setup Detection
        # Check 200EMA trend
        ema200_data = ind.distance_from_200ema()
        if self.PARAMS['require_200ema_uptrend']:
            if not ema200_data['is_above'] or not ema200_data['is_uptrend']:
                return False

        # Check distance from 50d high (< 5%)
        high_50d_data = ind.get_50d_high()
        if high_50d_data['distance_pct'] is None:
            return False
        if high_50d_data['distance_pct'] > self.PARAMS['max_distance_from_50d_high']:
            return False

        # Check volatility squeeze
        squeeze = ind.detect_squeeze(
            recent_days=10,
            previous_days=10,
            contraction_threshold=self.PARAMS['squeeze_contraction']
        )
        if not squeeze['is_squeezing']:
            return False

        # Phase 3: Entry Trigger
        high_50d = high_50d_data['high_50d']
        if current_price < high_50d * (1 + self.PARAMS['breakout_pct']):
            return False

        # Check volume
        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        if volume_ratio < self.PARAMS['volume_ratio']:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 4-dimensional scoring (RS, SQ, VC, TC)."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Calculate returns for RS
        price_3m_ago = df['close'].iloc[-63] if len(df) >= 63 else df['close'].iloc[0]
        ret_3m = (current_price - price_3m_ago) / price_3m_ago

        price_6m_ago = df['close'].iloc[-126] if len(df) >= 126 else df['close'].iloc[0]
        ret_6m = (current_price - price_6m_ago) / price_6m_ago

        price_12m_ago = df['close'].iloc[-252] if len(df) >= 252 else df['close'].iloc[0]
        ret_12m = (current_price - price_12m_ago) / price_12m_ago

        # 5-day return for RS resilience
        price_5d_ago = df['close'].iloc[-5] if len(df) >= 5 else df['close'].iloc[0]
        ret_5d = (current_price - price_5d_ago) / price_5d_ago

        rs_raw_score = ind.calculate_rs_score(ret_3m, ret_6m, ret_12m)

        # Get technical data
        ema200_data = ind.distance_from_200ema()
        high_50d_data = ind.get_50d_high()
        squeeze = ind.detect_squeeze(
            recent_days=10,
            previous_days=10,
            contraction_threshold=self.PARAMS['squeeze_contraction']
        )

        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        high_50d = high_50d_data['high_50d']
        breakout_pct_momentum = (current_price / high_50d - 1) * 100 if high_50d > 0 else 0

        dimensions = []

        # Get SPY return for RS resilience calculation
        spy_return_5d = getattr(self, '_spy_return_5d', 0.0)

        # Dimension 1: RS Strength (RS) - 0-5 points
        rs_score = self._calculate_rs(rs_raw_score, spy_return_5d, ret_5d)
        dimensions.append(ScoringDimension(
            name='RS',
            score=rs_score,
            max_score=5.0,
            details={
                'rs_raw_score': rs_raw_score,
                'ret_3m': ret_3m,
                'ret_6m': ret_6m,
                'ret_12m': ret_12m
            }
        ))

        # Dimension 2: Squeeze Quality (SQ) - 0-5 points
        sq_score = self._calculate_sq(squeeze)
        dimensions.append(ScoringDimension(
            name='SQ',
            score=sq_score,
            max_score=5.0,
            details={
                'range_ratio': squeeze.get('range_ratio', 1.0),
                'slope': squeeze.get('slope', 0),
                'tightening': squeeze.get('tightening', False)
            }
        ))

        # Dimension 3: Volume Confirmation (VC) - 0-5 points
        vc_score = self._calculate_vc(volume_ratio, breakout_pct_momentum)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'volume_ratio': volume_ratio,
                'breakout_pct': breakout_pct_momentum / 100  # Convert back to decimal
            }
        ))

        # Dimension 4: Trend Context (TC) - 0-5 points
        tc_score = self._calculate_tc(ema200_data, squeeze)
        dimensions.append(ScoringDimension(
            name='TC',
            score=tc_score,
            max_score=5.0,
            details={
                'ema200_distance': ema200_data.get('distance_pct', 0),
                'ema200_uptrend': ema200_data.get('is_uptrend', False)
            }
        ))

        return dimensions

    def _calculate_rs(self, rs_raw_score: float, spy_return_5d: float = 0.0, stock_return_5d: float = 0.0) -> float:
        """
        RS Strength dimension (0-5) based on raw RS score with resilience bonus (建议#2).

        When SPY is down but stock holds up (relative strength), add bonus.
        Formula: Resilience_Bonus = 0 to 1.5 based on relative performance vs SPY
        """
        rs_score = 0.0

        # Base score based on raw RS strength (linear interpolation)
        if rs_raw_score > 0.5:
            rs_score = 5.0
        elif rs_raw_score > 0.3:
            # Linear from 3.0 at 0.3 to 5.0 at 0.5
            rs_score = 3.0 + (rs_raw_score - 0.3) / 0.2 * 2.0
        elif rs_raw_score > 0.1:
            # Linear from 1.0 at 0.1 to 3.0 at 0.3
            rs_score = 1.0 + (rs_raw_score - 0.1) / 0.2 * 2.0
        else:
            # Linear from 0 at -0.1 to 1.0 at 0.1
            rs_score = max(0.0, (rs_raw_score + 0.1) / 0.2 * 1.0)

        # Resilience Bonus: If SPY is down but stock is up/flat, add bonus
        # This captures "refusing to decline" stocks in weak markets
        if spy_return_5d < -0.02:  # SPY down more than 2%
            # Calculate relative resilience
            relative_performance = stock_return_5d - spy_return_5d

            # Bonus: 0 to 1.5 based on how much better stock performed
            if relative_performance > 0.05:  # Stock beat SPY by 5%+
                resilience_bonus = 1.5
            elif relative_performance > 0:
                # Linear from 0 to 1.5 as relative performance goes from 0 to 5%
                resilience_bonus = relative_performance / 0.05 * 1.5
            else:
                # Stock also down, but less than SPY: partial bonus
                # If stock down 1% vs SPY down 3%, relative = 2%, bonus = 0.6
                resilience_bonus = max(0, relative_performance / 0.03)

            rs_score = min(5.0, rs_score + resilience_bonus)

        return round(rs_score, 2)

    def _calculate_sq(self, squeeze: Dict) -> float:
        """Squeeze Quality dimension (0-5)."""
        sq_score = 0.0
        range_ratio = squeeze.get('range_ratio', 1.0)

        # Contraction: <60% = 3pts, <80% = 2pts (linear)
        if range_ratio < 0.60:
            sq_score += 3.0
        elif range_ratio < 0.80:
            # Linear from 3.0 at 60% to 2.0 at 80%
            sq_score += 3.0 - (range_ratio - 0.60) / 0.20
        else:
            # Linear from 2.0 at 80% to 0 at 100%
            sq_score += max(0.0, 2.0 - (range_ratio - 0.80) / 0.20)

        # Trend slope negative (decreasing volatility) - up to 2pts
        if squeeze.get('qualitative_ok', False):
            sq_score += 2.0
        else:
            # Partial credit based on slope value
            slope = squeeze.get('slope', 0)
            sq_score += max(0.0, 2.0 + slope * 0.5)

        return round(min(5.0, sq_score), 2)

    def _calculate_vc(self, volume_ratio: float, breakout_pct: float) -> float:
        """Volume Confirmation dimension (0-5)."""
        vc_score = 0.0

        # Volume ratio: >3x = 3pts, >2x = 2pts, >1.8x = 1pt (linear)
        if volume_ratio > 3.0:
            vc_score += 3.0
        elif volume_ratio > 2.0:
            # Linear from 2.0 at 2x to 3.0 at 3x
            vc_score += 2.0 + (volume_ratio - 2.0)
        elif volume_ratio > 1.8:
            # Linear from 1.0 at 1.8x to 2.0 at 2x
            vc_score += 1.0 + (volume_ratio - 1.8) / 0.2
        else:
            # Linear from 0 at 1x to 1.0 at 1.8x
            vc_score += max(0.0, (volume_ratio - 1.0) / 0.8)

        # Breakout strength - up to 2pts
        if breakout_pct > 3:
            vc_score += 2.0
        elif breakout_pct > 1.5:
            # Linear from 0 at 1.5% to 2.0 at 3%
            vc_score += (breakout_pct - 1.5) / 1.5 * 2.0
        else:
            # Linear from 0 at 0% to partial at 1.5%
            vc_score += max(0.0, breakout_pct / 1.5 * 1.5)

        return round(min(5.0, vc_score), 2)

    def _calculate_tc(self, ema200_data: Dict, squeeze: Dict) -> float:
        """Trend Context dimension (0-5)."""
        tc_score = 0.0
        ema200_dist = abs(ema200_data.get('distance_pct', 0))

        # 200EMA distance: <10% = 2pts, <20% = 1pt (linear)
        if ema200_dist < 0.10:
            tc_score += 2.0
        elif ema200_dist < 0.20:
            # Linear from 2.0 at 10% to 1.0 at 20%
            tc_score += 2.0 - (ema200_dist - 0.10) / 0.10
        else:
            # Linear from 1.0 at 20% to 0 at 30%
            tc_score += max(0.0, 1.0 - (ema200_dist - 0.20) / 0.10)

        # 200EMA slope strength - up to 2pts
        if ema200_data.get('is_uptrend', False):
            tc_score += 2.0

        # Platform tightness bonus - up to 1pt
        if squeeze.get('tightening', False):
            tc_score += 1.0

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
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # Entry: Current price
        entry = round(current_price, 2)

        # Stop loss: Platform low (lowest low in last 20 days)
        platform_low = df['low'].tail(20).min()
        stop = round(platform_low, 2)

        # Target: 3R (3x risk)
        risk = entry - stop
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
        """Build human-readable match reasons."""
        rs = next((d for d in dimensions if d.name == 'RS'), None)
        sq = next((d for d in dimensions if d.name == 'SQ'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        tc = next((d for d in dimensions if d.name == 'TC'), None)

        position_pct = self.calculate_position_pct(tier)

        ind = TechnicalIndicators(df)
        squeeze = ind.detect_squeeze(
            recent_days=10,
            previous_days=10,
            contraction_threshold=self.PARAMS['squeeze_contraction']
        )
        high_50d_data = ind.get_50d_high()

        current_price = df['close'].iloc[-1]
        high_50d = high_50d_data['high_50d']
        breakout_pct = (current_price / high_50d - 1) * 100 if high_50d > 0 else 0

        current_volume = df['volume'].iloc[-1]
        volume_sma20 = df['volume'].tail(20).mean()
        volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

        return [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"RS:{rs.score:.2f} SQ:{sq.score:.2f} VC:{vc.score:.2f} TC:{tc.score:.2f}",
            f"RS raw: {rs.details.get('rs_raw_score', 0):.2f}",
            f"Squeeze: {sq.details.get('range_ratio', 0)*100:.0f}% range",
            f"Break +{breakout_pct:.1f}% | Vol {volume_ratio:.1f}x"
        ]

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen all symbols using Momentum strategy with RS percentile filtering.
        Overrides base screen() to add Phase 1 RS filtering.
        """
        matches = []

        # Phase 0: Get SPY data for market regime and RS resilience calculation
        spy_df = self._get_data('SPY')
        spy_return_5d = 0.0
        if spy_df is not None and len(spy_df) >= 5:
            spy_current = spy_df['close'].iloc[-1]
            spy_5d_ago = spy_df['close'].iloc[-5]
            spy_return_5d = (spy_current - spy_5d_ago) / spy_5d_ago

        # Store SPY return for RS resilience calculation
        self._spy_return_5d = spy_return_5d

        # Phase 1: Calculate RS scores for all symbols (need 1 year data)
        rs_scores = []
        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < self.PARAMS['min_data_days']:
                continue

            try:
                current_price = df['close'].iloc[-1]

                # 3-month return
                price_3m_ago = df['close'].iloc[-63] if len(df) >= 63 else df['close'].iloc[0]
                ret_3m = (current_price - price_3m_ago) / price_3m_ago

                # 6-month return
                price_6m_ago = df['close'].iloc[-126] if len(df) >= 126 else df['close'].iloc[0]
                ret_6m = (current_price - price_6m_ago) / price_6m_ago

                # 12-month return
                price_12m_ago = df['close'].iloc[-252] if len(df) >= 252 else df['close'].iloc[0]
                ret_12m = (current_price - price_12m_ago) / price_12m_ago

                # 5-day return for RS resilience
                price_5d_ago = df['close'].iloc[-5] if len(df) >= 5 else df['close'].iloc[0]
                ret_5d = (current_price - price_5d_ago) / price_5d_ago

                # Calculate RS score
                ind = TechnicalIndicators(df)
                rs_score = ind.calculate_rs_score(ret_3m, ret_6m, ret_12m)

                rs_scores.append({
                    'symbol': symbol,
                    'rs_score': rs_score,
                    'ret_3m': ret_3m,
                    'ret_6m': ret_6m,
                    'ret_12m': ret_12m,
                    'ret_5d': ret_5d,  # 5-day return for RS resilience
                    'df': df
                })
            except Exception as e:
                logger.debug(f"Error calculating RS for {symbol}: {e}")
                continue

        if not rs_scores:
            return []

        # Calculate percentile ranking
        all_rs_scores = [s['rs_score'] for s in rs_scores]
        for item in rs_scores:
            below_count = sum(1 for s in all_rs_scores if s < item['rs_score'])
            percentile = (below_count / len(all_rs_scores)) * 100
            item['rs_percentile'] = percentile

        # Filter to top 15%
        rs_filtered = [
            s for s in rs_scores
            if s['rs_percentile'] >= self.PARAMS['rs_percentile_threshold']
        ]

        logger.info(f"Momentum: {len(rs_filtered)}/{len(rs_scores)} symbols passed RS > 85 filter")

        # Phase 2 & 3: Use base class screen() on filtered symbols
        filtered_symbols = [s['symbol'] for s in rs_filtered]

        # Store RS data for dimension calculation
        self._rs_data = {s['symbol']: s for s in rs_filtered}

        for symbol in filtered_symbols:
            try:
                df = self._rs_data[symbol]['df']

                if not self.filter(symbol, df):
                    continue

                dimensions = self.calculate_dimensions(symbol, df)
                if not dimensions:
                    continue

                score, tier = self.calculate_score(dimensions)
                if tier == 'C':
                    continue

                entry, stop, target = self.calculate_entry_exit(symbol, df, dimensions, score, tier)
                confidence = self.calculate_confidence(score, tier)
                reasons = self.build_match_reasons(symbol, df, dimensions, score, tier)
                snapshot = self.build_snapshot(symbol, df, dimensions, score, tier)

                # Add RS-specific data to snapshot
                snapshot['rs_percentile'] = self._rs_data[symbol]['rs_percentile']
                snapshot['rs_raw_score'] = self._rs_data[symbol]['rs_score']

                matches.append(StrategyMatch(
                    symbol=symbol,
                    strategy=self.NAME,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    match_reasons=reasons,
                    technical_snapshot=snapshot
                ))

            except Exception as e:
                logger.error(f"Error screening {symbol} for {self.NAME}: {e}")
                continue

        # Sort by confidence and return top 5
        return sorted(matches, key=lambda x: x.confidence, reverse=True)[:5]
