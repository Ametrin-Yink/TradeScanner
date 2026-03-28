# Scoring Utils Refactoring Plan

## Overview
Extract duplicate scoring calculation functions from strategies into a unified `core/scoring_utils.py` module.

## Phase 1: Foundation (Immediate)

### Task 1.1: Create scoring_utils.py
**File:** `core/scoring_utils.py`
**Functions to extract:**
- `calculate_clv(close, high, low)` - CLV calculation
- `check_rsi_divergence(df, direction, lookback=20)` - RSI divergence
- `check_exhaustion_gap(df, level, direction, gap_threshold=0.01)` - Exhaustion gap
- `calculate_test_interval(df, level, atr, level_type, min_interval=3)` - Test quality
- `calculate_institutional_intensity(volume_ratio, clv)` - Institutional factor
- `detect_market_direction(spy_df)` - Market regime
- `check_vix_filter(vix_df, direction)` - VIX risk filter

**Verification:**
```bash
python3 -m py_compile core/scoring_utils.py
```

### Task 1.2: Update DTSS Strategy
**File:** `core/strategies/dtss.py`
**Changes:**
- Import functions from scoring_utils
- Remove `_calculate_clv`, `_check_rsi_divergence`, `_check_exhaustion_gap`
- Update `_calculate_test_info` to use shared function

**Verification:**
```bash
python3 -c "from core.strategies.dtss import DTSSStrategy; s = DTSSStrategy(); print('DTSS OK')"
```

### Task 1.3: Update Parabolic Strategy
**File:** `core/strategies/parabolic.py`
**Changes:**
- Import functions from scoring_utils
- Remove duplicate `_calculate_clv`, `_check_rsi_divergence`

**Verification:**
```bash
python3 -c "from core.strategies.parabolic import ParabolicStrategy; s = ParabolicStrategy(); print('Parabolic OK')"
```

### Task 1.4: Update UpthrustRebound Strategy
**File:** `core/strategies/upthrust_rebound.py`
**Changes:**
- Import functions from scoring_utils
- Remove duplicate `_calculate_clv`

**Verification:**
```bash
python3 -c "from core.strategies.upthrust_rebound import UpthrustReboundStrategy; s = UpthrustReboundStrategy(); print('U&R OK')"
```

### Task 1.5: Update CLAUDE.md
**File:** `CLAUDE.md`
**Add section:**
- Strategy scoring utilities module
- Refactoring guidelines
- Phase completion checklist

## Phase 2: Strategy A-D Refactoring (When Refactoring A-D)

### Task 2.1: Extract RS Score Calculation
**Function:** `calculate_rs_score_weighted(rs_3m, rs_6m, rs_12m)`
**Formula:** `0.4*rs_3m + 0.3*rs_6m + 0.3*rs_12m`

### Task 2.2: Extract Normalized EMA Slope
**Function:** `calculate_normalized_ema_slope(df, ema_period, atr)`
**Returns:** Slope normalized by ATR

### Task 2.3: Extract Volume Climax Detection
**Function:** `calculate_volume_climax(volume_ratio, thresholds)`
**Returns:** Climax score based on thresholds

### Task 2.4: Update Strategies A-D
**Files:**
- `core/strategies/vcp_ep.py`
- `core/strategies/momentum.py`
- `core/strategies/shoryuken.py`
- `core/strategies/pullback.py`

## Phase 3: Configuration Externalization (Optional)

### Task 3.1: Create Strategy Config Template
**File:** `config/strategy_config.yaml` (optional)
**Content:** Parameter templates for each strategy

### Task 3.2: Parameter Validation
**File:** `core/scoring_utils/validation.py`
**Functions:** Validate parameters against ranges

## Dependencies
- Phase 2 depends on Phase 1 completion
- Phase 3 is optional, depends on Phase 2

## Success Criteria
1. No duplicate `_calculate_clv` across strategies
2. All strategies import from scoring_utils
3. Syntax checks pass
4. Import tests pass
