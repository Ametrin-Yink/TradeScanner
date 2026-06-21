# Task 1.6 Report: Rewrite compute_stop_target()

## Summary

Rewrote `compute_stop_target()` in `core/swing_detector.py` with a zone quality gate, best-of-candidates stop selection, and target cascade with minimum R:R enforcement. Also created `config/portfolio_config.py` as a shared config loader and updated `core/sector_analyzer.py` to handle None returns.

## Files Changed

### Modified

- **`core/swing_detector.py`** — `compute_stop_target()` fully rewritten:
  - Stop cascade: multi-touch support zones (quality >= 2) preferred, EMAs (quality=2) next, single-touch zones next, ATR fallback (quality=1) last. Within each quality tier, the tightest (nearest to entry) stop is selected.
  - `max_stop_distance` caps stop distance to `min(2.5*ATR, 5% of price)`.
  - Target cascade: resistance zones in ascending order (first with R:R >= min_rr), then Fib 1.618 extension, then 3x ATR, then risk-multiple fallback.
  - Returns `(None, None, 'skip')` if no valid stop/target combo exists.
  - `_compute_fib_target()` now accepts `extension` parameter (default 1.618).

- **`core/sector_analyzer.py`**:
  - `_find_stock_highlights()` now checks if `stop is None` after `compute_stop_target()` and `continue`s to skip invalid setups.
  - Replaced local `_load_portfolio_config()` with shared `load_config()` from `config/portfolio_config`.
  - Removed unused `yaml` import.

- **`config/portfolio_config.yaml`** — Added `stop_target` section with all configurable parameters.

- **`tests/core/test_swing_detector.py`** — Added 13 new unit tests covering quality gate, EMAs, ATR fallback, target iteration, Fib extension, 3x ATR target, risk-multiple, far support filtering, position min R:R, and Fib extension param.

- **`tests/e2e/test_rr_algorithm.py`** — Updated existing tests for new stop distance constraints and method format.

### Created

- **`config/portfolio_config.py`** — Shared `load_config()` function to load from YAML with fallback defaults.

## Key Design Decisions

1. **Zone quality** uses `z.get('count', 1)` — multi-touch zones (count >= 2) always beat single-touch, even if the single-touch is closer to entry. This prevents spurious single-tick S/R levels from dominating.

2. **`max_stop_distance`** is `min(2.5 * ATR, 5% of price)` — the 5% price cap ensures stops are not impractically wide even on high-ATR stocks.

3. **R:R gate** applies to all target levels — resistance, Fib extension, and ATR 3x all get checked against `min_rr` (1.5 swing, 2.0 position). Only the risk-multiple fallback is unconditional (it calculates exactly `min_rr * risk`).

## Test Results

All 101 tests pass (13 new unit tests + updated E2E + existing tests).
