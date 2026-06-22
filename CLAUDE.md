# CLAUDE.md

## Project overview

Automated US stock trading scanner — sector-first daily analysis using DeepSeek V4 Pro AI with web search. Generates an HTML dashboard report with technical setups (entry/stop/target/R:R) across 13 curated sectors (~340 stocks).

## Environment

- Python 3.13 with Miniconda at `/home/ametrin/miniconda3/bin/python3`
- Required packages: flask, numpy, scipy, pandas, yfinance, pyyaml
- `DEEPSEEK_API_KEY` env var required for AI analysis (set in shell profile or `config/settings.py`)

## Commands

```bash
python scheduler.py --force      # Run full daily scan (AI + S/R + report)
python -m pytest tests/e2e/ -v   # Run E2E tests (23 tests, ~0.15s)
python api/server.py             # Start API + dashboard on port 19801
```

## Architecture

```
scheduler.py          # Daily orchestrator: sector analysis → highlights → report
core/
├── sector_analyzer.py   # AI sector analysis + stock highlight selection (entry/stop/target)
├── reporter.py          # HTML report generator (amber-palette dashboard)
├── swing_detector.py    # Support/resistance detection (60-bar, order=2) + stop/target calc
├── tag_manager.py       # Sector tag CRUD and stock assignment
├── ai_client.py         # DeepSeek V4 Pro wrapper with web search tool-calling
├── fetcher.py           # Market data fetcher (OHLC, ETF prices)
└── constants.py         # Sector ↔ ETF mappings
api/
├── server.py            # Flask API: scan endpoint, OHLC data, config CRUD
└── config_api.py        # Tag/sector config REST API
data/
└── db.py                # SQLite database (market_data, tier1_cache, tags, stocks)
config/
├── portfolio_config.yaml # Account value, risk %, entry distance thresholds
└── settings.py           # API keys, paths, report/web settings
web/
├── dashboard.html       # Single-page dashboard (Today/Tags/Reports/Config tabs)
├── js/                  # ES modules: app, api, tags, today, reports, config
└── reports/             # Generated HTML reports (report_YYYY-MM-DD.html)
```

## Working Orchestration

### 1. Plan Node Default

- Enter Plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use subagents to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop

- After ANY correction: update .claude/reference/lessons.md with the pattern
- Write rules that prevent the same mistake
- Review lessons at session start

### 4. Verification Before Done

- Never mark complete without proving it works
- Ask: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: implement the elegant solution
- Skip for simple, obvious fixes - don't over-engineer

### 6. Autonomous Bug Fixing

- When given a bug report: just fix it
- Point at logs, errors, failing tests, then resolve them
- Zero context switching required from the user

## Task Management

1. **Plan First**: Write plan with checkable items before touching code
2. **Track Progress**: Use TaskCreate/TaskUpdate to mark completion as you go
3. **Capture Lessons**: Update `.claude/reference/lessons.md` after any correction

## Gotchas

- S/R levels use a configurable lookback (default 120 bars, `sr.lookback_bars` in portfolio_config.yaml) with `order=2` (catches 2-day pullbacks). Levels >50% away from current price are filtered as artifacts.
- Entry prices are proximity-capped: if computed entry is >10% from current price, entry defaults to current price (`max_entry_distance_pct` in portfolio_config.yaml).
- Breakout and Strong Momentum setups always use current price as entry (they're trend-following, not pullback trades).
- Highlights are diversity-gated per sector: max 3 picks, preferring different reason types (Breakout, Near Support, Strong Momentum, etc.).
- `config/delisted.py` and `config/stocks.py` are static reference files — the live stock list is in the DB `stocks` table.
- Simulation engine and all simulation tests were removed 2026-06-21 — do not re-add until recommendation quality is solid.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Coding guideline

Read the rules and agent definitions in .claude/ before starting work.

### 1. General

- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.

### 2. Output

- Return code first. Explanation after, only if non-obvious.
- No inline prose. Use comments sparingly - only where logic is unclear.
- No boilerplate unless explicitly requested.

### 3. Code Rules

- Simplest working solution. No over-engineering.
- No abstractions for single-use operations.
- No speculative features or "you might also want..."
- Read the file before modifying it. Never edit blind.
- No docstrings or type annotations on code not being changed.
- No error handling for scenarios that cannot happen.
- Three similar lines is better than a premature abstraction.

### 4. Review Rules

- State the bug. Show the fix. Stop.
- No suggestions beyond the scope of the review.
- No compliments on the code before or after the review.

### 5. Debugging Rules

- Never speculate about a bug without reading the relevant code first.
- State what you found, where, and the fix. One pass.
- If cause is unclear: say so. Do not guess.

### 6. Script and Test Placement

- `core/` — library modules only, never run directly (no `if __name__ == '__main__'`)
- `scripts/` — standalone runners and one-shot utilities
- `tests/` — pytest only, organized in subdirs (`tests/e2e/`, `tests/core/`, etc.). Files must start with `test_`.
- Before creating a new script, check if an existing one can be extended. Delete stale ones.

### 7. Simple Formatting

- No em-dashes, smart quotes, or decorative Unicode symbols.
- Plain hyphens and straight quotes only.
- Natural language characters (accented letters, CJK, etc.) are fine when the content requires them.
- Code output must be copy-paste safe.
