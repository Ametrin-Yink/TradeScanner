# Report Generation Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 18 critical issues, 45+ medium issues, and 12 missing features in TradeScanner's report generation pipeline. Produce practical swing (5-20d) and position (10-40d) stock recommendations with statistically valid entry/stop/target levels.

**Architecture:** Seven sequential phases. Each phase produces a working, testable system. Deterministic core (S/R, scoring, sizing) with AI on the edges for narrative enrichment. Every recommendation tracked via `recommendations` table with daily reconciliation.

**Tech Stack:** Python 3.13, scipy, numpy, pandas, yfinance, flask, pytest, DeepSeek API

**Source spec:** `docs/superpowers/specs/2026-06-21-report-generation-overhaul-design.md`

## Global Constraints

- All existing tests must pass after every phase
- Two runs on same cached data must produce identical quantitative outputs
- All thresholds configurable in `portfolio_config.yaml` — no hardcoded magic numbers
- Silent failures are bugs — stale data, bad JSON, missing fields must produce explicit errors or skips
- `python -m pytest tests/ -v` after every task — never proceed with failing tests

---

## Phase 1: Foundation (Week 1)

### Task 1.1: Wire up RS_percentile computation in fetcher.py

**Files:**

- Modify: `core/fetcher.py` — `save_tier1_cache()` method
- Read: `data/db.py` — `get_all_rs_raw_values()`, `update_rs_percentile()`, `bulk_update_rs_percentiles()`

**Interfaces:**

- Consumes: `Database.get_tier1_cache()`, `Database.save_tier1_cache()`
- Produces: `rs_percentile` and `rs_consecutive_days_80` populated in `tier1_cache` for every stock

- [ ] **Step 1: Add RS_raw computation to save_tier1_cache()**

Read `core/fetcher.py` to find the `save_tier1_cache` method or equivalent tier1 population logic. Add after current_price is computed:

```python
# Compute RS_raw: 3-month relative strength
rs_raw = None
if len(df) >= 63:
    price_63d_ago = float(df['close'].iloc[-63])
    if price_63d_ago > 0:
        rs_raw = (current_price / price_63d_ago - 1) * 100

# Include rs_raw in the cache dict
cache_data['rs_raw'] = rs_raw
```

- [ ] **Step 2: Add post-batch RS percentile ranking**

After all stocks are cached in a batch, rank and assign percentiles. Add to the batch processing function:

```python
# After all stocks cached: rank by rs_raw and assign percentiles
rs_values = []
for sym in symbols:
    cache = self.db.get_tier1_cache(sym)
    if cache and cache.get('rs_raw') is not None:
        rs_values.append((sym, cache['rs_raw']))

if rs_values:
    rs_values.sort(key=lambda x: x[1])
    n = len(rs_values)
    for rank, (sym, rs_raw) in enumerate(rs_values):
        percentile = int(rank / (n - 1) * 99) if n > 1 else 50
        # Update rs_percentile in DB
        self.db.update_rs_percentile(sym, percentile)

    min_rs = rs_values[0][1]
    max_rs = rs_values[-1][1]
    logger.info(f"RS percentile range: {min_rs:.1f}–{max_rs:.1f}, stocks ranked: {n}")
```

- [ ] **Step 3: Add rs_consecutive_days_80 tracking**

```python
# After percentile assignment: update consecutive days streak
for sym, rs_raw in rs_values:
    cache = self.db.get_tier1_cache(sym)
    if not cache:
        continue
    rs_pct = cache.get('rs_percentile', 0) or 0
    prev_streak = cache.get('rs_consecutive_days_80', 0) or 0
    if rs_pct >= 80:
        new_streak = prev_streak + 1
    elif rs_pct < 50:
        new_streak = 0
    else:
        new_streak = prev_streak  # hold steady between 50-79
    self.db.update_tier1_field(sym, 'rs_consecutive_days_80', new_streak)
```

- [ ] **Step 4: Wire up DB methods**

Read `data/db.py`. Confirm `update_rs_percentile()` and `get_all_rs_raw_values()` exist. If they have correct SQL but are never called, leave them. Add `update_tier1_field(symbol, field, value)` if missing:

```python
def update_tier1_field(self, symbol, field, value):
    conn = self.get_connection()
    conn.execute(
        f"UPDATE tier1_cache SET {field} = ?, cache_date = date('now') WHERE symbol = ?",
        (value, symbol)
    )
    conn.commit()
```

- [ ] **Step 5: Test**

```bash
python -c "
from core.fetcher import DataFetcher
from data.db import Database
db = Database()
fetcher = DataFetcher(db=db)
# Fetch a few stocks to trigger cache population
fetcher.fetch_multiple(['AAPL', 'MSFT', 'GOOGL'], period='6mo')
# Check RS fields
for sym in ['AAPL', 'MSFT', 'GOOGL']:
    cache = db.get_tier1_cache(sym)
    print(f'{sym}: rs_raw={cache.get(\"rs_raw\")}, rs_percentile={cache.get(\"rs_percentile\")}, streak={cache.get(\"rs_consecutive_days_80\")}')
"
```

- [ ] **Step 6: Commit**

```bash
git add core/fetcher.py data/db.py
git commit -m "feat: compute RS_percentile and consecutive-days streak in tier1_cache

Wires up previously-dead rs_raw/rs_percentile/rs_consecutive_days_80 columns.
RS_raw = (price / price_63d_ago - 1) * 100. Percentile assigned by ranking all
cached stocks. Streak increments above 80th, resets below 50th.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.2: Fix composite_score() — remove ret_5d, use RS_percentile

**Files:**

- Modify: `core/sector_analyzer.py` — `composite_score()` inner function in `_find_stock_highlights()`

**Interfaces:**

- Consumes: `tier1_cache.rs_percentile`, `tier1_cache.rs_consecutive_days_80` (now populated by Task 1.1)
- Produces: Corrected `composite_score()` with live momentum dimension

- [ ] **Step 1: Edit the composite_score function**

Read `core/sector_analyzer.py`, find the `composite_score` inner function. Replace the momentum line:

```python
# Before:
momentum = (c.rs_percentile or 0) * 0.30 + min((c.ret_5d or 0) * 1.5, 10)

# After:
momentum = (c.rs_percentile or 0) * 0.30 + min((getattr(c, 'rs_consecutive_days_80', 0) or 0) / 2, 10)
```

- [ ] **Step 2: Add rs_consecutive_days_80 to highlight metadata**

In the highlight creation loop (where `highlight.rs_percentile = rs_percentile` is set), add:

```python
highlight.rs_consecutive_days_80 = cache.get('rs_consecutive_days_80', 0) or 0
```

- [ ] **Step 3: Verify**

```bash
python -c "
from core.sector_analyzer import SectorAnalyzer
from data.db import Database
analyzer = SectorAnalyzer(db=Database())
result = analyzer.analyze()
for s in result['sectors']:
    for h in s.highlights[:2]:
        rs = getattr(h, 'rs_percentile', 'N/A')
        streak = getattr(h, 'rs_consecutive_days_80', 'N/A')
        print(f'{h.symbol}: RS_pct={rs}, streak={streak}')
"
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "fix: use RS_percentile and streak in composite_score, remove ret_5d

ret_5d was double-counted with RS_percentile. Momentum dimension now comes
entirely from RS percentile (30%) + consecutive-days-above-80 bonus.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.3: Fix detect_swings() — adaptive order + find_peaks

**Files:**

- Modify: `core/swing_detector.py` — `detect_swings()` function

**Interfaces:**

- Consumes: DataFrame with 'High'/'Low' columns, ATR value
- Produces: `(swing_highs, swing_lows)` with meaningful, low-noise pivot points

- [ ] **Step 1: Rewrite detect_swings()**

```python
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
        # Adaptive: 60 bars → order=4, 120 bars → order=8
        order = max(3, min(8, len(df) // 15))

    if len(df) < order * 2 + 1:
        return [], []

    if atr is None:
        atr = (df['High'] - df['Low']).mean()

    prominence = atr * 0.5  # require at least 0.5 ATR prominence

    from scipy.signal import find_peaks

    high_idx, _ = find_peaks(df['High'].values, distance=order, prominence=prominence)
    low_idx, _ = find_peaks(-df['Low'].values, distance=order, prominence=prominence)

    swing_highs = df['High'].iloc[high_idx].tolist()
    swing_lows = df['Low'].iloc[low_idx].tolist()

    return swing_highs, swing_lows
```

- [ ] **Step 2: Fix the internal \_compute_fib_target call**

`_compute_fib_target` calls `detect_swings(df, order=5)` hardcoded. Change to pass through the order parameter:

```python
def _compute_fib_target(df, entry_price: float, order: int = None) -> Optional[float]:
    if order is None:
        order = max(3, min(8, len(df) // 15))
    swings_h, swings_l = detect_swings(df, order=order)
    # ... rest unchanged
```

- [ ] **Step 3: Test**

```bash
python -c "
import pandas as pd
import numpy as np
from core.swing_detector import detect_swings

# Generate synthetic data with known swings
np.random.seed(42)
n = 80
prices = 100 + np.cumsum(np.random.randn(n) * 2)
df = pd.DataFrame({
    'High': prices + np.abs(np.random.randn(n)),
    'Low': prices - np.abs(np.random.randn(n)),
    'Close': prices,
})

swing_h, swing_l = detect_swings(df)  # should auto-compute order=5
print(f'Order auto: {max(3, min(8, n // 15))}')
print(f'Swing highs: {len(swing_h)}, Swing lows: {len(swing_l)}')
# With prominence=ATR*0.5, should get far fewer than the 15-20 argrelextrema would produce
assert len(swing_h) < 15, f'Too many swing highs: {len(swing_h)}'
assert len(swing_l) < 15, f'Too many swing lows: {len(swing_l)}'
print('PASS')
"
```

- [ ] **Step 4: Commit**

