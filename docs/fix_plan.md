# Issue Summary & Fix Plan

## Issues Found Within Scripts

### W1: Phase time tracking broken (scheduler.py)

**File:** `scheduler.py:198-199, 716`
**Problem:** The pipeline writes phase times to `ctx.phase_times`, but `scheduler._update_workflow_status()` reads from `self._phase_times` (a separate dict). Phase 0's time is stored in `self._phase_times` but phases 1-6 times stored in `ctx.phase_times` are never copied to `self._phase_times`. Result: DB always shows 0 duration for phases 1-6.
**Fix:** After `_run_pipeline()` returns, copy `ctx.phase_times` into `self._phase_times`.

### W2: `fail_symbols` always empty (scheduler.py)

**File:** `scheduler.py:494`
**Problem:** `fail_symbols = []` is hardcoded in `_phase2_screening`. The report always shows 0 failures and success_count always equals total_stocks.
**Fix:** Track failed symbols during screening. At minimum, compute it as `set(symbols) - set(c.symbol for c in candidates)`.

### W3: `technical_snapshot` attribute missing on AnalyzedOpportunity (reporter.py)

**File:** `reporter.py:250-252`
**Problem:** `AnalyzedOpportunity` dataclass has no `technical_snapshot` field. The reporter tries `getattr(opp, 'technical_snapshot', {})` which always returns `{}`, so tier/score/position_pct badges never show.
**Fix:** Add `technical_snapshot: Dict = field(default_factory=dict)` to `AnalyzedOpportunity` and populate it when creating the object in `opportunity_analyzer.analyze_opportunity()`.

### W4: `_ai_deep_analysis` is a stub (analyzer.py)

**File:** `analyzer.py:378-387`
**Problem:** The deep analysis for top 10 returns hardcoded values without actually calling AI. The Tavily search result is not meaningfully used.
**Fix:** Make `_ai_deep_analysis` actually call the AI API with Tavily results for meaningful deep analysis.

### W5: Docstring mismatch on `screen_all` (screener.py)

**File:** `screener.py:796`
**Problem:** Docstring says "Returns: List of StrategyMatch (max 10 total, distributed per table)" but actually returns up to 30 candidates.
**Fix:** Update docstring.

### W6: `_load_tier1_cache` called redundantly inside loop (screener.py)

**File:** `screener.py:270-271`
**Problem:** Inside the fallback calculation loop, `_load_tier1_cache([symbol])` is called for each symbol individually, hitting the DB once per symbol. This was already loaded once at line 116 as `cached_tier1`.
**Fix:** Use the already-loaded `cached_tier1` dict instead of re-querying DB.

## Cross-Script Issues

### C1: Phase 3 returns `AnalyzedOpportunity` but Phase 4 expects `ScoredCandidate`

**File:** `phase3_ai_scoring.py:63`, `phase4_deep_analysis.py:20-24`
**Problem:** Phase 3 calls `opportunity_analyzer.analyze_opportunity()` which returns `AnalyzedOpportunity`. It stores these as `ctx.top_30`. Phase 4 passes `ctx.top_30` to `analyze_top_10_deep()` which sorts by `.confidence` and takes top 10. Both types have `confidence`, but `analyze_top_10_deep` was designed for `ScoredCandidate` (from the selector) with `technical_snapshot`. The data flow is inconsistent - Phase 3 should use the selector's output, not re-analyze everything.
**Fix:** Phase 3 should store the selector's `ScoredCandidate` list (top 30) directly. Then Phase 4 takes top 10 from those and does deep AI analysis on each.

### C2: Report passes `ctx.top_30` as `all_candidates` but these are `AnalyzedOpportunity` objects

**File:** `phase5_report.py:32`
**Problem:** Reporter's `generate_report` receives `all_candidates=ctx.top_30` which are `AnalyzedOpportunity` objects. The reporter's "runner-ups" section (lines 300-317) iterates expecting `entry_price`, `confidence`, `strategy`, `match_reasons`. `AnalyzedOpportunity` has all these, so this works but the section shows the same deep-analyzed objects rather than the broader 30-candidate pool.
**Fix:** Phase 3 should store raw top 30 (before deep analysis) separately from the analyzed ones.

