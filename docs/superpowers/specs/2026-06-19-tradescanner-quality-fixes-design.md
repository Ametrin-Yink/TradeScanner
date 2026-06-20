# TradeScanner Quality Fixes — Design Spec

**Date:** 2026-06-19
**Branch:** main
**Scope:** Data model, analysis pipeline, report quality, dashboard UX, simulation engine, cleanup, E2E tests

---

## Problem Summary

Systematic evaluation of the TradeScanner web app from a trader's perspective found 25 issues across 5 subsystems. The critical issues: 25.8% cross-sector stock overlap making sector rankings meaningless, mechanically fabricated 2.0x R/R ratios, entry=market-price with no execution logic, circular benchmark computation, zero position sizing, no outcome tracking, and a 2174-line single-file unmaintainable dashboard.

## Design Goals

1. Eliminate stock overlap via tag model — each recommendation contextually meaningful
2. Real technical stop/target levels from market structure, not algebra
3. Per-trade position sizing with configurable risk parameters
4. Simulation engine with full feedback loop — system improves from outcomes
5. Maintainable frontend and clean backend
6. Zero regression on working functionality

---

## Section 1: Data Model — Tag System

### New Tables

```sql
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'sector',  -- 'sector' | 'theme' | 'factor'
    etf TEXT DEFAULT ''
);

CREATE TABLE stock_tags (
    symbol TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    added_date TEXT NOT NULL DEFAULT (date('now')),
    PRIMARY KEY (symbol, tag_id),
    FOREIGN KEY (symbol) REFERENCES stocks(symbol),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);
```

### Migration (from sector_assignments)

For each row in `sector_assignments`:

1. Upsert a tag with `name = sector`, `type = 'sector'`, `etf = SECTOR_ETFS.get(sector, '')`
2. Insert into `stock_tags(symbol, tag_id)`
3. After all rows migrated, drop `sector_assignments`

### TagManager (replaces SectorManager)

Same API surface: `get_tags()`, `add_tag()`, `remove_tag()`, `get_tag_stocks()`, `add_stock_to_tag()`, `remove_stock_from_tag()`, `search_stocks()`, `get_unassigned_stocks()`, `get_pipeline_stocks()`, `get_tag_daily_change()`, `seed_from_csv()`.

Key change: `search_stocks()` deduplicates by symbol — a stock that's in 3 tags appears once with a merged tag list.

### Impact

- **Dashboard:** Sectors tab becomes Tags tab. Each card shows type badge (sector/theme/factor), name, stock count, daily change.
- **Report:** Header reads "N tags" instead of "N sectors." Per-tag detail cards unchanged in structure.
- **Benchmarks:** Computed per-tag from all stocks bearing that tag. Since stocks can have multiple tags, a stock contributes to each tag's benchmark it belongs to — this is intentional and reflects real market exposure.

---

## Section 2: Analysis Pipeline Fixes

### 2.1 Swing Point Detection

Use `scipy.signal.argrelextrema` with order=5:

```python
from scipy.signal import argrelextrema
swing_highs = data['High'][argrelextrema(data['High'].values, np.greater_equal, order=5)[0]]
swing_lows  = data['Low'][argrelextrema(data['Low'].values, np.less_equal, order=5)[0]]
```

Results stored in `tier1_cache.supports` and `tier1_cache.resistances` as JSON arrays of price levels.

### 2.2 Level Clustering

Nearby swing points grouped via hierarchical clustering (tolerance = 0.5% of price). Each zone scored: touch_count × recency_weight × bounce_magnitude.

### 2.3 Stop Placement (3-tier cascade)

| Priority | Method                                                 | Constraint                      |
| -------- | ------------------------------------------------------ | ------------------------------- |
| 1        | Nearest clustered swing low below entry (last 60 bars) | Must be > 0.5× ATR below entry  |
| 2        | 2.0× ATR below entry                                   | Standard swing-trade multiplier |
| 3        | 10% of price below entry                               | Hard cap for position trades    |