```bash
git add core/swing_detector.py
git commit -m "fix: adaptive swing order + find_peaks with ATR prominence

Replaces argrelextrema(order=2) with find_peaks(distance=order, prominence=ATR*0.5).
Order auto-computed: max(3, min(8, len(df)//15)). 60 bars → order=4.
Noise reduction: swing points must clear 0.5 ATR prominence.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.4: Fix cluster_levels() — complete-linkage + dynamic tolerance + count filter

**Files:**

- Modify: `core/swing_detector.py` — `cluster_levels()` function

**Interfaces:**

- Consumes: list of price floats, ATR value, current price
- Produces: `List[Dict]` with `level`, `count`, `range` — only multi-touch zones

- [ ] **Step 1: Rewrite cluster_levels()**

```python
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
    Z = linkage(prices, method='complete')  # was 'single'
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
```

- [ ] **Step 2: Add post-clustering filter in compute_sr_for_symbol()**

In `compute_sr_for_symbol()`, after `cluster_levels()` calls for highs and lows, filter:

```python
# Filter: only multi-touch zones (count >= 2)
high_zones = [z for z in high_zones if z['count'] >= 2]
low_zones = [z for z in low_zones if z['count'] >= 2]
```

- [ ] **Step 3: Update compute_sr_for_symbol() to pass ATR/price to cluster_levels**

```python
atr = (df['High'] - df['Low']).tail(14).mean()
high_zones = cluster_levels(swing_highs, atr=atr, price=current_price)
low_zones = cluster_levels(swing_lows, atr=atr, price=current_price)
```

- [ ] **Step 4: Test**

```bash
python -c "
from core.swing_detector import cluster_levels

# Points deliberately spread — shouldn't all merge
points = [100.0, 100.3, 102.0, 102.2, 105.0]
zones = cluster_levels(points, atr=2.0, price=100.0)
print(f'Zones: {zones}')
# With complete-linkage, 100.0+100.3 should cluster (0.3%),
# 102.0+102.2 should cluster, 105.0 alone (count=1)
for z in zones:
    print(f'  level={z[\"level\"]:.1f}, count={z[\"count\"]}')
print('PASS')
"
```

- [ ] **Step 5: Commit**

```bash
git add core/swing_detector.py
git commit -m "fix: complete-linkage clustering + dynamic ATR tolerance + min-count filter

- method='complete' prevents single-linkage chaining pathology
- tolerance = max(0.005, min(0.03, 0.3*ATR/price)) — dynamic per-stock
- zones with count < 2 filtered out (single-touch = noise)
- ATR and price passed through from compute_sr_for_symbol

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.5: Fix price filter in compute_sr_for_symbol()

**Files:**

- Modify: `core/swing_detector.py` — `compute_sr_for_symbol()`

**Interfaces:**

- Consumes: clustered zones, current_price, atr_pct
- Produces: filtered supports (below price) and resistances (above price) within dynamic bounds

- [ ] **Step 1: Replace static 50% filter with dynamic ATR-based filter**

Read `compute_sr_for_symbol()`. Find the `price_floor`/`price_ceiling` lines. Replace:

```python
# Before:
price_floor = current_price * 0.50
price_ceiling = current_price * 1.50

# After:
atr_pct_val = atr / current_price if current_price > 0 else 0.02
filter_pct = max(0.10, 5 * atr_pct_val)
price_floor = current_price * (1 - filter_pct)
price_ceiling = current_price * (1 + filter_pct)
```

- [ ] **Step 2: Verify bounds are reasonable**

```bash
python -c "
# SPY at 747 with 1.5% ATR: filter_pct = max(0.10, 5*0.015) = 0.10 → +/-10%
print('SPY 747, ATR 1.5%:', max(0.10, 5*0.015))
# TSLA at 20 with 4% ATR: filter_pct = max(0.10, 5*0.04) = 0.20 → +/-20%
print('Penny 20, ATR 4%:', max(0.10, 5*0.04))
# NVDA at 500 with 2.5% ATR: filter_pct = max(0.10, 5*0.025) = 0.125 → +/-12.5%
print('NVDA 500, ATR 2.5%:', max(0.10, 5*0.025))
"
```

- [ ] **Step 3: Commit**

```bash
git add core/swing_detector.py
git commit -m "fix: dynamic ATR-based price filter replaces static 50% bound

Filter_pct = max(0.10, 5*ATR_pct). Typical range 10-20% instead of flat 50%.
Keeps only levels relevant to swing/position trades.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.6: Rewrite compute_stop_target() — stop cascade + zone quality + min R:R

**Files:**

- Modify: `core/swing_detector.py` — `compute_stop_target()`
- Read: `config/portfolio_config.yaml`

**Interfaces:**

- Consumes: entry_price, atr, support_zones, resistance_zones, df, time_horizon, ema21, ema50
- Produces: `(stop, target, method_string)` with R:R ≥ 1.5 guaranteed; returns `(None, None, 'skip')` if no valid combo

- [ ] **Step 1: Rewrite stop cascade with zone quality gate**

```python
def compute_stop_target(
    entry_price: float,
    atr: float,
    support_zones: List[Dict],
    resistance_zones: List[Dict],
    df=None,
    time_horizon: str = 'swing',
    ema21: float = 0.0,
    ema50: float = 0.0,
) -> Tuple[Optional[float], Optional[float], str]:
    """Compute stop-loss and target. Returns (None, None, 'skip') if no valid R:R."""

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

    # Support zones (multi-touch only — already filtered by cluster_levels)
    for z in support_zones:
        if z['level'] < entry_price and (entry_price - z['level']) <= max_stop_distance:
            # Quality: prefer multi-touch, penalize single-touch
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
        stop, stop_method = min(candidates, key=lambda x: entry_price - x[0])

    # -- Target: first resistance giving R:R >= min_rr --
    target = None
    target_method = None
    risk = entry_price - stop
    if risk <= 0:
        return None, None, 'skip:zero_risk'

    # Check resistance zones in ascending order — pick first with valid R:R
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
```

- [ ] **Step 2: Update \_compute_fib_target to accept extension parameter**

```python
def _compute_fib_target(df, entry_price: float, extension: float = 1.618, order: int = None) -> Optional[float]:
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
```

- [ ] **Step 3: Handle skip in \_find_stock_highlights**

Read `sector_analyzer.py`. In the highlight loop, after calling `compute_stop_target()`, add:

```python
stop, target, method = compute_stop_target(...)
if stop is None:
    continue  # skip — no valid stop/target combo
```

- [ ] **Step 4: Test**

```bash
python -c "
from core.swing_detector import compute_stop_target

# Test: no valid zones → should return None
stop, target, method = compute_stop_target(
    100.0, 2.0, [], [], df=None, time_horizon='swing'
)
assert stop is not None, 'Should fall back to ATR stop'
assert target is not None, 'Should fall back to risk-multiple target'
rr = (target - 100.0) / (100.0 - stop)
assert rr >= 1.5, f'R:R {rr:.1f} < 1.5'
print(f'Fallback: stop={stop}, target={target}, R:R={rr:.1f}, method={method}')
print('PASS')
"
```

- [ ] **Step 5: Commit**

```bash
git add core/swing_detector.py core/sector_analyzer.py
git commit -m "fix: rewrite stop/target cascade with zone quality gate + min R:R gate

Stop: tightest quality (count>=2) support/EMA within 2.5*ATR or 5% of price.
Target: first resistance giving R:R >= 1.5 (swing) or 2.0 (position).
Falls back: ATR_stop → fib_1.618 → 3*ATR → risk_multiple.
Returns (None, None, 'skip') if no valid combo exists.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.7: Add S/R and stop/target config to portfolio_config.yaml

**Files:**

- Modify: `config/portfolio_config.yaml`

- [ ] **Step 1: Add new config sections**

Read `config/portfolio_config.yaml`. Append:

```yaml
# S/R detection parameters
sr:
  swing_order_min: 3
  swing_order_max: 8
  cluster_method: complete
  zone_min_touches: 2
  price_filter_atr_mult: 5.0
  price_filter_min_pct: 0.10

# Stop and target placement
stop_target:
  max_stop_distance_atr: 2.5
  max_stop_distance_pct: 0.05
  min_rr_swing: 1.5
  min_rr_position: 2.0
  atr_multiplier_swing: 1.5
  fib_extension_default: 1.618
```

- [ ] **Step 2: Add load_config helper if not exists**

Check if `config/portfolio_config.yaml` already has a loading function. If not, add to `config/settings.py` or a new `config/portfolio_config.py`:

```python
# config/portfolio_config.py (new file if needed)
import yaml
from pathlib import Path

_portfolio_config = None

def load_config():
    global _portfolio_config
    if _portfolio_config is None:
        config_path = Path(__file__).parent / "portfolio_config.yaml"
        with open(config_path) as f:
            _portfolio_config = yaml.safe_load(f)
    return _portfolio_config
```

Note: `sector_analyzer.py` already has `_load_portfolio_config()`. Update it to return the full dict (it already does). The S/R module should import from the same source. If `swing_detector.py` needs it, either import from sector_analyzer or extract to a shared config module. For now, keep `_load_portfolio_config()` in `sector_analyzer.py` and pass relevant values as parameters to `compute_stop_target()`.

- [ ] **Step 3: Commit**

```bash
git add config/portfolio_config.yaml
git commit -m "feat: add S/R detection and stop/target params to portfolio_config.yaml

All magic numbers now configurable: swing order bounds, cluster method,
price filter, stop distance limits, R:R thresholds, fib extension.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1.8: Update existing tests and run full test suite

**Files:**

- Modify: `tests/e2e/test_report_gen.py` (if needed)
- Read: `tests/` — all existing test files

- [ ] **Step 1: Run existing tests**

```bash
python -m pytest tests/ -v
```

Expected: some tests may fail due to changed function signatures or behavior. Note each failure.

- [ ] **Step 2: Update test fixtures and assertions**

Update any test that:

- Calls `detect_swings()` with hardcoded order — add `order=` kwarg
- Calls `cluster_levels()` expecting single-linkage results — update to complete-linkage expectations
- Expects `compute_stop_target()` to always return values — handle `None` returns
- Expects specific R:R values — adjust for new cascade

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/ -v
```

All tests must pass.

- [ ] **Step 4: Run full scan**

```bash
python scheduler.py --force
```

Must complete without error. Check log for: `RS percentile range`, zone counts, R:R values.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update tests for Phase 1 foundation changes

Adapt tests for: adaptive order, complete-linkage, zone count filter,
stop/target skip returns, RS_percentile population.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 2: Safety (Week 2)

### Task 2.1: Add data freshness validation

**Files:**

- Modify: `core/fetcher.py` — new function
- Modify: `scheduler.py` — call before analysis

**Interfaces:**

- Consumes: `Database` instance
- Produces: `validate_cache_freshness()` — raises `RuntimeError` if stale

- [ ] **Step 1: Write validate_cache_freshness()**

