# TradeScanner Report Generation — Full Overhaul Design

**Date:** 2026-06-21
**Source critique:** `.claude/critiques/report_generation_critique.md`
**Approach:** Sequential by Phase (A)

## Executive Summary

Fix all 18 critical issues, 45+ medium issues, and 12 missing features across the report generation pipeline. Seven phases over ~8 weeks. Each phase produces a working, testable system. Goal: practical swing (5-20d) and position (10-40d) stock recommendations with statistically valid entry/stop/target levels.

## Design Principles

1. **Deterministic core, AI on the edges.** Math (S/R, scoring, sizing) must produce identical results given identical data. AI enriches with narrative but never overrides quantitative signals.
2. **Every recommendation is tracked.** A `recommendations` table records every pick, every day. Reconciliation job checks outcomes. The system learns.
3. **Config over code.** All thresholds, weights, and parameters in `portfolio_config.yaml`.
4. **Fail loud, fail early.** Stale data aborts the pipeline. Bad JSON aborts the pipeline. Silent failures become noisy errors.
5. **One stock = one deterministic path.** From OHLC → S/R → setup → score → recommendation, fully traceable and reproducible.

## Files Changed

```
core/
├── swing_detector.py    # Major rewrite: order, clustering, stop/target cascade, recency, Fib, VPVR, MTF
├── sector_analyzer.py   # Heavy edits: RS computation, setup rules, scoring, diversity, checkpointing
├── ai_client.py         # Rewrite: native tool-calling, T=0, audit log, retry, cost tracking
├── reporter.py          # Heavy edits: embedded OHLC, lifecycle recap, responsive, sorting, guardrails
├── fetcher.py           # Medium edits: RS_raw computation, data freshness validation, batch period
├── reconciler.py        # NEW: daily reconciliation, performance summary, weekly report
├── tag_manager.py       # Light edits: configurable weights
data/
├── db.py                # Medium edits: RS methods, recommendations table, audit logs, outcomes
config/
├── portfolio_config.yaml # Expanded: scoring weights, S/R params, stop/target limits, R:R thresholds
scheduler.py             # Light edits: freshness check, checkpointing, reconciliation trigger
web/
├── js/table-utils.js    # NEW: sorting, filtering, keyboard shortcuts
├── js/chart.js          # Edit: embedded OHLC fallback
scripts/
├── backtest_scoring.py  # NEW: walk-forward rank-IC analysis
├── weekly_summary.py    # NEW: Saturday performance report
tests/
├── e2e/test_report_gen.py       # Updated tests
├── core/test_swing_detector.py  # NEW tests
├── core/test_scoring.py         # NEW tests
├── core/test_reconciler.py      # NEW tests
```

## Phase 1: Foundation (Week 1)

Fixes critical issues: #1 (RS dead code), #2 (order=2), #3 (single-linkage), #4 (single-touch zones), #5 (no min R:R), #10 (static tolerance), #11 (50% filter), #12 (ret_5d double-count).

### 1a. RS Percentile Computation

**File:** `core/fetcher.py` — `save_tier1_cache()`

- Compute `rs_raw = (current_price / price_63d_ago - 1) * 100`
- Rank all stocks by rs_raw, assign percentile 0-99 → `rs_percentile`
- Track consecutive days above 80th percentile → `rs_consecutive_days_80`
- Log: `RS percentile range: X-Y, stocks ranked: N`

**File:** `core/sector_analyzer.py` — `composite_score()`

- Remove `ret_5d` term (double-counted)
- Momentum becomes: `rs_percentile * 0.30 + min(rs_consecutive_days_80 / 2, 10)`

### 1b. S/R Detection Rewrite

**File:** `core/swing_detector.py`

`detect_swings()`:

- `order = max(3, min(8, len(df) // 15))` — 60 bars → order=4
- Switch `argrelextrema` → `scipy.signal.find_peaks` with `prominence=ATR`

`cluster_levels()`:

- `method='complete'` (was 'single') — prevents chaining
- `tolerance = max(0.005, min(0.03, 0.3 * atr / price))` — dynamic per-stock

Post-clustering filter:

- Drop zones with `count < 2`
- Fall back to EMA/ATR when no multi-touch zone exists

Price filter:

- `filter_pct = max(0.10, 5 * atr_pct)` (was flat 50%)

### 1c. Stop/Target Rewrite

**File:** `core/swing_detector.py` — `compute_stop_target()`

Stop cascade (revised):

1. Nearest multi-touch support zone (count ≥ 2) within `max(2.5 * ATR, price * 0.05)`
2. EMA21 if within same distance
3. EMA50 if within same distance
4. `entry - 1.5 * ATR` fallback

- Zone quality gate: skip single-touch zones > 1.5× ATR distance

