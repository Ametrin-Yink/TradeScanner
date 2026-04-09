# Critical Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all critical and high-severity bugs identified in the comprehensive code review, including security issues, runtime errors, data pipeline bugs, and strategy logic errors.

**Architecture:** Fix issues in dependency order: security → data pipeline → core utilities → strategies → documentation. Each fix includes proper error handling, bounds checking, and maintains backward compatibility where possible.

**Tech Stack:** Python 3.10+, pandas, numpy, Flask, SQLite, yfinance

---

## Phase 1: Security Fixes (CRITICAL)

### Task 1: Fix secrets.json file permissions

**Files:**

- Modify: `config/secrets.json` (file permissions only)

**Issue:** API keys stored with world-readable permissions (644)

- [ ] **Step 1: Change file permissions to 600**

Run: `chmod 600 /home/admin/Projects/TradeChanceScreen/config/secrets.json`
Expected: File now readable only by owner

- [ ] **Step 2: Verify permissions**

Run: `ls -la /home/admin/Projects/TradeChanceScreen/config/secrets.json`
Expected: Shows `-rw-------` permissions

- [ ] **Step 3: Commit**

```bash
git add config/secrets.json
git commit -m "security: restrict secrets.json permissions to owner-only"
```

---

### Task 2: Add input validation to Flask API

**Files:**

- Modify: `api/server.py:178, 203`

**Issue:** Stock symbols not validated against whitelist/format

- [ ] **Step 1: Add symbol validation function at top of server.py**

```python
import re

# After existing imports, add:
def validate_symbol(symbol: str) -> bool:
    """Validate stock symbol format."""
    if not symbol or len(symbol) > 10:
        return False
    # Allow A-Z, 0-9, and dot (for ETFs like BRK.B)
    return bool(re.match(r'^[A-Z0-9.]{1,10}$', symbol))
```

- [ ] **Step 2: Apply validation to get_stock_data endpoint**

Locate around line 178:

```python
@app.route('/api/stock/<symbol>')
def get_stock_data(symbol):
    """Get stock data for symbol."""
    symbol = symbol.upper()
    # Add validation:
    if not validate_symbol(symbol):
        return jsonify({'error': 'Invalid symbol format'}), 400
```

- [ ] **Step 3: Apply validation to scan_symbol endpoint**

Locate around line 203:

```python
@app.route('/api/scan/<symbol>')
def scan_symbol(symbol):
    """Scan single symbol."""
    symbol = symbol.upper()
    # Add validation:
    if not validate_symbol(symbol):
        return jsonify({'error': 'Invalid symbol format'}), 400
```

- [ ] **Step 4: Commit**

```bash
git add api/server.py
git commit -m "security: add stock symbol validation to API endpoints"
```

---

### Task 3: Fix Flask debug mode security

**Files:**

- Modify: `api/server.py:301`

**Issue:** Debug parameter can be enabled in production

- [ ] **Step 1: Read the current run_app function**

- [ ] **Step 2: Hardcode debug to False or use environment variable**

```python
# Replace:
# app.run(host='0.0.0.0', port=port, debug=debug)
# With:
import os
debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
app.run(host='0.0.0.0', port=port, debug=debug_mode)
```

- [ ] **Step 3: Commit**

```bash
git add api/server.py
git commit -m "security: use environment variable for Flask debug mode"
```

---

## Phase 2: Critical Runtime Error Fixes

### Task 4: Replace all bare except clauses

**Files:**

- Modify: `core/screener.py:383`
- Modify: `core/reporter.py:173`
- Modify: `core/indicators.py:677, 1018`

**Issue:** Bare `except:` masks critical errors

- [ ] **Step 1: Fix screener.py \_check_basic_requirements**

Locate line 276-277:

```python
# Replace:
except:
    return False
# With:
except (KeyError, IndexError, AttributeError, ValueError) as e:
    logger.debug(f"Basic requirements check failed: {e}")
    return False
```

- [ ] **Step 2: Fix reporter.py timestamp parsing**

Locate around line 173:

```python
# Replace:
except:
    sentiment['timestamp'] = 'Unknown'
# With:
except (ValueError, KeyError, TypeError) as e:
    logger.debug(f"Failed to parse timestamp: {e}")
    sentiment['timestamp'] = 'Unknown'
```

- [ ] **Step 3: Fix indicators.py \_detect_blow_off**

Locate around line 677:

```python
# Replace:
except:
    return 0
# With:
except (KeyError, IndexError, ValueError) as e:
    logger.debug(f"Blow-off detection failed: {e}")
    return 0
```

- [ ] **Step 4: Fix indicators.py \_calculate_clv_for_index**

Locate around line 1018:

```python
# Replace:
except:
    return 0.5
# With:
except (KeyError, IndexError, ValueError) as e:
    logger.debug(f"CLV calculation failed: {e}")
    return 0.5
```

- [ ] **Step 5: Commit**

```bash
git add core/screener.py core/reporter.py core/indicators.py
git commit -m "fix: replace bare except clauses with specific exceptions"
```

---

### Task 5: Fix thread-unsafe global cache

**Files:**

- Modify: `core/indicators.py:30-32`

**Issue:** Class-level cache without thread synchronization

- [ ] **Step 1: Add threading import**

```python
# Add to imports:
import threading
```

- [ ] **Step 2: Add lock to class definition**

Replace lines 30-32:

```python
class TechnicalIndicators:
    """Calculate technical indicators for stock analysis with caching."""

    # Class-level cache for indicator calculations
    _cache: Dict[str, Dict] = {}
    _cache_hits: int = 0
    _cache_misses: int = 0
    _cache_lock = threading.Lock()  # Thread-safe lock
```

- [ ] **Step 3: Wrap cache access with lock**

In `calculate_all()` method, replace cache check:

```python
# Replace:
if cache_key in TechnicalIndicators._cache:
    TechnicalIndicators._cache_hits += 1
    self.indicators = TechnicalIndicators._cache[cache_key]
    return self.indicators
# With:
with TechnicalIndicators._cache_lock:
    if cache_key in TechnicalIndicators._cache:
        TechnicalIndicators._cache_hits += 1
        self.indicators = TechnicalIndicators._cache[cache_key]
        return self.indicators
```

And cache storage:

```python
# Replace:
TechnicalIndicators._cache[cache_key] = self.indicators
# With:
with TechnicalIndicators._cache_lock:
    TechnicalIndicators._cache[cache_key] = self.indicators
```

- [ ] **Step 4: Commit**

```bash
git add core/indicators.py
git commit -m "fix: add thread-safe locking to indicator cache"
```

---

### Task 6: Fix IndexError vulnerabilities in screener

**Files:**

- Modify: `core/screener.py:101-102, 136, 139, 142, 146`

**Issue:** DataFrame index access without bounds checking

- [ ] **Step 1: Fix SPY data access**

Locate lines 100-103:

```python
# Replace:
if self._spy_data is not None and len(self._spy_data) >= 5:
    spy_current = self._spy_data['close'].iloc[-1]
    spy_5d_ago = self._spy_data['close'].iloc[-5]
# With:
if self._spy_data is not None and len(self._spy_data) >= 5:
    spy_current = self._spy_data['close'].iloc[-1]
    spy_5d_ago = self._spy_data['close'].iloc[-5]
else:
    logger.warning("SPY data insufficient for RS calculations")
    self._spy_return_5d = 0.0
```

- [ ] **Step 2: Fix returns calculations with proper bounds**

Locate lines 134-147:

```python
# Replace entire block with:
returns = {}
min_required = {'3m': 63, '6m': 126, '12m': 252}
for period, days in min_required.items():
    if len(df) >= days + 1:  # +1 for current price
        price_ago = df['close'].iloc[-days]
        returns[period] = (current_price - price_ago) / price_ago

# 5-day return with bounds check
if len(df) >= 6:
    price_5d_ago = df['close'].iloc[-5]
else:
    price_5d_ago = df['close'].iloc[0] if len(df) > 0 else current_price
ret_5d = (current_price - price_5d_ago) / price_5d_ago if price_5d_ago > 0 else 0.0
```

