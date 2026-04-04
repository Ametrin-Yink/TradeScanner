"""Strategy F: CapitulationRebound v5.0 - Capitulation bottom detection only."""
from ..scoring_utils import calculate_clv, check_rsi_divergence
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class CapitulationReboundStrategy(BaseStrategy):
    """
    Strategy F: CapitulationRebound v5.0 - Capitulation bottom detection with volume climax.

    v5.0 Changes:
    - VIX filter inverted: VIX < 15 = reject (no fear = no capitulation)
    - VIX 15-35 = full operation
    - VIX > 35 = Tier B max
    - Exempt from extreme regime scalar
    - RSI max changed to 22 (from 20)

    Expert suggestions implemented:
    A. Volume Climax: Vol > 4xMA20 = +2 points (panic exhaustion)
    B. RSI Divergence Core: Price extreme + RSI divergence = MO +2 points
    C. VIX Filter v5.0: VIX < 15 reject, VIX > 35 = Tier B cap
    """

    NAME = "CapitulationRebound"
    STRATEGY_TYPE = StrategyType.F
    DESCRIPTION = "CapitulationRebound v5.0 - VIX 15-35 window"
    DIMENSIONS = ['MO', 'EX', 'VC']
    DIRECTION = 'long'

    # This strategy is exempt from extreme regime scalar
    EXTREME_EXEMPT = True

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'rsi_overbought': 80,
        'rsi_oversold': 22,  # Changed from 20 to 22 for v5.0
        'ema_atr_multiplier': 4.0,
        'min_gaps': 2,
        'lookback_days': 5,
        'stop_atr_multiplier': 2.0,
        'volume_climax_threshold': 4.0,
        'volume_high_threshold': 3.0,
        'volume_medium_threshold': 2.0,
        'vix_min': 15,      # NEW: VIX < 15 = reject (no fear = no capitulation)
        'vix_max_full': 35,  # VIX > 35 = cap at Tier B
        'profit_efficiency_threshold': 1.5,
        'efficiency_penalty': 2.0,
        'time_window_days': 10,
    }

    def __init__(self, fetcher=None, db=None):
        """Initialize with VIX data cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.vix_data = None

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen symbols for capitulation bottom setups.
        """
        # Phase 0: Check VIX filter (ONCE)
        logger.info("CapitulationRebound: Phase 0 - Checking VIX filter...")
        self._vix_status = self._check_vix_filter()

        # v5.0: VIX filter inverted - VIX < 15 = reject
        if self._vix_status == 'reject':
            logger.info("CapitulationRebound: VIX < 15 - no capitulation fear, rejecting all signals")
            return []

        logger.info(f"CapitulationRebound: VIX status = {self._vix_status}")

        # Phase 0.5: Pre-filter by extreme conditions
        prefiltered = []
        logger.info("CapitulationRebound: Phase 0.5 - Pre-filtering for capitulation bottom setups...")

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    continue

                if self._prefilter_symbol(symbol, df):
                    prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"CapitulationRebound: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)

    def _check_vix_filter(self) -> str:
        """
        VIX Filter v5.0: Inverted logic for capitulation detection.
        - VIX < 15 = reject (no fear = no capitulation)
        - VIX 15-35 = full operation
        - VIX > 35 = limit (cap at Tier B)
        Returns: 'reject', 'limit', or 'normal'
        """
        try:
            # Try to get VIX data
            vix_df = self._get_data('^VIX')
            if vix_df is None or len(vix_df) < 10:
                logger.warning("VIX data unavailable, defaulting to normal mode")
                return 'normal'

            current_vix = vix_df['close'].iloc[-1]
            vix_5d_ago = vix_df['close'].iloc[-6] if len(vix_df) > 5 else current_vix
            vix_slope = (current_vix - vix_5d_ago) / 5

            self.vix_data = {
                'current': current_vix,
                'slope': vix_slope
            }

            # v5.0: Inverted VIX filter
            # VIX < 15 = no fear = no capitulation to catch
            if current_vix < self.PARAMS['vix_min']:
                logger.info(f"VIX {current_vix:.1f} < {self.PARAMS['vix_min']} - no fear, rejecting")
                return 'reject'
            # VIX > 35 = extreme fear, cap at Tier B
            elif current_vix > self.PARAMS['vix_max_full']:
                logger.info(f"VIX {current_vix:.1f} > {self.PARAMS['vix_max_full']} - extreme fear, limiting to Tier B")
                return 'limit'

            return 'normal'

        except Exception as e:
            logger.warning(f"Could not check VIX: {e}, defaulting to normal mode")
            return 'normal'  # Default to normal on error (VIX window 15-35 is safe)

    def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
        """Pre-filter symbol for capitulation bottom conditions only."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi')

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        price_metrics = ind.indicators.get('price_metrics', {})
        gaps = price_metrics.get('gaps_5d', 0)

        # Capitulation bottom conditions (long mode only)
        if rsi is None or rsi >= self.PARAMS['rsi_oversold']:
            logger.debug(f"CAP_REJ: {symbol} - RSI {rsi:.1f} >= {self.PARAMS['rsi_oversold']}")
            return False

        if current_price >= ema50 - self.PARAMS['ema_atr_multiplier'] * atr:
            logger.debug(f"CAP_REJ: {symbol} - Price {current_price:.2f} not below EMA50-4ATR {ema50 - self.PARAMS['ema_atr_multiplier'] * atr:.2f}")
            return False

        if gaps < self.PARAMS['min_gaps']:
            logger.debug(f"CAP_REJ: {symbol} - Gaps {gaps} < {self.PARAMS['min_gaps']}")
            return False

        logger.debug(f"CAP_PASS: {symbol} - All pre-filters passed")
        return True

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter with additional checks."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring with expert suggestions."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        rsi_data = ind.indicators.get('rsi', {})
        rsi = rsi_data.get('rsi', 50)

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price)

        price_metrics = ind.indicators.get('price_metrics', {})
        gaps = price_metrics.get('gaps_5d', 0)

        # Calculate distance from EMA
        distance_from_ema = abs(current_price - ema50) / ema50
        atr_multiple = distance_from_ema / (atr / current_price) if atr > 0 else 0

        dimensions = []

        # Dimension 1: MO - Momentum Overextension with RSI divergence (Expert suggestion B)
        mo_score, mo_details = self._calculate_mo(df, rsi, atr_multiple)
        dimensions.append(ScoringDimension(
            name='MO',
            score=mo_score,
            max_score=5.0,
            details=mo_details
        ))

        # Dimension 2: EX - Extension Level
        ex_score, ex_details = self._calculate_ex(distance_from_ema, gaps, df)
        dimensions.append(ScoringDimension(
            name='EX',
            score=ex_score,
            max_score=6.0,
            details=ex_details
        ))

        # Dimension 3: VC - Volume Confirmation with Volume Climax (Expert suggestion A)
        vc_score, vc_details = self._calculate_vc(ind, df)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=4.0,
            details=vc_details
        ))

        # Check profit efficiency
        total_score = sum(d.score for d in dimensions)
        entry = current_price
        stop = entry - atr * self.PARAMS['stop_atr_multiplier']
        target1 = ema50 - 2 * atr

        if abs(entry - stop) > 0:
            profit_potential = abs(target1 - entry) / abs(entry - stop)
            if profit_potential < self.PARAMS['profit_efficiency_threshold']:
                total_score -= self.PARAMS['efficiency_penalty']
                logger.debug(f"{symbol}: Efficiency penalty applied (R:R={profit_potential:.2f})")

        return dimensions

    def _calculate_mo(self, df: pd.DataFrame, rsi: float, atr_multiple: float) -> Tuple[float, Dict]:
        """
        Momentum Overextension dimension (0-5) with RSI divergence core scoring (Expert suggestion B).
        Long mode only: Capitulation bottom detection.
        """
        details = {
            'rsi': rsi,
            'atr_multiple': atr_multiple,
            'rsi_divergence': False
        }

        mo_score = 0.0

        # RSI oversold (capitulation detection) - matches doc thresholds
        if rsi < 12:
            mo_score += 3.0
        elif rsi < 15:
            mo_score += 2.5 + (15 - rsi) / 3.0 * 0.5
        elif rsi < 18:
            mo_score += 2.0 + (18 - rsi) / 3.0 * 0.5
        elif rsi < 22:
            mo_score += 1.0 + (22 - rsi) / 4.0 * 1.0
        else:
            mo_score += 0

        # Expert suggestion B: RSI bullish divergence (core scoring)
        if check_rsi_divergence(df, 'bullish'):
            mo_score += 2.0
            details['rsi_divergence'] = True

        # Distance from EMA in ATR terms
        if atr_multiple > 10:
            mo_score += 2.0
        elif atr_multiple > 7:
            mo_score += 1.5 + (atr_multiple - 7) / 3.0 * 0.5
        elif atr_multiple > 5:
            mo_score += 1.0 + (atr_multiple - 5) / 2.0 * 0.5
        else:
            mo_score += max(0, (atr_multiple - 3) / 2.0)

        return round(min(5.0, mo_score), 2), details

    def _check_rsi_divergence(self, df: pd.DataFrame, direction: str) -> bool:
        """Check for RSI divergence (Expert suggestion B)."""
        if len(df) < 20:
            return False

        # Calculate RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        if direction == 'bearish':
            # Bearish divergence: price higher high, RSI lower high
            recent_high_idx = df['high'].tail(10).idxmax()
            recent_high = df.loc[recent_high_idx, 'high']

            prev_period = df.loc[df.index < recent_high_idx]
            if len(prev_period) < 10:
                return False

            prev_high = prev_period['high'].tail(20).max()
            prev_rsi_high = rsi.loc[prev_period.tail(20).index].max()
            recent_rsi = rsi.loc[recent_high_idx]

            if recent_high > prev_high and recent_rsi < prev_rsi_high:
                return True
        else:
            # Bullish divergence: price lower low, RSI higher low
            recent_low_idx = df['low'].tail(10).idxmin()
            recent_low = df.loc[recent_low_idx, 'low']

            prev_period = df.loc[df.index < recent_low_idx]
            if len(prev_period) < 10:
                return False

            prev_low = prev_period['low'].tail(20).min()
            prev_rsi_low = rsi.loc[prev_period.tail(20).index].min()
            recent_rsi = rsi.loc[recent_low_idx]

            if recent_low < prev_low and recent_rsi > prev_rsi_low:
                return True

        return False

    def _calculate_ex(self, distance_pct: float, gaps: int, df: pd.DataFrame = None) -> Tuple[float, Dict]:
        """Extension Level dimension (0-6)."""
        details = {
            'distance_from_ema_pct': distance_pct,
            'gaps_5d': gaps
        }

        ex_score = 0.0

        # Distance from EMA
        if distance_pct > 0.20:
            ex_score += 3.0
        elif distance_pct > 0.15:
            ex_score += 2.0 + (distance_pct - 0.15) / 0.05
        elif distance_pct > 0.10:
            ex_score += 1.0 + (distance_pct - 0.10) / 0.05
        else:
            ex_score += max(0, distance_pct / 0.10)

        # Gaps
        if gaps >= 4:
            ex_score += 2.0
        elif gaps >= 3:
            ex_score += 1.5
        elif gaps >= 2:
            ex_score += 1.0

        # Consecutive down-day streak bonus (0-1.0 pts)
        if df is not None and len(df) >= 10:
            consecutive_down = 0
            for i in range(1, min(10, len(df))):
                if df['close'].iloc[-i] < df['close'].iloc[-i-1]:
                    consecutive_down += 1
                else:
                    break

            if consecutive_down >= 5:
                ex_score += 1.0
                details['consecutive_down_days'] = consecutive_down
            elif consecutive_down >= 3:
                ex_score += 0.5
                details['consecutive_down_days'] = consecutive_down

        return round(min(6.0, ex_score), 2), details

    def _calculate_vc(self, ind: TechnicalIndicators, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        Volume Confirmation dimension (0-4) with Volume Climax (Expert suggestion A).
        Long mode only: Capitulation bottom detection.
        """
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)
        volume_spike = volume_data.get('volume_spike', False)

        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])

        details = {
            'volume_ratio': volume_ratio,
            'volume_spike': volume_spike,
            'clv': clv
        }

        vc_score = 0.0

        # Expert suggestion A: Volume Climax
        if volume_ratio > self.PARAMS['volume_climax_threshold']:  # > 4xMA20
            vc_score += 2.0  # Maximum reward for panic exhaustion
            details['volume_climax'] = True
        elif volume_ratio > self.PARAMS['volume_high_threshold']:  # > 3xMA20
            vc_score += 1.5
        elif volume_ratio > self.PARAMS['volume_medium_threshold']:  # > 2xMA20
            vc_score += 1.0
        elif volume_ratio > 1.5:
            vc_score += 0.5

        # Capitulation with long lower shadow
        if clv > 0.7 and volume_ratio > 1.5:
            vc_score += 2.0

        # OBV divergence would be checked here if available

        return round(min(4.0, vc_score), 2), details


    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """Calculate entry, stop, and target prices for long positions."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        ema = ind.indicators.get('ema', {})
        ema50 = ema.get('ema50', current_price)

        entry = round(current_price, 2)
        stop = round(current_price - atr * self.PARAMS['stop_atr_multiplier'], 2)
        target = round(ema50, 2)

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
        mo = next((d for d in dimensions if d.name == 'MO'), None)
        ex = next((d for d in dimensions if d.name == 'EX'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        mo_details = mo.details if mo else {}
        ex_details = ex.details if ex else {}
        vc_details = vc.details if vc else {}

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"MO:{mo.score:.2f} EX:{ex.score:.2f} VC:{vc.score:.2f}",
            f"RSI: {mo_details.get('rsi', 0):.1f}",
            f"Gaps: {ex_details.get('gaps_5d', 0)}",
        ]

        if mo_details.get('rsi_divergence'):
            reasons.append("RSI divergence!")

        if vc_details.get('volume_climax'):
            reasons.append(f"Volume climax: {vc_details['volume_ratio']:.1f}x")

        if self.vix_data:
            reasons.append(f"VIX: {self.vix_data['current']:.1f}")

        return reasons

    def calculate_position_pct(self, tier: str, regime: str = 'neutral') -> float:
        """
        Override to implement VIX-based position limit for v5.0.
        - VIX > 35 = cap at Tier B (5%)
        Long mode only.
        """
        base_pct = super().calculate_position_pct(tier, regime)

        # v5.0: VIX > 35 = cap at Tier B max
        if self.vix_data:
            current_vix = self.vix_data['current']

            if current_vix > self.PARAMS['vix_max_full']:
                # Limit to Tier B max (5%)
                return min(base_pct, 0.05)

        return base_pct
