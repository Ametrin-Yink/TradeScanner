# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the Trade Scanner project.

## Project Overview

Automated US stock trading opportunity scanner based on strategies in `Strategy_All.txt`. Runs daily at 6:00 AM ET to analyze 2000+ stocks using 8 trading strategies, ranks opportunities via AI, generates web-based reports with Discord/WeChat notifications.

## Architecture

- `core/` - Pipeline components: market_analyzer, fetcher, screener, selector, analyzer, reporter
- `skill/` - Claude Skill interface for interactive commands
- `api/` - HTTP service for Skill communication
- `config/` - stocks.json, settings.json, secrets.json
- `data/` - SQLite database and generated charts
- `web/reports/` - HTML reports (15 reports max, rolling)
- `Strategy_All.txt` - Source trading strategies documentation (Chinese)

## Key Technical Decisions

- **Data Source:** yfinance (free), 0.5s interval between requests, 2 threads max
- **Database:** SQLite + JSON files, no external database needed
- **AI Service:** Alibaba DashScope (OpenAI-compatible endpoint), fallback to rule-based
- **Deployment:** 2C2G VPS (47.90.229.136), Flask web server on port 8080
- **Schedule:** 6:00 AM ET weekdays only (auto-skip weekends/holidays)
- **Scale:** 2000 stocks, completes in ~1 hour

## Development Conventions

- Python 3.10+, use type hints
- `yfinance.download()` with `threads=False` to avoid rate limits
- All API keys in `config/secrets.json` (gitignored)
- Charts cleanup after report generation to save disk
- Use pandas vectorized operations for technical indicators

## Claude Skill Commands

- `/scan [mode]` - Manual trigger (quick/deep)
- `/add <ticker>` - Add to stock universe
- `/remove <ticker>` - Remove from universe
- `/list` - View current universe
- `/history [n]` - View last n scan results
- `/status` - System status

## Resource Constraints

- Memory: Keep under 500MB (pandas DataFrames, cleanup after use)
- Disk: 15 reports max (~30MB), charts temporary
- API: yfinance has unofficial rate limits, implement retries

## Development Notes

- This session uses kimi-k2.5 model
- Subagents inherit parent model automatically - do not specify model parameter
- All API keys are in `config/secrets.json` (already configured with DashScope and Tavily)
- **API Key Access:** Secrets.json uses nested JSON - use `settings.get_secret('dashscope.api_key')` not `settings.get_secret('dashscope_api_key')`

## Server Deployment

- **Port:** Cloud security group only allows 80, 443, 22, 19801 - use 19801 for Flask server
- **Background:** Use `nohup python ... &` to keep server running after SSH disconnect
- **Path Issues:** Always set `sys.path.insert(0, '/home/admin/Projects/TradeChanceScreen')` when running api/server.py directly
- **Auto-Start:** Add to crontab: `@reboot sleep 10 && /path/to/venv/bin/python -c "..." &`
- **Check Status:** `ss -tlnp | grep 19801` to verify server is listening
- **Restart:** Kill old process, then use nohup to start new instance

## Data Sources

- **Stock Lists:** Wikipedia blocks scraping (403) - use Slickcharts (slickcharts.com/sp500, /nasdaq100, /dowjones) for reliable stock lists
- **yfinance:** Use `yfinance.download(threads=False)` for VPS stability, batch requests for 500+ stocks
- **Charts:** Set `matplotlib.use('Agg')` before importing pyplot for headless servers

## Memory Management

- **Streaming Processing**: Process stocks in batches of 50 to limit peak memory usage
- **Garbage Collection**: Call `gc.collect()` after each batch to free DataFrame memory
- **Single Worker**: Use `max_workers=1` for fetcher to reduce concurrent memory pressure
- **Keep 150 Trading Days**: Sufficient for swing trade analysis without excessive memory

## Data Cache Strategy

- **Existing Cache**: `market_data` table has 65k+ rows covering 523 stocks with 125 days history
- **Incremental Updates**: Fetch only missing days (typically 1-2 days) instead of full 6 months
- **Cache Check**: Query `SELECT MAX(date) FROM market_data WHERE symbol = ?` before fetching
- **Merge Logic**: Combine cached data with new data, keep last 150 trading days

## Testing

- **Full Scan (Cached):** 517 stocks takes ~20-25 minutes (incremental update, ~2-3 min for data)
- **Full Scan (First Run):** 517 stocks takes ~70-80 minutes (no cache, downloads full history)
- **Typical Output:** 10-20 candidates from 8 strategies, AI selects top 10 with confidence scores
- **Server:** Check `ss -tlnp | grep 19801` to verify Flask is listening

## AI API Compatibility

- **kimi-k2.5 via DashScope**: Does NOT support `response_format: {"type": "json_object"}` - use regex to extract JSON instead
- Remove `response_format` parameter and parse JSON from response text with `re.search(r'\{.*\}', content, re.DOTALL)`

