# BUG-006: Phase 0 incorrectly marked as failed due to expected errors

**Date:** 2026-04-01
**Severity:** High
**Status:** Fixed

## Problem Description

Phase 0 of the workflow is incorrectly marked as failed when there are any errors in the `errors` list, even if those errors are expected (e.g., delisted stocks). This causes the entire workflow to abort unnecessarily.

## Root Cause

In `core/premarket_prep.py` line 128:

```python
return {
    'success': len(errors) == 0,  # <-- Too strict
    'symbols': qualifying_stocks,
    ...
}
```

In `scheduler.py` line 118-126:

```python
phase0_result = self._phase0_data_prep(symbols)
if not phase0_result['success']:
    logger.error("Phase 0 failed, aborting workflow")
    ...
    return None
```

## Expected vs Actual Behavior

**Expected:** Phase 0 should be considered successful if:

- Database is initialized
- Tier 3 data is fetched
- Market data is updated for majority of symbols
- Pre-filter produces qualifying stocks
- Tier 1 cache is calculated

**Actual:** Phase 0 fails if ANY error occurs (including expected errors like delisted stocks: ABMD, ANTM, DISH, etc.)

## Evidence from Logs

```
2026-04-01 22:55:08,603 - core.premarket_prep - INFO - ✓ Market data updated: 2926/2941 symbols
2026-04-01 22:55:08,603 - core.premarket_prep - WARNING -   Failed: 15 symbols
...
2026-04-01 23:23:42,626 - core.premarket_prep - INFO - ✓ Pre-filter: 1559 stocks passed
2026-04-01 23:24:21,017 - core.premarket_prep - INFO - ✓ Tier 1 cache calculated: 1556 symbols
2026-04-01 23:24:21,017 - core.premarket_prep - INFO - PHASE 0 Complete in 5527.8s
2026-04-01 23:24:21,021 - __main__ - ERROR - Phase 0 failed, aborting workflow
```

Phase 0 actually **succeeded** but was marked as failed due to 15 delisted stock errors.

## Fix Applied

Changed the success criteria in `core/premarket_prep.py` line 127-137:

```python
# Phase 0 is successful if we have qualifying stocks and Tier 1 cache
# Some errors (e.g., delisted stocks) are expected and shouldn't fail the phase
phase0_success = len(qualifying_stocks) > 0 and tier1_count > 0

return {
    'success': phase0_success,
    'symbols': qualifying_stocks,
    ...
}
```

## Files Modified

- `core/premarket_prep.py` - Changed success criteria from `len(errors) == 0` to `len(qualifying_stocks) > 0 and tier1_count > 0`

## Verification

After fix, Phase 0 should complete successfully even when some stocks fail to fetch (delisted, etc.), as long as the core data preparation succeeds (has qualifying stocks and Tier 1 cache).
