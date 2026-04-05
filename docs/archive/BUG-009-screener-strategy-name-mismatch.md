# BUG-009: Strategy name mismatch in _allocate_candidates causing 0 selections

**Date:** 2026-04-02
**Severity:** High
**Status:** Fixed

## Problem Description

Phase 2 (Strategy Screening) found 10 candidates from Shoryuken strategy, but Phase 2 (Dynamic Allocation) selected 0 candidates. The allocation logic was not matching candidates to their strategy groups.

## Error Log

```
2026-04-02 02:06:05,945 - core.screener - INFO - PHASE 1 COMPLETE: 10 total candidates from all strategies
...
2026-04-02 02:06:05,947 - core.screener - INFO - [breakout_momentum] Selected 0/0 candidates (target: 5)
2026-04-02 02:06:05,947 - core.screener - INFO - [trend_pullback] Selected 0/0 candidates (target: 5)
2026-04-02 02:06:05,947 - core.screener - INFO - [rebound_range] Selected 0/0 candidates (target: 15)
2026-04-02 02:06:05,947 - core.screener - INFO - [extreme_reversal] Selected 0/0 candidates (target: 5)
2026-04-02 02:06:05,947 - core.screener - INFO - TOTAL: 0 candidates selected
```

## Root Cause

The `_allocate_candidates` method in `core/screener.py` was comparing `candidate.strategy` (strategy NAME like `"PullbackEntry"`) to `StrategyType.value` (like `"Shoryuken"`).

**StrategyType enum values:**
- `EP = "EP"`
- `SHORYUKEN = "Shoryuken"`
- etc.

**Strategy NAME attributes:**
- `MomentumBreakout.NAME = "MomentumBreakout"`
- `PullbackEntry.NAME = "PullbackEntry"`
- etc.

The `candidate.strategy` field is populated from `self.NAME` in each strategy, but the code was comparing against `StrategyType.value`.

## Fix Applied

1. Added new mapping `STRATEGY_NAME_TO_GROUP` that maps strategy NAME to group:
```python
STRATEGY_NAME_TO_GROUP = {
    "MomentumBreakout": "breakout_momentum",
    "PullbackEntry": "trend_pullback",
    "SupportBounce": "rebound_range",
    "RangeShort": "rebound_range",
    "DoubleTopBottom": "rebound_range",
    "CapitulationRebound": "extreme_reversal",
}
```

2. Updated `_allocate_candidates` to use the new mapping instead of `STRATEGY_GROUPS`.

## Files Modified
- `core/screener.py` - Added `STRATEGY_NAME_TO_GROUP` mapping and updated `_allocate_candidates` method

## Verification

After fix, candidates should be correctly allocated to their strategy groups based on the AI-driven allocation.