- [ ] **Step 3: Commit**

```bash
git add core/screener.py
git commit -m "fix: add bounds checking for DataFrame index access in screener"
```

---

### Task 7: Fix None dereference in strategy pipeline

**Files:**

- Modify: `core/strategies/base_strategy.py:184-186`

**Issue:** `_get_data` can return None but code assumes DataFrame

- [ ] **Step 1: Fix \_get_data return handling in screen method**

Locate lines 182-186:

```python
# Replace:
df = self._get_data(symbol)
if df is None or len(df) < 50:
    continue
# With:
df = self._get_data(symbol)
if df is None:
    logger.debug(f"No data for {symbol}")
    continue
if not isinstance(df, pd.DataFrame) or len(df) < 50:
    logger.debug(f"Insufficient data for {symbol}: {len(df) if isinstance(df, pd.DataFrame) else 'N/A'} rows")
    continue
```

- [ ] **Step 2: Commit**

```bash
git add core/strategies/base_strategy.py
git commit -m "fix: add proper None/type checking for DataFrame in strategy pipeline"
```

---

## Phase 3: Data Pipeline Fixes

### Task 8: Fix timezone inconsistency in cache merging

**Files:**

- Modify: `core/fetcher.py:150`

**Issue:** yfinance data may have timezone-aware timestamps while cached data is naive

- [ ] **Step 1: Add timezone normalization in \_merge_with_cache**

```python
# Before cache merge logic, add:
def _normalize_timezone(self, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize timezone to UTC for consistent comparisons."""
    if df.index.tz is not None:
        df.index = df.index.tz_convert('UTC').tz_localize(None)
    return df
```

- [ ] **Step 2: Apply normalization before comparison**

Locate cache merging code:

```python
# Before the merge, normalize both DataFrames:
cached_df = self._normalize_timezone(cached_df)
df = self._normalize_timezone(df)
```

- [ ] **Step 3: Commit**

```bash
git add core/fetcher.py
git commit -m "fix: normalize timezone before cache merging"
```

---

### Task 9: Fix date parsing in fetcher

**Files:**

- Modify: `core/fetcher.py:245`

**Issue:** `str(date)[:10]` produces malformed dates

- [ ] **Step 1: Replace with proper date formatting**

Locate line 245:

```python
# Replace:
str(date)[:10]
# With:
date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
```

- [ ] **Step 2: Commit**

```bash
git add core/fetcher.py
git commit -m "fix: use proper date formatting instead of string slicing"
```

---

### Task 10: Fix NaN handling in type conversions

**Files:**

- Modify: `core/fetcher.py:248-252`

**Issue:** Aggressive type conversion without null checks

- [ ] **Step 1: Add null checks before conversions**

Locate lines 248-252:

```python
# Replace with:
for col in ['open', 'high', 'low', 'close']:
    val = getattr(ticker, col, None)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        continue  # Skip or set default
    record[col] = float(val)

volume_val = getattr(ticker, 'volume', None)
if volume_val is not None and not (isinstance(volume_val, float) and np.isnan(volume_val)):
    record['volume'] = int(volume_val)
```

- [ ] **Step 2: Commit**

```bash
git add core/fetcher.py
git commit -m "fix: add NaN/null checks before type conversions in fetcher"
```

---

### Task 11: Fix JSON parsing in analyzer

**Files:**

- Modify: `core/analyzer.py:270-273`

**Issue:** Fragile regex extraction and unhandled json.loads

- [ ] **Step 1: Add robust JSON extraction with error handling**

Locate lines 270-273:

```python
# Replace with:
try:
    # Try to find JSON in response
    json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
    if json_match:
        result = json.loads(json_match.group())
    else:
        # Try parsing entire content as JSON
        result = json.loads(content)
except json.JSONDecodeError as e:
    logger.warning(f"Failed to parse AI response as JSON: {e}")
    result = {}  # Return empty dict as fallback
```

