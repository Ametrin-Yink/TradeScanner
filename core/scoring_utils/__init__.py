"""Scoring utilities package - shared calculation functions for trading strategies."""

from .validation import ParameterValidator, validate_strategy_config

__all__ = [
    'ParameterValidator',
    'validate_strategy_config',
]
"""Scoring utilities - shared calculation functions for trading strategies.

This module provides reusable scoring calculation functions to avoid
duplicate code across strategy implementations.
"""
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np


def calculate_clv(close: float, high: float, low: float) -> float:
    """
    Calculate Close Location Value (CLV).

    CLV = (close - low) / (high - low)
    Range: 0 to 1
    - 0 = Close at Low (bearish)
    - 0.5 = Close at middle
    - 1 = Close at High (bullish)

    Args:
        close: Closing price
        high: High price
        low: Low price

    Returns:
        CLV value between 0 and 1, or 0.5 if high == low
    """
    if high > low:
        return (close - low) / (high - low)
    return 0.5


def check_rsi_divergence(df: pd.DataFrame, direction: str, lookback: int = 20) -> bool:
    """
    Check for RSI divergence - price makes new extreme but RSI doesn't.

    Bearish Divergence (for short):
        - Price makes higher high
        - RSI makes lower high

    Bullish Divergence (for long):
        - Price makes lower low
        - RSI makes higher low

    Args:
        df: DataFrame with price data
        direction: 'bearish' or 'bullish'
        lookback: Number of days to look back for comparison

    Returns:
        True if divergence detected
    """
    if len(df) < lookback + 10:
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
        if recent_high_idx not in df.index:
            return False

        recent_high = df.loc[recent_high_idx, 'high']

        prev_period = df.loc[df.index < recent_high_idx]
        if len(prev_period) < lookback // 2:
            return False

        prev_high = prev_period['high'].tail(lookback).max()
        prev_rsi_high = rsi.loc[prev_period.tail(lookback).index].max()
        recent_rsi = rsi.loc[recent_high_idx]

        if recent_high > prev_high and recent_rsi < prev_rsi_high:
            return True

    else:  # bullish
        # Bullish divergence: price lower low, RSI higher low
        recent_low_idx = df['low'].tail(10).idxmin()
        if recent_low_idx not in df.index:
            return False

        recent_low = df.loc[recent_low_idx, 'low']

        prev_period = df.loc[df.index < recent_low_idx]
        if len(prev_period) < lookback // 2:
            return False

        prev_low = prev_period['low'].tail(lookback).min()
        prev_rsi_low = rsi.loc[prev_period.tail(lookback).index].min()
        recent_rsi = rsi.loc[recent_low_idx]

        if recent_low < prev_low and recent_rsi > prev_rsi_low:
            return True

    return False


def check_exhaustion_gap(df: pd.DataFrame, level: float, direction: str,
                         gap_threshold: float = 0.01) -> bool:
    """
    Check for exhaustion gap - gap to extreme level followed by rejection.

    Short Exhaustion:
        - Gap up to near level
        - Close below open (rejection)
        - Volume spike

    Long Exhaustion:
        - Gap down to near level
        - Close above open (rejection)
        - Volume spike

    Args:
        df: DataFrame with price data (needs at least 2 days)
        level: Support/resistance level to check against
        direction: 'short' or 'long'
        gap_threshold: Minimum gap percentage (default 1%)

    Returns:
        True if exhaustion gap detected
    """
    if len(df) < 2:
        return False

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # Calculate average volume
    avg_volume = df['volume'].tail(20).mean() if 'volume' in df.columns else 1
    volume_spike = today['volume'] > avg_volume * 1.5 if 'volume' in df.columns else False

    if direction == 'short':
        # Gap up
        gap_up = today['open'] > yesterday['high'] * (1 + gap_threshold)
        # Near level
        near_level = today['high'] >= level * 0.995
        # Close below open (rejection)
        rejection = today['close'] < today['open']

        return gap_up and near_level and rejection and volume_spike

    else:  # long
        # Gap down
        gap_down = today['open'] < yesterday['low'] * (1 - gap_threshold)
        # Near level
        near_level = today['low'] <= level * 1.005
        # Close above open (rejection)
        rejection = today['close'] > today['open']

        return gap_down and near_level and rejection and volume_spike