```python
def validate_cache_freshness(db, max_age_hours=24):
    """Abort if any cache table lacks today's data."""
    today = datetime.now().strftime('%Y-%m-%d')
    tables = ['tier1_cache', 'etf_cache']
    stale = []
    for table in tables:
        try:
            rows = db.get_connection().execute(
                f"SELECT COUNT(*) FROM {table} WHERE cache_date >= ?", (today,)
            ).fetchone()
            if rows and rows[0] == 0:
                stale.append(table)
        except Exception:
            stale.append(f"{table} (error checking)")

    if stale:
        raise RuntimeError(
            f"Stale cache detected in: {', '.join(stale)}. "
            f"Run data fetch before analysis."
        )
    logger.info(f"Cache freshness OK: {today}")
```

- [ ] **Step 2: Wire into scheduler.py**

```python
# In run_sector_scan(), after db creation, before analyzer.analyze():
from core.fetcher import validate_cache_freshness
try:
    validate_cache_freshness(db)
except RuntimeError as e:
    logger.error(f"Aborting: {e}")
    db.save_workflow_status({'run_date': run_date, 'status': 'aborted_stale_cache'})
    return None
```

- [ ] **Step 3: Test with stale cache**

```bash
python -c "
from core.fetcher import validate_cache_freshness
from data.db import Database
db = Database()
# Should raise if no tier1_cache data exists for today
try:
    validate_cache_freshness(db)
    print('Cache OK')
except RuntimeError as e:
    print(f'Correctly aborted: {e}')
"
```

- [ ] **Step 4: Commit**

```bash
git add core/fetcher.py scheduler.py
git commit -m "feat: data freshness validation aborts pipeline on stale cache

Checks tier1_cache and etf_cache have today's data before analysis.
Aborts with clear error instead of silently producing stale reports.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.2: Add pipeline checkpointing

**Files:**

- Modify: `core/sector_analyzer.py` — `analyze()` method
- Read: `data/db.py` — `save_workflow_status()` / `load_workflow_status()`

**Interfaces:**

- Consumes: `Database.save_workflow_status()`, `Database.get_workflow_status()`
- Produces: Idempotent pipeline — restart after crash skips completed steps

- [ ] **Step 1: Add checkpoint logic to analyze()**

Read `sector_analyzer.py`, find `analyze()`. Wrap each step:

```python
def analyze(self) -> Dict:
    today = datetime.now().strftime('%Y-%m-%d')
    status = self.db.load_workflow_status(today) or {}

    # Step 1: Market Overview (skip if done today)
    if 'market_overview_done' not in status:
        market = self._analyze_market()
        self.db.save_workflow_status({**status, 'market_overview_done': True})
        status['market_overview_done'] = True
    else:
        # Re-load from DB or re-compute (load from cache)
        market = self._analyze_market()  # fast enough to re-run without AI

    # Step 2: Sector Analysis (skip if done today)
    if 'sector_analysis_done' not in status:
        sectors = self._analyze_all_sectors(market)
        self.db.save_workflow_status({**status, 'sector_analysis_done': True})
        status['sector_analysis_done'] = True
    else:
        # Load from persisted results
        sectors = self._load_sector_analyses(today)

    # Step 2b: S/R Refresh (skip if done today)
    if 'sr_refresh_done' not in status:
        self._refresh_sr_levels()
        self.db.save_workflow_status({**status, 'sr_refresh_done': True})
        status['sr_refresh_done'] = True

    # Step 3: Highlights (skip if done today)
    if 'highlights_done' not in status:
        self._find_stock_highlights(sectors)
        self.db.save_workflow_status({**status, 'highlights_done': True})
        status['highlights_done'] = True

    # Step 4: Focus Summary (skip if done today)
    if 'focus_summary_done' not in status:
        focus = self._generate_focus_summary(market, sectors)
        self.db.save_workflow_status({**status, 'focus_summary_done': True})
    else:
        focus = self._load_focus_summary(today)

    return {
        'market': market, 'sectors': sectors,
        'focus_summary': focus,
        'timestamp': datetime.now().isoformat(),
    }
```

- [ ] **Step 2: Add load_workflow_status to db.py if missing**

```python
def load_workflow_status(self, run_date):
    conn = self.get_connection()
    row = conn.execute(
        "SELECT status_data FROM workflow_status WHERE run_date = ? ORDER BY created_at DESC LIMIT 1",
        (run_date,)
    ).fetchone()
    if row:
        import json
        return json.loads(row[0]) if row[0] else {}
    return {}
```

- [ ] **Step 3: Test — kill mid-pipeline and restart**

No automated test for this (requires process kill). Manual verification:

```bash
# Run and Ctrl+C after "Sector analysis" log
python scheduler.py --force &
sleep 10 && kill %1
# Re-run — should log "Skipping market overview (cached today)" etc.
python scheduler.py --force
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py data/db.py
git commit -m "feat: pipeline checkpointing — restart after crash skips done steps

Each of 5 pipeline steps persists completion to workflow_status.
On restart, completed steps are skipped. Prevents re-paying for
AI calls after mid-pipeline crashes.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.3: Fix Near Resistance → Resistance Test

**Files:**

- Modify: `core/sector_analyzer.py` — setup classification in `_find_stock_highlights()`

- [ ] **Step 1: Rewrite Near Resistance condition with confirmation requirements**

Find the `reason = 'Near Resistance'` block. Replace:

```python
# Before: Near Resistance fires unconditionally within 2%
elif high_60d and price < high_60d and (high_60d - price) / price <= 0.02:
    reason = 'Near Resistance'
    ...

# After: Resistance Test with confirmation requirements
elif high_60d and price < high_60d:
    near_threshold = max(0.01, atr_pct * 0.8)
    if (high_60d - price) / price <= near_threshold:
        # Require ALL confirmations
        ema_ok = (ema50 and price > ema50) or False
        vol_ok = volume_ratio > 1.0
        trend_ok = sector.trend == 'uptrend'
        rs_ok = rs_percentile >= 50

        if ema_ok and vol_ok and trend_ok and rs_ok:
            reason = 'Resistance Test'
            detail = f"Testing 60d high ${high_60d:.2f}, {(high_60d - price)/price*100:.1f}% below, {volume_ratio:.1f}x vol"
            time_horizon = 'swing'
```

Also update the setup priority to put it last (after Good R/R). Move the entire elif block to after the Good R/R block.

- [ ] **Step 2: Update setup_bonus reference (in composite_score)**

Add to the `setup_bonus` dict:

```python
'Resistance Test': 0.80,
```

- [ ] **Step 3: Update horizon_map**

```python
'Resistance Test': 'Swing (5-20d)',
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "fix: Near Resistance demoted to Resistance Test with 4 confirmations

Requires ALL: price > EMA50, volume > 1.0x, sector uptrend, RS >= 50th.
Without confirmations, stock approaching resistance is skipped (not a buy).
Moved to last priority after Good R/R. ATR-based near_threshold replaces 2%.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.4: Fix Good R/R trend filter + ATR-based thresholds

**Files:**

- Modify: `core/sector_analyzer.py` — Good R/R logic + "near" threshold computation

- [ ] **Step 1: Add uptrend requirement to Good R/R**

Find the Good R/R elif block. Before setting `reason = 'Good R/R'`, add:

```python
# Uptrend filter: require at least one confirmation
uptrend_ok = False
if ema50 and price > ema50:
    uptrend_ok = True
elif sector.trend == 'uptrend':
    uptrend_ok = True
elif volume_ratio > 1.2:
    uptrend_ok = True

if not uptrend_ok:
    continue  # skip falling knives
```

- [ ] **Step 2: Replace hardcoded 2% with ATR-based threshold everywhere**

Search for `0.02` in `_find_stock_highlights()`. Replace all "near" thresholds:

```python
near_threshold = max(0.01, atr_pct * 0.8)
```

Apply to: Near Support check, Near Resistance/Resistance Test check.

- [ ] **Step 3: Add volume check for Near Support**

```python
elif reason == 'Near Support':
    # Selling pressure should be fading at support
    if volume_ratio >= 1.0:
        continue  # skip — elevated volume at support = risk of breakdown
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "fix: Good R/R uptrend filter + ATR-based near thresholds + volume check

Good R/R now requires price>EMA50, sector uptrend, or elevated volume.
Near Support skips if volume elevated (selling pressure risk).
All 'near' thresholds use ATR-based formula instead of hardcoded 2%.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2.5: Update tests for Phase 2

- [ ] **Step 1: Run tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 2: Fix any broken tests, verify scan runs**

```bash
python scheduler.py --force
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: update tests for Phase 2 safety changes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3: AI Reliability (Weeks 2-3)

### Task 3.1: Rewrite ai_client.py — native DeepSeek tool-calling

**Files:**

- Modify: `core/ai_client.py` — full rewrite of `chat()` function

- [ ] **Step 1: Remove ddgs dependency, add native web search**

```python
"""AI client for DeepSeek API with native web search tool calling."""
import json
import hashlib
import logging
import time
import requests
from datetime import datetime
from typing import Optional, Dict, List

from config.settings import settings

logger = logging.getLogger(__name__)

API_KEY = settings.get_secret("dashscope.api_key")
API_BASE = settings.get_secret("dashscope.api_base") or "https://api.deepseek.com/v1"
MODEL = settings.get_secret("dashscope.model") or "deepseek-v4-pro"

# In-memory cache: (call_type, sector_name, date) -> result
_ai_cache = {}


