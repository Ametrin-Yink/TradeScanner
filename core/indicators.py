"""Technical indicators calculator with caching."""
import numpy as np
import pandas as pd
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass
class IndicatorValues:
    """Container for calculated indicators."""
    ema8: Optional[float] = None
    ema21: Optional[float] = None
    ema50: Optional[float] = None
    atr: Optional[float] = None
    adr: Optional[float] = None
    adr_pct: Optional[float] = None
    rsi: Optional[float] = None
    volume_sma: Optional[float] = None
    volume_spike: bool = False
    daily_range: Optional[float] = None


class TechnicalIndicators:
    """Calculate technical indicators for stock analysis with caching."""

    # Class-level cache for indicator calculations
    _cache: Dict[str, Dict] = {}
    _cache_hits: int = 0
    _cache_misses: int = 0
    _cache_lock = threading.Lock()

    def __init__(self, df: pd.DataFrame, symbol: str = None):
        """
        Initialize with OHLCV data.

        Args:
            df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
            symbol: Stock symbol (optional, for logging purposes)
        """
        self.df = df.copy()
        self.symbol = symbol or "UNKNOWN"
        self.indicators: Dict[str, any] = {}

    def calculate_all(self) -> Dict[str, any]:
        """
        Calculate all technical indicators with caching.

        Returns:
            Dict with all indicator values
        """
        if len(self.df) < 50:
            logger.warning(f"Insufficient data: {len(self.df)} rows, need at least 50")
            return {}

        # Generate cache key
        cache_key = self._get_cache_key()

        # Check cache
        with TechnicalIndicators._cache_lock:
            if cache_key in TechnicalIndicators._cache:
                TechnicalIndicators._cache_hits += 1
                self.indicators = TechnicalIndicators._cache[cache_key]
                logger.debug(f"Indicator cache hit for {self.symbol} (hits: {self._cache_hits})")
                return self.indicators

        # Cache miss - calculate
        with TechnicalIndicators._cache_lock:
            TechnicalIndicators._cache_misses += 1
        logger.debug(f"Indicator cache miss for {self.symbol} (misses: {self._cache_misses})")

        self.indicators = {
            'ema': self._calculate_emas(),
            'atr': self._calculate_atr(),
            'adr': self._calculate_adr(),
            'rsi': self._calculate_rsi(),
            'volume': self._calculate_volume_metrics(),
            'price_metrics': self._calculate_price_metrics(),
        }

        # Store in cache
        with TechnicalIndicators._cache_lock:
            TechnicalIndicators._cache[cache_key] = self.indicators

        return self.indicators

    def _get_cache_key(self) -> str:
        """Generate cache key based on data characteristics."""
        if len(self.df) == 0:
            return "empty_data"

        # Use data characteristics to generate unique key
        # This avoids needing the symbol - same data = same key
        last_date = str(self.df.index[-1])
        first_date = str(self.df.index[0])
        rows = len(self.df)
        last_close = self.df['close'].iloc[-1]
        last_volume = self.df['volume'].iloc[-1]

        return f"{first_date}_{last_date}_{rows}_{last_close}_{last_volume}"

    @classmethod
    def get_cache_stats(cls) -> Dict[str, int]:
        """Get cache statistics."""
        total = cls._cache_hits + cls._cache_misses
        return {
            'hits': cls._cache_hits,
            'misses': cls._cache_misses,
            'total': total,
            'hit_rate': round(cls._cache_hits / total * 100, 2) if total > 0 else 0,
            'cached_items': len(cls._cache)
        }

    @classmethod
    def clear_cache(cls):
        """Clear the indicator cache."""
        stats = cls.get_cache_stats()
        cls._cache.clear()
        cls._cache_hits = 0
        cls._cache_misses = 0
        logger.info(f"Indicator cache cleared. Stats: {stats}")

    def _calculate_emas(self) -> Dict[str, Optional[float]]:
        """Calculate EMA8, EMA21, EMA50, EMA200."""
        close = self.df['close']

        ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1] if len(close) >= 8 else None
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1] if len(close) >= 21 else None
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1] if len(close) >= 50 else None
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if len(close) >= 200 else None

        return {
            'ema8': float(ema8) if ema8 is not None else None,
            'ema21': float(ema21) if ema21 is not None else None,
            'ema50': float(ema50) if ema50 is not None else None,
            'ema200': float(ema200) if ema200 is not None else None,
        }

    def _calculate_atr(self, period: int = 14) -> Dict[str, Optional[float]]:
        """
        Calculate Average True Range (ATR).

        Args:
            period: ATR calculation period (default 14)

        Returns:
            Dict with ATR value
        """
        if len(self.df) < period + 1:
            return {'atr': None, 'atr_pct': None}

        high = self.df['high']
        low = self.df['low']
        close = self.df['close']

        # Calculate True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Calculate ATR
        atr = true_range.ewm(span=period, adjust=False).mean().iloc[-1]

        # ATR as percentage of current price (return decimal, not percentage)
        current_price = close.iloc[-1]
        if current_price <= 0:
            return {'atr': atr, 'atr_pct': None}
        atr_pct = atr / current_price

        return {
            'atr': float(atr) if atr is not None else None,
            'atr_pct': float(atr_pct) if atr_pct is not None else None,
        }

    def _calculate_adr(self, period: int = 20) -> Dict[str, Optional[float]]:
        """
        Calculate Average Daily Range (ADR).

        ADR is the average of (high - low) over the period.
        ADR% is ADR / close * 100.

        Args:
            period: ADR calculation period (default 20)

        Returns:
            Dict with ADR values
        """
        if len(self.df) < period:
            return {'adr': None, 'adr_pct': None}

        daily_range = self.df['high'] - self.df['low']
        adr = daily_range.rolling(window=period).mean().iloc[-1]

        current_price = self.df['close'].iloc[-1]
        adr_pct = (adr / current_price) * 100 if current_price > 0 else None

        return {
            'adr': float(adr) if adr is not None else None,
            'adr_pct': float(adr_pct) if adr_pct is not None else None,
        }

    def _calculate_rsi(self, period: int = 14) -> Dict[str, Optional[float]]:
        """
        Calculate Relative Strength Index (RSI).

        Args:
            period: RSI calculation period (default 14)

        Returns:
            Dict with RSI value
        """
        if len(self.df) < period + 1:
            return {'rsi': None}

        close = self.df['close']
        delta = close.diff()

        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)

        # Calculate average gains and losses
        avg_gains = gains.rolling(window=period).mean()
        avg_losses = losses.rolling(window=period).mean()

        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))

        rsi_value = rsi.iloc[-1]

        return {
            'rsi': float(rsi_value) if pd.notna(rsi_value) else None,
        }

    def _calculate_volume_metrics(self, sma_period: int = 20) -> Dict[str, any]:
        """
        Calculate volume metrics including SMA and spike detection.

        Args:
            sma_period: Volume SMA period (default 20)

        Returns:
            Dict with volume metrics
        """
        if len(self.df) < sma_period:
            return {'volume_sma': None, 'volume_spike': False, 'volume_ratio': None}

        volume = self.df['volume']

        # Volume SMA
        volume_sma = volume.rolling(window=sma_period).mean().iloc[-1]

        # Current volume
        current_volume = volume.iloc[-1]

        # Volume ratio (current / SMA)
        volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1.0

        # Volume spike (volume > 2x average)
        volume_spike = volume_ratio > 2.0

        return {
            'volume_sma': int(volume_sma) if pd.notna(volume_sma) else None,
            'current_volume': int(current_volume),
            'volume_ratio': float(volume_ratio),
            'volume_spike': volume_spike,
        }

    def _calculate_price_metrics(self) -> Dict[str, any]:
        """Calculate various price-based metrics."""
        close = self.df['close']
        high = self.df['high']
        low = self.df['low']

        current_price = close.iloc[-1]

        # 20-day high/low
        high_20d = high.tail(20).max()
        low_20d = low.tail(20).min()

        # Distance from 20-day high
        distance_from_high = ((current_price - high_20d) / high_20d * 100) if high_20d > 0 else None

        # Distance from 20-day low
        distance_from_low = ((current_price - low_20d) / low_20d * 100) if low_20d > 0 else None

        # 60-day high
        high_60d = high.tail(60).max() if len(high) >= 60 else high.max()

        # Daily gaps in last 5 days
        gaps = 0
        for i in range(1, 6):  # 1 to 5 days back
            if len(self.df) > i + 1:
                prev_close = self.df['close'].iloc[-(i + 1)]
                curr_open = self.df['open'].iloc[-i]
                gap_pct = abs((curr_open - prev_close) / prev_close)
                if gap_pct > 0.01:  # 1% gap
                    gaps += 1

        return {
            'current_price': float(current_price),
            'high_20d': float(high_20d),
            'low_20d': float(low_20d),
            'high_60d': float(high_60d) if high_60d is not None else None,
            'distance_from_high': float(distance_from_high) if distance_from_high is not None else None,
            'distance_from_low': float(distance_from_low) if distance_from_low is not None else None,
            'gaps_5d': gaps,
        }

    def get_summary(self) -> IndicatorValues:
        """
        Get a summary of key indicator values.

        Returns:
            IndicatorValues dataclass with key metrics
        """
        if not self.indicators:
            self.calculate_all()

        ema = self.indicators.get('ema', {})
        atr_data = self.indicators.get('atr', {})
        adr_data = self.indicators.get('adr', {})
        rsi_data = self.indicators.get('rsi', {})
        volume = self.indicators.get('volume', {})

        return IndicatorValues(
            ema8=ema.get('ema8'),
            ema21=ema.get('ema21'),
            ema50=ema.get('ema50'),
            atr=atr_data.get('atr'),
            adr=adr_data.get('adr'),
            adr_pct=adr_data.get('adr_pct'),
            rsi=rsi_data.get('rsi'),
            volume_sma=volume.get('volume_sma'),
            volume_spike=volume.get('volume_spike', False),
        )

    def is_above_ema(self, period: int = 50) -> bool:
        """Check if price is above specified EMA."""
        if not self.indicators:
            self.calculate_all()

        ema_key = f'ema{period}'
        ema_value = self.indicators.get('ema', {}).get(ema_key)
        current_price = self.df['close'].iloc[-1]

        if ema_value is None:
            return False

        return current_price > ema_value

    def is_uptrend(self, short_ema: int = 8, long_ema: int = 21) -> bool:
        """Check if in uptrend (short EMA above long EMA)."""
        if not self.indicators:
            self.calculate_all()

        ema = self.indicators.get('ema', {})
        ema_short = ema.get(f'ema{short_ema}')
        ema_long = ema.get(f'ema{long_ema}')

        if ema_short is None or ema_long is None:
            return False

        return ema_short > ema_long

    def get_trend_strength(self) -> float:
        """Calculate trend strength based on EMA alignment."""
        if not self.indicators:
            self.calculate_all()

        ema = self.indicators.get('ema', {})
        ema8 = ema.get('ema8')
        ema21 = ema.get('ema21')
        ema50 = ema.get('ema50')

        if ema8 is None or ema21 is None or ema50 is None:
            return 0.0

        # Bullish alignment: 8 > 21 > 50
        if ema8 > ema21 > ema50:
            return min(100.0, ((ema8 - ema50) / ema50) * 100)

        # Bearish alignment: 8 < 21 < 50
        if ema8 < ema21 < ema50:
            return max(-100.0, -((ema50 - ema8) / ema50) * 100)

        # Mixed alignment
        return 0.0

    def detect_vcp_platform(self, lookback_range=(15, 30), max_range_pct=0.12,
                        concentration_band=0.025, concentration_threshold=0.50) -> Optional[Dict]:
        """
        Detect Volatility Contraction Pattern (VCP) platform.
        RELAXED: Uses scoring system (2 of 3 criteria) instead of strict AND gate.
        """
        if len(self.df) < lookback_range[1] + 5:
            return None

        best_platform = None
        best_score = 0

        # Try different platform lengths within range
        for platform_days in range(lookback_range[1], lookback_range[0] - 1, -1):
            platform_df = self.df.tail(platform_days)

            platform_high = platform_df['high'].max()
            platform_low = platform_df['low'].min()
            platform_range_pct = (platform_high - platform_low) / platform_low

            # CRITERION 1: Range tightness (relaxed from 12% to 15%)
            range_score = 0
            if platform_range_pct < 0.08:  # Excellent
                range_score = 3
            elif platform_range_pct < 0.12:  # Good
                range_score = 2
            elif platform_range_pct < 0.15:  # Acceptable
                range_score = 1

            # Calculate midpoint and concentration
            midpoint = (platform_high + platform_low) / 2
            upper_band = midpoint * (1 + concentration_band)
            lower_band = midpoint * (1 - concentration_band)

            # Count days with close within band
            closes_in_band = platform_df[(platform_df['close'] >= lower_band) &
                                     (platform_df['close'] <= upper_band)]
            concentration_ratio = len(closes_in_band) / platform_days

            # CRITERION 2: Concentration (relaxed from 50% to 40%)
            concentration_score = 0
            if concentration_ratio >= 0.60:
                concentration_score = 3
            elif concentration_ratio >= 0.50:
                concentration_score = 2
            elif concentration_ratio >= 0.40:
                concentration_score = 1

            # Calculate volume metrics
            platform_volume_mean = platform_df['volume'].mean()
            last_5d_volume_mean = platform_df['volume'].tail(5).mean()
            volume_contraction_ratio = last_5d_volume_mean / platform_volume_mean if platform_volume_mean > 0 else 1.0

            # CRITERION 3: Volume contraction
            volume_score = 0
            if volume_contraction_ratio < 0.50:
                volume_score = 3
            elif volume_contraction_ratio < 0.70:
                volume_score = 2
            elif volume_contraction_ratio < 0.85:
                volume_score = 1

            # RELAXED: Require 2 of 3 criteria with at least score 1 each
            total_score = range_score + concentration_score + volume_score
            criteria_met = sum([range_score > 0, concentration_score > 0, volume_score > 0])

            # DEBUG logging for VCP detection
            if platform_days == lookback_range[1]:  # Log first attempt only
                logger.debug(f"VCP_DEBUG: {self.symbol} - Range:{platform_range_pct:.3f}(s:{range_score}), "
                            f"Conc:{concentration_ratio:.2f}(s:{concentration_score}), "
                            f"Vol:{volume_contraction_ratio:.2f}(s:{volume_score}), "
                            f"Total:{total_score}, Criteria:{criteria_met}")

            # Require at least 2 criteria with minimum quality
            if criteria_met >= 2 and total_score >= 3:
                if total_score > best_score:
                    best_score = total_score
                    contraction_quality = self._calculate_contraction_quality(platform_df)

                    best_platform = {
                        'platform_days': platform_days,
                        'platform_high': float(platform_high),
                        'platform_low': float(platform_low),
                        'platform_range_pct': float(platform_range_pct),
                        'midpoint': float(midpoint),
                        'concentration_ratio': float(concentration_ratio),
                        'volume_contraction_ratio': float(volume_contraction_ratio),
                        'platform_volume_mean': float(platform_volume_mean),
                        'contraction_quality': float(contraction_quality),
                        'range_score': range_score,
                        'concentration_score': concentration_score,
                        'volume_score': volume_score,
                        'is_valid': True
                    }

        if best_platform:
            logger.debug(f"VCP_FOUND: {self.symbol} - Score:{best_score}, Days:{best_platform['platform_days']}, "
                        f"Range:{best_platform['platform_range_pct']:.3f}")
        else:
            logger.debug(f"VCP_NONE: {self.symbol} - No valid platform found")

        return best_platform

    def _calculate_contraction_quality(self, platform_df) -> float:
        """
        Calculate VCP contraction sequence quality (建议#1).

        Ideal VCP shows progressively smaller amplitude waves (volatility contraction).
        We divide platform into 3 periods and check if amplitude is decreasing.

        Returns:
            Contraction quality score 0.0-1.0 (1.0 = perfect contraction)
        """
        if len(platform_df) < 15:
            return 0.0

        # Divide platform into 3 periods (early, middle, late)
        period_size = len(platform_df) // 3
        if period_size < 3:
            return 0.5  # Default for short platforms

        amplitudes = []
        for i in range(3):
            start_idx = i * period_size
            end_idx = start_idx + period_size if i < 2 else len(platform_df)
            period = platform_df.iloc[start_idx:end_idx]

            if len(period) == 0:
                amplitudes.append(0)
                continue

            period_high = period['high'].max()
            period_low = period['low'].min()
            period_mid = (period_high + period_low) / 2
            amplitude = (period_high - period_low) / period_mid if period_mid > 0 else 0
            amplitudes.append(amplitude)

        if len(amplitudes) < 3 or amplitudes[0] == 0:
            return 0.5

        # Check if amplitudes are decreasing
        # Wave 1 > Wave 2 > Wave 3 is ideal
        wave1_to_wave2 = amplitudes[1] / amplitudes[0] if amplitudes[0] > 0 else 1.0
        wave2_to_wave3 = amplitudes[2] / amplitudes[1] if amplitudes[1] > 0 else 1.0

        # Quality score: how much contraction we see
        # Perfect: wave2 = 70% of wave1, wave3 = 70% of wave2
        contraction_1_2 = max(0, 1 - wave1_to_wave2)  # 0 if no contraction, 1 if complete
        contraction_2_3 = max(0, 1 - wave2_to_wave3)

        # Weight later contraction more (recent is more important)
        quality = (contraction_1_2 * 0.4 + contraction_2_3 * 0.6)

        # Bonus for consistent contraction pattern
        if wave1_to_wave2 > 0.8 and wave2_to_wave3 > 0.8:  # Both waves contracted
            quality = min(1.0, quality * 1.2)

        return round(quality, 2)

    def calculate_clv(self) -> float:
        """
        Calculate Close Location Value (CLV).
        CLV = (close - low) - (high - close) / (high - low)
        Ranges from -1 (close at low) to +1 (close at high)

        Returns:
            CLV value for the most recent day
        """
        if len(self.df) < 1:
            return 0.0

        latest = self.df.iloc[-1]
        high = latest['high']
        low = latest['low']
        close = latest['close']

        if high == low:  # Avoid division by zero
            return 0.0

        clv = ((close - low) - (high - close)) / (high - low)
        return float(clv)

    def calculate_52w_metrics(self) -> Dict[str, Optional[float]]:
        """
        Calculate 52-week high/low metrics.

        Returns:
            Dict with 52w high, low, and distance metrics
        """
        if len(self.df) < 50:  # Need at least 50 days
            return {'high_52w': None, 'low_52w': None, 'distance_from_high': None}

        # Use available data (up to 252 trading days)
        lookback = min(252, len(self.df))
        hist_df = self.df.tail(lookback)

        high_52w = hist_df['high'].max()
        low_52w = hist_df['low'].min()
        current_price = self.df['close'].iloc[-1]

        distance_from_high = (high_52w - current_price) / high_52w if high_52w > 0 else None
        distance_from_low = (current_price - low_52w) / low_52w if low_52w > 0 else None

        return {
            'high_52w': float(high_52w),
            'low_52w': float(low_52w),
            'distance_from_high': float(distance_from_high) if distance_from_high is not None else None,
            'distance_from_low': float(distance_from_low) if distance_from_low is not None else None,
            'lookback_days': lookback
        }

    def calculate_stable_ema_slope(self, period=50, comparison_days=3) -> Dict[str, any]:
        """
        Calculate stable EMA slope using multi-day comparison.

        Args:
            period: EMA period (default 50)
            comparison_days: Days back to compare (default 3, avoids daily noise)

        Returns:
            Dict with slope info
        """
        if len(self.df) < period + comparison_days + 5:
            return {'slope': 0.0, 'is_uptrend': False, 'ema_current': None, 'ema_past': None}

        close = self.df['close']
        ema_series = close.ewm(span=period, adjust=False).mean()

        ema_current = ema_series.iloc[-1]
        ema_past = ema_series.iloc[-(comparison_days + 1)]

        # Simple slope check: current > past
        is_uptrend = ema_current > ema_past

        # Calculate percentage slope
        slope_pct = (ema_current - ema_past) / ema_past * 100 if ema_past > 0 else 0.0

        return {
            'slope_pct': float(slope_pct),
            'is_uptrend': is_uptrend,
            'ema_current': float(ema_current),
            'ema_past': float(ema_past),
            'comparison_days': comparison_days
        }

    def distance_from_ema50(self) -> Dict[str, float]:
        """
        Calculate distance from 50EMA (for deadzone filter).

        Returns:
            Dict with distance metrics
        """
        if len(self.df) < 50:
            return {'distance_pct': 0.0, 'ema50': None, 'current_price': None}

        ema50 = self.df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        current_price = self.df['close'].iloc[-1]

        distance_pct = abs(current_price - ema50) / ema50 if ema50 > 0 else 0.0

        return {
            'distance_pct': float(distance_pct),
            'ema50': float(ema50),
            'current_price': float(current_price),
            'is_above': current_price > ema50
        }

    def calculate_rs_score(self, rs_3m: float, rs_6m: float, rs_12m: float) -> float:
        """
        Calculate Relative Strength score.
        RS = 0.4*(3m) + 0.3*(6m) + 0.3*(12m)

        Args:
            rs_3m: 3-month return percentage
            rs_6m: 6-month return percentage
            rs_12m: 12-month return percentage

        Returns:
            Weighted RS score
        """
        return rs_3m * 0.4 + rs_6m * 0.3 + rs_12m * 0.3

    def detect_squeeze(self, recent_days: int = 10, previous_days: int = 10,
                       contraction_threshold: float = 0.8) -> Dict[str, any]:
        """
        Detect volatility squeeze (contraction) pattern.

        Quantitative: Recent average range < previous average range * threshold
        Qualitative: Linear regression slope of daily ranges is negative

        Args:
            recent_days: Days for recent period (default 10)
            previous_days: Days for previous period (default 10)
            contraction_threshold: Range contraction threshold (default 0.8 = 20% smaller)

        Returns:
            Dict with squeeze detection results
        """
        if len(self.df) < recent_days + previous_days + 5:
            return {'is_squeezing': False, 'reason': 'insufficient_data'}

        # Calculate daily ranges
        daily_range = self.df['high'] - self.df['low']

        # Quantitative: Compare recent vs previous average range
        recent_avg_range = daily_range.tail(recent_days).mean()
        previous_avg_range = daily_range.iloc[-(recent_days + previous_days):-recent_days].mean()

        if previous_avg_range == 0:
            return {'is_squeezing': False, 'reason': 'zero_previous_range'}

        range_ratio = recent_avg_range / previous_avg_range
        quantitative_ok = range_ratio < contraction_threshold

        # Qualitative: Linear regression slope of recent daily ranges
        recent_ranges = daily_range.tail(recent_days).values
        x = np.arange(recent_days)

        try:
            slope, intercept = np.polyfit(x, recent_ranges, 1)
            qualitative_ok = slope < 0  # Decreasing trend
        except (KeyError, IndexError, ValueError) as e:
            logger.debug(f"Blow-off detection failed: {e}")
            qualitative_ok = False
            slope = 0

        # Tightness factor trend (std/mean ratio decreasing)
        recent_tightness = recent_ranges.std() / recent_ranges.mean() if recent_ranges.mean() > 0 else 1
        previous_ranges = daily_range.iloc[-(recent_days + previous_days):-recent_days].values
        previous_tightness = previous_ranges.std() / previous_ranges.mean() if previous_ranges.mean() > 0 else 1
        tightening = recent_tightness < previous_tightness

        is_squeezing = quantitative_ok and qualitative_ok and tightening

        return {
            'is_squeezing': bool(is_squeezing),
            'quantitative_ok': bool(quantitative_ok),
            'qualitative_ok': bool(qualitative_ok),
            'tightening': bool(tightening),
            'range_ratio': float(range_ratio),
            'slope': float(slope),
            'recent_tightness': float(recent_tightness),
            'previous_tightness': float(previous_tightness)
        }

    def calculate_chandelier_exit(self, entry_price: float, highest_since_entry: float,
                                   atr: float, multiplier: float = 3.0) -> float:
        """
        Calculate Chandelier Exit (trailing stop).

        Formula: Stop = Highest_Since_Entry - multiplier × ATR

        Args:
            entry_price: Entry price
            highest_since_entry: Highest price since entry
            atr: Current ATR value
            multiplier: ATR multiplier (default 3.0)

        Returns:
            Chandelier stop level
        """
        return highest_since_entry - multiplier * atr

    def distance_from_200ema(self) -> Dict[str, any]:
        """
        Calculate distance from 200EMA and trend direction.

        Returns:
            Dict with distance and trend info
        """
        if len(self.df) < 200:
            return {'distance_pct': 0.0, 'ema200': None, 'is_above': False, 'is_uptrend': False}

        close = self.df['close']
        ema200_series = close.ewm(span=200, adjust=False).mean()

        ema200_current = ema200_series.iloc[-1]
        ema200_past = ema200_series.iloc[-4]  # 3 days ago for stability
        current_price = close.iloc[-1]

        distance_pct = (current_price - ema200_current) / ema200_current if ema200_current > 0 else 0.0
        is_above = current_price > ema200_current
        is_uptrend = ema200_current > ema200_past

        return {
            'distance_pct': float(distance_pct),
            'ema200': float(ema200_current),
            'current_price': float(current_price),
            'is_above': bool(is_above),
            'is_uptrend': bool(is_uptrend)
        }

    def get_50d_high(self) -> Dict[str, float]:
        """Get 50-day high and current distance."""
        if len(self.df) < 50:
            return {'high_50d': None, 'current_price': None, 'distance_pct': None}

        high_50d = self.df['high'].tail(50).max()
        current_price = self.df['close'].iloc[-1]
        distance_pct = (high_50d - current_price) / high_50d if high_50d > 0 else 0.0

        return {
            'high_50d': float(high_50d),
            'current_price': float(current_price),
            'distance_pct': float(distance_pct)
        }

    def calculate_normalized_ema_slope(self, market_atr_median: float) -> Dict[str, any]:
        """
        Calculate normalized EMA21 slope (Trend Intensity for Shoryuken v3.0).

        Formula: S_norm = (EMA21_today - EMA21_t-5) / ATR14

        Args:
            market_atr_median: Median ATR of all stocks for normalization

        Returns:
            Dict with normalized slope and score
        """
        if len(self.df) < 30:
            return {'slope_raw': 0.0, 'slope_norm': 0.0, 'score': 0, 'is_valid': False}

        close = self.df['close']

        # Calculate EMA21
        ema21_series = close.ewm(span=21, adjust=False).mean()
        ema21_today = ema21_series.iloc[-1]
        ema21_t5 = ema21_series.iloc[-6]  # 5 days ago

        # Calculate ATR14
        atr_data = self._calculate_atr(period=14)
        atr14 = atr_data.get('atr', 0)

        if atr14 == 0 or market_atr_median == 0:
            return {'slope_raw': 0.0, 'slope_norm': 0.0, 'score': 0, 'is_valid': False}

        # Raw slope
        slope_raw = ema21_today - ema21_t5

        # Normalized slope (using stock's own ATR)
        slope_norm = slope_raw / atr14

        # Scoring (0-5 points, 2 decimal precision with linear interpolation)
        if slope_norm > 1.2:
            score = 5.0  # Vertical喷发
        elif slope_norm >= 0.8:
            # Linear from 4.0 at 0.8 to 5.0 at 1.2
            score = 4.0 + (slope_norm - 0.8) / 0.4
        elif slope_norm >= 0.4:
            # Linear from 2.0 at 0.4 to 4.0 at 0.8
            score = 2.0 + (slope_norm - 0.4) / 0.4 * 2.0
        else:
            # Linear from 0 at 0 to 2.0 at 0.4
            score = max(0.0, slope_norm / 0.4 * 2.0)

        # Round to 2 decimals
        score = round(score, 2)

        return {
            'slope_raw': float(slope_raw),
            'slope_norm': float(slope_norm),
            'score': score,
            'is_valid': score > 0,
            'ema21_today': float(ema21_today),
            'ema21_t5': float(ema21_t5),
            'atr14': float(atr14)
        }

    def calculate_retracement_structure(self) -> Dict[str, any]:
        """
        Calculate Retracement Structure score for Shoryuken v3.0.

        Returns:
            Dict with structure metrics and score
        """
        if len(self.df) < 10:
            return {'score': 0, 'is_valid': False}

        recent_5d = self.df.tail(5)
        current_price = self.df['close'].iloc[-1]

        # Indicator A: Tightness (5-day range) - 2 decimal precision
        high_max = recent_5d['high'].max()
        low_min = recent_5d['low'].min()
        price_range = (high_max - low_min) / current_price if current_price > 0 else 1.0

        if price_range < 0.04:
            tightness_score = 3.0  # Extremely tight, institution locked
        elif price_range <= 0.08:
            # Linear from 3.0 at 4% to 1.0 at 8%
            tightness_score = 3.0 - (price_range - 0.04) / 0.04 * 2.0
        else:
            # Structure broken - linear penalty
            tightness_score = max(-2.0, 1.0 - (price_range - 0.08) / 0.04 * 3.0)

        # Indicator B: EMA8 support penetration - 2 decimal precision
        ema8_series = self.df['close'].ewm(span=8, adjust=False).mean()
        ema8_current = ema8_series.iloc[-1]
        low_min_val = low_min

        # Allow 1.5% noise penetration
        ema8_support_level = ema8_current * 0.985

        if low_min_val >= ema8_support_level:
            support_score = 2.0  # Strong support
        else:
            # Linear penalty based on penetration depth
            penetration = (ema8_support_level - low_min_val) / ema8_current
            support_score = max(0.0, 2.0 - penetration * 10)  # 10x multiplier for sensitivity

        # Round to 2 decimals
        total_score = round(tightness_score + support_score, 2)

        return {
            'tightness_score': tightness_score,
            'support_score': support_score,
            'total_score': total_score,
            'price_range_pct': float(price_range * 100),
            'ema8_current': float(ema8_current),
            'low_min': float(low_min_val),
            'is_valid': total_score > 0
        }

    def calculate_volume_confirmation(self) -> Dict[str, any]:
        """
        Calculate Volume Confirmation score for Shoryuken v3.0.

        Returns:
            Dict with volume metrics and score
        """
        if len(self.df) < 25:
            return {'dry_score': 0, 'surge_score': 0, 'total_score': 0}

        volume = self.df['volume']

        # Recent 5-day average (pullback period)
        vol_recent_5d = volume.tail(5).mean()

        # 20-day average
        vol_20d = volume.tail(20).mean()

        # Indicator A: Volume dry up (V_dry) - 2 decimal precision
        v_dry = vol_recent_5d / vol_20d if vol_20d > 0 else 1.0

        if v_dry < 0.7:
            dry_score = 2.0  # Selling exhaustion
        elif v_dry < 0.9:
            # Linear from 2.0 at 70% to 1.0 at 90%
            dry_score = 2.0 - (v_dry - 0.7) / 0.2
        else:
            # Linear from 1.0 at 90% to 0 at 100%
            dry_score = max(0.0, 1.0 - (v_dry - 0.9) / 0.1)

        # Indicator B: Today's volume surge (for trigger day) - 2 decimal precision
        vol_today = volume.iloc[-1]
        v_surge = vol_today / vol_20d if vol_20d > 0 else 1.0

        if v_surge > 1.5:
            surge_score = 3.0  # Institutional return
        elif v_surge >= 1.2:
            # Linear from 0 at 1.2 to 3.0 at 1.5
            surge_score = (v_surge - 1.2) / 0.3 * 3.0
        else:
            # Linear from 0 at 1.0 to partial at 1.2
            surge_score = max(0.0, (v_surge - 1.0) / 0.2 * 1.5)

        # Round to 2 decimals
        total_score = round(dry_score + surge_score, 2)

        return {
            'v_dry': float(v_dry),
            'dry_score': dry_score,
            'v_surge': float(v_surge),
            'surge_score': surge_score,
            'total_score': total_score,
            'vol_today': int(vol_today),
            'vol_20d_avg': int(vol_20d)
        }

    def detect_blow_off(self, symbol: str = None) -> Dict[str, any]:
        """
        Detect blow-off top signal for profit protection (建议#4).

        Logic: If price rises > 2x ATR in 3 days with volume spike
        and CLV declining (upper shadow forming), signal profit taking.

        Args:
            symbol: Stock symbol for earnings calendar check (optional)

        Returns:
            Dict with blow-off signal and details
        """
        if len(self.df) < 5:
            return {'is_blow_off': False, 'signal': None}

        # Check earnings calendar if symbol provided
        if symbol:
            from ..earnings_calendar import EarningsCalendar
            cal = EarningsCalendar()
            if cal.is_earnings_day(symbol):
                # Reduce signal strength around earnings - return early with HOLD signal
                return {
                    'is_blow_off': False,
                    'signal': 'HOLD',
                    'reason': 'Earnings day (±1 day) - pausing blow-off detection',
                    'price_change_3d': None,
                    'atr_pct': None,
                    'volume_ratio': None,
                    'clv_current': None,
                    'clv_prev': None,
                    'earnings_pause': True
                }

        # Get recent 3-day price change
        price_3d_ago = self.df['close'].iloc[-4]
        price_current = self.df['close'].iloc[-1]
        price_change_pct = (price_current - price_3d_ago) / price_3d_ago

        # Get ATR
        atr_data = self._calculate_atr(period=14)
        atr = atr_data.get('atr', 0)
        if atr == 0:
            return {'is_blow_off': False, 'signal': None}

        # Check if price change > 2x ATR (in percentage terms)
        atr_pct = atr / price_3d_ago
        price_spike = price_change_pct > (2 * atr_pct)

        # Check volume spike (>3x 5-day average)
        volume_current = self.df['volume'].iloc[-1]
        volume_5d_avg = self.df['volume'].tail(5).mean()
        volume_spike = volume_current > (volume_5d_avg * 3) if volume_5d_avg > 0 else False

        # Check CLV declining (forming upper shadow)
        clv_current = self.calculate_clv()
        clv_prev = self._calculate_clv_for_index(-2)
        clv_declining = clv_current < clv_prev and clv_current < 0.6

        # Blow-off confirmed if all conditions met
        is_blow_off = price_spike and volume_spike and clv_declining

        return {
            'is_blow_off': is_blow_off,
            'signal': 'REDUCE_50%' if is_blow_off else None,
            'reason': 'Blow-off detected: price spike + volume climax + CLV decline' if is_blow_off else None,
            'price_change_3d': round(price_change_pct * 100, 2),
            'atr_pct': round(atr_pct * 100, 2),
            'volume_ratio': round(volume_current / volume_5d_avg, 2) if volume_5d_avg > 0 else 0,
            'clv_current': round(clv_current, 2),
            'clv_prev': round(clv_prev, 2),
            'earnings_pause': False
        }

    def _calculate_clv_for_index(self, idx: int) -> float:
        """Calculate CLV for a specific index (negative = from end)."""
        try:
            row = self.df.iloc[idx]
            high = row['high']
            low = row['low']
            close = row['close']
            if high == low:
                return 0.5
            return (close - low) / (high - low)
        except (KeyError, IndexError, ValueError) as e:
            logger.debug(f"CLV calculation failed: {e}")
            return 0.5

    def estimate_gap_impact(self) -> Dict[str, any]:
        """
        Estimate next-day gap impact using ATR (for Shoryuken v3.0).

        Since we don't have pre-market data, we use ATR to estimate potential gap.

        Returns:
            Dict with gap estimation and penalty/bonus
        """
        atr_data = self._calculate_atr(period=14)
        atr14 = atr_data.get('atr', 0)
        current_price = self.df['close'].iloc[-1]

        if atr14 == 0 or current_price == 0:
            return {'gap_estimate_pct': 0.0, 'score': 0, 'is_valid': True}

        # Estimate potential gap as % of ATR (typical overnight gap is 0.3-0.5 ATR)
        gap_estimate = 0.4 * atr14  # Conservative estimate
        gap_pct = gap_estimate / current_price

        # Gap limit: > 0.8 ATR is dangerous
        gap_limit = 0.8 * atr14

        if gap_estimate > gap_limit:
            score = -10  # Veto - likely to gap through stop
            is_valid = False
        elif gap_pct < 0.003:  # < 0.3% (very small gap)
            score = 1  # Bonus for clean entry
            is_valid = True
        else:
            score = 0
            is_valid = True

        return {
            'gap_estimate': float(gap_estimate),
            'gap_estimate_pct': float(gap_pct * 100),
            'atr14': float(atr14),
            'score': score,
            'is_valid': is_valid
        }


def calculate_indicators_for_symbol(
    symbol: str,
    df: pd.DataFrame
) -> Optional[Dict[str, any]]:
    """
    Convenience function to calculate all indicators for a symbol.

    Args:
        symbol: Stock symbol
        df: OHLCV DataFrame

    Returns:
        Dict with indicators or None if calculation failed
    """
    try:
        calc = TechnicalIndicators(df)
        indicators = calc.calculate_all()

        # Add symbol info
        indicators['symbol'] = symbol
        indicators['last_price'] = float(df['close'].iloc[-1])
        indicators['timestamp'] = df.index[-1].isoformat() if hasattr(df.index[-1], 'isoformat') else str(df.index[-1])

        return indicators

    except Exception as e:
        logger.error(f"Error calculating indicators for {symbol}: {e}")
        return None
