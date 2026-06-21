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


def _compute_fib_target(df, entry_price: float) -> Optional[float]:
    """Compute Fibonacci extension target from the most recent completed swing.
    Returns target price or None if no valid swing found.
    """
    try:
        swings_h, swings_l = detect_swings(df, order=5)
        if len(swings_l) < 1 or len(swings_h) < 1:
            return None
        # Find last swing low and the subsequent swing high
        last_low = swings_l[-1]
        later_highs = [h for h in swings_h if h > last_low]
        if not later_highs:
            return None
        last_high = later_highs[-1]
        swing_range = last_high - last_low
        if swing_range <= 0:
            return None
        # 1.272 extension from the low through the high
        target = last_low + swing_range * 1.272
        if target > entry_price:
            return round(target, 2)
        return None
    except Exception:
        return None


def compute_stop_target(
    entry_price: float,
    atr: float,
    support_zones: List[Dict],
    resistance_zones: List[Dict],
    df,  # DataFrame with OHLC
    time_horizon: str = 'swing',
    ema21: float = 0.0,
    ema50: float = 0.0,
) -> Tuple[float, float, str]:
    """Compute stop-loss and target using chart-aligned S/R levels.

    Stop: nearest support below entry. Fallback chain: EMA21 → EMA50 → 1.5x ATR.
    Target: nearest resistance above entry. Fallback: Fibonacci extension or 2x risk.
    """
    # -- Stop: nearest support below entry (within 15%) --
    stop = None
    stop_method = None
    below = [z for z in support_zones if z['level'] < entry_price]
    if below:
        nearest = max(below, key=lambda z: z['level'])
        if entry_price - nearest['level'] <= entry_price * 0.15:
            stop = nearest['level']
            stop_method = 'support'
    # Dynamic support: EMA21 if within 15%
    if stop is None and ema21 > 0 and ema21 < entry_price:
        if entry_price - ema21 <= entry_price * 0.15:
            stop = ema21
            stop_method = 'ema21'
    # Dynamic support: EMA50 if within 15%
    if stop is None and ema50 > 0 and ema50 < entry_price:
        if entry_price - ema50 <= entry_price * 0.15:
            stop = ema50
            stop_method = 'ema50'
    if stop is None:
        stop = entry_price - 1.5 * atr
        stop_method = 'atr'

    # -- Target: nearest resistance above entry --
    target = None
    target_method = None
    above = [z for z in resistance_zones if z['level'] > entry_price]
    if above:
        nearest = min(above, key=lambda z: z['level'])
        if nearest['level'] - entry_price <= entry_price * 0.50:
            target = nearest['level']
            target_method = 'resistance'
    # ATH / no resistance: try Fibonacci extension
    if target is None and df is not None and len(df) >= 20:
        fib = _compute_fib_target(df, entry_price)
        if fib and fib > entry_price:
            target = fib
            target_method = 'fib_extension'
    if target is None and df is not None and len(df) >= 20:
        recent = df.tail(20)
        range_h = recent['High'].max()
        range_l = recent['Low'].min()
        if range_h > range_l:
            target = entry_price + (range_h - range_l)
            target_method = 'measured_move'
    # Fallback
    if target is None:
        target = entry_price + 2.0 * (entry_price - stop)
        target_method = 'risk_multiple'

    return round(stop, 2), round(target, 2), f"{stop_method}+{target_method}"


def compute_sr_for_symbol(db, symbol: str) -> tuple:
    """Compute support/resistance levels from recent (60-bar) and full-range OHLC.
    Returns (supports: List[float], resistances: List[float]).
    Updates tier1_cache with the results.
    """
    try:
        import pandas as pd
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT date, open, high, low, close FROM market_data "
            "WHERE symbol = ? ORDER BY date ASC",
            (symbol,)
        ).fetchall()
        if len(rows) < 30:
            return [], []
        df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close'])
        df.columns = ['date', 'Open', 'High', 'Low', 'Close']

        # Use recent 60 bars with order=2 to catch 2-day pullbacks
        recent = df.tail(60)
        swing_highs, swing_lows = detect_swings(recent, order=2)
        high_zones = cluster_levels(swing_highs, tolerance=0.005)
        low_zones = cluster_levels(swing_lows, tolerance=0.005)

        current_price = float(df['Close'].iloc[-1])
        # Filter levels >50% away from current price (data artifacts, pre-split prices)
        price_floor = current_price * 0.50
        price_ceiling = current_price * 1.50
        supports = sorted([z['level'] for z in low_zones if price_floor < z['level'] < current_price], reverse=True)[:5]
        resistances = sorted([z['level'] for z in high_zones if current_price < z['level'] < price_ceiling])[:5]

        # Cache in tier1_cache
        import json
        cache = db.get_tier1_cache(symbol)
        if cache:
            conn.execute(
                "UPDATE tier1_cache SET supports = ?, resistances = ? WHERE symbol = ?",
                (json.dumps(supports), json.dumps(resistances), symbol)
            )
            conn.commit()

        return supports, resistances
    except Exception as e:
        logger.warning(f"S/R computation failed for {symbol}: {e}")
        return [], []
