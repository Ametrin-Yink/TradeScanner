# Critical Performance Analysis - Trade Scanner Workflow

## Executive Summary

**MAJOR BOTTLENECK IDENTIFIED**: Phase 0 pre-filter takes 45+ minutes because it makes **2,921 individual HTTP requests to Yahoo Finance** (one per stock) to fetch market cap, with a 0.5s delay between each request.

## 1. Root Cause: Phase 0 Pre-Filter Performance

### Current Implementation (premarket_prep.py:240-286)
```python
for i, symbol in enumerate(stocks):  # 2,921 iterations
    # Individual DB query per symbol
    cursor = conn.execute("SELECT close, volume FROM market_data WHERE symbol = ?", (symbol,))
    rows = cursor.fetchall()

    # ... price/volume checks ...

    # CRITICAL: Individual yfinance call per symbol (line 272)
    info = self.fetcher.fetch_stock_info(symbol)  # HTTP request + 0.5s delay
    market_cap = info.get('market_cap', 0)
```

### Why It's Slow
| Operation | Count | Time Each | Total Time |
|-----------|-------|-----------|------------|
| DB query per symbol | 2,921 | ~10ms | ~30s |
| yfinance HTTP request | 2,921 | ~1s + 0.5s delay | **~44 minutes** |
| **Total** | | | **~45 minutes** |

### The 0.5s Delay Kills Performance
In `fetcher.py:26,42,56-57`:
```python
request_delay: float = 0.5  # 500ms between requests

def _rate_limited_request(self, func, *args, **kwargs):
    elapsed = time.time() - self._last_request_time
    if elapsed < self.request_delay:
        time.sleep(self.request_delay - elapsed)  # Sleeps 500ms!
```

## 2. Old Strategy Names in Logs

### Strategy Name Mapping Issue

**StrategyType enum** (base_strategy.py) uses short codes:
- `EP` → logs show `[EP]`
- `SHORYUKEN` → logs show `[Shoryuken]`

**But screener.py uses class names for mapping:**
```python
STRATEGY_NAME_TO_GROUP = {
    "MomentumBreakout": "breakout_momentum",  # Class name
    "PullbackEntry": "trend_pullback",
    ...
}
```

**The mismatch**: Logs show short names (EP, Shoryuken) but mapping uses class names (MomentumBreakout, PullbackEntry). This causes confusion but doesn't break functionality since the mapping is only used for allocation reporting.

## 3. Server Down Incident Analysis

Based on the workflow pattern and the 2GB RAM / 2-core constraint:

### Likely Causes
1. **Memory exhaustion** during Phase 0:
   - 2,921 symbols × DataFrame (~200KB each) = ~584MB
   - Plus Tier 1 cache data
   - Plus Python overhead
   - Could trigger OOM killer

2. **Process killed due to timeout**:
   - Phase 0 taking 45+ minutes
   - May hit systemd timeout or external monitor timeout

3. **yfinance rate limiting**:
   - 2,921 rapid requests may trigger Yahoo's rate limiting
   - Causing cascading failures

## 4. Systematic Performance Optimization Plan

### CRITICAL FIX #1: Batch Market Cap Fetching (Saves 40+ minutes)

**Current**: Individual HTTP requests with 0.5s delay  
**Solution**: Use cached market cap from database

**Implementation**:
```python
# Option A: Use already-cached market cap from data fetching phase
# During fetch_stock_data(), market cap is already fetched (line 211 in fetcher.py)
# Just read from stocks table instead of making new yfinance calls

def _apply_prefilter(self) -> Dict:
    # ...
    # Check 3: Market cap from database (already fetched during data fetch)
    market_cap = self.db.get_stock_market_cap(symbol)  # DB read, not HTTP!
    if market_cap < self.MIN_MARKET_CAP:
        filtered_by_cap += 1
        continue
```

**Expected improvement**: 45 min → 2 min

### CRITICAL FIX #2: Batch Database Queries (Saves 30s)

**Current**: Individual SQL query per symbol  
**Solution**: Single query with GROUP BY

```python
# Current: 2,921 individual queries
cursor = conn.execute("SELECT close, volume FROM market_data WHERE symbol = ?", (symbol,))

# Optimized: 1 query for all symbols
cursor = conn.execute("""
    SELECT symbol, close, AVG(volume) as avg_volume
    FROM market_data
    WHERE symbol IN (SELECT symbol FROM stocks WHERE category='stocks')
    GROUP BY symbol
    ORDER BY date DESC
""")
```