def calculate_test_interval(df: pd.DataFrame, level: float, atr: float,
                           level_type: str, min_interval: int = 3) -> Dict:
    """
    Calculate test quality metrics including interval between tests.

    High quality tests are spaced apart, indicating true support/resistance.

    Args:
        df: DataFrame with price data
        level: Price level to test against
        atr: Average True Range for tolerance calculation
        level_type: 'support', 'resistance', 'high', or 'low'
        min_interval: Minimum days between valid tests

    Returns:
        Dict with test_count, avg_interval, max_interval
    """
    tolerance = atr * 0.5  # Standard tolerance
    tests = []
    last_test_idx = None

    lookback = min(90, len(df) - 1)

    for i in range(1, lookback + 1):
        idx = -(i + 1)
        if idx < -len(df):
            break

        row = df.iloc[idx]

        # Check if price touched the level
        touched = False
        if level_type in ['support', 'low']:
            # Near low, bounced up
            if abs(row['low'] - level) <= tolerance or row['low'] <= level + tolerance:
                if row['close'] > level:
                    touched = True
        else:  # resistance or high
            # Near high, rejected
            if abs(row['high'] - level) <= tolerance or row['high'] >= level - tolerance:
                if row['close'] < level:
                    touched = True

        if touched:
            # Apply interval constraint
            if last_test_idx is None or (last_test_idx - i) >= min_interval:
                tests.append({'idx': i, 'days_since': i})
                last_test_idx = i

    # Calculate intervals
    intervals = []
    if len(tests) >= 2:
        for i in range(1, len(tests)):
            intervals.append(tests[i-1]['idx'] - tests[i]['idx'])

    avg_interval = sum(intervals) / len(intervals) if intervals else 0

    return {
        'test_count': len(tests),
        'avg_interval': avg_interval,
        'max_interval': max(intervals) if intervals else 0
    }


def calculate_institutional_intensity(volume_ratio: float, clv: float) -> float:
    """
    Calculate institutional intensity factor.

    Formula: (Volume / MA20) * |CLV - 0.5|

    High values indicate institutional participation:
    - High volume + CLV away from 0.5 = institutional activity
    - Low volume or CLV near 0.5 = retail/noise

    Args:
        volume_ratio: Volume / MA20_Volume
        clv: Close Location Value (0 to 1)

    Returns:
        Institutional intensity score
    """
    return volume_ratio * abs(clv - 0.5)


def detect_market_direction(spy_df: pd.DataFrame) -> str:
    """
    Detect market direction based on SPY trend.

    Args:
        spy_df: DataFrame with SPY price data

    Returns:
        'long', 'short', or 'neutral'
    """
    if spy_df is None or len(spy_df) < 50:
        return 'neutral'

    try:
        current = spy_df['close'].iloc[-1]
        ema50 = spy_df['close'].ewm(span=50).mean().iloc[-1]
        atr = spy_df['close'].rolling(14).apply(lambda x: (x.max() - x.min())).iloc[-1]
        open_price = spy_df['open'].iloc[-1]

        # Short mode: distribution environment
        if current < ema50 or current < open_price * 0.99:
            return 'short'
        # Long mode: accumulation environment
        elif current > ema50 or current > open_price * 1.01:
            return 'long'
        else:
            return 'neutral'

    except Exception:
        return 'neutral'