Target cascade (revised):

1. First resistance zone giving R:R ≥ 1.5 with chosen stop
2. Fibonacci 1.618 extension
3. `entry + 3 * ATR`
4. `entry + 2 * (entry - stop)` fallback

Hard gate: `MIN_RR = 1.5` swing, `2.0` position. Skip stock if no valid combo.

### 1d. Config Externalization

New keys in `portfolio_config.yaml`:

```yaml
sr:
  swing_order_min: 3
  swing_order_max: 8
  cluster_method: complete
  zone_min_touches: 2
  price_filter_atr_mult: 5.0
  price_filter_min_pct: 0.10
stop_target:
  max_stop_distance_atr: 2.5
  max_stop_distance_pct: 0.05
  min_rr_swing: 1.5
  min_rr_position: 2.0
  atr_multiplier_swing: 1.5
  fib_extension_default: 1.618
```

### Phase 1 Success Criteria

- All existing tests pass
- Full scan completes without error
- Log: `RS percentile range: X-Y, stocks ranked: N`
- Spot-check: all zones have count ≥ 2, all highlights have R:R ≥ 1.5
- Two runs on same cached data → identical S/R levels and highlights (before AI)

---

## Phase 2: Safety (Week 2)

Fixes critical issues: #6 (Near Resistance BUY), #8 (Good R/R no trend filter), #16 (stale data), #17 (no checkpointing).

### 2a. Data Freshness Validation

**File:** `core/fetcher.py` — new `validate_cache_freshness(db, max_age_hours=24)`

- Check `tier1_cache.cache_date`, `etf_cache.cache_date` ≥ today
- Abort with `RuntimeError` listing stale tables if any missing today's data
- Called at `scheduler.py` entry, before any analysis

### 2b. Pipeline Checkpointing

**Inline in `sector_analyzer.py` or new `data/checkpoint.py`:**

- Persist intermediate results after each step: market overview, sector analyses, S/R, highlights, focus summary
- On restart, check `workflow_status` for today's completed steps, skip if done
- Prevents re-paying for AI calls after mid-pipeline crash

### 2c. Near Resistance → Resistance Test

**File:** `core/sector_analyzer.py` — setup classification:

- Demoted from 2nd priority to last
- Requires ALL of: volume > 1.0x, price > EMA50, sector uptrend, RS ≥ 50th
- Renamed "Resistance Test"
- Without confirmation → skip (not a buy signal)

### 2d. Good R/R Trend Filter

**File:** `core/sector_analyzer.py` — Good R/R logic:

- Before classifying: require at least one uptrend signal (price > EMA50, sector uptrend, or volume > 1.2x)
- Failing stocks skip entirely (no falling knife picks)

### 2e. Other Safety Fixes

- ATR-based "near" threshold: `max(0.01, atr_pct * 0.8)`
- Volume < 1.0x required for Near Support (selling pressure fading)
- 15%/50% hardcoded limits → config keys
- Market hours window check (9:30-16:00 ET)

### Phase 2 Success Criteria

- Stale cache → pipeline aborts, no report generated
- Kill pipeline mid-run → restart picks up at last checkpoint
- No "Near Resistance" BUY without all 4 confirmation criteria
- No Good R/R in downtrends without evidence

---

## Phase 3: AI Reliability (Weeks 2-3)

Fixes critical issues: #13 (ddgs pre-search, wrong model), #14 (no determinism, no audit).

### 3a. Native DeepSeek Web Search

**File:** `core/ai_client.py`:

- Remove `ddgs` import and `_execute_search()`
- Use DeepSeek API `tools: [{type: "web_search", web_search: {search_query: ..., search_result_format: "text"}}]`
- Model: `deepseek-v4-pro` (fixes `qwen-max` bug in settings)

**File:** `config/settings.py`:

- `"model": "deepseek-v4-pro"`

### 3b. Deterministic Outputs

All AI calls: `temperature=0.0, seed=42, response_format={"type": "json_object"}`

- json_object enforcement eliminates JSON parse failures
- Same input → same output every run

### 3c. Bi-Temporal Audit Logging

**File:** `data/db.py` — new `ai_audit_log` table:

```sql
CREATE TABLE ai_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_type TEXT, sector_name TEXT,
    prompt_hash TEXT, response_hash TEXT,
    model TEXT, temperature REAL, seed INTEGER,
    tokens_in INTEGER, tokens_out INTEGER, cost_estimate REAL,
    created_at TEXT
)
```

### 3d. AI Caching

In-memory dict by `(call_type, sector_name, date)`, 24h TTL. Same-day re-runs skip AI entirely.

### 3e. Retry & Rate Limiting

Exponential backoff (1s → 2s → 4s) on 429/5xx, 3 attempts max.

