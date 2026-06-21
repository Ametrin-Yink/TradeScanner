"""Swing point detection and technical stop/target placement."""
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
from scipy.signal import find_peaks
from scipy.cluster.hierarchy import linkage, fcluster

logger = logging.getLogger(__name__)


def detect_swings(df, order: int = None, atr: float = None):
    """Detect swing highs and lows using adaptive order and peak prominence.

    Args:
        df: DataFrame with 'High' and 'Low' columns
        order: bars on each side (auto-computed if None)
        atr: average true range for prominence threshold

    Returns:
        (list of swing_high_prices, list of swing_low_prices)
    """
    if order is None:
        order = max(3, min(8, len(df) // 15))

    if len(df) < order * 2 + 1:
        return [], []

    if atr is None:
        atr = (df['High'] - df['Low']).mean()

    prominence = atr * 0.5

    high_idx, _ = find_peaks(df['High'].values, distance=order, prominence=prominence)
    low_idx, _ = find_peaks(-df['Low'].values, distance=order, prominence=prominence)

    swing_highs = df['High'].iloc[high_idx].tolist()
    swing_lows = df['Low'].iloc[low_idx].tolist()

    return swing_highs, swing_lows


def cluster_levels(points: List[float], tolerance: float = None,
                   atr: float = None, price: float = None) -> List[Dict]:
    """Group nearby price levels into zones using complete-linkage clustering.

    Args:
        points: list of price levels
        tolerance: max distance as fraction of price (auto-computed if None)
        atr: average true range for dynamic tolerance
        price: current price for dynamic tolerance

    Returns:
        List of dicts with 'level', 'count', 'range' — only zones with count >= 2
    """
    if not points:
        return []

    if tolerance is None and atr is not None and price is not None:
        tolerance = max(0.005, min(0.03, 0.3 * (atr / price)))
    elif tolerance is None:
        tolerance = 0.01

    if len(points) == 1:
        return [{'level': points[0], 'count': 1, 'range': (points[0], points[0])}]

    prices = np.array(points).reshape(-1, 1)
    Z = linkage(prices, method='complete')
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


def _compute_fib_target(df, entry_price: float, extension: float = 1.618, order: int = None) -> Optional[float]:
    """Compute Fibonacci extension target from the most recent completed swing.
    Returns target price or None if no valid swing found.
    """
    try:
        if order is None:
            order = max(3, min(8, len(df) // 15))
        swings_h, swings_l = detect_swings(df, order=order)
        if len(swings_l) < 1 or len(swings_h) < 1:
            return None
        last_low = swings_l[-1]
        later_highs = [h for h in swings_h if h > last_low]
        if not later_highs:
            return None
        last_high = later_highs[-1]
        swing_range = last_high - last_low
        if swing_range <= 0:
            return None
        target = last_low + swing_range * extension
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
) -> Tuple[Optional[float], Optional[float], str]:
    """Compute stop-loss and target. Returns (None, None, 'skip') if no valid R:R.

    Stop: tightest quality (count>=2) support/EMA within max_stop_distance.
    Target: first resistance giving R:R >= min_rr. Falls back to fib / 3xATR / risk_multiple.
    """
    from config.portfolio_config import load_config
    cfg = load_config()
    sr_cfg = cfg.get('stop_target', {})
    max_dist_atr = sr_cfg.get('max_stop_distance_atr', 2.5)
    max_dist_pct = sr_cfg.get('max_stop_distance_pct', 0.05)
    min_rr = sr_cfg.get('min_rr_swing', 1.5) if time_horizon == 'swing' else sr_cfg.get('min_rr_position', 2.0)
    fib_ext = sr_cfg.get('fib_extension_default', 1.618)
    atr_mult = sr_cfg.get('atr_multiplier_swing', 1.5)

    max_stop_distance = min(max_dist_atr * atr, entry_price * max_dist_pct)

    # -- Stop: find best valid stop --
    stop = None
    stop_method = None

    # Candidates: multi-touch supports + EMAs + ATR fallback
    candidates = []

    # Support zones (multi-touch only -- already filtered by cluster_levels)
    for z in support_zones:
        if z['level'] < entry_price and (entry_price - z['level']) <= max_stop_distance:
            quality = z.get('count', 1)
            candidates.append((z['level'], f"support(x{z['count']})", quality))

    # EMA21
    if ema21 > 0 and ema21 < entry_price and (entry_price - ema21) <= max_stop_distance:
        candidates.append((ema21, 'ema21', 2))

    # EMA50
    if ema50 > 0 and ema50 < entry_price and (entry_price - ema50) <= max_stop_distance:
        candidates.append((ema50, 'ema50', 2))

    # ATR fallback
    atr_stop = entry_price - atr_mult * atr
    if atr_stop < entry_price:
        candidates.append((atr_stop, 'atr', 1))

    if not candidates:
        return None, None, 'skip:no_stop'

    # Pick tightest stop among quality candidates (quality >= 2 preferred)
    quality_stops = [(l, m) for l, m, q in candidates if q >= 2]
    if quality_stops:
        stop, stop_method = min(quality_stops, key=lambda x: entry_price - x[0])
    else:
        stop, stop_method, _ = min(candidates, key=lambda x: entry_price - x[0])

    # -- Target: first resistance giving R:R >= min_rr --
    target = None
    target_method = None
    risk = entry_price - stop
    if risk <= 0:
        return None, None, 'skip:zero_risk'

    # Check resistance zones in ascending order -- pick first with valid R:R
    above = sorted(
        [z for z in resistance_zones if z['level'] > entry_price],
        key=lambda z: z['level']
    )
    for z in above:
        if (z['level'] - entry_price) <= entry_price * 0.50:
            rr = (z['level'] - entry_price) / risk
            if rr >= min_rr:
                target = z['level']
                target_method = f"resistance(x{z['count']})"
                break

    # Fib extension fallback
    if target is None and df is not None and len(df) >= 20:
        fib = _compute_fib_target(df, entry_price, extension=fib_ext)
        if fib and fib > entry_price:
            rr = (fib - entry_price) / risk
            if rr >= min_rr:
                target = fib
                target_method = f'fib_{fib_ext}'

    # ATR-based target
    if target is None:
        atr_target = entry_price + 3 * atr
        rr = (atr_target - entry_price) / risk
        if rr >= min_rr:
            target = atr_target
            target_method = 'atr_3x'

    # Risk-multiple fallback
    if target is None:
        target = entry_price + min_rr * risk
        target_method = f'risk_{min_rr}x'

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
        current_price = float(df['Close'].iloc[-1])
        atr = (df['High'] - df['Low']).tail(14).mean()

        high_zones = cluster_levels(swing_highs, atr=atr, price=current_price)
        low_zones = cluster_levels(swing_lows, atr=atr, price=current_price)

        # Filter: only multi-touch zones (count >= 2)
        high_zones = [z for z in high_zones if z['count'] >= 2]
        low_zones = [z for z in low_zones if z['count'] >= 2]
        # Dynamic ATR-based filter: typical range 10-20% instead of flat 50%
        atr_pct_val = atr / current_price if current_price > 0 else 0.02
        filter_pct = max(0.10, 5 * atr_pct_val)
        price_floor = current_price * (1 - filter_pct)
        price_ceiling = current_price * (1 + filter_pct)
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
