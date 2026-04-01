# CLAUDE.md

Trade Scanner - Current State Reference

## Project Overview

Automated US stock trading opportunity scanner analyzing stocks with market cap >$2B daily using 6 trading strategies. Generates web-based reports with AI-powered analysis.

## Current Architecture (v4.0)

**6 Strategy Plugins** (`core/strategies/`):
| Strategy | File | Type | Description |
|----------|------|------|-------------|
| MomentumBreakout | momentum_breakout.py | Long | VCP + momentum with RS bonus |
| PullbackEntry | pullback_entry.py | Long | EMA pullback with 4D scoring |
| SupportBounce | support_bounce.py | Long | Upthrust & rebound |
| RangeShort | range_short.py | Short | Range breakdown |
| DoubleTopBottom | double_top_bottom.py | Both | Distribution/accumulation |
| CapitulationRebound | capitulation_rebound.py | Long | Capitulation reversal |

**5-Phase Daily Workflow** (runs at 6 AM ET):
| Phase | Component | Duration | Description |
|-------|-----------|----------|-------------|
| 0 | PreMarketPrep | 15-20 min | Universe sync, Tier 1/3 pre-calculation |
| 1 | MarketAnalyzer | 2-3 min | Sentiment analysis (Tavily + AI) |
| 2 | StrategyScreener | 10-15 min | Screen with cached Tier 1/3 data |
| 3 | OpportunityAnalyzer | 15-20 min | Deep AI analysis of top 10 |
| 4 | ReportGenerator | 2-3 min | HTML report generation |
| 5 | MultiNotifier | 1 min | WeChat + Discord notifications |

**Pipeline**:
- `stock_universe.py` → `premarket_prep.py` → `market_analyzer.py` → `screener.py` → `analyzer.py` → `reporter.py` → `notifier.py`
- Database: SQLite (`data/market_data.db`)
- Web: Flask on port 19801

## 3-Tier Pre-Calculation Architecture

**Tier 1 (Universal Metrics)**: Calculated for ALL symbols at 6 AM
- Price, Volume, EMAs (8/21/50/200), ATR/ADR
- Returns (3m/6m/12m/5d), RS scores, 52-week metrics
- Stored in `tier1_cache` table

**Tier 2 (Strategy-Specific)**: Calculated LAZY during screening
- VCP platform detection, S/R levels
- RSI divergence, EMA slopes
- Calculated only for candidates passing Tier 1 filters

**Tier 3 (Market Data)**: Fetched once at 6 AM, shared
- SPY, QQQ, IWM (benchmarks)
- VIXY, UVXY (volatility)
- XLK, XLF, XLE, etc. (sectors)
- Stored in `tier3_cache` table as pickled DataFrames

## Key Technical Decisions

- **Data**: yfinance (free), threads=False, 0.5s delay, incremental updates
- **Universe**: finvizfinance for >$2B market cap stocks, synced daily
- **AI**: Alibaba DashScope (OpenAI-compatible)
- **Scale**: Dynamic universe (~2500 stocks), ~45-60 min total workflow
- **Caching**: Tier 1/3 pre-calculation, 280 trading days retained
- **Charts**: matplotlib with Agg backend

## Database Schema

**Core Tables**:
- `stocks` - symbol, name, sector, is_active
- `market_data` - OHLCV data by symbol/date
- `scan_results` - scan history
- `system_status` - last scan info

**New Tables (v4.0)**:
- `universe_sync` - sync history (date, added, removed, total)
- `tier1_cache` - universal metrics (symbol, price, EMAs, RS, etc.)
- `tier3_cache` - market data (SPY, VIX, ETFs as pickled DataFrames)
- `workflow_status` - 6-phase execution tracking

## Scoring System

- **Unified**: 0-15 points, 4 dimensions per strategy
- **Tiers**: S (12+, 20%), A (9+, 10%), B (7+, 5%), C (<7, reject)
- **Linear interpolation** for boundary values

## Development Conventions

- Python 3.10+ with type hints
- API keys in `config/secrets.json` (nested: `dashscope.api_key`)
- Vectorized pandas operations
- Test: `python scheduler.py --test --symbols AAPL,MSFT,NVDA`

## Commands

```bash
# Test scan (uses provided symbols, skips universe sync)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Full 6-phase workflow (runs at 6 AM ET via cron)
python scheduler.py

# Phase 0 only (universe sync + Tier 1/3 pre-calc)
python -c "from core.premarket_prep import run_premarket_prep; run_premarket_prep()"

# Web server
python api/server.py

# Check status
ss -tlnp | grep 19801
```

## Critical Patterns

**Strategy Plugin Interface**:
```python
class MyStrategy(BaseStrategy):
    NAME = "StrategyName"
    STRATEGY_TYPE = StrategyType.XXX
    DIMENSIONS = ['D1', 'D2', 'D3', 'D4']

    def filter(self, symbol, df, tier1_data=None, tier3_data=None) -> bool: ...
    def calculate_dimensions(self, symbol, df) -> List[ScoringDimension]: ...
    def calculate_entry_exit(self, symbol, df, dims, score, tier) -> Tuple[float, float, float]: ...
    def build_match_reasons(self, symbol, df, dims, score, tier) -> List[str]: ...
```

**Pre-calculation Access** (from `core/premarket_prep.py`):
```python
from data.db import db

# Get cached Tier 1 metrics
tier1 = db.get_tier1_cache('AAPL')  # Returns dict with price, EMAs, RS, etc.

# Get cached Tier 3 market data
spy_df = db.get_tier3_cache('SPY')  # Returns DataFrame
```

**Shared Utilities** (`core/scoring_utils.py`):
- `calculate_clv()`, `check_rsi_divergence()`, `check_exhaustion_gap()`
- `calculate_rs_score_weighted()`, `calculate_normalized_ema_slope()`

## Important Notes

- **kimi-k2.5**: No `response_format` support - use regex JSON extraction
- **yfinance**: Wikipedia blocks (403), use Slickcharts for stock lists
- **Memory**: Keep under 500MB, batch processing in 50s
- **Server**: Port 19801 only (security group restriction)
- **Cron**: 6 AM ET daily: `0 6 * * 1-5 cd /path && python scheduler.py >> /var/log/trade_scanner.log 2>&1`
- **Subagent Deadlock Detection**: When dispatching subagents, implement timeout/watchdog mechanisms. If a subagent task hangs (>5 min without progress), kill and retry with reduced scope. Check TaskOutput with timeout parameter instead of blocking indefinitely.

## Documentation Alignment Rule

**Rule**: `docs/Strategy_Description.md` must match actual code implementation.

### Verification Process
1. Before modifying strategy code, read the documentation section
2. After modifying code, update documentation if behavior changed
3. Document entry/exit rules must match calculate_entry_exit() implementation
4. Dimension names in docs must match DIMENSIONS class variable

### Common Mismatches to Avoid
- Intraday vs EOD: Code uses daily data, docs must not describe intraday entries
- Dimension abbreviations: Must match code exactly (e.g. RS vs RC)
- Scoring formulas: Must match actual interpolation logic
- Position tiers: Must match calculate_position_pct() implementation

### Checklist Before Commit
- [ ] Entry/exit rules verified against code
- [ ] Dimension names match code
- [ ] Scoring formulas match implementation
- [ ] No intraday terminology in daily strategy docs