Pick the tightest valid stop. A stop is invalid if distance < 0.5× ATR (noise would trigger it).

### 2.4 Target Placement (3-tier cascade)

| Priority | Method                 | Details                                                                                                                    |
| -------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 1        | Fibonacci extensions   | From most recent completed swing: 127.2% (conservative) or 161.8% (aggressive). Prefer swings with 38.2–61.8% retracement. |
| 2        | Measured move          | Consolidation range height × 0.93 projected from breakout (Bulkowski: Leg C ≈ 93% of Leg A).                               |
| 3        | Pivot point resistance | Weekly pivot R1 = (2×PP) - L, R2 = PP + (H - L) from prior week's OHLC.                                                    |

Pick the closest target giving ≥ 2:1 R/R vs chosen stop. Fallback: 2× risk distance (ensures minimum 2:1).

### 2.5 R/R Calculation

```
risk = entry - stop
reward = target - entry
rr = reward / risk
```

Each pick gets a unique, market-structure-derived R/R. No mechanical formulas.

### 2.6 Benchmark De-circularization

Tag `daily_change` computed from all stocks in the tag using market data — happens before any picks are made. AI outlook from web search, not constituent performance. Stock selection in Step 3 is downstream of benchmark computation.

### 2.7 Deduplication

After all tag analyses complete:

- Collect all candidate highlights into one pool
- Sort by R/R descending
- Take top N unique symbols (N configurable, default 25)
- Per-tag cards show top 3 for that tag (may overlap between tags — that's fine, each tag context is different)
- Master pick list at top of report is fully deduplicated with a "Tags" column

---

## Section 3: Per-Trade Sizing

### Config (new file: `config/portfolio_config.yaml`)

```yaml
account_value: 50000
risk_per_trade_pct: 0.01 # 1% of account
max_position_pct: 0.20 # no single position > 20% of account
```

### Formula

```
risk_per_share = entry - stop
max_risk_dollars = account_value * risk_per_trade_pct
position_size_shares = floor(max_risk_dollars / risk_per_share)
position_size_dollars = position_size_shares * entry
```

Capped: if `position_size_dollars > account_value * max_position_pct`, clamp to max size.

### Report Columns

Added to each pick row: `Size (shares)`, `Cost`, `Risk ($)`.

### Time Horizon

Derived from setup type, displayed as badge:

- Breakout / Near Resistance: **Swing (5-20d)**
- Near Support / Bounce: **Swing (5-20d)**
- Strong Momentum: **Position (10-40d)**

---

## Section 4: Simulation Engine & Feedback Loop

### 4.1 Auto-Selection

After each scan: top 5 unique picks by R/R become simulated trades. Skip if symbol already has an open simulated position.

### 4.2 Database

```sql
CREATE TABLE simulation_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    tag TEXT NOT NULL,
    reason TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    position_size_shares INTEGER NOT NULL,
    risk_dollars REAL NOT NULL,
    time_horizon_days INTEGER NOT NULL,
    close_date TEXT,
    close_price REAL,
    outcome TEXT DEFAULT 'open',  -- 'open' | 'win' | 'loss' | 'expired'
    pnl_dollars REAL,
    pnl_r REAL,
    report_date TEXT NOT NULL
);
```

### 4.3 Position Lifecycle

1. **Open** — entry at next day's open (or report price if real data unavailable)
2. **Active** — checked daily against current price
3. **Close** — price hits stop (Loss), hits target (Win), or exceeds time horizon (Expired)
4. Daily check: `if low <= stop → loss at stop`, `if high >= target → win at target`, `if days_open > time_horizon → expired at current price`

### 4.4 Simulation Tab (Dashboard)

Three panels:

1. **Summary cards:** Total Trades, Win Rate %, Avg R/Trade, Profit Factor, Expectancy
2. **Active positions table:** Symbol, Entry, Current Price, Unrealized P&L, Days Open, Progress bar (price position between entry-stop-target)
3. **Closed positions table:** Historical log, filterable by outcome, sortable by date/P&L

### 4.5 Feedback Loop

Every closed trade adjusts scoring weights (20-trade SMA):

- **Tag scoring:** Tags producing wins get score multiplier bump (e.g., 0.05 per net win in last 20)
- **Setup type scoring:** Setup types (Breakout, Near Support, etc.) that win get priority in highlight selection Pass 1
- **AI confidence calibration:** `ai_confidence_outcomes` repopulated from simulation results; confidence scores adjust against realized outcomes

All adjustments are gentle tilts — no overfitting, no drastic swings.

---

## Section 5: Report Quality

### 5.1 AI Content Freshness

- Search queries use dynamic date: `f"{tag_name} sector stocks news {datetime.now().strftime('%B %Y')}"`
- Each AI-generated outlook stamped with generation timestamp
- Web search results cached per tag per day

### 5.2 Driver/Risk Specificity

AI prompts tightened to require catalyst dates where possible:

- JSON format: `{"drivers": [{"text": "...", "catalyst_date": "..."|null}], "risks": [{"text": "...", "catalyst_date": "..."|null}]}`
- Generic statements rejected unless no specific news exists

### 5.3 Competitive Context

Each tag detail card: "3 picks selected from N candidates" — shows selection density.

### 5.4 Reason Column

Enhanced: "Strong Momentum (RS 97th)" instead of "Strong Momentum" — embeds key metric.

### 5.5 Report Diff

Header shows delta from prior report: "+3 new, -2 removed, —20 unchanged vs yesterday." New picks get visual indicator (left border accent).

### 5.6 Error Visibility

On AI failure: card shows dimmed notice "AI analysis unavailable — using fallback data." No silent degradation.

---

## Section 6: Dashboard & Architecture

### 6.1 Frontend Split

```
web/
├── dashboard.html          # ~100 lines — shell: nav, tab containers, <script type="module"> imports
├── css/
│   └── dashboard.css       # extracted <style> block
└── js/
    ├── app.js              # init, tab routing, toast, scope indicator
    ├── api.js              # api() helper, fetch wrappers
    ├── tags.js             # tag list, search, add/remove
    ├── strategies.js       # strategy accordion, save bar
    ├── reports.js          # report list, filter, inline preview
    ├── scan.js             # scan trigger, status cards, progress polling
    └── simulation.js       # simulation tab — summary cards, active/closed tables
```

Plain ES modules. No framework. Zero new dependencies.

### 6.2 Prompt() Replacement

Inline mini-form slides into sidebar header for add-tag flow. Two text inputs (name, ETF) + Save button. Dark theme styling matching existing design.

### 6.3 Authentication

- `API_KEY` env var. If set, all `/api/*` routes require `Authorization: Bearer <key>`.
- `/dashboard` and `/reports/<path>` remain public (static file serving).
- Key value: `Ametrin+1`.
- **Dashboard-to-API flow:** A new endpoint `/api/config/auth-key` (only accessible from localhost referrer) returns the API key to the dashboard JS on page load. The JS stores it in memory and attaches `Authorization: Bearer <key>` to all subsequent API calls. If the endpoint is hit from a non-localhost origin, it returns 403.

### 6.4 Scan UX

- Poll `/api/scan/status` every 5s during scan for phase progress
- Show current phase and estimated time remaining (from historical average)
- Button disabled with pulsating indicator during scan

### 6.5 Inline Report Preview

Reports tab: "Preview" button fetches report HTML, renders inline. "Open" button opens new tab (existing behavior).

---

## Section 7: Migration & Rollout Plan

### Phase 1: Data Migration

- Create `tags`, `stock_tags` tables
- Migrate from `sector_assignments`
- TagManager replaces SectorManager
- Drop `sector_assignments`

### Phase 2: Pipeline Fixes

- Swing detection populates `tier1_cache.supports`/`resistances`
- R/R calculation rewritten
- Per-trade sizing in report
- AI prompt changes

### Phase 3: Dashboard Rewrite

- CSS/JS split into modules
- Simulation tab built
- Inline forms replace prompts
- Auth middleware
- Report preview

### Phase 4: Simulation & Feedback

- `simulation_positions` table
- Daily auto-selection after scan
- Feedback weights active

### Phase 5: Cleanup & E2E Tests

#### Legacy Removal

**Tables to drop:**

- `scan_results` — superseded by `workflow_status` + `simulation_positions`
- `tier3_cache` — unused serialized blob
- `ai_confidence_outcomes` — rebuilt by simulation feedback
- `universe_sync` — unrefd historical log

**Code to audit and prune:**

- `core/engine/` — old strategy pipeline; remove if nothing imports
- `core/screener.py` — replaced by `sector_analyzer.py`
- `core/premarket_prep.py`, `core/market_analyzer.py` — check callers; remove if dead
- `core/ai_confidence_scorer.py` — replaced by simulation feedback
- `scripts/run_phase*.py` — remove if tied to old pipeline
- `scripts/bulk_*.py` — keep if useful, remove if stale

**Verification:** `python -m compileall core/ api/` after pruning.

#### E2E Test Suite

```
tests/e2e/
├── conftest.py            # fixtures: Flask test client, in-memory DB, mock AI
├── test_tag_manager.py    # tag CRUD, stock-tag assignment, search dedup
├── test_pipeline.py       # full pipeline: market → tags → highlights → report
├── test_rr_algorithm.py   # swing detection, level clustering, stop/target cascade
├── test_simulation.py     # position lifecycle: open → win/loss/expire → feedback
├── test_report_gen.py     # report HTML structure, dedup, mandatory fields
├── test_api.py            # all endpoints: auth, CRUD, scan trigger, status
└── test_feedback.py       # scoring adjustments from closed trades
```

**Key patterns:**

- Mock AI via `conftest.py` fixture patching `core.ai_client.chat` with deterministic JSON
- In-memory SQLite per test, seeded with minimal fixtures
- Pipeline integration: 10 stocks × 3 tags, real-shaped data, assert dedup + valid R/R + complete report
- R/R algorithm: known OHLC with obvious swing points, assert correct levels within tolerance
- Simulation lifecycle: create positions, simulate price hitting stop/target/expiry, assert outcome + P&L
- Auth: 401 on mutating endpoints when API key set but not provided

Run: `pytest tests/e2e/ -v`

---

## New Dependencies

| Package  | Purpose                                   | Notes                                        |
| -------- | ----------------------------------------- | -------------------------------------------- |
| `scipy`  | `argrelextrema` for swing point detection | Added to `requirements.txt`                  |
| `pytest` | E2E test runner                           | Already in dev; verify in `requirements.txt` |

No new JS dependencies. No new Python web framework dependencies.

---

## Key Design Decisions

| Decision                              | Rationale                                                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Tag model over strict exclusivity     | Real-world sector exposure is multi-dimensional. Forcing exclusivity creates artificial boundaries.          |
| Technical levels over AI-generated    | Deterministic, auditable, no API cost, no hallucination risk. AI still used for narrative context.           |
| Per-trade sizing over portfolio-level | User explicitly chose this. Simpler to implement, sufficient for daily top-5 picks.                          |
| Plain ES modules over framework       | Zero-dependency ethos of project. 6 JS files is manageable without a build step.                             |
| Flask stays, no FastAPI migration     | Over-engineering for single-user tool. Flask works.                                                          |
| scipy.signal.argrelextrema for swings | Standard library, zero look-ahead bias, vectorized. Used by SMC toolkit, swingtrend, liquidity-hunt-and-run. |
| 2.0× ATR stop fallback                | Practitioner standard for swing trades. Research consensus.                                                  |
| Fibonacci 127.2%/161.8% targets       | Industry standard extensions for swing trading.                                                              |
| Simulation uses top 5 (not all picks) | Manageable, trackable, sufficient for statistical significance over weeks.                                   |