### 3f. Cost Tracking

- Log tokens + cost per call: `tokens_in * 0.28 + tokens_out * 1.10 / 1M`
- Daily total saved to `workflow_status`
- Report footer shows AI cost

### 3g. AI-Quant Consistency Check

- Flag when AI outlook conflicts with quantitative trend
- Warning logged + surfaced in report as ⚠ marker

### Phase 3 Success Criteria

- Two runs same data → identical AI outputs (verified by response_hash)
- `ai_audit_log` populated for every call
- Log shows token counts and cost
- 429/500 errors retried, never crash pipeline
- `ddgs` import removed

---

## Phase 4: Scoring Overhaul (Weeks 3-4)

### 4a. Corrected Composite Score

```python
def composite_score(c):
    momentum = (c.rs_percentile or 0) * 0.30 + min((rs_consecutive_days_80 or 0) / 2, 10)
    quality = min(c.rr * 5, 15) + min((c.volume_ratio or 1) * 5, 10)

    setup_bonus = {  # tightened: 0.75-1.0
        'Breakout': 1.0, 'Strong Momentum': 0.95,
        'Near Support': 0.85, 'Resistance Test': 0.80, 'Good R/R': 0.75,
    }
    structure = setup_bonus.get(c.reason, 0.5) * 15 + (1.0 if ema_above else 0.4) * 10
    vol_penalty = -min((c.atr_pct or 0.03) * 100, 10) * 0.5

    # Data completeness gate
    missing_fields = sum(1 for f in ['rs_percentile', 'volume_ratio'] if not getattr(c, f, None))
    if missing_fields >= 2: return -999

    return momentum + quality + structure + vol_penalty
```

### 4b. Walk-Forward Rank-IC Validation

**New:** `scripts/backtest_scoring.py`

- Compute score at day T, measure forward return at T+5/T+10/T+20
- Rank IC = corr(score, forward_return)
- Target: rank IC ≥ 0.03 for 10d forward
- Output: IC per component, per horizon

### 4c. Minimum Score Threshold

`MIN_SCORE = 20` (configurable). Stocks below threshold excluded. Empty sector shows "No qualifying setups" placeholder.

### 4d. Diversity Gate Fix

Soft diversity: allow same-reason picks only if their score ≥ 70% of top candidate. Prevents excluding high-scoring stocks for diversity's sake.

### 4e. Config-Driven Weights

All scoring parameters in `portfolio_config.yaml`:

```yaml
scoring:
  momentum_weight: 0.30
  quality_weight: 0.30
  structure_weight: 0.25
  volatility_penalty_weight: 0.05
  min_composite_score: 20
  setup_bonus: { Breakout: 1.0, ... }
  diversity_soft_threshold: 0.70
```

### Phase 4 Success Criteria

- `composite_score()` returns non-zero momentum for all RS-cached stocks
- Rank IC script runs, outputs IC per horizon
- No stock with 2+ missing fields in highlights
- Config changes take effect without code changes

---

## Phase 5: Feedback Loop (Weeks 4-5)

Fixes critical issues: #9 (no performance tracking), #15 (no lifecycle tracking).

### 5a. Recommendations Table

**File:** `data/db.py`:

```sql
CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT, symbol TEXT, sector TEXT, setup_type TEXT,
    entry_price REAL, stop_price REAL, target_price REAL,
    rr REAL, composite_score REAL,
    position_size INTEGER, position_cost REAL, risk_dollars REAL,
    current_price REAL, entry_distance_pct REAL,
    status TEXT DEFAULT 'active',  -- active/triggered/stopped_out/target_hit/expired
    outcome TEXT, pnl_pct REAL, days_held INTEGER, resolved_date TEXT,
    max_days INTEGER,  -- 20 for swing, 40 for position
    created_at TEXT DEFAULT (datetime('now'))
)
```

### 5b. Daily Reconciliation

**New:** `core/reconciler.py`:

- Load all active recommendations
- Check current price vs stop/target
- Resolve stopped_out, target_hit, or expired (past max_days)
- Record P&L and days_held

### 5c. Performance Summary

**New:** `core/reconciler.py` → `generate_performance_summary(db, lookback_days=30)`

- Total trades, win rate, avg win/loss, profit factor, avg realized R:R
- Breakdown by sector, by setup type

### 5d. Prior Picks Recap in Report

**File:** `core/reporter.py` — new section before Tag Details:

- Table: Symbol, Date, Setup, Entry, Stop, Target, Status (▲ Active / ✓ Hit / ▼ Stopped / — Expired), P&L
- Resolved picks show actual P&L, active picks show current distance

### 5e. Weekly Summary

**New:** `scripts/weekly_summary.py` — runs Saturday, appends standalone HTML card to report