### FIX #3: Parallel Strategy Screening

**Current**: Sequential strategy execution  
**Solution**: ThreadPoolExecutor with 2 workers

```python
from concurrent.futures import ThreadPoolExecutor

def screen_strategy(strategy_type):
    strategy = self._strategies[strategy_type]
    return strategy.screen(symbols, market_data, tier1_data)

with ThreadPoolExecutor(max_workers=2) as executor:
    results = executor.map(screen_strategy, self._strategies.keys())
```

### FIX #4: Optimize Request Delay

**Current**: 0.5s delay between ALL requests  
**Solution**: 0.1s delay for batch operations

```python
# In fetcher.py
request_delay: float = 0.1  # Reduce from 0.5s to 0.1s
```

yfinance can handle faster rates, and Yahoo Finance limits are typically ~2,000 requests/hour with proper spacing.

### FIX #5: Lazy Market Cap Fetching

**Current**: Fetch market cap for ALL 2,921 stocks during pre-filter  
**Solution**: Only fetch for stocks passing price/volume filters

```python
# New flow
for symbol in stocks:
    # Check 1: Price (fast - from cached data)
    if not price_check(symbol):
        continue

    # Check 2: Volume (fast - from cached data)
    if not volume_check(symbol):
        continue

    # Check 3: Market cap (slow - only for survivors)
    # ~70% of stocks filtered out before this point
    if not market_cap_check(symbol):
        continue
```

**Expected**: 2,921 market cap fetches → ~800 fetches (70% reduction)

## 5. Implementation Priority

| Priority | Fix | Time Saved | Complexity |
|----------|-----|------------|------------|
| P0 | Use cached market cap | 40 min | Low |
| P0 | Batch DB queries | 30s | Low |
| P1 | Lazy market cap fetching | 15 min | Medium |
| P1 | Reduce request delay | 10 min | Low |
| P2 | Parallel strategy screening | 5 min | Medium |
| P2 | Parallel AI analysis | 10 min | Medium |

## 6. Expected Performance After Fixes

| Phase | Before | After | Improvement |
|-------|--------|-------|-------------|
| Phase 0 | 60+ min | 5-8 min | **-90%** |
| Phase 1 | 30s | 30s | - |
| Phase 2 | 30+ min | 10 min | **-67%** |
| Phase 3 | 15 min | 8 min | -47% |
| **TOTAL** | **~2 hours** | **~25 min** | **-80%** |

## 7. Immediate Actions Required

1. **Fix market cap fetching** in `premarket_prep.py` line 272
   - Use `db.get_stock_market_cap()` instead of `fetcher.fetch_stock_info()`
   - Market cap is already fetched during data fetch phase (fetcher.py:211)

2. **Verify market cap caching** is working in `fetcher.py`
   - Check that `fetch_stock_data` calls `fetch_stock_info` (line 211)
   - Check that market cap is saved to database

3. **Fix strategy name consistency**
   - Either use short names everywhere (EP, Shoryuken) or class names everywhere (MomentumBreakout, PullbackEntry)
   - Update `STRATEGY_NAME_TO_GROUP` mapping if needed

4. **Add progress logging** for long operations
   - Current: "Checked 500/2921 stocks" every 500 stocks
   - Better: Show estimated time remaining

## 8. Code Changes Needed

### File: core/premarket_prep.py
```python
# Line 270-275 - Replace this:
try:
    info = self.fetcher.fetch_stock_info(symbol)  # SLOW!
    market_cap = info.get('market_cap', 0)
except Exception:
    market_cap = 0

# With this:
market_cap = self.db.get_stock_market_cap(symbol) or 0  # FAST!
```

### File: core/fetcher.py
```python
# Line 26 - Reduce delay
request_delay: float = 0.1  # Was 0.5
```

### File: data/db.py (add if missing)
```python
def get_stock_market_cap(self, symbol: str) -> Optional[float]:
    """Get cached market cap for a stock."""
    conn = self.get_connection()
    cursor = conn.execute(
        "SELECT market_cap FROM stocks WHERE symbol = ?",
        (symbol,)
    )
    row = cursor.fetchone()
    return row[0] if row and row[0] else None
```