## Chart Generation

- **Static PNG Charts**: Use matplotlib with `matplotlib.use('Agg')` - no Chrome dependency
- **Image Tag**: Use `<img src="...">` not `<iframe>` to avoid path/port issues
- **Chart Size**: 350x500px, displayed beside Analysis section via flex layout
- **Chart Path**: Return `../data/charts/{symbol}_{date}.png` from generator

## Confidence Scoring

- **AI-Powered Scoring**: Use AI to calculate 0-100 confidence with market-sentiment adaptive weights
- **Batch Scoring**: Send 20 candidates per API call to minimize costs
- **Score Range**: Expect 50-80% for good setups (vs previous 12-17% with rule-based)
- **Include Reasoning**: AI returns confidence with explanation and key_factors/risk_factors

## UI Design Preferences

- **Financial/Professional style preferred** over "AI" style with gradients/emojis
- Use dark header (#1a1a2e), clean borders, compact spacing
- Color-code confidence: green (high), orange (medium), red (low)
- **Compact Layout**: Stats in single line, sentiment with full AI reasoning
- **Chart Position**: Side-by-side with Analysis section using flex layout

## Stock Management

- **Reference**: See `docs/STOCK_MANAGEMENT.md` for complete stock management procedures
- **Quick Add**: `python -c "from data.db import Database; db = Database(); db.get_connection().execute('INSERT INTO stocks (symbol, name, sector, added_date, is_active) VALUES (?, ?, ?, datetime('now'), 1)', ('SYMBOL', 'Name', 'Sector')); db.get_connection().commit()"`
- **Verify First**: Use `yfinance.Ticker(symbol).info` to confirm validity
- **Soft Delete**: Set `is_active = 0` to preserve history
- **Delisted**: Add to `config/delisted.py` blacklist

## Report Generation

- Pass `all_candidates` (40 items) separately from `opportunities` (10 analyzed) to show Additional Candidates (11-40)
- Use symbol deduplication to avoid overlap between Top 10 and Additional sections
- **Market Sentiment Section**: Display AI reasoning, key_factors, and confidence percentage
- **Compact Stats**: Single line format: "Scanned: N | Success: N | Failed: N | Top Picks: N"

## Strategy Scoring System

All 8 strategies use unified 0-15 point scoring with 4 dimensions (3-4 points each):
- **Tier S (13-15 pts)**: 20% position size - Exceptional setup with confirmation
- **Tier A (10-12 pts)**: 10% position size - Qualified setup with minor concerns
- **Tier B (7-9 pts)**: 5% position size - Marginal setup, reduced exposure
- **Below 7**: Filter out - Insufficient edge

Score dimensions vary by strategy (PQ/BS/VC/TC for VCP-EP, RS/SQ/VC/TC for Momentum, etc.)

## Industry Data

Sector/industry data from yfinance for sector rotation analysis:
- `fetch_stock_info(symbol)` - Get sector, industry from Ticker.info
- `fetch_batch_stock_info(symbols)` - Batch fetch with SQLite caching
- **stock_info table**: symbol, sector, industry, updated_date
- Use for sector resonance detection (+2 bonus when industry clusters active)

## Strategy Development Testing

When developing/upgrading strategies:
- Create isolated test script (e.g., `test_strategy_a_v2.py`) before modifying screener.py
- Use existing cache data (`market_data` table) for fast iteration (20-30 min vs 70-80 min)
- Test with 5-10 known symbols before full scan
- Check Feb 2026 data for extreme cases (tight platforms, volatility spikes)
- Use `yfinance.Ticker(symbol).history(period="1d")` to verify live data availability

## Dynamic Trailing Stops

4-stage exit system based on price action:
1. **Initial Stop**: Fixed stop-loss at entry (ATR-based or technical level)
2. **Chandelier Exit**: 3× ATR(22) from highest high since entry (early trend phase)
3. **21EMA Trail**: Switch to EMA21 when price extends > 2 ATR above it
4. **10EMA Trail**: Final acceleration phase, tightest exit

Use `calculate_chandelier_exit(df, atr_period=22, multiplier=3)` for trailing calculation

## Technical Indicators

New calculations in `core/indicators.py`:
- `calculate_normalized_ema_slope(df, ema_period, window)` - Trend intensity (slope/ATR)
- `detect_vcp_platform(df)` - 15-30 day platform with concentration metrics
- `detect_squeeze(df)` - Volatility contraction (quantitative + qualitative)
- `calculate_clv(df)` - Close Location Value (0 to 1, institutional footprint)
- `calculate_volume_confirmation(df)` - Dry up (-50%) followed by surge (>2x)
- `estimate_gap_impact(df, atr)` - ATR-based next-day gap estimation
- `calculate_rs_score(df, benchmark)` - 3m(40%) + 6m(30%) + 12m(30%) weighted RS
- `calculate_retracement_structure(df, ema_periods)` - Fibonacci pullback analysis

## Strategy Documentation

**策略描述.md** (`/home/admin/Projects/TradeChanceScreen/策略描述.md`) is the canonical documentation for all 8 trading strategies.

**Critical Rule**: When modifying strategy logic in `core/screener.py` or scoring calculations in `core/indicators.py`, **you MUST同步更新 `策略描述.md`**.

Documentation requirements:
- All 8 strategies (A: VCP-EP, B: Momentum, C: Shoryuken, D: Pullbacks, E: U&R, F: RangeSupport, G: DTSS, H: Parabolic)
- Unified 0-15 scoring system with 2 decimal precision
- 4-dimensional scoring breakdown per strategy
- Entry/exit rules and trailing stop logic
- **Detailed calculation formulas** (RS评分, EMA斜率, CLV, 能量比, etc.)
- Update the maintenance record table when making changes

**Formula Sync Checklist**:
When modifying any calculation in code, update these sections in `策略描述.md`:
1. "核心指标计算公式" - Add/modify the formula with mathematical notation
2. Strategy-specific scoring tables - Update if scoring logic changes
3. 维护记录 - Log the change

Before committing strategy changes:
1. Update code in `core/screener.py` or `core/indicators.py`
2. 同步更新 `策略描述.md` formulas and scoring tables
3. Update the maintenance record at the bottom of `策略描述.md`
4. Test with `test_strategies_abc.py` to verify scoring

**Key Formulas Reference**:
- RS评分: `0.4×R3m + 0.3×R6m + 0.3×R12m`
- 标准化EMA斜率: `(EMA21_today - EMA21_5d) / ATR14`
- CLV: `(Close - Low) / (High - Low)`
- 能量比: `突破幅度 / 平台振幅` (capped at 3.0)

## Strategy Plugin Architecture

All 8 strategies now use plugin pattern under `core/strategies/`:
- `BaseStrategy` abstract class defines interface: `filter()`, `calculate_dimensions()`, `calculate_entry_exit()`, `build_match_reasons()`
- `STRATEGY_REGISTRY` maps `StrategyType` enum to strategy classes
- `create_strategy()` factory instantiates by type
- Each strategy implements 4-dimensional 0-15 point scoring with linear interpolation

## Linear Interpolation Scoring Pattern

All strategies use linear interpolation for boundary values:
```python
score = X + (value - A) / (B - A) * (Y - X)  # value in [A,B] → score in [X,Y]
```
Example: RS > 0.3 → 3.0 pts, RS > 0.5 → 5.0 pts, at RS=0.4: 3.0 + (0.1/0.2)*2.0 = 4.0
Never use step functions - always interpolate between boundaries.

## SPY Market Data Requirement

SPY is automatically added to stock universe in `config/stocks.py` for:
- Market regime detection (SPY vs EMA200) in `core/screener.py`
- RS resilience bonus calculation in `core/strategies/momentum.py`
- Always fetch SPY data first in strategy `screen()` methods that need market context

## Strategy Formula Documentation

When modifying any scoring calculation, **同步更新 `策略描述.md`**:
1. Update formula in "核心指标计算公式" section with mathematical notation
2. Update strategy-specific scoring tables
3. Add entry to 维护记录 table with date
4. Test with isolated script before full scan

## Refactoring Strategy Pattern

For large refactoring (like strategy migration):
1. Create isolated test script first (e.g., `test_strategy_a_v2.py`)
2. Verify scoring matches expected outputs using cached data
3. Create new plugin files alongside existing code
4. Update registry and switch over
5. Remove old code only after full scan passes
6. Update 策略描述.md with any formula changes

## File Corruption Recovery

If code file contains garbage content (model output pollution):
1. Find corruption start: `grep -n "garbage_text" file.py`
2. Find where code resumes: `grep -n "expected_code" file.py`
3. Extract clean parts: `head -N file.py > fixed.py && tail -n +M file.py >> fixed.py`
4. Verify: `python3 -m py_compile fixed.py`
5. Replace: `cp fixed.py file.py`

## Strategy Pre-Filter Design

Pre-filter vs Scoring trade-off:
- **Pre-filter**: Hard cut before scoring (performance)
- **Scoring dimension**: Soft threshold in 0-5 scale (flexibility)

Guidelines:
- Use pre-filter for expensive calculations (RS ranking, 52w high)
- Relaxed thresholds: A<25%, B>75%, C price>EMA21
- Keep filter logic in `screen()` method, scoring in `calculate_dimensions()`

## Quick Syntax Check

Validate multiple files: `python3 -m py_compile file1.py file2.py ...`
Exit code 0 = all valid
Shows first error with line number