### Phase 5 Success Criteria

- `recommendations` table populated after each scan
- Reconciliation resolves prior picks correctly
- "Prior Picks Recap" section in report
- `generate_performance_summary()` returns valid metrics

---

## Phase 6: Report UX (Weeks 5-6)

Fixes critical issue #18 (offline charts) plus all medium UX issues.

### 6a. Embedded OHLC Data

**File:** `core/reporter.py`:

- Embed 120-bar OHLC as `window._EMBEDDED_OHLC` JSON blob in HTML
- Chart JS uses embedded data as primary source, API as fallback
- Charts work when report opened from disk/email

### 6b. Responsive CSS

New `@media (max-width: 768px)` and `@media print` rules in STYLE.

### 6c. Table Sorting & Filtering

**New:** `web/js/table-utils.js`:

- Click column headers to sort (asc/desc/unsorted)
- Text filter input above tables

### 6d. New Setup Types

| Setup               | Detection                                                      | Priority              |
| ------------------- | -------------------------------------------------------------- | --------------------- |
| MA Bounce           | price within 2% of EMA21/EMA50, bullish reversal candle        | After Near Support    |
| Inside Day Breakout | today H<yesterday H, L>yesterday L, vol>avg, price>yesterday H | After Breakout        |
| Bull Flag           | 5d >5%, 3d consolidation declining vol, price>EMA21            | After Strong Momentum |
| ADX Trend           | ADX(14)>20, +DI>-DI, price>EMA21                               | Before Good R/R       |

### 6e. Pre-Trade Guardrails

- Liquidity: position_size / avg_volume < 5%
- Earnings proximity: halve size if earnings within 5 days, add warning
- Correlation: flag pairs with >0.75 correlation in same sector

### 6f. UX Polish

- Horizon badges color-coded: short (green), swing (gold), position (ash)
- Dist column always shows numeric %
- Keyboard shortcuts: j/k, Enter, /
- Expand All / Collapse All
- Timestamp: "Sun, Jun 21, 2026 11:59 AM ET"
- Volume/liquidity column

### Phase 6 Success Criteria

- Report opened from disk → charts render
- 375px viewport → readable, no horizontal scroll
- Table sorting by R:R, Dist, Risk$ works
- At least 2 new setup types fire in full scan
- Guardrails filter at least 1 illiquid stock

---

## Phase 7: Polish (Weeks 6-8)

No remaining critical issues.

### 7a. Multiple Timeframe S/R

- Weekly S/R from 24-week resampled OHLC, order=2
- Confluence bonus: daily + weekly zone within 1% → 1.5× weight, +2 count

### 7b. Volume Profile (VPVR)

- 60-bar volume-at-price with 15 levels
- POC + value area treated as S/R zones

### 7c. Whole-Number & Gap-Fill Levels

- Nearest $X.00, $X.50, $X.10 levels within 5%
- Unfilled gaps from `tier1_cache.gap_1d_pct`

### 7d. Anchored VWAP

- From last earnings date, 52-week high date, last 5%+ gap date
- Within 15% of current price → added as S/R zone

### 7e. Previous Session Reference Levels

- Weekly pivot (H+L+C)/3
- Prior week high/low
- Monthly open

### 7f. Automated Holiday Calendar

- Replace hardcoded `HOLIDAYS_2026` with `pandas_market_calendars`

### 7g. Report Enhancements

- Correlation matrix heatmap (top 10 symbols)
- Best/worst performing sectors MTD
- AI confidence indicator per sector
- Export to CSV button

### Phase 7 Success Criteria

- Weekly S/R confluent zones boosted in logs
- POC visible on charts for liquid stocks
- Round-number levels as faint chart lines
- Gap-fill levels marked for unfilled-gap stocks
- NYSE holidays auto-determined

---

## Testing Strategy

**Per-phase regression:** `python -m pytest tests/ -v` after every phase. All tests must pass.

**New tests added:**

- `tests/core/test_swing_detector.py`: order calc, clustering method, zone filter, R:R validation
- `tests/core/test_scoring.py`: RS percentile scoring, diversity gate, min threshold
- `tests/core/test_reconciler.py`: reconciliation logic, performance summary
- `tests/e2e/test_report_gen.py`: updated for new report structure

**Reproducibility test:**

```bash
# After Phase 3: run twice on same cached data, diff the JSON outputs
python scheduler.py --force 2>&1 | tee run1.log
python scheduler.py --force 2>&1 | tee run2.log
diff <(grep "AI response_hash" run1.log) <(grep "AI response_hash" run2.log)
# Should be identical
```

## Rollback

Each phase committed separately. If a phase introduces regressions, revert that commit. No phase depends on partial work from the next phase.