- [ ] **Step 2: Commit**

```bash
git add core/analyzer.py
git commit -m "fix: add robust JSON parsing with error handling"
```

---

### Task 12: Fix KeyError in API response parsing

**Files:**

- Modify: `core/ai_confidence_scorer.py:405`

**Issue:** Assumes nested structure exists without validation

- [ ] **Step 1: Add safe navigation for API response**

Locate line 405:

```python
# Replace:
content = result['choices'][0]['message']['content']
# With:
try:
    content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
    if not content:
        logger.warning("Empty content in AI response")
        return None
except (AttributeError, IndexError) as e:
    logger.error(f"Unexpected API response structure: {e}")
    return None
```

- [ ] **Step 2: Commit**

```bash
git add core/ai_confidence_scorer.py
git commit -m "fix: add safe navigation for AI API response parsing"
```

---

## Phase 4: Strategy Logic Fixes

### Task 13: Fix RSI divergence logic

**Files:**

- Modify: `core/strategies/double_top_bottom.py:543-552`

**Issue:** `tail(20).head(10)` gets wrong historical period

- [ ] **Step 1: Fix divergence detection logic**

```python
# Replace the entire _check_rsi_divergence method:
def _check_rsi_divergence(self, df: pd.DataFrame, rsi: pd.Series) -> bool:
    """Check for bearish RSI divergence."""
    if len(df) < 30:
        return False

    try:
        # Get recent high (last 10 days)
        recent_slice = df.tail(10)
        recent_high_idx = recent_slice['high'].idxmax()
        recent_high = df.loc[recent_high_idx, 'high']
        recent_rsi = rsi.loc[recent_high_idx]

        # Get previous high from days 11-30 ago
        prev_start = max(0, len(df) - 30)
        prev_end = len(df) - 10
        if prev_start >= prev_end:
            return False

        prev_period = df.iloc[prev_start:prev_end]
        prev_rsi_period = rsi.iloc[prev_start:prev_end]

        if len(prev_period) < 5:
            return False

        prev_high = prev_period['high'].max()
        prev_rsi_high = prev_rsi_period.max()

        # Bearish divergence: higher price high, lower RSI high
        return recent_high > prev_high and recent_rsi < prev_rsi_high

    except (KeyError, IndexError, ValueError) as e:
        logger.debug(f"RSI divergence check failed: {e}")
        return False
```

- [ ] **Step 2: Commit**

```bash
git add core/strategies/double_top_bottom.py
git commit -m "fix: correct RSI divergence logic to compare proper time periods"
```

---

### Task 14: Fix ATR percentage calculation

**Files:**

- Modify: `core/indicators.py:166`

**Issue:** Returns percentage instead of decimal

- [ ] **Step 1: Fix ATR percentage calculation**

Locate line 166:

```python
# Replace:
atr_pct = (atr / current_price) * 100
# With:
atr_pct = atr / current_price if current_price > 0 else None
```

- [ ] **Step 2: Add division by zero protection**

Also add check for current_price:

```python
if current_price <= 0:
    return {'atr': atr, 'atr_pct': None}
```

- [ ] **Step 3: Commit**

```bash
git add core/indicators.py
git commit -m "fix: remove *100 from ATR percentage (return decimal not percentage)"
```

---

### Task 15: Fix gap detection off-by-one

**Files:**

- Modify: `core/indicators.py:291-297`

**Issue:** Loop skips yesterday which should be included

- [ ] **Step 1: Fix gap detection loop**

```python
# Replace:
for i in range(-5, 0):
    if i < -1:  # Skip current day
# With:
# Check last 5 completed days (indices -5 to -1 relative to yesterday)
for i in range(1, 6):  # 1 to 5 days back
    if len(self.df) > i + 1:
        prev_close = self.df['close'].iloc[-(i + 1)]
        curr_open = self.df['open'].iloc[-i]
        gap_pct = abs((curr_open - prev_close) / prev_close)
        if gap_pct > 0.01:
            gaps += 1
```

