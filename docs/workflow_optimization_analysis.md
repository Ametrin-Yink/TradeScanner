# Workflow Performance Optimization Analysis

## Current Workflow Timing (from test run)

| Phase | Component | Duration | Bottleneck Analysis |
|-------|-----------|----------|---------------------|
| Phase 0 | PreMarketPrep | ~4 min (240s) | Data fetching, Tier 1 calc |
| Phase 1 | Market Sentiment | ~26s | 3x Tavily API calls + AI |
| Phase 2 | Strategy Screening | ~4 min (240s) | 6 strategies × 186 symbols |
| Phase 3 | AI Analysis | ~15-20 min | 10× Tavily + 10× AI calls |
| Phase 4 | Report Generation | ~2-3 min | Chart generation |
| Phase 5 | Notifications | ~1 min | Webhook calls |
| **TOTAL** | | **~30-35 min** | |

## Critical Bottlenecks Identified

### 1. Phase 0: Data Preparation (High Impact)

**Problems:**
- Sequential fetching in batches of 50 with 0.5s delay between requests
- Market cap fetched individually from yfinance (1 API call per stock)
- Tier 1 calculations run sequentially per symbol

**Current flow:**
```
for batch in symbols:
    for symbol in batch:
        fetch_stock_data(symbol)          # ~1-2s per symbol
        fetch_stock_info(symbol)          # ~1s per symbol (market cap)
        _calculate_tier1_metrics(symbol)  # CPU bound
```

### 2. Phase 2: Strategy Screening (High Impact)

**Problems:**
- 6 strategies each screening ALL symbols sequentially
- MomentumBreakout calculates RS scores per-symbol without caching
- TechnicalIndicators.calculate_all() called multiple times per symbol
- No parallel processing across strategies

**Current flow:**
```
for each of 6 strategies:
    for batch in symbols:
        for symbol in batch:
            TechnicalIndicators(df).calculate_all()  # Expensive!
            strategy-specific calculations
```

### 3. Phase 3: AI Analysis (Medium Impact)

**Problems:**
- Sequential AI calls (10 symbols × ~60s each = 10 min)
- Each symbol triggers 1 Tavily + 1 AI call
- No parallel processing

## Optimization Recommendations

### Optimization 1: Parallel Data Fetching (Phase 0) ⭐ HIGH PRIORITY

**Current:**
- `max_workers=2` in fetcher
- Batch size 50 with sequential processing

**Recommendation:**
- Increase to `max_workers=4` (respecting 2-core limit, I/O bound)
- Use ThreadPoolExecutor for market cap fetching
- Reduce request_delay from 0.5s to 0.2s (yfinance can handle it)

**Expected gain:** 4-5 minutes → 2 minutes (50% reduction)

### Optimization 2: Lazy TechnicalIndicators Calculation (Phase 2) ⭐ HIGH PRIORITY

**Current:**
- `TechnicalIndicators(df).calculate_all()` called for every symbol in every strategy
- `calculate_all()` computes: EMAs, RSI, MACD, Bollinger, ADR, ATR, VWAP, etc.

**Recommendation:**
- Cache TechnicalIndicators per-symbol in Phase 0
- Only compute indicators needed by specific strategies
- Lazy evaluation: compute on-demand with memoization

**Code changes:**
```python
# In Phase 0, pre-compute indicators for all symbols
self._indicators_cache = {}
for symbol, df in phase0_data.items():
    self._indicators_cache[symbol] = TechnicalIndicators(df)
    # Only compute common indicators, not all
    self._indicators_cache[symbol].calculate_core()  # EMAs, ATR, ADR only

# In strategies, use cached indicators
def filter(self, symbol, df):
    ind = self.phase0_data.get('indicators', {}).get(symbol)
    if not ind:
        ind = TechnicalIndicators(df)
```

**Expected gain:** 4 min → 1.5 min (60% reduction)

### Optimization 3: Parallel Strategy Screening (Phase 2) ⭐ MEDIUM PRIORITY

**Current:**
- 6 strategies run sequentially
- Each strategy processes all symbols

