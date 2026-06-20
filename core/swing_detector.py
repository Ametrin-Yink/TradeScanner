"""Swing point detection and technical stop/target placement."""
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
from scipy.signal import argrelextrema
from scipy.cluster.hierarchy import linkage, fcluster

logger = logging.getLogger(__name__)


def detect_swings(df, order: int = 5):
    """Detect swing highs and lows using local extrema.

    Args:
        df: DataFrame with 'High' and 'Low' columns
        order: bars on each side to confirm a pivot

    Returns:
        (list of swing_high_prices, list of swing_low_prices)
    """
    if len(df) < order * 2 + 1:
        return [], []

    high_idx = argrelextrema(df['High'].values, np.greater_equal, order=order)[0]
    low_idx = argrelextrema(df['Low'].values, np.less_equal, order=order)[0]

    swing_highs = df['High'].iloc[high_idx].tolist()
    swing_lows = df['Low'].iloc[low_idx].tolist()

    return swing_highs, swing_lows


def cluster_levels(points: List[float], tolerance: float = 0.005) -> List[Dict]:
    """Group nearby price levels into zones using hierarchical clustering.

    Args:
        points: list of price levels
        tolerance: max distance as fraction of price to group together (0.005 = 0.5%)

    Returns:
        List of dicts with 'level' (mean price), 'count' (touches), 'range' (min, max)
    """
    if not points:
        return []

    if len(points) == 1:
        return [{'level': points[0], 'count': 1, 'range': (points[0], points[0])}]

    prices = np.array(points).reshape(-1, 1)
    Z = linkage(prices, method='single')
    threshold = tolerance * np.mean(prices)
    labels = fcluster(Z, t=threshold, criterion='distance')

    zones = []
    for label in np.unique(labels):
        cluster_prices = prices[labels == label].flatten()
        zones.append({
            'level': float(np.mean(cluster_prices)),
            'count': int(len(cluster_prices)),
            'range': (float(np.min(cluster_prices)), float(np.max(cluster_prices))),
        })

    zones.sort(key=lambda z: z['level'])
    return zones


def compute_stop_target(
    entry_price: float,
    atr: float,
    support_zones: List[Dict],
    resistance_zones: List[Dict],
    df,  # DataFrame with OHLC for pivot/measured-move calculations
    time_horizon: str = 'swing',
) -> Tuple[float, float, str]:
    """Compute stop-loss and target price using 3-tier cascade.

    Returns:
        (stop_price, target_price, method_used)
    """
    # -- Stop Placement --
    stop = None
    stop_method = None

    # Tier 1: Nearest swing low below entry (from support zones)
    below_zones = [z for z in support_zones if z['level'] < entry_price]
    if below_zones:
        nearest = max(below_zones, key=lambda z: z['level'])
        candidate = nearest['level']
        if entry_price - candidate >= 0.5 * atr:
            stop = candidate
            stop_method = 'swing_low'

    # Tier 2: 2x ATR below entry
    if stop is None:
        candidate = entry_price - 2.0 * atr
        if candidate > 0:
            stop = candidate
            stop_method = 'atr_fallback'

    # Tier 3: 10% below entry (hard cap)
    if stop is None:
        stop = entry_price * 0.90
        stop_method = 'pct_cap'

    # -- Target Placement --
    target = None
    target_method = None

    # Tier 1: Fibonacci extension from most recent swing
    if resistance_zones:
        nearest_resistance = min(
            [z for z in resistance_zones if z['level'] > entry_price],
            key=lambda z: z['level'],
            default=None
        )
        if nearest_resistance:
            # Use 127.2% extension as target
            candidate = nearest_resistance['level']
            if candidate > entry_price:
                rr = (candidate - entry_price) / (entry_price - stop)
                if rr >= 2.0:
                    target = candidate
                    target_method = 'fib_extension'

    # Tier 2: Measured move from consolidation range
    if target is None and len(df) >= 20:
        recent = df.tail(20)
        range_high = recent['High'].max()
        range_low = recent['Low'].min()
        range_height = range_high - range_low
        if range_height > 0:
            candidate = entry_price + range_height * 0.93  # Bulkowski factor
            rr = (candidate - entry_price) / (entry_price - stop)
            if rr >= 2.0:
                target = candidate
                target_method = 'measured_move'

    # Tier 3: Pivot point R1 (weekly projection from last 5 bars)
    if target is None and len(df) >= 5:
        last_5 = df.tail(5)
        h, l, c = last_5['High'].max(), last_5['Low'].min(), last_5['Close'].iloc[-1]
        pp = (h + l + c) / 3.0
        r1 = 2.0 * pp - l
        if r1 > entry_price:
            rr = (r1 - entry_price) / (entry_price - stop)
            if rr >= 2.0:
                target = r1
                target_method = 'pivot_r1'

    # Fallback: 2x risk
    if target is None:
        target = entry_price + 2.0 * (entry_price - stop)
        target_method = 'risk_multiple'

    method = f"{stop_method}+{target_method}"
    return round(stop, 2), round(target, 2), method