- [ ] **Step 2: Commit**

```bash
git add core/indicators.py
git commit -m "fix: correct gap detection to include all 5 days"
```

---

### Task 16: Fix RangeShort risk/reward calculation

**Files:**

- Modify: `core/strategies/range_short.py:294-299`

**Issue:** Incorrect use of abs() for short positions

- [ ] **Step 1: Fix profit efficiency calculation**

```python
# For short positions, profit is entry - target, risk is stop - entry
# Replace the calculation with:
if stop > entry:  # Short position
    profit_potential = (entry - target1) / (stop - entry)
else:
    profit_potential = (target1 - entry) / (entry - stop)
```

- [ ] **Step 2: Commit**

```bash
git add core/strategies/range_short.py
git commit -m "fix: correct risk/reward calculation for short positions"
```

---

### Task 17: Add bounds checking to scoring_utils

**Files:**

- Modify: `core/scoring_utils/__init__.py:262-278, 284-317`

**Issue:** Missing bounds checking in detect_market_direction and check_vix_filter

- [ ] **Step 1: Add bounds checking to detect_market_direction**

```python
def detect_market_direction(spy_df: pd.DataFrame) -> str:
    if spy_df is None or len(spy_df) < 50:
        return 'neutral'

    try:
        current = spy_df['close'].iloc[-1] if len(spy_df) > 0 else 0
        if len(spy_df) >= 50:
            ema50 = spy_df['close'].ewm(span=50).mean().iloc[-1]
        else:
            ema50 = current

        # Validate values
        if pd.isna(current) or pd.isna(ema50):
            return 'neutral'

        open_price = spy_df['open'].iloc[-1] if len(spy_df) > 0 else current
        if pd.isna(open_price):
            open_price = current

        # Short mode: distribution environment
        if current < ema50:
            return 'short'
        # Long mode: accumulation environment
        elif current > ema50:
            return 'long'
        else:
            return 'neutral'

    except (KeyError, IndexError, ValueError):
        return 'neutral'
```

- [ ] **Step 2: Add bounds checking to check_vix_filter**

```python
def check_vix_filter(vix_df: Optional[pd.DataFrame], direction: str,
                     reject_threshold: float = 30.0,
                     limit_threshold: float = 25.0) -> str:
    if vix_df is None or len(vix_df) < 10:
        return 'normal'

    try:
        current_vix = vix_df['close'].iloc[-1]
        if pd.isna(current_vix):
            return 'normal'

        vix_5d_ago = vix_df['close'].iloc[-6] if len(vix_df) > 5 else current_vix
        if pd.isna(vix_5d_ago):
            vix_5d_ago = current_vix

        vix_slope = (current_vix - vix_5d_ago) / 5

        if direction == 'long':
            if current_vix > reject_threshold and vix_slope > 0:
                return 'reject'
            elif current_vix > limit_threshold:
                return 'limit'

        return 'normal'

    except (KeyError, IndexError, ValueError):
        return 'normal'
```

- [ ] **Step 3: Commit**

```bash
git add core/scoring_utils/__init__.py
git commit -m "fix: add bounds checking to market direction and VIX filter functions"
```

---

## Phase 5: Shared Mutable State Fix

### Task 18: Fix shared market_data in strategies

**Files:**

- Modify: `core/strategies/base_strategy.py:71`

**Issue:** `market_data` dictionary shared across strategy instances

- [ ] **Step 1: Make market_data instance-specific**

Locate line 71:

```python
# Replace:
self.market_data: Dict[str, pd.DataFrame] = {}
# With:
# Initialize empty dict per instance (not shared)
self.market_data: Dict[str, pd.DataFrame] = {} if market_data is None else market_data.copy()
```

Actually, better approach - just ensure each instance gets its own dict:

```python
# In __init__, line 71:
self.market_data: Dict[str, pd.DataFrame] = {}
```

This is already the case. The issue is in how it's used. Let me check if market_data is passed between instances.

Actually, the current code is correct - each instance gets its own empty dict. The concern was unfounded. Skip this task.