**Recommendation:**
- Use ThreadPoolExecutor to run strategies in parallel (2 workers for 2 cores)
- Each strategy gets subset of symbols based on pre-filtering
- Shared Phase 0 data is read-only, safe for threading

**Expected gain:** 4 min → 2.5 min (parallelization overhead reduces gains)

### Optimization 4: Batch AI Analysis (Phase 3) ⭐ MEDIUM PRIORITY

**Current:**
- 10 symbols × (1 Tavily + 1 AI call) = 20 API calls sequential

**Recommendation:**
- Parallel Tavily calls (up to 5 concurrent, API limit)
- Parallel AI calls (up to 2 concurrent for 2-core CPU)
- Use ThreadPoolExecutor with max_workers=2 for AI (CPU+network bound)

**Expected gain:** 15-20 min → 8-10 min (50% reduction)

### Optimization 5: Reduce Data Fetch Scope (Phase 0) ⭐ LOW PRIORITY

**Current:**
- Fetching 200+ symbols, but Phase 2 only screens 186
- Tier 3 data fetched for all ETFs even if not needed

**Recommendation:**
- Pre-filter by price/volume from database before fetching
- Only fetch data for symbols passing basic filters
- Skip Tier 3 data for ETFs not used by strategies

**Expected gain:** Small, but reduces memory pressure

### Optimization 6: Memory Optimization ⭐ HIGH PRIORITY (for 2GB RAM)

**Current memory issues:**
- DataFrames held in memory for all symbols during Phase 0
- `gc.collect()` called frequently suggests memory pressure
- `copy.copy()` of market_data for each strategy

**Recommendations:**
1. Use generators instead of lists where possible
2. Clear DataFrames after processing: `del df; gc.collect()`
3. Don't copy market_data, use shared read-only reference
4. Process symbols in smaller batches (25 instead of 100)
5. Use `weakref` for shared data structures

### Optimization 7: Database Connection Pooling ⭐ MEDIUM PRIORITY

**Current:**
- New connection created frequently in loops
- `_get_cached_data` opens connection per symbol

**Recommendation:**
- Use connection pooling (sqlite3 built-in or SQLAlchemy)
- Batch reads instead of per-symbol queries

## Implementation Priority

### Phase 1 (Immediate, High Impact)
1. **Lazy TechnicalIndicators** - Single biggest win for Phase 2
2. **Parallel data fetching** - Configure fetcher for 4 workers, 0.2s delay
3. **Memory optimization** - Reduce batch sizes, clear DataFrames

### Phase 2 (Next)
4. **Parallel AI analysis** - Batch Tavily + AI calls
5. **Parallel strategy screening** - Run 2 strategies concurrently

### Phase 3 (Nice to have)
6. **Database connection pooling**
7. **Pre-filter before fetch**

## Expected Total Performance

| Phase | Before | After | Improvement |
|-------|--------|-------|-------------|
| Phase 0 | 4 min | 2 min | -50% |
| Phase 1 | 26s | 26s | - |
| Phase 2 | 4 min | 1.5 min | -62% |
| Phase 3 | 15 min | 8 min | -47% |
| Phase 4-5 | 4 min | 3 min | -25% |
| **TOTAL** | **~27 min** | **~15 min** | **-45%** |

## Server Constraints (2GB RAM, 2 Cores)

### Threading Strategy:
- **I/O bound** (network requests): 4-6 threads (yfinance, API calls)
- **CPU bound** (calculations): 2 threads (match CPU cores)
- **Mixed** (AI analysis): 2 threads

### Memory Budget:
- Base Python + imports: ~200MB
- 200 symbols × DataFrame (~100KB each): ~20MB
- TechnicalIndicators cache: ~50MB
- AI model (if local): N/A (API-based)
- **Target working memory**: <500MB to leave headroom

### Batch Size Recommendations:
- Data fetching: 50 symbols (current)
- Tier 1 calculation: 25 symbols (reduce from 100)
- Strategy screening: 50 symbols (current)
