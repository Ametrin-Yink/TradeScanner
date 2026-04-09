# BUG-007: DataFrame truth value ambiguous in screener.py

**Date:** 2026-04-01
**Severity:** High
**Status:** Fixed

## Problem Description

Phase 2 (Strategy Screening) crashes with `ValueError: The truth value of a DataFrame is ambiguous` when trying to load SPY data.

## Error Log

```
2026-04-01 23:40:32,873 - __main__ - ERROR - Workflow failed: The truth value of a DataFrame is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().
Traceback (most recent call last):
  File "/home/admin/Projects/TradeChanceScreen/scheduler.py", line 134, in run_complete_workflow
    phase2_result = self._phase2_screening(symbols)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/admin/Projects/TradeChanceScreen/scheduler.py", line 274, in _phase2_screening
    candidates = self.screener.screen_all(symbols=symbols)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/admin/Projects/TradeChanceScreen/core/screener.py", line 567, in screen_all
    self._phase0_data = self._run_phase0_precalculation(symbols, self.market_data)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/admin/Projects/TradeChanceScreen/core/screener.py", line 95, in _run_phase0_precalculation
    self._spy_data = self._load_tier3_data('SPY') or self._get_data('SPY')
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/admin/Projects/TradeChanceScreen/core/screener.py", line 122
    df = market_data.get(symbol) or self._get_data(symbol)
ValueError: The truth value of a DataFrame is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().
```

## Root Cause

Using Python's `or` operator with pandas DataFrames. When the first operand returns a DataFrame, Python tries to evaluate its truth value, which is ambiguous for DataFrames.

**Line 95:**

```python
self._spy_data = self._load_tier3_data('SPY') or self._get_data('SPY')
```

**Line 122:**

```python
df = market_data.get(symbol) or self._get_data(symbol)
```

## Fix Applied

Changed both lines to use explicit None checks:

**Line 95-98:**

```python
# Before:
self._spy_data = self._load_tier3_data('SPY') or self._get_data('SPY')

# After:
spy_data = self._load_tier3_data('SPY')
if spy_data is None:
    spy_data = self._get_data('SPY')
self._spy_data = spy_data
```

**Line 122-123:**

```python
# Before:
df = market_data.get(symbol) or self._get_data(symbol)

# After:
df = market_data.get(symbol)
if df is None:
    df = self._get_data(symbol)
```

## Files Modified

- `core/screener.py` - Lines 95-98 and 122-123

## Verification

After fix, Phase 2 should proceed without the DataFrame truth value error.