### C3: Hardcoded report URL in two places

**File:** `scheduler.py:677`, `phase6_notify.py:28`
**Problem:** The report URL `http://47.90.229.136:19801/reports/` is hardcoded in both `scheduler.py` and `phase6_notify.py`. When the pipeline is used (normal flow), phase6_notify.py is the one that runs. But when `_phase6_notify` method on `CompleteScanner` is called (not via pipeline), it uses scheduler.py's version. Both need to stay in sync.
**Fix:** Move to settings.json as `report.base_url`.

### C4: Phase 2 passes ETF data as stock market_data

**File:** `phase2_screening.py:30-41`
**Problem:** `tier3_data` contains only ETF/index symbols (SPY, VIX, sector ETFs). This is passed as `market_data` to `screener.screen_all()`. Inside `screen_all`, `self.market_data = market_data` means stock lookups via `market_data.get(symbol)` return None, falling through to `_get_data()` which reads from DB. This works but is misleading - `market_data` should be named `etf_data` or similar.
**Fix:** Rename variable for clarity, or merge Tier 3 data with stock data from DB in the screener.

## Severity Summary

| ID  | Severity | Description                           | Status   |
| --- | -------- | ------------------------------------- | -------- |
| W1  | Medium   | Phase timing always 0 in DB           | FIXED    |
| W2  | Low      | fail_symbols cosmetic issue           | FIXED    |
| W3  | Medium   | Tier/score badges missing from report | FIXED    |
| W4  | Medium   | Deep analysis is stub, no real AI     | FIXED    |
| W5  | Low      | Docstring mismatch                    | FIXED    |
| W6  | Low      | Redundant DB queries                  | FIXED    |
| C1  | High     | Data type mismatch between phases     | FIXED    |
| C2  | Medium   | Report runner-ups shows wrong data    | FIXED    |
| C3  | Low      | Hardcoded URL in two places           | FIXED    |
| C4  | Low      | Variable naming confusion             | DEFERRED |

## Fix Details

### W1: Copy ctx.phase_times to self.\_phase_times

- `scheduler.py:197` - Added loop to copy pipeline phase times after `_run_pipeline()` returns

### W2: Track fail_symbols in Phase 2

- `phase2_screening.py` - Compute `fail_symbols` as input symbols minus candidate symbols

### W3: Add technical_snapshot to AnalyzedOpportunity

- `core/analyzer.py` - Added `technical_snapshot: dict` field to dataclass
- `core/analyzer.py` - Populate it from `match.technical_snapshot` in `analyze_opportunity()`
- `phase4_deep_analysis.py` - Pass `technical_snapshot` when converting to AnalyzedOpportunity

### W4: AI-powered deep analysis

- `core/analyzer.py:_ai_deep_analysis` - Now calls Dashscope AI with Tavily news context, with proper fallback

### W5: Docstring fix

- `core/screener.py:796` - Updated "max 10" to "max 30"

### W6: Eliminate redundant DB queries

- `core/screener.py:270-271` - Use already-loaded `cached_tier1` instead of per-symbol DB query

### C1: Phase 3 data flow fix

- `phase3_ai_scoring.py` - Removed redundant `analyze_opportunity()` calls. Now stores `ScoredCandidate` directly from selector
- `phase4_deep_analysis.py` - Converts `ScoredCandidate` to `AnalyzedOpportunity` after deep analysis

### C2: Report runner-ups now use correct data

- Resolved by C1 fix: `ctx.top_30` is now `ScoredCandidate` list (broader pool), `ctx.top_10` is `AnalyzedOpportunity` (deep analysis)

### C3: Report URL centralized

- `config/settings.py` - Added `report.base_url` to default settings
- `scheduler.py:677` - Uses `settings.get('report', {}).get('base_url', ...)`
- `phase6_notify.py:28` - Same pattern

### C4: Variable naming - deferred

- Low impact, works correctly. Can be renamed in future cleanup pass.