def chat(
    messages: List[Dict],
    system: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 8000,
    enable_search: bool = False,
    search_query: Optional[str] = None,
    timeout: int = 300,
    seed: int = 42,
    call_type: str = 'unknown',
    sector_name: str = '',
) -> Optional[str]:
    """Send a chat request with optional native web search.

    Uses DeepSeek's native tool-calling for web search.
    Deterministic: temperature=0.0, seed=42, json_object response format.
    Results cached by (call_type, sector_name, date) for 24h.
    """
    if not API_KEY:
        logger.error("No API key configured")
        return None

    # Check cache
    today = datetime.now().strftime('%Y-%m-%d')
    cache_key = f"{call_type}:{sector_name}:{today}"
    if cache_key in _ai_cache:
        logger.info(f"AI cache hit: {cache_key}")
        return _ai_cache[cache_key]

    url = f"{API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    tools = None
    if enable_search:
        tools = [{
            "type": "web_search",
            "web_search": {
                "search_query": search_query or messages[-1]["content"],
                "search_result_format": "text"
            }
        }]

    payload = {
        "model": MODEL,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": seed,
        "response_format": {"type": "json_object"},
    }
    if tools:
        payload["tools"] = tools

    prompt_text = json.dumps(msgs, sort_keys=True)
    prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()[:16]

    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)

            if response.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                wait = 2 ** attempt
                logger.warning(f"Server error {response.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"].get("content", "")

            # Audit logging
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            response_hash = hashlib.sha256((content or "").encode()).hexdigest()[:16]

            # Cost estimate (DeepSeek pricing)
            cost = (tokens_in * 0.28 + tokens_out * 1.10) / 1_000_000

            logger.info(
                f"AI call: {call_type} {sector_name} — "
                f"{tokens_in}+{tokens_out} tokens, ${cost:.4f}, "
                f"hash={response_hash}"
            )

            # Cache result
            if content:
                _ai_cache[cache_key] = content

            return content or None

        except requests.exceptions.Timeout:
            logger.warning(f"AI call timeout (attempt {attempt+1}/3)")
            if attempt == 2:
                return None
        except Exception as e:
            logger.error(f"AI call failed (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                return None

    return None
```

- [ ] **Step 2: Fix settings.py model**

Read `config/settings.py`. Find the model config:

```python
# Before (likely):
"model": "qwen-max"

# After:
"model": "deepseek-v4-pro"
```

- [ ] **Step 3: Test AI call**

```bash
python -c "
from core.ai_client import chat
result = chat(
    messages=[{'role': 'user', 'content': 'Return JSON: {\"test\": true}'}],
    system='You are a test. Return only valid JSON.',
    temperature=0.0,
    call_type='test',
)
print(f'Result: {result}')
"
```

- [ ] **Step 4: Commit**

```bash
git add core/ai_client.py config/settings.py
git commit -m "feat: rewrite ai_client with native DeepSeek web search + determinism

- Removes ddgs pre-search in favor of native tool-calling
- temperature=0.0, seed=42, response_format=json_object for determinism
- 24h in-memory cache by (call_type, sector, date)
- Exponential backoff retry on 429/5xx
- Token + cost tracking per call
- Model fixed to deepseek-v4-pro (was qwen-max)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3.2: Add AI audit logging to database

**Files:**

- Modify: `data/db.py` — new table + insert method

- [ ] **Step 1: Add ai_audit_log table**

```python
def create_ai_audit_table(self):
    conn = self.get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_type TEXT,
            sector_name TEXT,
            prompt_hash TEXT,
            response_hash TEXT,
            model TEXT,
            temperature REAL,
            seed INTEGER,
            tokens_in INTEGER,
            tokens_out INTEGER,
            cost_estimate REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

def log_ai_call(self, call_type, sector_name, prompt_hash, response_hash,
                model, temperature, seed, tokens_in, tokens_out, cost):
    conn = self.get_connection()
    conn.execute("""
        INSERT INTO ai_audit_log (call_type, sector_name, prompt_hash,
            response_hash, model, temperature, seed, tokens_in, tokens_out,
            cost_estimate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (call_type, sector_name, prompt_hash, response_hash, model,
          temperature, seed, tokens_in, tokens_out, cost))
    conn.commit()
```

- [ ] **Step 2: Wire into ai_client.py**

Add `from data.db import Database` and call `db.log_ai_call(...)` after each successful response.

- [ ] **Step 3: Commit**

```bash
git add data/db.py core/ai_client.py
git commit -m "feat: bi-temporal AI audit logging

Every AI call logged with prompt_hash, response_hash, model, temperature,
seed, token counts, and cost. Enables reproducibility verification and
cost tracking.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3.3: Add AI-quant consistency check + cost footer

**Files:**

- Modify: `core/sector_analyzer.py` — after `_ai_sector_analysis()`
- Modify: `core/reporter.py` — footer

- [ ] **Step 1: Add consistency check after AI sector analysis**

In `_analyze_sector()`, after getting AI outlook:

```python
# Consistency check: AI outlook vs quantitative trend
if outlook and trend:
    outlook_lower = outlook.lower()
    if trend == 'uptrend' and any(w in outlook_lower for w in ['bearish', 'declining', 'weak']):
        logger.warning(f"{name}: AI outlook conflicts with uptrend — flagging")
        outlook = outlook.rstrip('.') + ".\n\n[AI/quantitative divergence: uptrend detected but AI outlook cautious]"
    elif trend == 'downtrend' and any(w in outlook_lower for w in ['bullish', 'strong', 'accelerating']):
        logger.warning(f"{name}: AI outlook conflicts with downtrend — flagging")
        outlook = outlook.rstrip('.') + ".\n\n[AI/quantitative divergence: downtrend detected but AI outlook optimistic]"
```

- [ ] **Step 2: Add AI status to report footer**

In `reporter.py` `_build_html()`, footer section:

```python
# Track AI status
ai_errors = sum(1 for s in sectors if 'unavailable' in (s.outlook or ''))
ai_status = f"AI: {len(sectors) - ai_errors}/{len(sectors)} sectors OK"
# Add cost total from audit log
parts.append(f'<div class="footer">TradeScanner &middot; {timestamp[:16]} &middot; {ai_status}</div>')
```

- [ ] **Step 3: Commit**

```bash
git add core/sector_analyzer.py core/reporter.py
git commit -m "feat: AI-quantitative consistency check + AI status in report footer

Flags sectors where AI outlook contradicts computed trend.
Report footer shows AI sector coverage and cost summary.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 4: Scoring Overhaul (Weeks 3-4)

### Task 4.1: Rewrite composite_score() with all components

**Files:**

- Modify: `core/sector_analyzer.py` — `composite_score()` inner function

- [ ] **Step 1: Full rewrite of composite_score**

```python
def composite_score(c):
    # Momentum (30%): RS percentile + streak bonus
    momentum = (c.rs_percentile or 0) * 0.30
    momentum += min((getattr(c, 'rs_consecutive_days_80', 0) or 0) / 2, 10)

    # Quality (30%): R:R quality + volume confirmation
    quality = min(c.rr * 5, 15) + min((c.volume_ratio or 1) * 5, 10)

    # Structure (25%): setup type bonus + trend alignment
    setup_bonus = {
        'Breakout': 1.0,
        'Strong Momentum': 0.95,
        'Near Support': 0.85,
        'Resistance Test': 0.80,
        'Good R/R': 0.75,
    }
    trend_above = 1.0 if getattr(c, 'ema_above', False) else 0.4
    structure = setup_bonus.get(c.reason, 0.5) * 15 + trend_above * 10

    # Volatility penalty (5%): high-vol stocks penalized
    atr_pct_val = getattr(c, 'atr_pct', 0.03) or 0.03
    vol_penalty = -min(atr_pct_val * 100, 10) * 0.5

    # Data completeness gate
    missing = 0
    for field in ['rs_percentile', 'volume_ratio']:
        val = getattr(c, field, None)
        if val is None or val == 0:
            missing += 1
    if missing >= 2:
        return -999

    return momentum + quality + structure + vol_penalty
```

- [ ] **Step 2: Add atr_pct to highlight metadata**

In the highlight creation loop, add:

```python
highlight.atr_pct = atr_pct
```

- [ ] **Step 3: Add MIN_SCORE threshold**

After `composite_score(c)` call, filter:

```python
from config.settings import settings
min_score = settings.get('scoring', {}).get('min_composite_score', 20) if hasattr(settings, 'get') else 20

all_candidates = [c for c in all_candidates if composite_score(c) >= min_score]
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "fix: rewrite composite_score with volatility penalty + data completeness gate

- Momentum: RS_percentile(30%) + streak bonus
- Quality: R:R(15pts max) + volume(10pts max)
- Structure: setup_bonus(0.75-1.0)*15 + trend_alignment*10
- Volatility penalty: -0.5 per ATR% point
- Data gate: stocks missing >=2 fields scored -999 (excluded)
- MIN_SCORE threshold from config

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4.2: Add config-driven scoring weights

**Files:**

- Modify: `config/portfolio_config.yaml`

- [ ] **Step 1: Add scoring section**

```yaml
scoring:
  momentum_weight: 0.30
  quality_weight: 0.30
  structure_weight: 0.25
  volatility_penalty_weight: 0.05
  min_composite_score: 20
  setup_bonus:
    Breakout: 1.0
    Strong Momentum: 0.95
    Near Support: 0.85
    Resistance Test: 0.80
    Good R/R: 0.75
  diversity_soft_threshold: 0.70
```

- [ ] **Step 2: Wire into composite_score**

```python
from config.portfolio_config import load_config
pcfg = load_config()
scoring_cfg = pcfg.get('scoring', {})
setup_bonus = scoring_cfg.get('setup_bonus', {
    'Breakout': 1.0, 'Strong Momentum': 0.95,
    'Near Support': 0.85, 'Resistance Test': 0.80, 'Good R/R': 0.75,
})
min_score = scoring_cfg.get('min_composite_score', 20)
```

- [ ] **Step 3: Commit**

```bash
git add config/portfolio_config.yaml core/sector_analyzer.py
git commit -m "feat: scoring weights driven by portfolio_config.yaml

Setup bonuses, min score threshold, diversity threshold all configurable.
No hardcoded scoring parameters remain.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4.3: Fix diversity gate

**Files:**

- Modify: `core/sector_analyzer.py` — selection logic in `_find_stock_highlights()`

- [ ] **Step 1: Implement soft diversity**

Replace the rigid diversity gate:

```python
selected = []
used_reasons = set()
div_threshold = scoring_cfg.get('diversity_soft_threshold', 0.70)

for c in all_candidates:
    if len(selected) >= 3:
        break
    if c.reason not in used_reasons:
        selected.append(c)
        used_reasons.add(c.reason)
    elif len(selected) < 3:
        # Soft diversity: allow same reason if score >= threshold * top_score
        top_score = composite_score(selected[0])
        if composite_score(c) >= top_score * div_threshold:
            selected.append(c)
```

- [ ] **Step 2: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "fix: soft diversity gate allows high-scoring same-type picks

Was: if top 2 same type, force 3rd different (could exclude top scorers).
Now: allow same reason only if score >= 70% of top candidate.
Threshold configurable via portfolio_config.yaml.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4.4: Walk-forward backtest script

**Files:**

- Create: `scripts/backtest_scoring.py`

- [ ] **Step 1: Write rank-IC analysis script**

```python
"""Walk-forward rank-IC analysis for composite score validation."""
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.db import Database
from core.sector_analyzer import SectorAnalyzer


def compute_rank_ic(db, horizon_days=10):
    """Compute rank IC: correlation between score and forward return."""
    # Get all stocks with tier1_cache
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT symbol, rs_percentile, volume_ratio, ret_5d,
               supports, resistances, current_price
        FROM tier1_cache WHERE current_price > 0
    """).fetchall()

    if not rows:
        print("No cached data available")
        return None

    scores = []
    forward_returns = []

    for row in rows:
        symbol = row[0]
        # Compute score (simplified — full scoring needs OHLC context)
        rs = row[1] or 0
        vol = row[3] or 0
        score = rs * 0.30 + min(vol * 1.5, 10) * 0.30  # approximate

        # Get forward return
        ohlc = db.get_market_data_df(symbol)
        if ohlc is None or len(ohlc) < horizon_days:
            continue

        current = float(ohlc['close'].iloc[-1])
        future = float(ohlc['close'].iloc[min(-1 + horizon_days, -1)])
        if current > 0:
            fwd_ret = (future - current) / current * 100
            scores.append(score)
            forward_returns.append(fwd_ret)

    if len(scores) < 20:
        print(f"Insufficient data: {len(scores)} valid stocks")
        return None

    # Rank IC: Spearman correlation between rank(score) and forward return
    from scipy.stats import spearmanr
    score_ranks = pd.Series(scores).rank()
    ic, p_value = spearmanr(score_ranks, forward_returns)

    print(f"Stocks analyzed: {len(scores)}")
    print(f"Rank IC (Spearman): {ic:.4f}, p-value: {p_value:.4f}")
    print(f"Target: |IC| >= 0.03 for useful ranking")
    print(f"Status: {'PASS' if abs(ic) >= 0.03 else 'FAIL — scoring may not predict returns'}")

    return ic


if __name__ == '__main__':
    db = Database()
    for horizon in [5, 10, 20]:
        print(f"\n--- Horizon: {horizon}d ---")
        compute_rank_ic(db, horizon)
```

- [ ] **Step 2: Run it**

```bash
python scripts/backtest_scoring.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_scoring.py
git commit -m "feat: walk-forward rank-IC backtest script for scoring validation

Computes Spearman rank correlation between composite score and forward
returns at 5/10/20 day horizons. Target: |IC| >= 0.03 for useful ranking.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 5: Feedback Loop (Weeks 4-5)

### Task 5.1: Create recommendations table + DB methods

**Files:**

- Modify: `data/db.py` — new table + CRUD

- [ ] **Step 1: Add recommendations table**

```python
def create_recommendations_table(self):
    conn = self.get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            sector TEXT NOT NULL,
            setup_type TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            target_price REAL NOT NULL,
            rr REAL,
            composite_score REAL,
            position_size INTEGER,
            position_cost REAL,
            risk_dollars REAL,
            current_price REAL,
            entry_distance_pct REAL,
            status TEXT DEFAULT 'active',
            outcome TEXT,
            pnl_pct REAL,
            days_held INTEGER,
            resolved_date TEXT,
            max_days INTEGER DEFAULT 20,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

def save_recommendation(self, rec: dict):
    conn = self.get_connection()
    conn.execute("""
        INSERT INTO recommendations (trade_date, symbol, sector, setup_type,
            entry_price, stop_price, target_price, rr, composite_score,
            position_size, position_cost, risk_dollars, current_price,
            entry_distance_pct, max_days)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec['trade_date'], rec['symbol'], rec['sector'], rec['setup_type'],
        rec['entry_price'], rec['stop_price'], rec['target_price'],
        rec.get('rr'), rec.get('composite_score'),
        rec.get('position_size'), rec.get('position_cost'),
        rec.get('risk_dollars'), rec.get('current_price'),
        rec.get('entry_distance_pct'), rec.get('max_days', 20)
    ))
    conn.commit()

def get_active_recommendations(self):
    conn = self.get_connection()
    rows = conn.execute(
        "SELECT * FROM recommendations WHERE status = 'active'"
    ).fetchall()
    return [dict(r) for r in rows]

def resolve_recommendation(self, rec_id, status, outcome, pnl_pct, days_held):
    conn = self.get_connection()
    conn.execute("""
        UPDATE recommendations
        SET status = ?, outcome = ?, pnl_pct = ?, days_held = ?,
            resolved_date = date('now')
        WHERE id = ?
    """, (status, outcome, pnl_pct, days_held, rec_id))
    conn.commit()

def get_resolved_recommendations(self, lookback_days=30):
    conn = self.get_connection()
    rows = conn.execute("""
        SELECT * FROM recommendations
        WHERE status IN ('stopped_out', 'target_hit', 'expired')
          AND resolved_date >= date('now', ?)
        ORDER BY resolved_date DESC
    """, (f'-{lookback_days} days',)).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Commit**

```bash
git add data/db.py
git commit -m "feat: recommendations table with full lifecycle tracking

Tracks every pick: entry/stop/target, score, position sizing, status.
Status lifecycle: active → triggered/stopped_out/target_hit/expired.
Outcome tracking with P&L and days_held.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.2: Create reconciler.py

**Files:**

- Create: `core/reconciler.py`

- [ ] **Step 1: Write reconciliation logic**

```python
"""Daily recommendation reconciliation and performance tracking."""
import logging
from datetime import datetime, date
from data.db import Database

logger = logging.getLogger(__name__)


def reconcile_recommendations(db: Database):
    """Check all active recommendations against current prices."""
    active = db.get_active_recommendations()
    today = date.today()
    resolved = 0

    for rec in active:
        cache = db.get_tier1_cache(rec['symbol'])
        if not cache or not cache.get('current_price'):
            continue

        price = cache['current_price']
        trade_date = datetime.strptime(rec['trade_date'], '%Y-%m-%d').date()
        days_open = (today - trade_date).days

        # Stop hit
        if price <= rec['stop_price']:
            pnl_pct = (rec['stop_price'] - rec['entry_price']) / rec['entry_price'] * 100
            db.resolve_recommendation(rec['id'], 'stopped_out', 'loss', round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: stopped out, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

        # Target hit
        elif price >= rec['target_price']:
            pnl_pct = (rec['target_price'] - rec['entry_price']) / rec['entry_price'] * 100
            db.resolve_recommendation(rec['id'], 'target_hit', 'win', round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: target hit, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

        # Expired
        elif days_open >= rec['max_days']:
            pnl_pct = (price - rec['entry_price']) / rec['entry_price'] * 100
            outcome = 'win' if pnl_pct > 0 else 'loss'
            db.resolve_recommendation(rec['id'], 'expired', outcome, round(pnl_pct, 2), days_open)
            logger.info(f"{rec['symbol']}: expired, {pnl_pct:+.1f}%, {days_open}d")
            resolved += 1

    logger.info(f"Reconciliation: {resolved} resolved, {len(active) - resolved} still active")
    return resolved


def generate_performance_summary(db: Database, lookback_days: int = 30):
    """Generate performance metrics from resolved recommendations."""
    resolved = db.get_resolved_recommendations(lookback_days)

    if not resolved:
        return {'total_trades': 0, 'note': 'No resolved trades in lookback period'}

    wins = [r for r in resolved if r['outcome'] == 'win']
    losses = [r for r in resolved if r['outcome'] == 'loss']

    total_pnl = sum(r['pnl_pct'] for r in wins) + sum(r['pnl_pct'] for r in losses)

    # By sector
    by_sector = {}
    for r in resolved:
        sec = r['sector']
        if sec not in by_sector:
            by_sector[sec] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
        if r['outcome'] == 'win':
            by_sector[sec]['wins'] += 1
        else:
            by_sector[sec]['losses'] += 1
        by_sector[sec]['total_pnl'] += r['pnl_pct']

    # By setup type
    by_setup = {}
    for r in resolved:
        st = r['setup_type']
        if st not in by_setup:
            by_setup[st] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
        if r['outcome'] == 'win':
            by_setup[st]['wins'] += 1
        else:
            by_setup[st]['losses'] += 1
        by_setup[st]['total_pnl'] += r['pnl_pct']

    return {
        'total_trades': len(resolved),
        'win_rate': round(len(wins) / len(resolved) * 100, 1) if resolved else 0,
        'avg_win_pct': round(sum(w['pnl_pct'] for w in wins) / len(wins), 2) if wins else 0,
        'avg_loss_pct': round(sum(l['pnl_pct'] for l in losses) / len(losses), 2) if losses else 0,
        'total_pnl_pct': round(total_pnl, 2),
        'profit_factor': round(
            abs(sum(w['pnl_pct'] for w in wins) / sum(l['pnl_pct'] for l in losses)), 2
        ) if losses and sum(l['pnl_pct'] for l in losses) != 0 else None,
        'by_sector': {s: {'win_rate': round(d['wins']/(d['wins']+d['losses'])*100, 1),
                          'pnl': round(d['total_pnl'], 2)}
                      for s, d in by_sector.items()},
        'by_setup': {s: {'win_rate': round(d['wins']/(d['wins']+d['losses'])*100, 1),
                         'pnl': round(d['total_pnl'], 2)}
                     for s, d in by_setup.items()},
    }
```

- [ ] **Step 2: Wire reconciliation into scheduler.py**

```python
# In run_sector_scan(), BEFORE analysis:
from core.reconciler import reconcile_recommendations
reconciled = reconcile_recommendations(db)
logger.info(f"Reconciled {reconciled} prior recommendations")
```

- [ ] **Step 3: Save recommendations after analysis**

```python
# In _find_stock_highlights(), after highlights are selected:
for sector in sector_analyses:
    for h in sector.highlights:
        self.db.save_recommendation({
            'trade_date': datetime.now().strftime('%Y-%m-%d'),
            'symbol': h.symbol, 'sector': sector.name,
            'setup_type': h.reason,
            'entry_price': h.entry, 'stop_price': h.stop,
            'target_price': h.target, 'rr': h.rr,
            'composite_score': composite_score(h),
            'position_size': h.position_size,
            'position_cost': h.position_cost,
            'risk_dollars': h.risk_dollars,
            'current_price': h.price,
            'entry_distance_pct': h.entry_distance_pct,
            'max_days': 20 if 'Swing' in (h.time_horizon or '') else 40,
        })
```

- [ ] **Step 4: Commit**

```bash
git add core/reconciler.py scheduler.py core/sector_analyzer.py
git commit -m "feat: daily reconciliation + performance tracking

New reconciler.py: checks active recs vs current prices, resolves
stopped_out/target_hit/expired. Generates performance summary by sector
and setup type. Recommendations saved after each scan.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.3: Add Prior Picks Recap to report HTML

**Files:**

- Modify: `core/reporter.py` — `_build_html()`

- [ ] **Step 1: Add Prior Picks Recap section**

After the positioning box, before Tag Details:

```python
# Prior Picks Recap
db = self.db  # need DB access — pass to ReportGenerator constructor
prior_recs = db.get_recommendations_since(
    (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
)

if prior_recs:
    parts.append('<h2>Prior Picks Recap</h2>')
    parts.append('<table><thead><tr><th>Symbol</th><th>Date</th><th>Setup</th>'
                 '<th>Entry</th><th>Stop</th><th>Target</th><th>Status</th><th>P&L</th></tr></thead><tbody>')

    for r in prior_recs[:30]:  # last 30
        status_icon = {
            'active': '<span class="badge-up">▲ Active</span>',
            'target_hit': '<span class="badge-up">✓ Hit</span>',
            'stopped_out': '<span class="badge-down">▼ Stopped</span>',
            'expired': '<span class="badge-neutral">— Expired</span>',
        }.get(r['status'], r['status'])

        pnl_str = f"{r['pnl_pct']:+.1f}%" if r.get('pnl_pct') else '--'
        parts.append(f'<tr><td class="sym">{r["symbol"]}</td>'
                     f'<td>{r["trade_date"][-5:]}</td>'
                     f'<td>{r["setup_type"]}</td>'
                     f'<td class="num">${r["entry_price"]:.2f}</td>'
                     f'<td class="num">${r["stop_price"]:.2f}</td>'
                     f'<td class="num">${r["target_price"]:.2f}</td>'
                     f'<td>{status_icon}</td>'
                     f'<td class="num">{pnl_str}</td></tr>')

    parts.append('</tbody></table>')
```

- [ ] **Step 2: Update ReportGenerator to accept db parameter**

```python
class ReportGenerator:
    def __init__(self, reports_dir=None, db=None):
        self.reports_dir = Path(reports_dir) if reports_dir else REPORTS_DIR
        self.db = db
```

- [ ] **Step 3: Add get_recommendations_since to db.py**

```python
def get_recommendations_since(self, since_date):
    conn = self.get_connection()
    rows = conn.execute(
        "SELECT * FROM recommendations WHERE trade_date >= ? ORDER BY trade_date DESC, id DESC",
        (since_date,)
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Commit**

```bash
git add core/reporter.py data/db.py
git commit -m "feat: Prior Picks Recap section in daily report

Shows last 7 days of picks with status (Active/Hit/Stopped/Expired)
and realized P&L. Enables traders to track recommendation accountability.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5.4: Weekly summary script

**Files:**

- Create: `scripts/weekly_summary.py`

- [ ] **Step 1: Write weekly summary generator**

```python
"""Generate weekly performance summary."""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.db import Database
from core.reconciler import generate_performance_summary


def main():
    db = Database()
    summary = generate_performance_summary(db, lookback_days=30)

    if summary.get('total_trades', 0) == 0:
        print("No resolved trades in last 30 days")
        return

    print(f"=== Weekly Performance Summary ({datetime.now().strftime('%Y-%m-%d')}) ===")
    print(f"Trades resolved (30d): {summary['total_trades']}")
    print(f"Win rate: {summary['win_rate']}%")
    print(f"Avg win: {summary['avg_win_pct']:+.1f}%")
    print(f"Avg loss: {summary['avg_loss_pct']:+.1f}%")
    print(f"Total P&L (30d): {summary['total_pnl_pct']:+.1f}%")
    if summary.get('profit_factor'):
        print(f"Profit factor: {summary['profit_factor']}")

    print("\nBy sector:")
    for sector, stats in sorted(summary.get('by_sector', {}).items(),
                                 key=lambda x: x[1]['pnl'], reverse=True):
        print(f"  {sector}: {stats['win_rate']}% win, {stats['pnl']:+.1f}% P&L")

    print("\nBy setup type:")
    for setup, stats in sorted(summary.get('by_setup', {}).items(),
                                key=lambda x: x[1]['pnl'], reverse=True):
        print(f"  {setup}: {stats['win_rate']}% win, {stats['pnl']:+.1f}% P&L")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Test**

```bash
python scripts/weekly_summary.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/weekly_summary.py
git commit -m "feat: weekly performance summary script

Outputs 30-day performance: win rate, avg win/loss, profit factor,
by-sector and by-setup breakdown. Designed for Saturday cron.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 6: Report UX (Weeks 5-6)

### Task 6.1: Embed OHLC data in report HTML

**Files:**

- Modify: `core/reporter.py` — `_build_html()`

- [ ] **Step 1: Pass db to ReportGenerator**

Already done in Task 5.3.

- [ ] **Step 2: Embed OHLC data as JSON blob**

In `_build_html()`, before `</body>`:

```python
# Embed OHLC data for offline chart rendering
all_ohlc = {}
if self.db:
    for sector in sectors:
        for h in sector.highlights:
            if h.symbol not in all_ohlc:
                df = self.db.get_market_data_df(h.symbol)
                if df is not None and len(df) > 0:
                    df_tail = df.tail(120)
                    records = []
                    for _, row in df_tail.iterrows():
                        records.append({
                            'date': str(row['date'])[:10] if 'date' in row else '',
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close'])
                        })
                    all_ohlc[h.symbol] = records

parts.append('<script>window._EMBEDDED_OHLC = ')
parts.append(json.dumps(all_ohlc))
parts.append(';</script>')
```

- [ ] **Step 3: Update chart JS to use embedded data**

In the inline `showChart()` JS function, add before the API fetch:

```javascript
// Try embedded data first
if (window._EMBEDDED_OHLC && window._EMBEDDED_OHLC[sym]) {
  drawCandles(
    anchor + "-canvas",
    window._EMBEDDED_OHLC[sym],
    supports || [],
    resistances || [],
    sym,
  );
  return;
}
// Fall back to API fetch...
```

- [ ] **Step 4: Commit**

```bash
git add core/reporter.py
git commit -m "feat: embed 120-bar OHLC data in report for offline charts

Charts now work when report opened from disk or email. JS tries
embedded data first, API fetch second.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6.2: Add responsive CSS

**Files:**

- Modify: `core/reporter.py` — `STYLE` constant

- [ ] **Step 1: Append responsive rules to STYLE**

```python
STYLE += """
@media (max-width: 768px) {
    body { padding: 12px; max-width: 100%; }
    table { font-size: 9px; }
    th, td { padding: 2px 4px; }
    .bar-label { width: 60px; font-size: 8px; }
    .positioning { flex-direction: column; }
    .card { padding: 8px 10px; }
    .stats-strip { gap: 8px; font-size: 10px; }
}

@media print {
    body { background: #fff; color: #000; max-width: 100%; }
    .fold-body { max-height: none !important; opacity: 1 !important; }
    .fold-body.hidden { max-height: none !important; opacity: 1 !important; }
    .bar-chart-wrap, .chart-inline { break-inside: avoid; }
    .footer { border-top: 1px solid #ccc; color: #666; }
    .card { background: #fff; border: 1px solid #ddd; }
    .up { color: #2d7d3a; } .down { color: #c0392b; }
}
"""
```

- [ ] **Step 2: Commit**

```bash
git add core/reporter.py
git commit -m "feat: responsive CSS for mobile and print

Mobile (<768px): stacked layout, smaller fonts, full-width.
Print: white background, expanded fold sections, avoid page breaks.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6.3: Add client-side table sorting and filtering

**Files:**

- Create: `web/js/table-utils.js`

- [ ] **Step 1: Write sortable/filterable table JS**

```javascript
// web/js/table-utils.js
function makeTablesSortable() {
  document.querySelectorAll("table").forEach((table) => {
    const headers = table.querySelectorAll("th");
    headers.forEach((th, colIdx) => {
      th.style.cursor = "pointer";
      th.title = "Click to sort";
      th.addEventListener("click", () => sortTable(table, colIdx));
    });
  });
}

function sortTable(table, colIdx) {
  const tbody = table.querySelector("tbody");
  if (!tbody) return;

  const rows = Array.from(tbody.querySelectorAll("tr"));
  const currentDir = table.dataset.sortDir === "asc" ? -1 : 1;
  const isNum = table.querySelector("td.num") !== null;

  rows.sort((a, b) => {
    let aVal =
      a.children[colIdx]?.textContent?.replace(/[$,%x]/g, "").trim() || "";
    let bVal =
      b.children[colIdx]?.textContent?.replace(/[$,%x]/g, "").trim() || "";

    if (isNum && colIdx >= 3) {
      // price columns and beyond
      aVal = parseFloat(aVal) || 0;
      bVal = parseFloat(bVal) || 0;
    } else {
      aVal = aVal.toLowerCase();
      bVal = bVal.toLowerCase();
    }

    if (aVal < bVal) return -1 * currentDir;
    if (aVal > bVal) return 1 * currentDir;
    return 0;
  });

  table.dataset.sortDir = currentDir === 1 ? "asc" : "desc";
  rows.forEach((row) => tbody.appendChild(row));

  // Update header indicators
  table
    .querySelectorAll("th")
    .forEach(
      (th) =>
        (th.textContent = th.textContent.replace(" ↑", "").replace(" ↓", "")),
    );
  const th = table.querySelectorAll("th")[colIdx];
  th.textContent += currentDir === 1 ? " ↑" : " ↓";
}

document.addEventListener("DOMContentLoaded", makeTablesSortable);
```

- [ ] **Step 2: Include in report HTML**

In `_build_html()`, add script reference:

```html
<script src="../js/table-utils.js"></script>
```

Or inline it if standalone operation is needed.

- [ ] **Step 3: Commit**

```bash
git add web/js/table-utils.js core/reporter.py
git commit -m "feat: client-side table sorting (click column headers)

Numeric columns sorted by value, text columns alphabetically.
Asc/desc toggle. Works in all sector detail tables.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 6.4: Add new setup types (MA Bounce, Inside Day, Bull Flag, ADX)

**Files:**

- Modify: `core/sector_analyzer.py` — `_find_stock_highlights()`

- [ ] **Step 1: Add ADX computation helper**

```python
def _compute_adx(df, period=14):
    """Compute ADX trend strength indicator."""
    if len(df) < period * 2:
        return None, None, None
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values

    tr = np.zeros(len(df))
    plus_dm = np.zeros(len(df))
    minus_dm = np.zeros(len(df))

    for i in range(1, len(df)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        up = high[i] - high[i-1]
        down = low[i-1] - low[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    atr_vals = pd.Series(tr).rolling(period).mean().values
    plus_di = pd.Series(plus_dm).rolling(period).mean().values / atr_vals * 100
    minus_di = pd.Series(minus_dm).rolling(period).mean().values / atr_vals * 100
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 0.0001) * 100
    adx = pd.Series(dx).rolling(period).mean().values

    return float(adx[-1]), float(plus_di[-1]), float(minus_di[-1])
```

- [ ] **Step 2: Add new setup types in the classification chain**

Insert after Strong Momentum block, before Good R/R:

```python
# MA Bounce: price near EMA with bullish reversal candle
elif ema21 and ema50:
    near_ema = (abs(price - ema21) / price < 0.02 or abs(price - ema50) / price < 0.02)
    bullish_candle = (
        cache.get('close', price) > cache.get('open', price) and
        (cache.get('close', price) - cache.get('low', price)) >
        (cache.get('high', price) - cache.get('low', price)) * 0.6
    )
    if near_ema and bullish_candle and price > ema50:
        reason = 'MA Bounce'
        detail = f"Bounced near EMA, bullish reversal candle"
        time_horizon = 'swing'

# Inside Day Breakout: today's range within yesterday's, breaks above
elif len(ohlc_df) >= 2 if ohlc_df is not None else False:
    try:
        yest = ohlc_df.iloc[-2]
        today_bar = ohlc_df.iloc[-1]
        inside = (today_bar['High'] < yest['High'] and today_bar['Low'] > yest['Low'])
        if inside and volume_ratio > 1.0 and price > yest['High'] * 0.995:
            reason = 'Inside Day Breakout'
            detail = f"Inside day, broke above ${yest['High']:.2f}"
            time_horizon = 'swing'
    except Exception:
        pass

# Bull Flag: sharp move up, then tight consolidation on declining volume
elif ret_5d and ret_5d > 5 and volume_ratio < 0.8 and ema21 and price > ema21:
    reason = 'Bull Flag'
    detail = f"{ret_5d:.1f}% 5d surge, low-vol consolidation"
    time_horizon = 'swing'

# ADX Trend: strong trend with directional bias
elif ohlc_df is not None and len(ohlc_df) >= 28:
    adx, plus_di, minus_di = _compute_adx(ohlc_df)
    if adx and adx > 20 and plus_di > minus_di and ema21 and price > ema21:
        reason = 'ADX Trend'
        detail = f"ADX {adx:.0f}, +DI > -DI, strong uptrend"
        time_horizon = 'position'
```

- [ ] **Step 3: Update setup_bonus, horizon_map, and reason_map**

```python
setup_bonus.update({
    'MA Bounce': 0.85,
    'Inside Day Breakout': 0.90,
    'Bull Flag': 0.80,
    'ADX Trend': 0.90,
})

horizon_map.update({
    'MA Bounce': 'Swing (5-20d)',
    'Inside Day Breakout': 'Short (3-10d)',
    'Bull Flag': 'Swing (5-20d)',
    'ADX Trend': 'Position (10-40d)',
})
```

- [ ] **Step 4: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "feat: 4 new setup types — MA Bounce, Inside Day, Bull Flag, ADX Trend

MA Bounce: price near EMA21/50 with bullish reversal candle.
Inside Day Breakout: NR7 pattern breaking above yesterday's high.
Bull Flag: 5%+ surge followed by low-vol consolidation above EMA21.
ADX Trend: ADX>20 with +DI>-DI for strong trending positions.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6.5: Add pre-trade guardrails

**Files:**

- Modify: `core/sector_analyzer.py` — `_find_stock_highlights()`

- [ ] **Step 1: Add liquidity guardrail**

Before scoring, after position sizing:

```python
# Liquidity check: position must be < 5% of average daily volume
avg_volume = cache.get('avg_volume_20d', 0)
if avg_volume > 0 and position_size / avg_volume > 0.05:
    continue  # too illiquid for position size

# Earnings proximity check
earnings_date = self.db.get_stock_earnings_date(symbol) if hasattr(self.db, 'get_stock_earnings_date') else None
if earnings_date:
    days_to_earnings = (datetime.strptime(earnings_date, '%Y-%m-%d').date() - datetime.now().date()).days
    if 0 < days_to_earnings <= 5:
        position_size = int(position_size * 0.5)
        position_cost = position_size * entry
        risk_dollars = position_size * risk_per_share
        highlight.earnings_warning = f"Earnings in {days_to_earnings}d — halved position"
```

- [ ] **Step 2: Add correlation flag**

After highlights selected for a sector:

```python
# Correlation check within sector: flag pairs with high correlation
for i in range(len(selected)):
    for j in range(i + 1, len(selected)):
        # Simple check: if both same setup type and both near support/resistance
        if selected[i].reason == selected[j].reason:
            selected[i].correlation_warning = f"Similar setup to {selected[j].symbol}"
```

- [ ] **Step 3: Commit**

```bash
git add core/sector_analyzer.py
git commit -m "feat: pre-trade guardrails — liquidity, earnings, correlation

Skips stocks where position >5% of avg daily volume.
Halves position size if earnings within 5 days.
Flags correlated picks in same sector.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6.6: UX polish — badges, keyboard shortcuts, timestamps

**Files:**

- Modify: `core/reporter.py` — `_build_html()` and JS

- [ ] **Step 1: Color-code horizon badges**

```python
# In HIGHLIGHT_ROW: color-code by horizon
horizon_cls_map = {
    'Short (3-10d)': 'badge-up',
    'Swing (5-20d)': 'badge-neutral',
    'Position (10-40d)': 'badge-neutral',
}
horizon_cls = horizon_cls_map.get(horizon_str, 'badge-neutral')
```

- [ ] **Step 2: Add keyboard shortcuts JS**

```javascript
// Keyboard navigation
document.addEventListener("keydown", function (e) {
  if (e.target.tagName === "INPUT") return;
  var cards = document.querySelectorAll(".tag-card");
  var visible = Array.from(cards).filter(function (c) {
    return c.style.display !== "none";
  });
  var currentIdx = visible.indexOf(document.activeElement);

  if (e.key === "j" || e.key === "ArrowDown") {
    e.preventDefault();
    var next = visible[Math.min(currentIdx + 1, visible.length - 1)];
    if (next) {
      next.focus();
      next.scrollIntoView({ behavior: "smooth" });
    }
  } else if (e.key === "k" || e.key === "ArrowUp") {
    e.preventDefault();
    var prev = visible[Math.max(currentIdx - 1, 0)];
    if (prev) {
      prev.focus();
      prev.scrollIntoView({ behavior: "smooth" });
    }
  } else if (e.key === "Enter") {
    e.preventDefault();
    var toggle = document.activeElement?.querySelector(".fold-toggle");
    if (toggle) toggle.click();
  }
});
```

- [ ] **Step 3: Format timestamp as human-readable**

```python
from datetime import datetime as dt
ts = dt.fromisoformat(timestamp)
formatted_ts = ts.strftime('%a, %b %d, %Y %I:%M %p ET')
```

- [ ] **Step 4: Add Expand All / Collapse All button**

```html
<button
  onclick="document.querySelectorAll('.fold-toggle').forEach(function(el){el.classList.remove('collapsed');el.nextElementSibling.classList.remove('hidden')})"
>
  Expand All
</button>
<button
  onclick="document.querySelectorAll('.fold-toggle').forEach(function(el){el.classList.add('collapsed');el.nextElementSibling.classList.add('hidden')})"
>
  Collapse All
</button>
```

- [ ] **Step 5: Commit**

```bash
git add core/reporter.py
git commit -m "feat: UX polish — horizon badge colors, keyboard shortcuts, timestamps

Color-coded horizon badges, j/k navigation, Enter toggle, Expand/Collapse All.
Human-readable timestamps (Sun, Jun 21, 2026 11:59 AM ET).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 7: Polish (Weeks 6-8)

### Task 7.1: Multiple timeframe S/R

**Files:**

- Modify: `core/swing_detector.py` — `compute_sr_for_symbol()`

- [ ] **Step 1: Add weekly S/R computation**

```python
# After daily S/R computation in compute_sr_for_symbol():
# Weekly S/R: resample to weekly, last 24 weeks
if len(df) >= 60:
    weekly = df.resample('W').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'
    }).dropna().tail(24)

    if len(weekly) >= 10:
        weekly_swing_h, weekly_swing_l = detect_swings(weekly, order=2)
        weekly_high_zones = cluster_levels(weekly_swing_h, atr=atr, price=current_price)
        weekly_low_zones = cluster_levels(weekly_swing_l, atr=atr, price=current_price)

        # Confluence bonus: boost daily zones that align with weekly
        for dz in low_zones:
            for wz in weekly_low_zones:
                if abs(dz['level'] - wz['level']) / dz['level'] < 0.01:
                    dz['count'] = dz.get('count', 1) + 2
                    dz['level'] = (dz['level'] + wz['level']) / 2  # average

        for dz in high_zones:
            for wz in weekly_high_zones:
                if abs(dz['level'] - wz['level']) / dz['level'] < 0.01:
                    dz['count'] = dz.get('count', 1) + 2
                    dz['level'] = (dz['level'] + wz['level']) / 2
```

- [ ] **Step 2: Commit**

```bash
git add core/swing_detector.py
git commit -m "feat: multiple timeframe S/R with weekly confluence bonus

Weekly S/R from 24-week OHLC. Daily zones aligned within 1% of weekly
get +2 count and averaged price. MTF-confirmed zones are stronger.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.2: Volume profile (VPVR)

**Files:**

- Modify: `core/swing_detector.py` — new function

- [ ] **Step 1: Add compute_volume_profile()**

```python
def compute_volume_profile(df, num_levels=15):
    """Volume-at-price for recent bars. Returns POC and value area."""
    if len(df) < 20:
        return None

    recent = df.tail(60)
    price_min = float(recent['Low'].min())
    price_max = float(recent['High'].max())

    bins = np.linspace(price_min, price_max, num_levels + 1)
    volume_by_price = np.zeros(num_levels)

    for _, row in recent.iterrows():
        candle_min = float(row['Low'])
        candle_max = float(row['High'])
        vol = float(row['Volume']) if 'Volume' in row and row['Volume'] > 0 else 1

        for j in range(num_levels):
            overlap = max(0, min(candle_max, bins[j+1]) - max(candle_min, bins[j]))
            if overlap > 0:
                volume_by_price[j] += vol * (overlap / (candle_max - candle_min + 0.01))

    poc_idx = int(np.argmax(volume_by_price))
    poc = float((bins[poc_idx] + bins[poc_idx + 1]) / 2)

    return {
        'poc': poc,
        'levels': [
            {'price': float((bins[i] + bins[i+1]) / 2), 'volume': float(volume_by_price[i])}
            for i in range(num_levels)
        ]
    }
```

- [ ] **Step 2: Wire POC into S/R zones**

In `compute_sr_for_symbol()`, after existing zone computation:

```python
vp = compute_volume_profile(df)
if vp:
    # POC as support/resistance depending on position vs current price
    if vp['poc'] < current_price:
        supports.append(vp['poc'])
    else:
        resistances.append(vp['poc'])
```

- [ ] **Step 3: Commit**

```bash
git add core/swing_detector.py
git commit -m "feat: volume profile (VPVR) with POC as S/R

Computes 15-level volume-at-price over 60 bars. Point of control
added as support or resistance depending on position vs price.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.3: Psychological levels + gap fills + session levels

**Files:**

- Modify: `core/swing_detector.py` — new helper functions

- [ ] **Step 1: Add psychological_levels()**

```python
def psychological_levels(price):
    """Round-number levels within 5% of price."""
    levels = []
    for base in [100, 50, 10]:
        near = round(price / base) * base
        for offset in [-base, 0, base]:
            lvl = near + offset
            if lvl > 0 and abs(lvl - price) / price < 0.05:
                levels.append({'level': float(lvl), 'count': 2, 'type': f'psych_{base}'})
    return levels

def gap_fill_levels(cache, price):
    """Unfilled gap as price magnet."""
    gap_pct = cache.get('gap_1d_pct')
    if gap_pct and abs(gap_pct) > 0.01:
        gap_price = price / (1 + gap_pct)
        if abs(gap_price - price) / price < 0.15:
            return [{'level': round(gap_price, 2), 'count': 2, 'type': 'gap_fill'}]
    return []

def session_levels(df):
    """Weekly pivot, prior week high/low."""
    recent = df.tail(5)
    if len(recent) < 5:
        return []
    h = float(recent['High'].max())
    l = float(recent['Low'].min())
    c = float(recent['Close'].iloc[-1])
    pivot = (h + l + c) / 3
    return [
        {'level': round(pivot, 2), 'count': 3, 'type': 'weekly_pivot'},
        {'level': h, 'count': 1, 'type': 'prior_week_high'},
        {'level': l, 'count': 1, 'type': 'prior_week_low'},
    ]
```

- [ ] **Step 2: Wire all into compute_sr_for_symbol()**

```python
# After existing zone computation:
psych = psychological_levels(current_price)
gaps = gap_fill_levels(cache, current_price)
sessions = session_levels(df)

# Merge into supports/resistances
for lvl_dict in psych + gaps + sessions:
    if lvl_dict['level'] < current_price:
        supports.append(lvl_dict['level'])
    elif lvl_dict['level'] > current_price:
        resistances.append(lvl_dict['level'])
```

- [ ] **Step 3: Commit**

```bash
git add core/swing_detector.py
git commit -m "feat: psychological levels + gap fills + session reference levels

Round-number ($X.00/$X.50/$X.10) levels, unfilled gap magnets,
weekly pivot, prior week high/low added to S/R zone pool.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.4: Anchored VWAP

**Files:**

- Modify: `core/swing_detector.py` — new function

- [ ] **Step 1: Add anchored_vwap()**

```python
def anchored_vwap(df, anchor_date, current_price):
    """VWAP from a specific anchor date to present."""
    anchor_df = df[df.index >= pd.to_datetime(anchor_date)]
    if len(anchor_df) < 5:
        return None
    if 'Volume' not in anchor_df.columns or anchor_df['Volume'].sum() == 0:
        return None
    vwap = (anchor_df['Close'] * anchor_df['Volume']).sum() / anchor_df['Volume'].sum()
    if abs(vwap - current_price) / current_price < 0.15:
        return {'level': round(float(vwap), 2), 'count': 2, 'type': 'anchored_vwap'}
    return None


def compute_anchored_vwaps(db, symbol, df, current_price):
    """Compute AVWAPs from key anchor dates: earnings, 52w high, gap day."""
    levels = []
    # From last earnings date
    earnings = db.get_stock_earnings_date(symbol)
    if earnings and earnings > (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d'):
        avwap = anchored_vwap(df, earnings, current_price)
        if avwap:
            levels.append(avwap)
    return levels
```

- [ ] **Step 2: Wire into compute_sr_for_symbol()**

```python
avwaps = compute_anchored_vwaps(db, symbol, df, current_price)
for lvl_dict in avwaps:
    if lvl_dict['level'] < current_price:
        supports.append(lvl_dict['level'])
    else:
        resistances.append(lvl_dict['level'])
```

- [ ] **Step 3: Commit**

```bash
git add core/swing_detector.py
git commit -m "feat: anchored VWAP from earnings dates as S/R

Computes VWAP from last earnings date anchor. Within 15% of price,
added as support or resistance zone.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.5: Report enhancements — correlation matrix, CSV export, AI confidence

**Files:**

- Modify: `core/reporter.py` — `_build_html()`

- [ ] **Step 1: Add AI confidence indicator per sector**

```python
# In SECTOR_CARD: add confidence dot before sector name
if s.outlook and 'unavailable' not in s.outlook:
    if 'divergence' in s.outlook.lower():
        confidence_dot = '<span style="color:var(--ember)" title="AI/quant divergence">●</span> '
    else:
        confidence_dot = '<span style="color:var(--volt)" title="AI analysis OK">●</span> '
else:
    confidence_dot = '<span style="color:var(--ash)" title="AI unavailable">●</span> '
```

- [ ] **Step 2: Add CSV export button**

```html
<button onclick="exportHighlightsCSV()" style="margin-bottom:12px">
  Export CSV
</button>
<script>
  function exportHighlightsCSV() {
    var rows = [
      [
        "Symbol",
        "Sector",
        "Reason",
        "Entry",
        "Stop",
        "Target",
        "R/R",
        "Size",
        "Cost",
        "Risk$",
      ],
    ];
    document.querySelectorAll(".tag-card").forEach(function (card) {
      var sector = card.querySelector("h3").textContent.trim();
      card.querySelectorAll("tbody tr").forEach(function (tr) {
        var cells = tr.querySelectorAll("td");
        if (cells.length >= 12) {
          rows.push([
            cells[0].textContent,
            sector,
            cells[3].textContent,
            cells[4].textContent,
            cells[6].textContent,
            cells[7].textContent,
            cells[8].textContent,
            cells[9].textContent,
            cells[10].textContent,
            cells[11].textContent,
          ]);
        }
      });
    });
    var csv = rows
      .map(function (r) {
        return r.join(",");
      })
      .join("\\n");
    var blob = new Blob([csv], { type: "text/csv" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "tradescanner_highlights.csv";
    a.click();
  }
</script>
```

- [ ] **Step 3: Commit**

```bash
git add core/reporter.py
git commit -m "feat: AI confidence indicator + CSV export button

Green/yellow/red dots per sector showing AI status.
One-click CSV export of all highlight rows.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.6: Automated holiday calendar

**Files:**

- Modify: `scheduler.py` — `is_trading_day()`

- [ ] **Step 1: Replace hardcoded holidays**

```python
# Remove HOLIDAYS_2026 set
# Replace is_trading_day():
def is_trading_day() -> bool:
    """Check if today is a US trading day using pandas_market_calendars."""
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar('NYSE')
        today = datetime.now().date()
        schedule = nyse.schedule(start_date=today, end_date=today)
        return not schedule.empty
    except ImportError:
        # Fallback: basic weekday check
        return datetime.now().weekday() < 5
```

- [ ] **Step 2: Install dependency**

```bash
pip install pandas_market_calendars
```

- [ ] **Step 3: Commit**

```bash
git add scheduler.py
git commit -m "fix: automated NYSE holiday calendar via pandas_market_calendars

Replaces hardcoded HOLIDAYS_2026 set. Auto-detects holidays
including dynamic dates (Good Friday, etc.). Falls back to
weekday check if library not installed.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7.7: Final test suite run and integration check

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 2: Run full scan**

```bash
python scheduler.py --force
```

- [ ] **Step 3: Verify report**

```bash
ls -la web/reports/report_$(date +%Y-%m-%d).html
# Open in browser, verify: charts render, sorting works, Prior Picks section present
```

- [ ] **Step 4: Reproducibility check**

```bash
python scheduler.py --force 2>&1 | grep "AI call:"
python scheduler.py --force 2>&1 | grep "AI call:"
# Response hashes should be identical (cached)
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: final integration — Phase 7 polish complete

All 18 critical issues resolved. All 45+ medium issues resolved.
All missing features implemented.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Summary

| Phase         | Tasks | Critical Issues Fixed             | Key Deliverable                                             |
| ------------- | ----- | --------------------------------- | ----------------------------------------------------------- |
| 1. Foundation | 8     | #1, #2, #3, #4, #5, #10, #11, #12 | Live RS scoring, order=4 S/R, min R:R=1.5                   |
| 2. Safety     | 5     | #6, #8, #16, #17                  | Freshness validation, checkpointing, no falling knives      |
| 3. AI         | 4     | #13, #14                          | Native search, T=0 determinism, audit log                   |
| 4. Scoring    | 4     | Medium issues                     | Config-driven weights, rank-IC validation                   |
| 5. Feedback   | 4     | #9, #15                           | Lifecycle tracking, Prior Picks Recap                       |
| 6. UX         | 7     | #18 + 10 medium                   | Offline charts, responsive, sorting, new setups, guardrails |
| 7. Polish     | 7     | Remaining medium                  | Multi-TF S/R, VPVR, AVWAP, psych levels, auto-calendar, CSV |

**Total:** ~39 tasks across 7 phases.
