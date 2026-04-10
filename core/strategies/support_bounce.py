"""Strategy C: Support Bounce - Near support with volume contraction, false breakdown entry."""
from ..scoring_utils import calculate_clv
from ..constants import SECTOR_ETFS
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from ..support_resistance import SupportResistanceCalculator
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class SupportBounceStrategy(BaseStrategy):
    """
    Strategy C: SupportBounce v8.0
    - Regime-adaptive position sizing (no SPY gate)
    - Depth range 2-10% for support distance
    - Continuous 1-3 day reclaim scoring for RB dimension
    - S/R cached per symbol (no redundant recalculation)
    - Volume Phase 1: low volume on breakdown = bullish (false breakdown)
    - Entry at reclaim confirmation or limit at support
    - Stop at breakdown wick low, target at resistance or 2R
    """

    NAME = "SupportBounce"
    STRATEGY_TYPE = StrategyType.C
    DESCRIPTION = "SupportBounce v8.0 - regime-adaptive false breakdown"
    DIMENSIONS = ['SQ', 'VD', 'RB']
    DIRECTION = 'long'

    PARAMS = {
        'min_dollar_volume': 50_000_000,
        'min_atr_pct': 0.015,
        'min_listing_days': 50,
        'max_distance_from_support': 0.10,
        'min_touches_60d': 3,
        'min_touches_30d': 2,
        'target_r_multiplier': 2.0,
        'support_tolerance_atr': 0.5,
        'max_reclaim_days': 5,
        'volume_veto_threshold': 2.0,
        'clv_veto_threshold': 0.3,
    }

    def __init__(self, fetcher=None, db=None, config=None):
        """Initialize with sector ETF data cache and S/R cache."""
        super().__init__(fetcher=fetcher, db=db, config=config)
        self.sector_etf_data = {}
        self.stock_info = {}
        self._sr_cache: Dict[str, Dict] = {}

    def _reset_sr_cache(self):
        """Clear S/R cache between symbols."""
        self._sr_cache.clear()

    def _get_sr_levels(self, df: pd.DataFrame, symbol: str = '') -> Dict:
        """Get cached S/R levels, compute once per symbol."""
        if symbol and symbol in self._sr_cache:
            return self._sr_cache[symbol]['levels']
        calc = SupportResistanceCalculator(df)
        levels = calc.calculate_all()
        if symbol:
            self._sr_cache[symbol] = {'levels': levels, 'calc': calc}
        return levels

    def _get_sr_calculator(self, df: pd.DataFrame, symbol: str = ''):
        """Get cached S/R calculator instance."""
        self._get_sr_levels(df, symbol)
        if symbol and symbol in self._sr_cache:
            return self._sr_cache[symbol]['calc']
        return None

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with lightweight Phase 0 pre-filter.
        Pre-filter only checks: support exists, price within max distance.
        Full validation (touches, EMA50, ADR, volume) happens in filter().
        S/R results are cached so filter() and calculate_dimensions() reuse them.
        """
        logger.info("SupportBounce: Phase 0 - Pre-filtering by support existence...")

        # Check for pre-calculated phase0_data (from Phase 0 pre-calculation)
        phase0_data = getattr(self, 'phase0_data', {})

        prefiltered = []

        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    logger.debug(f"SupportBounce_REJ: {symbol} - Insufficient data")
                    continue

                current_price = df['close'].iloc[-1]

                # Try pre-calculated supports from phase0_data first
                p0 = phase0_data.get(symbol, {}) if phase0_data else {}
                supports = p0.get('supports', [])

                if not supports:
                    # Fall back to inline S/R calculation
                    sr_levels = self._get_sr_levels(df, symbol)
                    supports = sr_levels.get('support', [])

                if not supports:
                    logger.debug(f"SupportBounce_REJ: {symbol} - No support levels found")
                    continue

                supports_below = [s for s in supports if s < current_price]
                if not supports_below:
                    logger.debug(f"SupportBounce_REJ: {symbol} - No support below price {current_price:.2f}")
                    continue

                nearest_support = max(supports_below)
                distance_pct = (current_price - nearest_support) / current_price

                max_depth = self.PARAMS['max_distance_from_support']
                if distance_pct > max_depth:
                    logger.debug(f"SupportBounce_REJ: {symbol} - Depth {distance_pct:.2%} > {max_depth:.0%}")
                    continue

                logger.debug(f"SupportBounce_PASS: {symbol} - Support at {nearest_support:.2f}, depth {distance_pct:.2%}")
                prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"SupportBounce: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        # Load sector ETF data for comparison
        self._load_sector_etf_data()

        # Load stock info for sector alpha (only for symbols without phase0_data sector)
        symbols_needing_info = [s for s in prefiltered if not phase0_data.get(s, {}).get('sector')]
        if symbols_needing_info:
            try:
                if self.fetcher:
                    fetched = self.fetcher.fetch_batch_stock_info(symbols_needing_info)
                    self.stock_info.update(fetched)
            except Exception as e:
                logger.warning(f"Could not load stock info: {e}")

        # Use base class screen on pre-filtered symbols
        return super().screen(prefiltered, max_candidates=max_candidates)

    def _load_sector_etf_data(self):
        """Load sector ETF data for Sector Alpha comparison."""
        try:
            for etf in SECTOR_ETFS.values():
                df = self._get_data(etf)
                if df is not None and len(df) > 50:
                    self.sector_etf_data[etf] = df
        except Exception as e:
            logger.warning(f"Could not load sector ETF data: {e}")

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for SupportBounce candidates per v8.0 spec."""
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        if not self._check_basic_requirements(df):
            return False

        current_price = df['close'].iloc[-1]

        # Price vs EMA50 within +/-15%
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)
        ema50_distance = abs(current_price - ema50) / ema50 if ema50 > 0 else 1.0
        if ema50_distance > 0.15:
            logger.debug(f"SupportBounce_REJ: {symbol} - Price {ema50_distance:.1%} from EMA50 > 15%")
            return False

        # S/R from cache
        sr_levels = self._get_sr_levels(df, symbol)
        supports = sr_levels.get('support', [])
        if not supports:
            return False

        supports_below = [s for s in supports if s < current_price]
        if not supports_below:
            return False

        nearest_support = max(supports_below)
        distance_pct = abs(current_price - nearest_support) / current_price

        max_depth = self.PARAMS['max_distance_from_support']
        if distance_pct > max_depth:
            return False

        # Support touch requirement: >=3 touches in 60d OR >=2 touches in 30d
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        support_touches = self._calculate_support_touches(df, nearest_support, atr)
        touch_dates = support_touches.get('touch_dates', [])

        touches_60d = len([d for d in touch_dates if d <= 60])
        touches_30d = len([d for d in touch_dates if d <= 30])

        if not (touches_60d >= 3 or touches_30d >= 2):
            logger.debug(f"{symbol}: Touch requirement failed (60d:{touches_60d}, 30d:{touches_30d})")
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate 3-dimensional scoring."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # S/R from cache
        sr_levels = self._get_sr_levels(df, symbol)
        supports = sr_levels.get('support', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.99
        distance_pct = abs(current_price - nearest_support) / current_price

        # Get support touches and recency
        support_touches = self._calculate_support_touches(df, nearest_support, atr)
        recency_weight = self._calculate_recency_weight(support_touches['last_touch_days'])

        # Volume and CLV data for veto check
        volume_data = ind.indicators.get('volume', {})
        volume_ratio = volume_data.get('volume_ratio', 1.0)

        # Calculate CLV (Close Location Value)
        today = df.iloc[-1]
        clv = calculate_clv(today['close'], today['high'], today['low'])

        # Volume Trap Veto: high volume + low CLV = falling knife
        is_falling_knife = (volume_ratio > self.PARAMS['volume_veto_threshold'] and
                           clv < self.PARAMS['clv_veto_threshold'])

        # Sector Alpha Bonus
        sector_alpha = self._calculate_sector_alpha(symbol, current_price, atr)

        dimensions = []

        # Dimension 1: Support Quality (SQ) - 4 points max
        sq_score, sq_details = self._calculate_sq(df, ind, nearest_support,
                                                   support_touches, recency_weight)
        # Add sector alpha bonus
        if sector_alpha > 0:
            sq_score += sector_alpha
            sq_details['sector_alpha'] = sector_alpha
        sq_score = min(4.0, sq_score)
        dimensions.append(ScoringDimension(
            name='SQ',
            score=sq_score,
            max_score=4.0,
            details=sq_details
        ))

        # Dimension 2: Volume Dynamics (VD) - 5 points max
        if is_falling_knife:
            logger.debug(f"{symbol}: Volume trap veto (Vol:{volume_ratio:.2f}x, CLV:{clv:.2f})")
            return []

        vd_score, vd_details = self._calculate_vd(volume_ratio, df)
        dimensions.append(ScoringDimension(
            name='VD',
            score=vd_score,
            max_score=5.0,
            details=vd_details
        ))

        # Dimension 3: Rebound Setup (RB) - 6 points max
        rb_score, rb_details = self._calculate_rb(ind, df, clv, symbol,
                                                   sr_levels, nearest_support, distance_pct)
        dimensions.append(ScoringDimension(
            name='RB',
            score=rb_score,
            max_score=6.0,
            details=rb_details
        ))

        return dimensions

    def _calculate_support_touches(self, df: pd.DataFrame, support_level: float, atr: float) -> Dict:
        """
        Calculate support touches within tolerance (+/-0.5 ATR).
        Tracks touch_dates list for recency-based filtering.
        """
        tolerance = atr * self.PARAMS['support_tolerance_atr']
        touches = 0
        last_touch_idx = None
        bounce_strengths = []
        touch_dates = []

        lookback = min(63, len(df) - 1)

        for i in range(1, lookback + 1):
            idx = -(i + 1)
            if idx < -len(df):
                break

            low = df['low'].iloc[idx]
            close = df['close'].iloc[idx]
            open_price = df['open'].iloc[idx]

            if abs(low - support_level) <= tolerance or low <= support_level + tolerance:
                touches += 1
                last_touch_idx = i
                touch_dates.append(i)

                if close > open_price:
                    strength = (close - open_price) / open_price * 100
                    bounce_strengths.append(min(strength, 5.0))

        avg_bounce = sum(bounce_strengths) / len(bounce_strengths) if bounce_strengths else 0

        return {
            'touches': touches,
            'last_touch_days': last_touch_idx if last_touch_idx else 90,
            'avg_bounce_strength': avg_bounce,
            'bounce_count': len(bounce_strengths),
            'touch_dates': touch_dates,
        }

    def _calculate_recency_weight(self, days_since_touch: int) -> float:
        """Calculate recency weight with time decay."""
        if days_since_touch <= 30:
            return 1.0
        elif days_since_touch <= 60:
            return 0.7
        elif days_since_touch <= 90:
            return 0.5
        else:
            return 0.3

    def _calculate_sector_alpha(self, symbol: str, current_price: float, atr: float) -> float:
        """Check if sector ETF is also near support (confluence bonus)."""
        # Try phase0_data sector first
        phase0_data = getattr(self, 'phase0_data', {})
        p0 = phase0_data.get(symbol, {}) if phase0_data else {}
        sector = p0.get('sector', '')

        # Fall back to stock_info
        if not sector and symbol in self.stock_info:
            sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')

        if not sector or sector == 'Unknown' or sector not in SECTOR_ETFS:
            return 0.0
        if sector == 'Unknown' or sector not in SECTOR_ETFS:
            return 0.0

        etf_symbol = SECTOR_ETFS[sector]
        if etf_symbol not in self.sector_etf_data:
            return 0.0

        etf_df = self.sector_etf_data[etf_symbol]
        if len(etf_df) < 20:
            return 0.0

        etf_price = etf_df['close'].iloc[-1]

        calc = SupportResistanceCalculator(etf_df)
        etf_sr = calc.calculate_all()
        etf_supports = etf_sr.get('support', [])

        if not etf_supports:
            return 0.0

        etf_supports_below = [s for s in etf_supports if s < etf_price]
        if not etf_supports_below:
            return 0.0

        nearest_etf_support = max(etf_supports_below)
        etf_distance = abs(etf_price - nearest_etf_support) / etf_price

        if etf_distance < self.PARAMS['max_distance_from_support']:
            return 1.0

        return 0.0

    def _calculate_sq(self, df: pd.DataFrame, ind: TechnicalIndicators,
                      nearest_support: float, support_touches: Dict,
                      recency_weight: float) -> Tuple[float, Dict]:
        """Calculate SQ dimension with support data passed in (no redundant S/R)."""
        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
        distance_pct = abs(current_price - nearest_support) / current_price

        return self._calculate_sq_base(
            distance_pct, support_touches, recency_weight,
            0.0, atr, ind, df
        )

    def _calculate_sq_base(
        self,
        distance_pct: float,
        support_touches: Dict,
        recency_weight: float,
        sector_alpha: float,
        atr: float,
        ind: TechnicalIndicators,
        df: pd.DataFrame
    ) -> Tuple[float, Dict]:
        """
        Support Quality (SQ) - 4 points max (v8.0).
        Touch frequency + Bounce strength + Sector Alpha.
        Distance scoring moved to RB to avoid double-counting.
        """
        details = {
            'distance_pct': distance_pct,
            'touches': support_touches['touches'],
            'recency_weight': recency_weight,
            'last_touch_days': support_touches['last_touch_days'],
            'avg_bounce_strength': support_touches['avg_bounce_strength'],
            'bounce_count': support_touches['bounce_count'],
            'sector_alpha': sector_alpha
        }

        sq_score = 0.0

        # 1. Touch frequency (0-2.0 pts) -- increased from 1.5
        touches = support_touches['touches']
        if touches >= 3:
            sq_score += 2.0
        elif touches == 2:
            sq_score += 1.3
        elif touches == 1:
            sq_score += 0.7

        # Apply recency weight to touch score
        sq_score = round(sq_score * recency_weight, 2)

        # 2. Bounce strength (0-2.0 pts) -- increased from 1.5
        avg_bounce = support_touches['avg_bounce_strength']
        if avg_bounce >= 2.0:
            sq_score += 2.0
        elif avg_bounce >= 1.0:
            sq_score += 1.3
        elif avg_bounce > 0:
            sq_score += 0.7

        # 3. Sector Alpha bonus (0-1.0 pts)
        sq_score += sector_alpha

        return round(min(4.0, sq_score), 2), details

    def _calculate_vd(self, volume_ratio: float, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        Volume Dynamics (VD) - 5 points max.
        3-phase pattern: Breakdown Volume -> Dry-up -> Surge
        - Phase 1 (0-1.5 pts): LOW volume on breakdown = false breakdown (bullish)
        - Phase 2 (0-1.5 pts): Current volume < 0.6x avg (selling exhaustion)
        - Phase 3 (0-2.0 pts): Volume on reclaim >= 2x avg (confirmation)
        """
        details = {
            'volume_ratio': volume_ratio,
            'phase1_breakdown_vol': 0.0,
            'phase2_dryup': 0.0,
            'phase3_surge': 0.0,
            'vd_dry_up': False
        }

        vd_score = 0.0
        vol_ma20 = df['volume'].iloc[-20:].mean() if len(df) >= 20 else df['volume'].mean()

        # Phase 1: Breakdown volume detection (look back up to 5 days)
        # v8.0: LOW volume on the breakdown dip = bullish (false breakdown)
        # HIGH volume = real breakdown = bearish = 0 pts
        breakdown_vol_score = 0.0
        for i in range(1, min(6, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break
            day_vol = df['volume'].iloc[idx]
            day_avg = df['volume'].iloc[max(-len(df), idx-20):idx].mean() if idx >= -len(df) + 20 else vol_ma20
            if day_avg > 0:
                day_ratio = day_vol / day_avg
                # Low volume = good (false breakdown)
                if day_ratio < 0.8:
                    breakdown_vol_score = 1.5
                    details['breakdown_day'] = i
                    details['breakdown_vol_ratio'] = day_ratio
                    break
                elif day_ratio < 1.0:
                    breakdown_vol_score = 1.0
                    details['breakdown_day'] = i
                    details['breakdown_vol_ratio'] = day_ratio
                    break
                elif day_ratio >= 1.5:
                    # High volume breakdown = real selling, 0 pts
                    breakdown_vol_score = 0.0
                    details['breakdown_day'] = i
                    details['breakdown_vol_ratio'] = day_ratio
                    details['real_breakdown'] = True
                    break

        details['phase1_breakdown_vol'] = round(breakdown_vol_score, 2)
        vd_score += breakdown_vol_score

        # Phase 2: Dry-up detection (current volume)
        dryup_score = 0.0
        if volume_ratio < 0.4:
            dryup_score = 1.5
            details['vd_dry_up'] = True
        elif volume_ratio < 0.6:
            dryup_score = 1.5 - (volume_ratio - 0.4) * 2.5
            details['vd_dry_up'] = True

        details['phase2_dryup'] = round(dryup_score, 2)
        vd_score += dryup_score

        # Phase 3: Surge detection (volume on reclaim >= 2x avg)
        surge_score = 0.0
        for i in range(1, min(4, len(df))):
            idx = -(i + 1)
            if idx < -len(df):
                break
            day_vol = df['volume'].iloc[idx]
            day_avg = df['volume'].iloc[max(-len(df), idx-20):idx].mean() if idx >= -len(df) + 20 else vol_ma20
            if day_avg > 0:
                day_ratio = day_vol / day_avg
                if day_ratio >= 3.0:
                    surge_score = 2.0
                    details['surge_day'] = i
                    details['surge_ratio'] = day_ratio
                    break
                elif day_ratio >= 2.0:
                    surge_score = 1.0 + (day_ratio - 2.0)
                    details['surge_day'] = i
                    details['surge_ratio'] = day_ratio
                    break

        details['phase3_surge'] = round(surge_score, 2)
        vd_score += surge_score

        return round(min(5.0, vd_score), 2), details

    def _calculate_rb(self, ind: TechnicalIndicators, df: pd.DataFrame, clv: float,
                      symbol: str = '', sr_levels: Dict = None,
                      nearest_support: float = None, depth_pct: float = None) -> Tuple[float, Dict]:
        """
        Rebound Setup (RB) - 6 points max.

        v8.0: Changes:
          - Depth quality scoring (0-1.0) replaces SQ's duplicate distance scoring
          - Reclaim scoring: 1 day = full, 2-3 days = medium, 4+ days = expired
          - Accepts pre-computed S/R and support data from caller
        """
        today = df.iloc[-1]
        current_price = today['close']
        high = today['high']
        low = today['low']
        open_price = today['open']

        # Candle geometry
        total_range = high - low
        lower_shadow = min(open_price, current_price) - low if min(open_price, current_price) > low else 0

        # Days since false breakdown
        days_since_breakdown = self._calculate_days_since_breakdown_cached(
            df, nearest_support, sr_levels
        )

        # Ensure depth_pct is set
        if depth_pct is None:
            if nearest_support is None:
                if sr_levels is None:
                    sr_levels = self._get_sr_levels(df)
                supports = sr_levels.get('support', [])
                supports_below = [s for s in supports if s < current_price]
                nearest_support = max(supports_below) if supports_below else current_price * 0.99
            depth_pct = abs(current_price - nearest_support) / current_price

        # Sector alignment
        sector_alignment = self._calculate_sector_alignment(symbol)

        details = {
            'clv': clv,
            'lower_shadow_pct': 0,
            'has_hammer': False,
            'days_since_breakdown': days_since_breakdown,
            'depth_pct': depth_pct,
            'sector_alignment': sector_alignment
        }

        rb_score = 0.0

        # Hard gate - depth must be >=2%
        if depth_pct < 0.02:
            details['depth_gate_failed'] = True
            details['reclaim_score'] = 'depth_too_shallow'
            return 0.0, details

        # Reclaim timing scoring
        if days_since_breakdown <= 1:
            rb_score += 2.0
            details['reclaim_score'] = 'full'
        elif days_since_breakdown <= 3:
            rb_score += 2.0 - (days_since_breakdown - 1) * 0.5
            details['reclaim_score'] = 'medium'
        elif days_since_breakdown <= 5:
            details['reclaim_score'] = 'expired'
        else:
            details['reclaim_score'] = 'expired'

        # Lower shadow bonus (0-1.0 pts)
        if total_range > 0:
            lower_shadow_pct = lower_shadow / total_range
            details['lower_shadow_pct'] = lower_shadow_pct

            if lower_shadow_pct >= 0.6:
                rb_score += 1.0
                details['has_hammer'] = True
            elif lower_shadow_pct >= 0.4:
                rb_score += 0.7
            elif lower_shadow_pct >= 0.3:
                rb_score += 0.4

        # CLV position bonus (0-1.0 pts)
        if clv >= 0.7:
            rb_score += 1.0
        elif clv >= 0.5:
            rb_score += 0.7
        elif clv >= 0.4:
            rb_score += 0.4

        # Depth quality (0-1.0 pts) -- moved from SQ distance scoring
        if depth_pct < 0.01:
            rb_score += 1.0   # Very close to support, ideal bounce zone
        elif depth_pct < 0.02:
            rb_score += 0.7   # At depth gate boundary
        elif depth_pct < 0.05:
            rb_score += 0.4   # Moderate distance
        # depth >= 5%: 0 pts (too far from support for clean bounce)

        # Sector alignment bonus (0-1.0 pts)
        rb_score += sector_alignment

        return round(min(6.0, rb_score), 2), details

    def _calculate_sector_alignment(self, symbol: str) -> float:
        """
        Calculate sector alignment score based on sector ETF vs EMA50.
        Returns 0-1.0 points.
        """
        # Try phase0_data sector first
        phase0_data = getattr(self, 'phase0_data', {})
        p0 = phase0_data.get(symbol, {}) if phase0_data else {}
        sector = p0.get('sector', '')

        # Fall back to stock_info
        if not sector and symbol in self.stock_info:
            sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')

        if not sector or sector == 'Unknown' or sector not in SECTOR_ETFS:
            return 0.0
        if sector == 'Unknown' or sector not in SECTOR_ETFS:
            return 0.0

        etf_symbol = SECTOR_ETFS[sector]
        if etf_symbol not in self.sector_etf_data:
            return 0.0

        etf_df = self.sector_etf_data[etf_symbol]
        if len(etf_df) < 50:
            return 0.0

        etf_price = etf_df['close'].iloc[-1]
        etf_ema50 = etf_df['close'].ewm(span=50).mean().iloc[-1]

        if etf_ema50 == 0:
            return 0.0

        etf_vs_ema_pct = (etf_price - etf_ema50) / etf_ema50

        if etf_vs_ema_pct > 0.02:
            return 1.0
        elif abs(etf_vs_ema_pct) <= 0.02:
            return 0.5
        else:
            return 0.0

    def _calculate_days_since_breakdown(self, df: pd.DataFrame) -> int:
        """Calculate days since false breakdown (uncached, for external callers)."""
        sr_levels = self._get_sr_levels(df)
        supports = sr_levels.get('support', [])

        if not supports:
            return 999

        current_price = df['close'].iloc[-1]
        supports_below = [s for s in supports if s < current_price]
        if not supports_below:
            return 999

        nearest_support = max(supports_below)
        return self._find_breakdown_day(df, nearest_support)

    def _calculate_days_since_breakdown_cached(self, df: pd.DataFrame,
                                                nearest_support: float,
                                                sr_levels: Dict = None) -> int:
        """Calculate days since false breakdown using cached data."""
        if nearest_support is None:
            if sr_levels is None:
                sr_levels = self._get_sr_levels(df)
            supports = sr_levels.get('support', [])
            if not supports:
                return 999
            current_price = df['close'].iloc[-1]
            supports_below = [s for s in supports if s < current_price]
            if not supports_below:
                return 999
            nearest_support = max(supports_below)

        return self._find_breakdown_day(df, nearest_support)

    def _find_breakdown_day(self, df: pd.DataFrame, nearest_support: float) -> int:
        """Find the most recent false breakdown day."""
        if len(df) < 10:
            return 999

        current_price = df['close'].iloc[-1]
        lookback_days = min(10, len(df) - 1)
        breakdown_day = None

        for i in range(1, lookback_days + 1):
            idx = -(i + 1)
            if idx < -len(df):
                break

            low = df['low'].iloc[idx]
            close = df['close'].iloc[idx]

            if low < nearest_support and close > nearest_support:
                breakdown_day = i
                break
            elif low < nearest_support:
                for j in range(1, i):
                    check_idx = -(j + 1)
                    if check_idx >= -len(df):
                        check_close = df['close'].iloc[check_idx]
                        if check_close > nearest_support:
                            breakdown_day = j
                            break
                if breakdown_day:
                    break

        return breakdown_day if breakdown_day else 999

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, and target prices aligned with SFP pattern.
        - Entry: reclaim candle close (if fresh) or limit at support
        - Stop: breakdown wick low minus buffer
        - Target: nearest resistance or 2R (whichever is closer)
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        sr_levels = self._get_sr_levels(df)
        supports = sr_levels.get('support', [])
        resistances = sr_levels.get('resistance', [])

        supports_below = [s for s in supports if s < current_price]
        nearest_support = max(supports_below) if supports_below else current_price * 0.98

        # Determine days since breakdown for entry logic
        days_since_breakdown = self._calculate_days_since_breakdown_cached(
            df, nearest_support, sr_levels
        )

        # Entry: reclaim confirmation or limit at support
        if days_since_breakdown <= 1:
            # Fresh false breakdown, reclaim candle just formed
            # Enter at the prior (breakdown) candle's close -- confirmation entry
            prev_close = df['close'].iloc[-2]
            entry = max(prev_close, nearest_support)
        else:
            # No fresh reclaim, set limit order at support
            entry = nearest_support + atr * 0.1

        # Stop loss: breakdown wick low minus buffer
        breakdown_wick_low = None
        if days_since_breakdown <= 10 and days_since_breakdown != 999:
            bd_idx = -(days_since_breakdown + 1)
            if bd_idx >= -len(df):
                breakdown_wick_low = df['low'].iloc[bd_idx]

        if breakdown_wick_low is not None:
            stop = round(breakdown_wick_low - atr * 0.25, 2)
        else:
            stop = round(nearest_support - atr * 0.5, 2)

        # Take profit: nearest resistance or 2R, whichever is closer
        target = round(current_price + atr * self.PARAMS['target_r_multiplier'], 2)
        if resistances:
            resistances_above = [r for r in resistances if r > current_price]
            if resistances_above:
                nearest_resistance = min(resistances_above)
                target = min(nearest_resistance, target)

        entry = round(entry, 2)

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
        sq = next((d for d in dimensions if d.name == 'SQ'), None)
        vd = next((d for d in dimensions if d.name == 'VD'), None)
        rb = next((d for d in dimensions if d.name == 'RB'), None)

        position_pct = self.calculate_position_pct(tier)

        sq_details = sq.details if sq else {}
        vd_details = vd.details if vd else {}
        rb_details = rb.details if rb else {}

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"SQ:{sq.score:.2f} VD:{vd.score:.2f} RB:{rb.score:.2f}"
        ]

        # SQ details
        touches = sq_details.get('touches', 0)
        recency_weight = sq_details.get('recency_weight', 0)
        sector_alpha = sq_details.get('sector_alpha', 0)
        if sector_alpha > 0:
            reasons.append(f"Support x{touches} (w:{recency_weight}, +{sector_alpha}alpha)")
        else:
            reasons.append(f"Support x{touches} (w:{recency_weight})")

        # VD details
        vol_ratio = vd_details.get('volume_ratio', 0)
        reasons.append(f"Vol {vol_ratio:.1f}x")

        # RB details
        reclaim_days = rb_details.get('days_since_breakdown')
        if reclaim_days and reclaim_days <= 3:
            reasons.append(f"Reclaim d{reclaim_days} ({rb_details.get('reclaim_score', 'unknown')})")
        if rb_details.get('has_hammer'):
            reasons.append("Hammer candle + bounce")

        return reasons