---

## Phase 6: Documentation Alignment

### Task 19: Update Strategy_Description.md dimension names

**Files:**

- Modify: `docs/Strategy_Description.md`

**Issue:** Dimension names in docs don't match code

- [ ] **Step 1: Update MomentumBreakout dimensions**

Find Section A and update:

```markdown
**Dimensions (4):**

- PQ: Platform Quality
- BS: Breakout Strength
- VC: Volume Confirmation
- TC: Trend Context (includes RS bonus)
```

- [ ] **Step 2: Update PullbackEntry dimensions**

Find Section B and update:

```markdown
**Dimensions (4):**

- TI: Trend Intensity
- RC: Retracement Structure
- VC: Volume Confirmation
- BONUS: EMA Confluence Bonus
```

- [ ] **Step 3: Update SupportBounce dimensions**

Find Section C and update (note it's 3 dimensions in code):

```markdown
**Dimensions (3):**

- SQ: Support Quality
- VD: Volume Dynamics
- RB: Reversal Breadth
```

- [ ] **Step 4: Update RangeShort dimensions**

Find Section D and update (note it's 3 dimensions in code):

```markdown
**Dimensions (3):**

- TQ: Trend Quality
- RL: Range Location
- VC: Volume Confirmation
```

- [ ] **Step 5: Commit**

```bash
git add docs/Strategy_Description.md
git commit -m "docs: align dimension names with code implementation"
```

---

### Task 20: Add missing features documentation

**Files:**

- Modify: `docs/Strategy_Description.md`

**Issue:** Several features undocumented

- [ ] **Step 1: Add market direction filtering documentation**

Add new section to each relevant strategy:

```markdown
**Market Direction Filter:**

- Long signals only in accumulation environment (price > EMA50)
- Short signals only in distribution environment (price < EMA50)
- SPY trend analysis used for direction determination
```

- [ ] **Step 2: Add VIX second wave filter documentation**

Add to CapitulationRebound:

```markdown
**VIX Risk Filter:**

- VIX > 30 with positive slope: Reject signals
- VIX > 25: Limit position size to Tier B maximum
- VIX < 25: Normal position sizing
```

- [ ] **Step 3: Add position limit documentation**

Add to relevant strategies:

```markdown
**Position Size Limits:**

- DoubleTopBottom: Left-side signals capped at Tier B (5%) maximum
- CapitulationRebound: VIX > 25 limits to Tier B maximum
```

- [ ] **Step 4: Commit**

```bash
git add docs/Strategy_Description.md
git commit -m "docs: add missing risk management and filtering features"
```

---

## Phase 7: Testing and Verification

### Task 21: Run test scan to verify fixes

**Files:**

- Run: `scheduler.py --test`

- [ ] **Step 1: Run test scan**

```bash
cd /home/admin/Projects/TradeChanceScreen
python scheduler.py --test --symbols AAPL,MSFT,NVDA
```

- [ ] **Step 2: Check for errors**

Expected: No runtime errors, all strategies complete successfully

- [ ] **Step 3: Verify output**

Check that reports are generated and strategies produce matches

---

### Task 22: Final commit

- [ ] **Step 1: Create summary commit**

```bash
git log --oneline -20
```

- [ ] **Step 2: Final status check**

```bash
git status
```

- [ ] **Step 3: Complete**

All critical and high-severity bugs fixed.

---

## Summary

| Phase | Tasks | Description                                          |
| ----- | ----- | ---------------------------------------------------- |
| 1     | 1-3   | Security fixes (permissions, validation, debug mode) |
| 2     | 4-7   | Runtime error fixes (exceptions, threading, bounds)  |
| 3     | 8-12  | Data pipeline fixes (timezone, parsing, JSON)        |
| 4     | 13-17 | Strategy logic fixes (RSI, ATR, gaps, R/R)           |
| 5     | 18    | Shared state (skip - already correct)                |
| 6     | 19-20 | Documentation alignment                              |
| 7     | 21-22 | Testing and verification                             |

**Total: 21 tasks**
