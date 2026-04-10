"""Strategy D: DistributionTop - Short distribution tops (v7.1).

Created from:
- DoubleTopBottom short-side logic (distribution detection)
- RangeShort sector-weak pattern

v7.1 changes:
- Removed dead market_cap filter, dollar_volume check, ADR gate
- Unified resistance detection to phase0 only (removed _detect_resistance_level)
- Replaced EMA8/EMA21 gate with EMA50 slope in TQ scoring
- Added prior trend requirement (25% rally from 52w low)
- Re-balanced TQ: EMA 2.0 + slope 0.5 + sector 1.0 + trend 0.5 = 4.0
"""
from typing import Dict, List, Tuple, Any, Optional
import logging

import pandas as pd
import numpy as np

from ..indicators import TechnicalIndicators
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType
from core.constants import SECTOR_ETFS

logger = logging.getLogger(__name__)


class DistributionTopStrategy(BaseStrategy):
    """
    Strategy D: DistributionTop v7.1
    Short-only distribution tops at multi-week highs.
    Combines DoubleTopBottom short logic + RangeShort sector-weak pattern.
    """

    NAME = "DistributionTop"
    STRATEGY_TYPE = StrategyType.D
    DESCRIPTION = "DistributionTop v7.1 - short distribution patterns"
    DIMENSIONS = ['TQ', 'RL', 'DS', 'VC']
    DIRECTION = 'short'

    PARAMS = {
        'min_listing_days': 60,
        'prior_trend_rally_pct': 0.25,  # Must have rallied >= 25% from 52w low
        'max_distance_from_ema50': 1.05,
        'volume_veto_threshold': 1.5,
        'min_touches': 2,
        'min_test_interval_days': 5,
        'breakout_threshold_atr': 0.3,
    }

    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """Filter for distribution top candidates per v7.1 spec.

        Hard gates only: listing days, regime, volume, prior trend, resistance.
        """
        if len(df) < self.PARAMS['min_listing_days']:
            return False

        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        current_price = df['close'].iloc[-1]

        # Market regime filter: in bull markets, require sector weakness
        regime = getattr(self, '_current_regime', 'neutral')
        if regime in ('bull_strong', 'bull_moderate'):
            sector_weak = self._is_sector_weak(symbol, df)
            if not sector_weak:
                logger.debug(f"DIST_REJ: {symbol} - Bull regime ({regime}) and sector not weak")
                return False

        # Liquidity gate: avg vol 20d >= 100K
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume < 100_000:
            logger.debug(f"DIST_REJ: {symbol} - Avg volume {avg_volume:,.0f} < 100K")
            return False

        # Prior trend: must have rallied >= 25% from 52w low
        low_52w = df['low'].tail(252).min() if len(df) >= 252 else df['low'].min()
        if low_52w > 0:
            rally_pct = (current_price - low_52w) / low_52w
            if rally_pct < self.PARAMS['prior_trend_rally_pct']:
                logger.debug(f"DIST_REJ: {symbol} - Rally from 52w low {rally_pct:.1%} < 25%")
                return False

        # Resistance above price required
        resistances = data.get('resistances', [])
        if not resistances:
            logger.debug(f"DistribTop_REJ: {symbol} - No resistance data in phase0")
            return False

        resistances_above = [r for r in resistances if r > current_price]
        if not resistances_above:
            logger.debug(f"DistribTop_REJ: {symbol} - No resistance above price")
            return False

        return True

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols with Phase 0 pre-filter using cached data.

        v7.1: Uses phase0_data for fast pre-filter (price near 60d high),
        only fetches DataFrames for symbols that pass the pre-filter.
        """
        logger.info("DistributionTop: Phase 0 - Using cached data for pre-filter...")

        phase0_data = getattr(self, 'phase0_data', {})
        prefiltered = []

        logger.info("DistributionTop: Phase 0.5 - Pre-filtering by 60d high proximity...")

        for symbol in symbols:
            try:
                if phase0_data and symbol in phase0_data:
                    pdata = phase0_data[symbol]
                    p = pdata.get('current_price', 0)
                    h = pdata.get('high_60d', 0)
                    if h > 0 and p > 0:
                        distance_from_high = (h - p) / h
                        if distance_from_high > 0.10:
                            logger.debug(f"DistribTop_REJ: {symbol} - Price {distance_from_high:.1%} below 60d high")
                            continue

                df = self._get_data(symbol)
                if df is None or len(df) < self.PARAMS['min_listing_days']:
                    continue

                if self.filter(symbol, df):
                    prefiltered.append(symbol)

            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue

        logger.info(f"DistributionTop: {len(prefiltered)}/{len(symbols)} passed pre-filter")

        self.market_data = {sym: self._get_data(sym) for sym in prefiltered}

        return super().screen(prefiltered, max_candidates=max_candidates)

    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate TQ, RL, DS, VC per v7.1 spec."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        resistances = data.get('resistances', [])
        nearest_resistance_distance_pct = data.get('nearest_resistance_distance_pct')

        # Build resistance level dict from phase0 data for RL/DS
        level = self._build_level_from_phase0(df, resistances)

        tq_score = self._calculate_tq(ind, df, symbol)
        rl_score = self._calculate_rl(df, level, resistances, nearest_resistance_distance_pct)
        ds_score = self._calculate_ds(df, level, resistances)
        vc_score = self._calculate_vc(df)

        return [
            ScoringDimension(name='TQ', score=tq_score, max_score=4.0, details={}),
            ScoringDimension(name='RL', score=rl_score, max_score=4.0, details={}),
            ScoringDimension(name='DS', score=ds_score, max_score=4.0, details={}),
            ScoringDimension(name='VC', score=vc_score, max_score=3.0, details={}),
        ]

    def _build_level_from_phase0(self, df: pd.DataFrame, resistances: List[float]) -> Optional[Dict]:
        """Build a resistance level dict from phase0 resistances for use in RL/DS scoring."""
        if not resistances:
            return None

        current_price = df['close'].iloc[-1]
        resistances_above = [r for r in resistances if r > current_price]
        if not resistances_above:
            return None

        level_high = min(resistances_above)

        # Estimate touches and width from recent price action near this level
        recent_highs = df['high'].tail(90)
        touches = 0
        touch_indices = []
        tolerance = level_high * 0.02  # 2% tolerance

        for i, h in enumerate(recent_highs.values):
            if abs(h - level_high) / level_high < tolerance:
                touches += 1
                touch_indices.append(i)

        if touches < self.PARAMS['min_touches']:
            return None

        atr_df = df['high'].tail(90) - df['low'].tail(90)
        atr = atr_df.ewm(span=14, adjust=False).mean().iloc[-1] if len(atr_df) >= 14 else current_price * 0.02

        # Width: range of prices at touches
        touch_prices = recent_highs.values[touch_indices] if touch_indices else [level_high]
        level_low = np.min(touch_prices)
        width_atr = (level_high - level_low) / atr if atr > 0 else 0

        avg_days = float(np.mean(np.diff(touch_indices))) if len(touch_indices) >= 2 else 0.0

        return {
            'high': float(level_high),
            'low': float(level_low),
            'touches': touches,
            'width_atr': float(width_atr),
            'avg_days_between': avg_days,
            'touch_indices': touch_indices,
        }

    def _calculate_tq(self, ind: TechnicalIndicators, df: pd.DataFrame, symbol: str = None) -> float:
        """Trend Quality - EMA alignment, EMA50 slope, sector weakness, prior trend.

        EMA alignment (0-2.0):
        - Price<EMA50 AND EMA8<EMA21 = 2.0
        - Price<EMA50 only = 1.2
        - Price>EMA50 but EMA8<EMA21 = 0.8
        - Price>EMA50 AND EMA8>EMA21 = 0

        EMA50 slope (0-0.5):
        - Declining (slope <= 0) = 0.5
        - Flat (0 < slope <= 2%) = 0.3
        - Rising (slope > 2%) = 0.0

        Sector weakness (0-1.0):
        - Sector ETF < its EMA50 = 1.0
        - Sector ETF data unavailable = 0.3
        - Sector ETF > EMA50 = 0.0

        Prior trend strength (0-0.5):
        - ret_6m > 20% = 0.5
        - 10% < ret_6m <= 20% = 0.3
        - ret_6m <= 10% = 0.0
        """
        current_price = df['close'].iloc[-1]
        ema8 = ind.indicators.get('ema', {}).get('ema8', current_price)
        ema21 = ind.indicators.get('ema', {}).get('ema21', current_price)
        ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)

        score = 0.0

        # EMA alignment (0-2.0)
        if current_price < ema50 and ema8 < ema21:
            score += 2.0
        elif current_price < ema50:
            score += 1.2
        elif current_price > ema50 and ema8 < ema21:
            score += 0.8

        # EMA50 slope (0-0.5)
        ema50_series = df['close'].ewm(span=50, adjust=False).mean()
        if len(ema50_series) >= 11:
            ema50_10d_ago = ema50_series.iloc[-11]
            if ema50_10d_ago > 0:
                slope = (ema50 - ema50_10d_ago) / ema50_10d_ago
                if slope <= 0:
                    score += 0.5
                elif slope <= 0.02:
                    score += 0.3

        # Sector weakness (0-1.0)
        sector_score = self._calculate_sector_weakness_v71(symbol, df)
        score += sector_score

        # Prior trend strength (0-0.5)
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        ret_6m = data.get('ret_6m', 0)
        if ret_6m > 0.20:
            score += 0.5
        elif ret_6m > 0.10:
            score += 0.3

        return min(4.0, score)

    def _is_sector_weak(self, symbol: str, df: pd.DataFrame) -> bool:
        """Check if the stock's sector ETF is below its EMA50.

        Used in regime filter: in bull markets, require sector weakness.
        """
        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        sector = data.get('sector', '')

        if not sector or sector not in SECTOR_ETFS:
            return True

        etf_symbol = SECTOR_ETFS[sector]

        try:
            etf_data = self.db.get_etf_cache(etf_symbol) if hasattr(self, 'db') else None
            if etf_data is None or len(etf_data) < 50:
                return True
        except Exception:
            return True

        close = etf_data['close']
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        return close.iloc[-1] < ema50

    def _calculate_sector_weakness_v71(self, symbol: str, df: pd.DataFrame) -> float:
        """Sector weakness scoring for TQ dimension (0-1.0).

        v7.1: Reduced from 1.5 to 1.0 to make room for EMA50 slope and prior trend.
        """
        if symbol is None:
            return 0.3

        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        sector = data.get('sector', '')

        if not sector or sector not in SECTOR_ETFS:
            return 0.3

        etf_symbol = SECTOR_ETFS[sector]

        try:
            etf_data = self.db.get_etf_cache(etf_symbol) if hasattr(self, 'db') else None
            if etf_data is None or len(etf_data) < 50:
                return 0.3
        except Exception:
            return 0.3

        close = etf_data['close']
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        current_etf_price = close.iloc[-1]

        if current_etf_price < ema50:
            return 1.0

        return 0.0

    def _calculate_rl(self, df: pd.DataFrame, level: Optional[Dict] = None,
                      resistances: List[float] = None,
                      nearest_resistance_distance_pct: float = None) -> float:
        """Resistance Level quality - touches, interval, width."""
        if level is None:
            return 0.0

        score = 0.0

        # Touch count (0-1.5)
        touches = level['touches']
        if touches >= 5:
            score += 1.5
        elif touches == 4:
            score += 1.2
        elif touches == 3:
            score += 0.8
        elif touches == 2:
            score += 0.3

        # Interval quality (0-1.5)
        score += self._calculate_rl_interval_score(level)

        # Width (0-1.0) - tighter is better
        width_atr = level['width_atr']
        if 0.0 < width_atr < 0.5:
            score += 1.0
        elif 1.0 <= width_atr <= 2.5:
            score += 1.0
        elif 0.5 <= width_atr < 1.0:
            score += 0.5
        elif width_atr > 3.0:
            score += 0.3

        return min(4.0, score)

    def _calculate_rl_interval_score(self, level: Dict) -> float:
        """Calculate RL interval score.

        >=14d = 1.5, 7-14d = 0.8-1.5, 5-7d = 0.3-0.8, <5d = 0
        """
        avg_days = level.get('avg_days_between', 0)

        if avg_days >= 14:
            return 1.5
        elif 7 <= avg_days < 14:
            return 0.8 + (avg_days - 7) / 7 * 0.7
        elif 5 <= avg_days < 7:
            return 0.3 + (avg_days - 5) / 2 * 0.5
        else:
            return 0.0

    def _calculate_ds(self, df: pd.DataFrame, level: Optional[Dict] = None,
                      resistances: List[float] = None) -> float:
        """Distribution Signs - heavy volume on failed up-days at resistance + price action exhaustion."""
        if level is None:
            return 0.0

        recent = df.tail(30)
        avg_volume = df['volume'].tail(20).mean()
        level_high = level['high']

        # Count heavy volume days that close lower (distribution)
        heavy_vol_lower_close_days = 0
        for idx, row in recent.iterrows():
            if row['close'] < row['open'] and row['volume'] > avg_volume * 1.5:
                if abs(row['high'] - level_high) / level_high < 0.02:
                    heavy_vol_lower_close_days += 1

        # Score heavy volume on lower-close days (0-2.0)
        if heavy_vol_lower_close_days >= 3:
            vol_score = 2.0
        elif heavy_vol_lower_close_days == 2:
            vol_score = 1.3
        elif heavy_vol_lower_close_days == 1:
            vol_score = 0.6
        else:
            vol_score = 0.0

        # Price action exhaustion detection (0-2.0)
        price_action_signals = self._detect_price_action_exhaustion(df, level)
        signal_count = len(price_action_signals)

        if signal_count >= 3:
            pa_score = 2.0
        elif signal_count == 2:
            pa_score = 1.5
        elif signal_count == 1:
            pa_score = 0.8
        else:
            pa_score = 0.0

        return min(4.0, vol_score + pa_score)

    def _detect_price_action_exhaustion(self, df: pd.DataFrame, level: Dict) -> List[str]:
        """Detect price action exhaustion patterns at resistance."""
        signals = []
        recent_10d = df.tail(10).reset_index(drop=True)
        level_high = level['high']

        for idx, row in recent_10d.iterrows():
            open_p = row['open']
            high_p = row['high']
            low_p = row['low']
            close_p = row['close']

            if abs(high_p - level_high) / level_high > 0.03:
                continue

            body = abs(close_p - open_p)
            upper_shadow = high_p - max(open_p, close_p)

            # Shooting star: upper shadow >= 2x body, CLV > 0.7
            if body > 0 and upper_shadow >= 2 * body:
                clv = ((close_p - low_p) - (high_p - close_p)) / (high_p - low_p) if (high_p - low_p) > 0 else 0
                if clv > 0.7:
                    signals.append(f"shooting_star_day{idx}")
                    continue

            # Long upper wick: upper shadow >= 3x body
            if body > 0 and upper_shadow >= 3 * body:
                signals.append(f"long_wick_day{idx}")
                continue

            # Failed breakout: breaks above resistance but closes below
            if high_p > level_high and close_p < level_high:
                signals.append(f"failed_breakout_day{idx}")
                continue

            # Gap fade: gap up but closes near low
            if idx > 0:
                prev_close = recent_10d.iloc[idx - 1]['close']
                gap_pct = (open_p - prev_close) / prev_close
                if gap_pct > 0.005:
                    day_range = high_p - low_p
                    if day_range > 0:
                        close_position = (close_p - low_p) / day_range
                        if close_position < 0.3:
                            signals.append(f"gap_fade_day{idx}")
                            continue

        return signals

    def _calculate_vc(self, df: pd.DataFrame) -> float:
        """Volume Confirmation - breakdown surge and follow-through per v7.1 spec.

        Base score (0-2.0) from volume ratio:
        - >=2.5x = 2.0
        - 1.8-2.5x = 1.3-2.0 (interpolated)
        - 1.2-1.8x = 0.5-1.3 (interpolated)
        - <1.2x = 0

        Follow-through (0-1.0):
        - 2 down-days in last 2 sessions = +1.0

        Returns max 3.0.
        """
        recent_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()

        if avg_volume == 0:
            return 0.0

        volume_ratio = recent_volume / avg_volume

        # Base volume score (0-2.0)
        if volume_ratio >= 2.5:
            base_score = 2.0
        elif volume_ratio >= 1.8:
            base_score = 1.3 + (volume_ratio - 1.8) / 0.7 * 0.7
        elif volume_ratio >= 1.2:
            base_score = 0.5 + (volume_ratio - 1.2) / 0.6 * 0.8
        else:
            base_score = 0.0

        # Follow-through (+1.0 if 2 down-days within 2 sessions)
        follow_through_score = 0.0
        if len(df) >= 3:
            down_days_count = 0
            for i in range(1, 3):
                if df['close'].iloc[-i] < df['open'].iloc[-i]:
                    down_days_count += 1
            if down_days_count >= 2:
                follow_through_score = 1.0

        return min(3.0, base_score + follow_through_score)

    def calculate_entry_exit(self, symbol: str, df: pd.DataFrame,
                            dimensions: List[ScoringDimension],
                            score: float, tier: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Calculate entry, stop, target for short position.

        v7.1 Entry rules:
        - Close < resistance - 0.3x ATR
        - Vol >= 1.5x avg20d
        - CLV <= 0.35
        - Not within 5d of earnings
        """
        current_price = df['close'].iloc[-1]
        high = df['high'].iloc[-1]
        low = df['low'].iloc[-1]
        ind = TechnicalIndicators(df)
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        resistances = data.get('resistances', [])

        if resistances:
            resistances_above = [r for r in resistances if r > current_price]
            resistance_high = min(resistances_above) if resistances_above else df['high'].tail(20).max()
        else:
            resistance_high = df['high'].tail(20).max()

        # Entry condition 1: Close < resistance - 0.3x ATR
        entry_threshold = resistance_high - 0.3 * atr
        if current_price > entry_threshold:
            return None, None, None

        # Entry condition 2: Vol >= 1.5x avg20d
        avg_volume = df['volume'].tail(20).mean()
        if avg_volume > 0 and df['volume'].iloc[-1] < avg_volume * 1.5:
            return None, None, None

        # Entry condition 3: CLV <= 0.35
        if high - low > 0:
            clv = ((current_price - low) - (high - current_price)) / (high - low)
        else:
            clv = 0.5
        if clv > 0.35:
            return None, None, None

        # Entry condition 4: Not within 5d of earnings
        days_to_earnings = data.get('days_to_earnings')
        if days_to_earnings is not None and 0 <= days_to_earnings <= 5:
            return None, None, None

        entry = round(current_price, 2)
        stop = round(min(resistance_high + 0.5 * atr, entry * 1.05), 2)
        risk = stop - entry
        target = round(entry - risk * 2.5, 2)

        return entry, stop, target

    def build_match_reasons(self, symbol: str, df: pd.DataFrame,
                           dimensions: List[ScoringDimension],
                           score: float, tier: str) -> List[str]:
        """Build human-readable match reasons."""
        tq = next((d for d in dimensions if d.name == 'TQ'), None)
        rl = next((d for d in dimensions if d.name == 'RL'), None)
        ds = next((d for d in dimensions if d.name == 'DS'), None)
        vc = next((d for d in dimensions if d.name == 'VC'), None)

        position_pct = self.calculate_position_pct(tier)

        phase0_data = getattr(self, 'phase0_data', {})
        data = phase0_data.get(symbol, {})
        nearest_resistance_distance_pct = data.get('nearest_resistance_distance_pct')

        reasons = [
            f"Score: {score:.2f}/15 (Tier {tier}-{position_pct*100:.0f}%)",
            f"TQ:{tq.score:.2f} RL:{rl.score:.2f} DS:{ds.score:.2f} VC:{vc.score:.2f}"
        ]

        if nearest_resistance_distance_pct is not None:
            reasons.append(f"Resistance distance: {nearest_resistance_distance_pct:.1%}")

        return reasons
