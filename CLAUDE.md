# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the Trade Scanner project.

## Project Overview

Automated US stock trading opportunity scanner based on strategies in `Strategy_All.txt`. Runs daily at 6:00 AM ET to analyze 2000+ stocks using 6 trading strategies, ranks opportunities via AI, generates web-based reports with Discord/WeChat notifications.

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
- **Typical Output:** 10-20 candidates from 6 strategies, AI selects top 10 with confidence scores
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

All 6 strategies use unified scoring with 4 dimensions:
- **Tier S**: 20% position - Exceptional setup
- **Tier A**: 10% position - Qualified setup
- **Tier B**: 5% position - Marginal setup
- **Below Tier B**: Reject

**Non-equal weights** (Strategy D example):
- TQ (Trend): 4 pts - Foundation
- VS (Volume): 5 pts - Core signal ⭐
- PD (Depth): 3 pts - Timing
- RS (Strength): 3 pts - Resilience
- **Total**: 15 points

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

**策略描述.md** (`/home/admin/Projects/TradeChanceScreen/策略描述.md`) is the canonical documentation for all 6 trading strategies.

**Critical Rule**: When modifying strategy logic in `core/screener.py` or scoring calculations in `core/indicators.py`, **you MUST同步更新 `策略描述.md`**.

Documentation requirements:
- All 6 strategies (A+B: 动能右侧突破, C+D: 均线回踩买入, E: 支撑回踩买入, F: 区间阻力做空, G: 双顶双底策略, H: 抛物线回弹)
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

All 6 strategies now use plugin pattern under `core/strategies/`:
- `BaseStrategy` abstract class defines interface: `filter()`, `calculate_dimensions()`, `calculate_entry_exit()`, `build_match_reasons()`
- `STRATEGY_REGISTRY` maps `StrategyType` enum to strategy classes
- `create_strategy()` factory instantiates by type
- Each strategy implements 4-dimensional 0-15 point scoring with linear interpolation

## Strategy Merges (v2.2)

The 6-strategy architecture was achieved through strategic merges and conversions:

- **A+B Merged**: 动能右侧突破 (VCP-EP + Momentum) - Combined with RS bonus for merged scoring
- **C+D Merged**: 均线回踩买入 (Shoryuken + Pullbacks) - Combined with PD dimension for pullback depth
- **E**: 支撑回踩买入 (Upthrust & Rebound) - Unchanged, 4-dimension scoring
- **F Converted**: Range Support → 区间阻力做空 (short only) - Direction constraint added
- **G Updated**: DTSS → 双顶双底策略 - TS max 4, market filter added
- **H Converted**: Parabolic → 抛物线回弹 (long only) - Direction constraint added

**Benefits**:
- Reduced complexity from 8 to 6 strategies while maintaining coverage
- Clearer directionality (F short-only, H long-only)
- Stronger merged strategies (A+B, C+D) with combined scoring power
- Easier maintenance and documentation

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

## Sector ETF Data

Sector ETFs automatically loaded into universe for industry strength comparison:

**Core Sectors**: XLK, XLF, XLE, XLI, XLP, XLY, XLB, XLU, XLV
**Industries**: XBI, SMH, IGV, IYT

Use for: Relative sector strength, industry rotation detection, group move confirmation.

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

## Testing

Run all tests: `python -m pytest tests/ -v`
Run specific test: `python -m pytest tests/test_screener.py -v`
Run with coverage: `python -m pytest tests/ --cov=core --cov-report=html`

## Common Errors

**SQLite database locked**: Close any open SQLite browsers, or use WAL mode
**yfinance rate limit**: Use cached data in `market_data` table, wait 1 hour
**Port 19801 in use**: `lsof -ti:19801 | xargs kill -9` then restart server

## Sector ETF Reference

Main sector ETFs for industry strength comparison:

**Select Sector SPDR**:
- XLK - Technology
- XLF - Financials
- XLE - Energy
- XLI - Industrials
- XLP - Consumer Staples
- XLY - Consumer Discretionary
- XLB - Materials
- XLU - Utilities
- XLV - Health Care

**Industry ETFs**:
- XBI - Biotech
- SMH - Semiconductor
- IGV - Software
- IYT - Transportation

Usage: Compare stock's sector to ETF performance for relative strength context.

## Strategy Development Workflow

When developing/upgrading strategies (E/F/G v2.x pattern):
1. **Document First**: Update `策略描述.md` with scoring tables before coding
2. **Quick Syntax Check**: `python3 -m py_compile core/strategies/x.py`
3. **Import Test**: `python3 -c "from core.strategies.x import Strategy; s = Strategy()"`
4. **Commit**: Use detailed messages explaining dimensions and devil details

## Bidirectional Strategy Pattern

For strategies supporting long/short (e.g., Range, DTSS):
- Phase 0: Detect market direction via `SPY >/< EMA50` or `SPY >/< open`
- Store in `self.market_direction = 'long'/'short'/'neutral'`
- Pre-filter: Check trend alignment before expensive calculations
- Scoring: Adjust dimension logic based on direction (e.g., VC for short = relative weakness)