def check_vix_filter(vix_df: Optional[pd.DataFrame], direction: str,
                     reject_threshold: float = 30.0,
                     limit_threshold: float = 25.0) -> str:
    """
    Check VIX-based risk filter for capitulation strategies.

    Args:
        vix_df: DataFrame with VIX data (optional)
        direction: 'long' or 'short'
        reject_threshold: VIX level to reject signals
        limit_threshold: VIX level to limit position size

    Returns:
        'reject', 'limit', or 'normal'
    """
    if vix_df is None or len(vix_df) < 10:
        return 'normal'

    try:
        current_vix = vix_df['close'].iloc[-1]
        vix_5d_ago = vix_df['close'].iloc[-6] if len(vix_df) > 5 else current_vix
        vix_slope = (current_vix - vix_5d_ago) / 5

        # Capitulation mode: be extra careful
        if direction == 'long':
            if current_vix > reject_threshold and vix_slope > 0:
                return 'reject'
            elif current_vix > limit_threshold:
                return 'limit'

        return 'normal'

    except Exception:
        return 'normal'


def calculate_rs_score_weighted(rs_3m: float, rs_6m: float, rs_12m: float) -> float:
    """
    Calculate weighted Relative Strength score.

    Formula: 0.4 * rs_3m + 0.3 * rs_6m + 0.3 * rs_12m

    Args:
        rs_3m: 3-month relative strength
        rs_6m: 6-month relative strength
        rs_12m: 12-month relative strength

    Returns:
        Weighted RS score
    """
    return 0.4 * rs_3m + 0.3 * rs_6m + 0.3 * rs_12m


def calculate_volume_climax_score(volume_ratio: float,
                                  climax_threshold: float = 4.0,
                                  high_threshold: float = 3.0,
                                  medium_threshold: float = 2.0) -> float:
    """
    Calculate volume climax score for capitulation detection.

    Args:
        volume_ratio: Volume / MA20_Volume
        climax_threshold: Threshold for maximum score
        high_threshold: Threshold for high score
        medium_threshold: Threshold for medium score

    Returns:
        Climax score (typically 0-2)
    """
    if volume_ratio >= climax_threshold:
        return 2.0
    elif volume_ratio >= high_threshold:
        return 1.5 + (volume_ratio - high_threshold) / (climax_threshold - high_threshold) * 0.5
    elif volume_ratio >= medium_threshold:
        return 1.0 + (volume_ratio - medium_threshold) / (high_threshold - medium_threshold) * 0.5
    elif volume_ratio >= 1.5:
        return 0.5 + (volume_ratio - 1.5) / (medium_threshold - 1.5) * 0.5
    else:
        return max(0, volume_ratio - 1.0)


def calculate_normalized_ema_slope(df: pd.DataFrame, ema_period: int = 21,
                                   atr_period: int = 14) -> Dict[str, any]:
    """
    Calculate normalized EMA slope (trend intensity).

    Formula: (EMA_today - EMA_n_days_ago) / ATR

    Args:
        df: DataFrame with price data
        ema_period: EMA period
        atr_period: ATR period for normalization

    Returns:
        Dict with slope, normalized_slope, is_uptrend
    """
    if len(df) < ema_period + 5:
        return {'slope': 0, 'normalized_slope': 0, 'is_uptrend': False}

    try:
        ema = df['close'].ewm(span=ema_period).mean()
        ema_current = ema.iloc[-1]
        ema_prev = ema.iloc[-6]  # 5 days ago

        # Calculate ATR
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=atr_period).mean().iloc[-1]

        slope = (ema_current - ema_prev) / ema_prev
        normalized_slope = slope / (atr / ema_current) if atr > 0 else 0

        return {
            'slope': slope,
            'normalized_slope': normalized_slope,
            'is_uptrend': slope > 0
        }

    except Exception:
        return {'slope': 0, 'normalized_slope': 0, 'is_uptrend': False}


def calculate_linear_interpolation(value: float, min_val: float, max_val: float,
                                   min_score: float, max_score: float) -> float:
    """
    Calculate linear interpolation for scoring.

    Formula: min_score + (value - min_val) / (max_val - min_val) * (max_score - min_score)

    Args:
        value: Current value
        min_val: Minimum threshold value
        max_val: Maximum threshold value
        min_score: Score at min_val
        max_score: Score at max_val

    Returns:
        Interpolated score
    """
    if value <= min_val:
        return min_score
    if value >= max_val:
        return max_score

    return min_score + (value - min_val) / (max_val - min_val) * (max_score - min_score)
