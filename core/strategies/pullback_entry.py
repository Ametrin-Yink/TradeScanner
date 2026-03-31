"""Strategy C: Shoryuken v3.0 - Institutional Grade Scoring System."""
from typing import Dict, List, Optional, Tuple, Any
import logging

import pandas as pd

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

logger = logging.getLogger(__name__)


class ShoryukenStrategy(BaseStrategy):
    """Strategy C: Shoryuken v3.0 - Pullback to EMA with 4D scoring."""

    NAME = "Shoryuken"
    STRATEGY_TYPE = StrategyType.SHORYUKEN
    DESCRIPTION = "Shoryuken v3.0 - Institutional Grade Pullback System"
    DIMENSIONS = ['TI', 'RS', 'VC', 'BONUS']

    # Shoryuken Parameters
    PARAMS = {
        'min_data_days': 50,
        'ema21_slope_threshold': 0.4,  # Minimum normalized slope
        'max_retracement_range': 0.08,  # 8% max range for structure
        'ema8_penetration_tolerance': 0.985,  # 1.5% below EMA8 allowed
        'volume_dry_threshold': 0.7,  # <70% of 20d avg
        'volume_surge_threshold': 1.5,  # >150% of 20d avg
        'gap_veto_threshold': 0.8,  # 0.8 ATR gap = veto
        'atr_initial_stop': 1.2,  # Initial stop: 1.2x ATR
        'position_tiers': {
            'S': {'min_score': 12, 'position_pct': 0.20, 'label': 'Apex'},
            'A': {'min_score': 9, 'position_pct': 0.10, 'label': 'Strong'},
            'B': {'min_score': 7, 'position_pct': 0.05, 'label': 'Speculative'},
            'C': {'min_score': 0, 'position_pct': 0.00, 'label': 'Reject'}
        }
    }

    def __init__(self, fetcher=None, db=None):
        """Initialize strategy with market ATR cache."""
        super().__init__(fetcher=fetcher, db=db)
        self.market_atr_median = 0.0
        self.sector_counts = {}
        self.stock_info = {}

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 market statistics calculation.

        Args:
            symbols: List of stock symbols

        Returns:
            List of StrategyMatch objects
        """
        # Phase 0: Calculate market-wide statistics
        logger.info("Shoryuken v3.0: Calculating market statistics...")

        all_atrs = []
        symbol_data = {}

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < self.PARAMS['min_data_days']:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            atr = ind.indicators.get('atr', {}).get('atr', 0)
            if atr > 0:
                all_atrs.append(atr)

            symbol_data[symbol] = {'df': df, 'ind': ind}

        if not all_atrs:
            logger.warning("Shoryuken: No valid ATR data found")
            return []

        self.market_atr_median = sorted(all_atrs)[len(all_atrs) // 2]
        logger.info(f"Shoryuken: Market ATR median = {self.market_atr_median:.2f}, "
                    f"Processing {len(symbol_data)} symbols")

        # Phase 0.5: Pre-filter by EMA21 trend (price > EMA21 and slope > 0)
        logger.info("Shoryuken: Phase 0.5 - Pre-filtering by EMA21 trend...")
        prefiltered_symbols = []
        symbols_to_remove = []  # Collect symbols to remove after iteration

        # Use list() to create a copy for safe iteration
        for symbol, data in list(symbol_data.items()):
            try:
                df = data['df']
                ind = data['ind']

                # Check price above EMA21
                current_price = df['close'].iloc[-1]
                ema21 = ind.indicators.get('ema', {}).get('ema21', 0)

                # Check EMA21 slope (current vs 5 days ago)
                ema21_5d_ago = df['close'].ewm(span=21).mean().iloc[-6] if len(df) >= 6 else ema21 * 0.99
                ema_slope = ema21 - ema21_5d_ago if ema21 and ema21_5d_ago else 0

                if current_price > ema21 and ema_slope > 0:
                    prefiltered_symbols.append(symbol)
                else:
                    # Mark for removal after iteration
                    symbols_to_remove.append(symbol)
            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                symbols_to_remove.append(symbol)
                continue

        # Remove filtered out symbols after iteration
        for symbol in symbols_to_remove:
            symbol_data.pop(symbol, None)


        logger.info(f"Shoryuken: {len(prefiltered_symbols)}/{len(symbol_data) + len(prefiltered_symbols)} passed EMA21 trend pre-filter")

        # Get industry data for sector bonus
        try:
            if self.fetcher:
                self.stock_info = self.fetcher.fetch_batch_stock_info(list(symbol_data.keys()))
                self.sector_counts = {}
                for info in self.stock_info.values():
                    sector = info.get('sector', 'Unknown')
                    self.sector_counts[sector] = self.sector_counts.get(sector, 0) + 1
        except Exception as e:
            logger.warning(f"Could not fetch sector data: {e}")
            self.stock_info = {}
            self.sector_counts = {}

        # Cache market data for use in filter/calculate_dimensions
        self.market_data = {sym: data['df'] for sym, data in symbol_data.items()}

        # Call parent screen method
        matches = super().screen(list(symbol_data.keys()))

        # Sort by confidence and limit to 5 per tier for diversity
        scored_candidates = []
        for match in matches:
            scored_candidates.append({
                'match': match,
                'score': match.technical_snapshot.get('score', 0),
                'tier': match.technical_snapshot.get('tier', 'C')
            })

        scored_candidates.sort(key=lambda x: x['score'], reverse=True)

        # Limit 5 per tier
        tier_limits = {'S': 5, 'A': 5, 'B': 5}
        tier_current = {'S': 0, 'A': 0, 'B': 0}

        filtered_matches = []
        for cand in scored_candidates:
            tier = cand['tier']
            if tier in tier_current and tier_current[tier] >= tier_limits[tier]:
                continue
            tier_current[tier] = tier_current.get(tier, 0) + 1
            filtered_matches.append(cand['match'])

        return filtered_matches

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        Filter symbols based on Shoryuken criteria with Phase 0 fast pre-filter.
        """
        # Phase 0: Fast pre-filter (O(1) checks before expensive calculations)
        current_price = df['close'].iloc[-1]

        # Skip penny stocks and extreme prices
        if current_price < 2.0 or current_price > 3000.0:
            return False

        # Skip low volume stocks (avg volume < 100K)
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume < 100000:
            return False

        # Skip insufficient data
        if len(df) < self.PARAMS['min_data_days']:
            return False

        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # Calculate TI score for filtering
        ti_data = ind.calculate_normalized_ema_slope(self.market_atr_median)
        ti_score = ti_data['score']

        # Filter out weak trends
        if ti_score == 0:
            return False

        # Calculate RS score for filtering
        rs_data = ind.calculate_retracement_structure()
        rs_score = rs_data['total_score']

        # Filter out poor structure
        if rs_score <= 0:
            return False

        # Check gap veto
        gap_data = ind.estimate_gap_impact()
        if not gap_data['is_valid']:
            return False

        return True

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """
        Calculate 4-dimensional scoring (TI, RS, VC, Bonus).

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            List of ScoringDimension objects
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        dimensions = []

        # Dimension 1: Trend Intensity (TI) - 0-5 points
        ti_data = ind.calculate_normalized_ema_slope(self.market_atr_median)
        ti_score = ti_data['score']

        # Calculate EMA21 touch count (deduct for multiple touches) - VECTORIZED
        ema21 = ind.indicators.get('ema', {}).get('ema21', 0)
        touch_count = 0
        if ema21 > 0:
            # Vectorized: Count how many times price crossed below EMA21 in last 20 days
            last_20 = df.tail(20)
            touched = (last_20['low'] <= ema21) & (last_20['close'] > ema21 * 0.99)
            touch_count = touched.sum()

        # Deduct TI score for multiple touches (first touch is best)
        touch_deduction = min(1.5, (touch_count - 1) * 0.5) if touch_count > 1 else 0
        ti_score = max(0, ti_score - touch_deduction)

        dimensions.append(ScoringDimension(
            name='TI',
            score=ti_score,
            max_score=5.0,
            details={
                'slope_norm': ti_data.get('slope_norm', 0),
                'slope_raw': ti_data.get('slope_raw', 0),
                'ema21_today': ti_data.get('ema21_today', 0),
                'ema21_t5': ti_data.get('ema21_t5', 0),
                'atr14': ti_data.get('atr14', 0),
                'ema21_touch_count': touch_count,
                'touch_deduction': touch_deduction
            }
        ))

        # Dimension 2: Retracement Structure (RS) - 0-5 points
        rs_data = ind.calculate_retracement_structure()
        rs_score = rs_data['total_score']
        dimensions.append(ScoringDimension(
            name='RS',
            score=rs_score,
            max_score=5.0,
            details={
                'tightness_score': rs_data.get('tightness_score', 0),
                'support_score': rs_data.get('support_score', 0),
                'price_range_pct': rs_data.get('price_range_pct', 0),
                'ema8_current': rs_data.get('ema8_current', 0),
                'low_min': rs_data.get('low_min', 0)
            }
        ))

        # Dimension 3: Volume Confirmation (VC) - 0-5 points
        vc_data = ind.calculate_volume_confirmation()
        vc_score = vc_data['total_score']
        dimensions.append(ScoringDimension(
            name='VC',
            score=vc_score,
            max_score=5.0,
            details={
                'v_dry': vc_data.get('v_dry', 0),
                'dry_score': vc_data.get('dry_score', 0),
                'v_surge': vc_data.get('v_surge', 0),
                'surge_score': vc_data.get('surge_score', 0),
                'vol_today': vc_data.get('vol_today', 0),
                'vol_20d_avg': vc_data.get('vol_20d_avg', 0)
            }
        ))

        # Dimension 4: Environment Bonus - +2/-10 points
        bonus_score = 0

        # Sector resonance bonus (+2 when same sector >= 3 stocks)
        sector = self.stock_info.get(symbol, {}).get('sector', 'Unknown')
        if sector != 'Unknown' and self.sector_counts.get(sector, 0) >= 3:
            bonus_score += 2

        # Gap estimation
        gap_data = ind.estimate_gap_impact()
        bonus_score += gap_data.get('score', 0)

        dimensions.append(ScoringDimension(
            name='BONUS',
            score=bonus_score,
            max_score=2.0,
            details={
                'sector': sector,
                'sector_count': self.sector_counts.get(sector, 0),
                'gap_estimate_pct': gap_data.get('gap_estimate_pct', 0),
                'gap_score': gap_data.get('score', 0)
            }
        ))

        return dimensions

    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """
        Calculate entry, stop, and target prices with 4-stage exit system.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            dimensions: Dimension scores
            score: Total score
            tier: Tier (S/A/B/C)

        Returns:
            Tuple of (entry_price, stop_loss, take_profit)
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        entry_price = round(current_price, 2)

        # Dynamic stop loss: Platform low or EMA21 - ATR
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price * 0.95)
        platform_low = df['low'].tail(5).min()
        stop_candidates = [
            platform_low,
            ema21 - atr,
            entry_price - atr * self.PARAMS['atr_initial_stop']
        ]
        stop_loss = round(min(stop_candidates), 2)

        # Risk for position sizing reference
        risk = entry_price - stop_loss

        # Reference target (3R)
        target = round(entry_price + risk * 3, 2)

        return entry_price, stop_loss, target

    def build_match_reasons(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> List[str]:
        """Build human-readable match reasons."""
        ti = next((d for d in dimensions if d.name == 'TI'), None)
        rs = next((d for d in dimensions if d.name == 'RS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        position_pct = self.calculate_position_pct(tier)

        reasons = [
            f"Score: {score:.0f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TI:{ti.score if ti else 0} RS:{rs.score if rs else 0} "
            f"VC:{vc.score if vc else 0} B:{bonus.score if bonus else 0}"
        ]

        # Add TI detail
        if ti and 'slope_norm' in ti.details:
            reasons.append(f"EMA21 slope: {ti.details['slope_norm']:.2f}")

        # Add RS detail
        if rs and 'price_range_pct' in rs.details:
            reasons.append(f"Range: {rs.details['price_range_pct']:.1f}%")

        # Add VC detail
        if vc and 'v_dry' in vc.details:
            reasons.append(f"Vol dry: {vc.details['v_dry']:.2f}x")

        # Add sector info
        if bonus and bonus.details.get('sector') and bonus.details['sector'] != 'Unknown':
            reasons.append(f"Sector: {bonus.details['sector']}")

        return reasons

    def build_snapshot(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Dict[str, Any]:
        """
        Build technical snapshot with 4-stage exit logic.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            dimensions: Dimension scores
            score: Total score
            tier: Tier (S/A/B/C)

        Returns:
            Dict with technical snapshot data
        """
        snapshot = super().build_snapshot(symbol, df, dimensions, score, tier)

        # Get indicators for exit calculations
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # Entry price
        entry_price = round(current_price, 2)

        # Calculate stop loss
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price * 0.95)
        platform_low = df['low'].tail(5).min()
        stop_candidates = [
            platform_low,
            ema21 - atr,
            entry_price - atr * self.PARAMS['atr_initial_stop']
        ]
        stop_loss = round(min(stop_candidates), 2)

        risk = entry_price - stop_loss

        # 4-Stage Exit System
        # Stage 1: Initial stop (already in stop_loss)

        # Stage 2: Lock-profit at Entry + 0.5R when profit = 2.5R
        lock_profit_trigger = entry_price + risk * 2.5
        lock_profit_stop = entry_price + risk * 0.5

        # Stage 3: Trend exit: EMA10 or Chandelier 3x ATR
        ema8 = ind.indicators.get('ema', {}).get('ema8')
        chandelier_stop = ind.calculate_chandelier_exit(
            entry_price, entry_price, atr, 3.0
        )

        # Stage 4: Acceleration exit: Close below EMA5 when >20% from EMA21
        ema21_val = ind.indicators.get('ema', {}).get('ema21', current_price)
        acceleration_trigger = ema21_val * 1.20

        # Add 4-stage exit system to snapshot
        snapshot.update({
            'lock_profit_trigger': lock_profit_trigger,
            'lock_profit_stop': lock_profit_stop,
            'chandelier_stop': chandelier_stop,
            'acceleration_trigger': acceleration_trigger,
            'ema10': ema8,  # Use EMA8 as proxy for EMA10
            'atr': atr,
            'dynamic_exit_notes': (
                'Initial:1.2xATR | Lock:+2.5R->+0.5R | '
                'Trend:EMA10/3xATR | Accel:EMA5 when>20%'
            )
        })

        # Add dimension-specific details
        ti = next((d for d in dimensions if d.name == 'TI'), None)
        rs = next((d for d in dimensions if d.name == 'RS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)
        bonus = next((d for d in dimensions if d.name == 'BONUS'), None)

        if ti:
            snapshot['ema21_slope_norm'] = ti.details.get('slope_norm', 0)

        if rs:
            snapshot['retracement_range_pct'] = rs.details.get('price_range_pct', 0)

        if vc:
            snapshot['volume_dry_ratio'] = vc.details.get('v_dry', 0)
            snapshot['volume_surge_ratio'] = vc.details.get('v_surge', 0)

        if bonus:
            snapshot['sector'] = bonus.details.get('sector', 'Unknown')
            snapshot['gap_estimate_pct'] = bonus.details.get('gap_estimate_pct', 0)

        return snapshot