## Devil Details Pattern

Quality filters for reducing false signals:
- **Width Constraint**: `Range_Width < 1.5×ATR` → veto (no profit space)
- **Time Decay**: `Days_at_Level > 5` with minimal movement → exit signal
- **Stability Filter**: Tests must be ≥3 days apart (prevent double counting)
- **Profit Efficiency**: `R:R < 1.5` → score penalty (force good entry)
- **Relative Weakness**: SPY up + stock flat = distribution signal

## 策略描述.md Maintenance

When adding strategies, update these sections:
1. Strategy section with dimensions, scoring tables, formulas
2. 维护记录 table at bottom with date and changes
3. Keep formulas in code blocks with Chinese labels

## Scoring Utils Module

To avoid duplicate code across strategies, use the shared `core/scoring_utils.py` module:

### Available Functions

```python
from core.scoring_utils import (
    calculate_clv,                    # CLV calculation
    check_rsi_divergence,             # RSI divergence detection
    check_exhaustion_gap,             # Exhaustion gap detection
    calculate_test_interval,          # Test quality with interval
    calculate_institutional_intensity, # (Vol/MA20) * |CLV-0.5|
    detect_market_direction,          # SPY trend detection
    check_vix_filter,                 # VIX risk filter
    calculate_rs_score_weighted,      # 0.4*R3m + 0.3*R6m + 0.3*R12m
    calculate_volume_climax_score,    # Volume climax scoring
)
```

### When to Extract Functions

**Extract to scoring_utils.py when:**
- Same function appears in 2+ strategies
- Calculation logic is identical (only thresholds differ)
- Function is a "pure calculation" (no strategy-specific state)

**Keep in strategy when:**
- Strategy-specific thresholds/logic
- Needs access to strategy state (PARAMS, etc.)
- Different implementations across strategies

### Refactoring Checklist

When creating a new strategy:
1. Check if calculation exists in `scoring_utils.py`
2. If yes: import and use it
3. If no: implement in strategy first
4. If duplicated later: extract to `scoring_utils.py`

### Phase 1 Complete (E/F/G Strategies)

Refactored duplicate functions:
- `calculate_clv()` - extracted from DTSS, Parabolic, UpthrustRebound
- `check_rsi_divergence()` - extracted from DTSS, Parabolic
- `calculate_test_interval()` - extracted from DTSS, RangeSupport
- `check_exhaustion_gap()` - extracted from DTSS
- `calculate_institutional_intensity()` - extracted from DTSS

### Phase 2 Complete (A-D Strategies)

Additional utilities extracted to scoring_utils.py:
- `calculate_normalized_ema_slope(df, ema_period, atr_period)` - EMA slope normalized by ATR
- `calculate_linear_interpolation(value, min_val, max_val, min_score, max_score)` - Linear scoring
- `calculate_rs_score_weighted(rs_3m, rs_6m, rs_12m)` - 0.4*R3m + 0.3*R6m + 0.3*R12m
- `calculate_volume_climax_score(volume_ratio, thresholds)` - Volume climax detection

### Phase 3 Complete (Configuration System)

- `core/scoring_utils/` - Package with validation utilities
- `core/scoring_utils/__init__.py` - Package initialization
- `core/scoring_utils/validation.py` - ParameterValidator class
- `config/strategy_config.yaml` - Strategy parameter templates

Usage:
```python
from core.scoring_utils.validation import ParameterValidator

validator = ParameterValidator()
is_valid, errors = validator.validate_params(strategy_params)
```

## Python Package Imports

When creating shared utility packages:
- Place functions in `package/__init__.py` for `from package import func` syntax
- Don't use separate `package.py` file alongside `package/` directory
- Example: `core/scoring_utils/__init__.py` not `core/scoring_utils.py`

## Quick Strategy Testing

Test all strategies without full data:
```bash
python3 test_all_strategies.py
```
Validates: imports, attributes, methods, scoring_utils integration

## Strategy Structure Checklist

All strategies must define:
- NAME: Short strategy identifier
- STRATEGY_TYPE: StrategyType enum value
- DESCRIPTION: Human-readable description
- DIMENSIONS: List of dimension names (3-4 items)
- PARAMS: Dict of strategy-specific thresholds

All strategies must implement:
- filter(symbol, df) -> bool
- calculate_dimensions(symbol, df) -> List[ScoringDimension]
- calculate_entry_exit(symbol, df, dimensions, score, tier) -> Tuple[float, float, float]
- build_match_reasons(symbol, df, dimensions, score, tier) -> List[str]

## Scoring Utils Usage

Import shared calculations:
```python
from ..scoring_utils import calculate_clv, check_rsi_divergence
```

Available functions: calculate_clv, check_rsi_divergence, check_exhaustion_gap,
calculate_test_interval, calculate_institutional_intensity, detect_market_direction,
check_vix_filter, calculate_rs_score_weighted, calculate_volume_climax_score,
calculate_normalized_ema_slope, calculate_linear_interpolation

