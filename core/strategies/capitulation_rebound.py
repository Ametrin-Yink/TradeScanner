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
        'rsi_oversold': 25,  # v7.0: Changed from 22 to 25 for looser pre-filter
        'ema_atr_multiplier': 3.0,  # v7.0: Changed from 4.0 to 3.0 for looser pre-filter
        'min_gaps': 2,
        'lookback_days': 5,
        'stop_atr_multiplier': 2.0,
        'volume_climax_threshold': 4.0,
        'volume_high_threshold': 3.0,
        'volume_medium_threshold': 2.0,
        'vix_min': 15,      # NEW: VIX < 15 = reject (no fear = no capitulation)
        'vix_max_full': 35,  # VIX > 35 = cap at Tier B
    }

    def __init__(self, fetcher=None, db=None, config=None, earnings_calendar=None):
        """Initialize with VIX data cache and optional earnings calendar."""
        super().__init__(fetcher=fetcher, db=db, config=config)
        self.vix_data = None
        self.earnings_calendar = earnings_calendar

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen symbols for capitulation bottom setups with Phase 0 pre-filter.

        v7.1: Uses phase0_data for fast RSI pre-filter, only fetches DataFrames
        for symbols that pass the pre-filter.
        """
        # Phase 0: Check VIX filter (ONCE)
        logger.info("CapitulationRebound: Phase 0 - Checking VIX filter...")
        self._vix_status = self._check_vix_filter()

        # v5.0: VIX filter inverted - VIX < 15 = reject
        if self._vix_status == 'reject':
            logger.info("CapitulationRebound: VIX < 15 - no capitulation fear, rejecting all signals")
            return []

        logger.info(f"CapitulationRebound: VIX status = {self._vix_status}")

        # Phase 0.5: Pre-filter using cached data
        prefiltered = []
        logger.info("CapitulationRebound: Phase 0.5 - Pre-filtering for capitulation bottom setups...")

        phase0_data = getattr(self, 'phase0_data', {})

        for symbol in symbols:
            try:
                # Use phase0_data for fast RSI pre-filter
                if phase0_data and symbol in phase0_data:
                    data = phase0_data[symbol]
                    rsi = data.get('rsi_14', 50)

                    # Pre-filter: RSI must be oversold (< 35)
                    if rsi >= 35:
                        logger.debug(f"CapitRebound_REJ: {symbol} - RSI {rsi:.1f} not oversold")
                        continue

                # Fetch full data for detailed pre-filter
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
            # Use cached Tier 3 VIX data from market_data (set by screener)
            vix_df = self.market_data.get('^VIX') if hasattr(self, 'market_data') else None
            if vix_df is None:
                # Fallback: try to get from fetcher (should not happen in production)
                logger.warning("VIX not in market_data cache, attempting fetch fallback")
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

    def _check_reversal_confirmation(self, df: pd.DataFrame) -> Tuple[bool, Dict]:
        """
        Check if the most recent candle shows strong reversal confirmation (for MO bonus).

        Returns (is_strong, details) where:
        - is_strong: strong reversal signal (body majority or outside day)
        - details: dict with signal flags for match reasons
        """
        if len(df) < 2:
            return False, {}

        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        today_open = today['open']
        today_close = today['close']
        today_high = today['high']
        today_low = today['low']

        yesterday_high = yesterday['high']
        yesterday_low = yesterday['low']

        body_size = abs(today_close - today_open)
        lower_wick = min(today_open, today_close) - today_low
        has_long_lower_wick = lower_wick > body_size if body_size > 0 else lower_wick > 0

        # Strong reversal signals (for scoring bonus)
        total_range = today_high - today_low
        body_is_majority = body_size > 0.5 * total_range if total_range > 0 else False
        today_range = today_high - today_low
        yesterday_range = yesterday_high - yesterday_low
        is_outside_day = today_range > yesterday_range if yesterday_range > 0 else False
        is_strong = body_is_majority or is_outside_day

        details = {
            'is_green': today_close > today_open,
            'closed_higher': today_close > yesterday_close,
            'has_long_lower_wick': has_long_lower_wick,
            'body_is_majority': body_is_majority,
            'is_outside_day': is_outside_day,
        }

        return is_strong, details

    def _is_large_single_gap(self, df: pd.DataFrame) -> bool:
        """Check if a single large gap-down (>5%) is likely earnings-driven."""
        lookback = self.PARAMS['lookback_days']
        recent = df.tail(lookback + 1)  # +1 to capture the pre-gap close

        for i in range(1, len(recent)):
            prev_close = recent.iloc[i-1]['close']
            today_open = recent.iloc[i]['open']
            gap_pct = (today_open - prev_close) / prev_close
            if gap_pct < -0.05:  # >5% gap down
                return True
        return False

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
            logger.debug(f"CAP_REJ: {symbol} - Price not below EMA50-{self.PARAMS['ema_atr_multiplier']}xATR")
            return False

        # v7.0: Use pre-calculated consecutive down-days from phase0_data
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        consecutive_down = data.get('consecutive_down_days', 0)

        # v7.0: Accept >=2 gap-downs OR >=5 consecutive down-days
        if gaps < self.PARAMS['min_gaps'] and consecutive_down < 5:
            logger.debug(f"CAP_REJ: {symbol} - No exhaustion signal (gaps={gaps}, down_streak={consecutive_down})")
            return False

        # Reject likely earnings-driven gaps (fundamental repricing, not capitulation)
        if gaps == 1 and self._is_large_single_gap(df):
            logger.debug(f"CAP_REJ: {symbol} - Likely earnings gap (single large gap)")
            return False

        logger.debug(f"CAP_PASS: {symbol} - All pre-filters passed")
        return True

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """All filtering done in _prefilter_symbol; pass-through for base class screen()."""
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

        # Distance from EMA (used by EX dimension only)
        distance_from_ema = abs(current_price - ema50) / ema50
        atr_ratio = distance_from_ema / (atr / current_price) if atr > 0 else 0

        dimensions = []

        # Dimension 1: MO - Momentum Overextension with RSI divergence and velocity
        reversal_strong, reversal_details = self._check_reversal_confirmation(df)
        mo_score, mo_details = self._calculate_mo(df, rsi, reversal_strong, reversal_details)
        dimensions.append(ScoringDimension(
            name='MO',
            score=mo_score,
            max_score=5.5,
            details=mo_details
        ))

        # Dimension 2: EX - Extension Level (uses ATR ratio per doc)
        ex_score, ex_details = self._calculate_ex(atr_ratio, gaps, df, symbol)
        dimensions.append(ScoringDimension(
            name='EX',
            score=ex_score,
            max_score=6.0,
            details=ex_details
        ))

        # Dimension 3: VC - Volume Confirmation with Volume Climax
        vc_score, vc_details = self._calculate_vc(ind, df)
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details=vc_details
        ))

        return dimensions

    def _calculate_mo(self, df: pd.DataFrame, rsi: float,
                      reversal_strong: bool = False, reversal_details: Dict = None) -> Tuple[float, Dict]:
        """
        Momentum Overextension dimension (0-5.5) with RSI divergence and velocity scoring.
        Long mode only: Capitulation bottom detection.
        """
        details = {
            'rsi': rsi,
            'rsi_divergence': False
        }

        if reversal_details:
            details['reversal'] = reversal_details

        mo_score = 0.0

        # RSI oversold (capitulation detection)
        if rsi < 12:
            mo_score += 3.0
        elif rsi < 15:
            mo_score += 2.5 + (15 - rsi) / 3.0 * 0.5
        elif rsi < 18:
            mo_score += 2.0 + (18 - rsi) / 3.0 * 0.5
        elif rsi < 25:
            mo_score += 0.5 + (25 - rsi) / 7.0 * 1.5
        else:
            mo_score += 0

        # RSI bullish divergence (core scoring)
        if check_rsi_divergence(df, 'bullish'):
            mo_score += 2.0
            details['rsi_divergence'] = True

        # RSI velocity: how fast RSI has dropped over last 10 days
        rsi_velocity = self._calculate_rsi_velocity(df)
        details['rsi_velocity'] = rsi_velocity

        if rsi_velocity >= 20:
            mo_score += 2.0
        elif rsi_velocity >= 15:
            mo_score += 1.5 + (rsi_velocity - 15) / 5.0 * 0.5
        elif rsi_velocity >= 10:
            mo_score += 1.0 + (rsi_velocity - 10) / 5.0 * 0.5
        elif rsi_velocity >= 5:
            mo_score += 0.5 + (rsi_velocity - 5) / 5.0 * 0.5

        # Reversal confirmation bonus (+0.5 for strong signals)
        if reversal_strong:
            mo_score += 0.5
            details['reversal_bonus'] = True

        return round(min(5.5, mo_score), 2), details

    def _calculate_rsi_velocity(self, df: pd.DataFrame) -> float:
        """Calculate RSI(14) drop over last 10 days. Positive = capitulation signal."""
        if len(df) < 25:
            return 0.0

        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = rsi.iloc[-1]
        rsi_10d_ago = rsi.iloc[-11] if len(rsi) >= 11 else None

        if rsi_10d_ago is not None and pd.notna(rsi_10d_ago):
            return max(0.0, float(rsi_10d_ago - current_rsi))

        return 0.0

    def _calculate_ex(self, atr_ratio: float, gaps: int, df: pd.DataFrame = None, symbol: str = None) -> Tuple[float, Dict]:
        """
        Extension Level dimension (0-6) using ATR ratio.

        Documentation (lines 484-489):
        | (EMA50 − price) / ATR | Score |
        |-----------------------|-------|
        | >8× | 3.0 |
        | 6-8× | 2.0-3.0 |
        | 4-6× | 1.0-2.0 |
        | <4× | 0-1.0 |
        """
        details = {
            'atr_ratio': atr_ratio,
            'gaps_5d': gaps
        }

        ex_score = 0.0

        # Distance from EMA in ATR ratio terms (per doc)
        if atr_ratio > 8:
            ex_score += 3.0
        elif atr_ratio > 6:
            ex_score += 2.0 + (atr_ratio - 6) / 2.0
        elif atr_ratio > 4:
            ex_score += 1.0 + (atr_ratio - 4) / 2.0
        else:
            ex_score += max(0, atr_ratio / 4.0)

        # Gaps
        if gaps >= 4:
            ex_score += 2.0
        elif gaps >= 3:
            ex_score += 1.5
        elif gaps >= 2:
            ex_score += 1.0

        # Consecutive down-day streak bonus (0-1.0 pts) - use phase0_data
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {}) if symbol else {}
        consecutive_down = data.get('consecutive_down_days', 0)

        if consecutive_down >= 5:
            ex_score += 1.0
            details['consecutive_down_days'] = consecutive_down
        elif consecutive_down >= 3:
            ex_score += 0.5
            details['consecutive_down_days'] = consecutive_down

        return round(min(6.0, ex_score), 2), details

    def _calculate_vc(self, ind: TechnicalIndicators, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        Volume Confirmation dimension (0-5) with extended capitulation tiers.

        | Vol / avg20d | Score |
        |--------------|-------|
        | >8x | 4.0 (true capitulation climax) |
        | 6-8x | 3.5 |
        | 5-6x | 3.0 |
        | 4-5x | 2.5-3.0 |
        | 3-4x | 2.0-2.5 |
        | 2-3x | 1.0-2.0 |
        | 1.5-2x | 0.3-1.0 |
        | <1.5x | 0 |

        Bonus: +1.0 if CLV>0.65 AND vol>1.5x avg20d
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

        # Extended volume scoring tiers for true capitulation
        if volume_ratio > 8:
            vc_score += 4.0
            details['extreme_volume_climax'] = True
        elif volume_ratio > 6:
            vc_score += 3.5
        elif volume_ratio > 5:
            vc_score += 3.0
        elif volume_ratio > 4:
            vc_score += 2.5 + (volume_ratio - 4) * 0.5
        elif volume_ratio > 3:
            vc_score += 2.0 + (volume_ratio - 3) * 0.5
        elif volume_ratio > 2:
            vc_score += 1.0 + (volume_ratio - 2) * 1.0
        elif volume_ratio > 1.5:
            vc_score += 0.3 + (volume_ratio - 1.5) * 1.4
        # else: <1.5x = 0

        # Capitulation candle bonus (line 502): +1.0 if CLV>0.65 AND vol>1.5x
        if clv > 0.65 and volume_ratio > 1.5:
            vc_score += 1.0
            details['capitulation_candle'] = True

        return round(min(5.0, vc_score), 2), details


    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """Calculate entry, stop, and target prices for long positions.

        Mean-reversion targets are tiered:
        - Primary target: EMA8 (quick mean reversion)
        - Secondary target: EMA21 (stored as self.current_secondary_target)
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', current_price)
        ema21 = ema.get('ema21', current_price)

        entry = round(current_price, 2)
        stop = round(current_price - atr * self.PARAMS['stop_atr_multiplier'], 2)
        target = round(ema8, 2)

        # Store secondary target for partial exit management
        self.current_secondary_target = round(ema21, 2)

        # Keep target1 alias for compatibility
        self.current_target1 = entry

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
        mo = next((d for d in dimensions if d.name == 'MO'), None)
        ex = next((d for d in dimensions if d.name == 'EX'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        mo_details = mo.details if mo else {}
        ex_details = ex.details if ex else {}
        vc_details = vc.details if vc else {}

        reasons = [
            f"Score: {score:.2f}/16.5 (Tier {tier}-{position_pct*100:.0f}%)",
            f"MO:{mo.score:.2f} EX:{ex.score:.2f} VC:{vc.score:.2f}",
            f"RSI: {mo_details.get('rsi', 0):.1f}",
            f"RSI velocity: {mo_details.get('rsi_velocity', 0):.1f}",
            f"Gaps: {ex_details.get('gaps_5d', 0)}",
        ]

        if mo_details.get('rsi_divergence'):
            reasons.append("RSI divergence!")

        if mo_details.get('reversal_bonus'):
            reasons.append("Reversal candle confirmed")

        if vc_details.get('extreme_volume_climax'):
            reasons.append("Extreme volume climax (>8x)!")

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
