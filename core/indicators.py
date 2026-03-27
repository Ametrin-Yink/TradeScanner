"""Technical indicators calculator."""
import numpy as np
import pandas as pd
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
import logging

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
    """Calculate technical indicators for stock analysis."""

    def __init__(self, df: pd.DataFrame):
        """
        Initialize with OHLCV data.

        Args:
            df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
        """
        self.df = df.copy()
        self.indicators: Dict[str, any] = {}

    def calculate_all(self) -> Dict[str, any]:
        """
        Calculate all technical indicators.

        Returns:
            Dict with all indicator values
        """
        if len(self.df) < 50:
            logger.warning(f"Insufficient data: {len(self.df)} rows, need at least 50")
            return {}

        self.indicators = {
            'ema': self._calculate_emas(),
            'atr': self._calculate_atr(),
            'adr': self._calculate_adr(),
            'rsi': self._calculate_rsi(),
            'volume': self._calculate_volume_metrics(),
            'price_metrics': self._calculate_price_metrics(),
        }

        return self.indicators

    def _calculate_emas(self) -> Dict[str, Optional[float]]:
        """Calculate EMA8, EMA21, EMA50."""
        close = self.df['close']

        ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1] if len(close) >= 8 else None
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1] if len(close) >= 21 else None
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1] if len(close) >= 50 else None

        return {
            'ema8': float(ema8) if ema8 is not None else None,
            'ema21': float(ema21) if ema21 is not None else None,
            'ema50': float(ema50) if ema50 is not None else None,
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

        # ATR as percentage of current price
        current_price = close.iloc[-1]
        atr_pct = (atr / current_price) * 100 if current_price > 0 else None

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
        for i in range(-5, 0):
            if i < -1:
                prev_close = close.iloc[i - 1]
                curr_open = self.df['open'].iloc[i]
                gap_pct = abs((curr_open - prev_close) / prev_close) * 100
                if gap_pct > 1.0:  # 1% gap
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
