# CLAUDE.md

Trade Scanner - Current State Reference

## Project Overview

Automated US stock trading opportunity scanner analyzing stocks with market cap >$2B daily using 8 trading strategies. Generates web-based reports with AI-powered analysis.

## Current Architecture (v6.0)

**8 Strategy Plugins** (`core/strategies/`) - Clean A-H Naming:

| Letter | Strategy | File | Type | Description |
|--------|----------|------|------|-------------|
| A | MomentumBreakout | momentum_breakout.py | Long | Multi-pattern CQ, TC gate, bonus pool |
| B | PullbackEntry | pullback_entry.py | Long | EMA pullback with 4D scoring |
| C | SupportBounce | support_bounce.py | Long | False breakdown reclaim |
| D | DistributionTop | distribution_top.py | Short | Distribution tops (from RangeShort + DTB) |
| E | AccumulationBottom | accumulation_bottom.py | Long | Accumulation bottoms (from DTB) |
| F | CapitulationRebound | capitulation_rebound.py | Long | VIX 15-35 window, extreme exempt |
| G | EarningsGap | earnings_gap.py | Both | Post-earnings gap continuation |
| H | RelativeStrengthLong | relative_strength_long.py | Long | RS leaders in bear markets |

**6-Phase Daily Workflow** (runs at 3 AM ET):
| Phase | Component | Duration | Description |
|-------|-----------|----------|-------------|
| 0 | PreMarketPrep | 15-20 min | Initialize stock DB, Tier 1/3 pre-calculation, market cap filtering |
| 1 | AIMarketRegime | 3-5 min | Tavily + AI regime detection (replaces deterministic) |
| 2 | StrategyScreener | 10-15 min | Screen 30 slots, duplicate handling, skip 0-slot strategies |
| 3 | AIScoring | 15-20 min | AI confidence scoring with tiered sector penalty |
| 4 | DeepAnalysis | 10-15 min | Tavily + AI deep analysis for top 10 |
| 5 | ReportGenerator | 2-3 min | HTML report with top 30 + deep analysis for top 10 |
| 6 | MultiNotifier | 1 min | WeChat + Discord notifications with AI regime info |

**Regime-Based Allocation** (30 slots total):
| Regime | A | B | C | D | E | F | G | H | **Total** |
|--------|---|---|---|---|---|---|---|---|----------|
| bull_strong | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | **30** |
| bull_moderate | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | **30** |
| neutral | 6 | 5 | 5 | 4 | 4 | 0 | 3 | 3 | **30** |
| bear_moderate | 4 | 4 | 4 | 5 | 5 | 2 | 0 | 6 | **30** |
| bear_strong | 0 | 0 | 4 | 6 | 6 | 8 | 0 | 6 | **30** |
| extreme_vix | 0 | 0 | 0 | 3 | 3 | 12 | 0 | 12 | **30** |

**Regime-Adaptive Position Sizing**:
| Regime | Long Scalar | Short Scalar | Exemptions |
|--------|-------------|--------------|------------|
| bull_strong | 1.0× | 0.3× | None |
| bull_moderate | 1.0× | 0.3× | None |
| neutral | 0.8× | 0.8× | None |
| bear_moderate | 0.5× | 1.0× | None |
| bear_strong | 0.5× | 1.0× | None |
| extreme_vix | 0.3× | 0.5× | F, H get 1.0× |

**Pipeline**:
- `stock_universe.py` → `premarket_prep.py` → `market_regime.py` → `screener.py` → `ai_confidence_scorer.py`/`analyzer.py` → `reporter.py` → `notifier.py`
- Database: SQLite (`data/market_data.db`)
- Web: Flask on port 19801

## 3-Tier Pre-Calculation Architecture

**Tier 1 (Universal Metrics)**: Calculated for ALL symbols at 3 AM
- Price, Volume, EMAs (8/21/50/200), ATR/ADR
- Returns (3m/6m/12m/5d), RS scores, 52-week metrics
- **v5.0**: accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction, spy_regime
- Stored in `tier1_cache` table

**Tier 2 (Strategy-Specific)**: Calculated LAZY during screening
- VCP platform detection, S/R levels
- RSI divergence, EMA slopes
- Calculated only for candidates passing Tier 1 filters

**Tier 3 (Market Data)**: Fetched once at 3 AM, shared
- SPY, QQQ, IWM (benchmarks)
- VIXY, UVXY (volatility)
- XLK, XLF, XLE, etc. (sectors)
- Stored in `tier3_cache` table as pickled DataFrames

## Key Technical Decisions

- **Data**: yfinance (free), threads=False, 0.5s delay, incremental updates
- **Universe**: Static CSV (nasdaq_stocklist_screener.csv) with 2 categories: stocks and market_index_etf
- **Pre-filter**: Market cap >=$2B (from yfinance), price $2-3000, volume >=100K avg
- **AI**: Alibaba DashScope (OpenAI-compatible)
- **Scale**: ~2,900 symbols (~2,800 stocks + ~100 ETFs), ~45-60 min total workflow
- **Caching**: Tier 1/3 pre-calculation, 280 trading days retained
- **Charts**: matplotlib with Agg backend

## Database Schema

**Core Tables**:
- `stocks` - symbol, name, sector, **category** (stocks/market_index_etf), **market_cap**, is_active
- `market_data` - OHLCV data by symbol/date
- `scan_results` - scan history
- `system_status` - last scan info

**Pre-calculation Tables**:
- `universe_sync` - sync history (date, added, removed, total)
- `tier1_cache` - universal metrics (symbol, price, EMAs, RS, etc.) + **v5.0** (accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction, spy_regime)
- `tier3_cache` - market data (SPY, VIX, ETFs as pickled DataFrames)
- `workflow_status` - 5-phase execution tracking

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

# Full 5-phase workflow (runs at 3 AM ET via cron)
python scheduler.py

# Phase 0 only (universe sync + Tier 1/3 pre-calc)
python -c "from core.premarket_prep import run_premarket_prep; run_premarket_prep()"

# Web server
python api/server.py

# Check status
ss -tlnp | grep 19801
```

## Critical Patterns

**Stock Database Initialization**:
```python
from core.stock_universe import StockUniverseManager, initialize_stock_database

# Initialize database (run once)
result = initialize_stock_database()
# Returns: stocks_added, etfs_added, total_symbols

# Get stocks for scanning (>=$2B market cap)
manager = StockUniverseManager()
stocks = manager.get_stocks(min_market_cap=2e9)

# Get market ETFs for Tier 3
etfs = manager.get_market_etfs()
```

**Strategy Plugin Interface**:
```python
class MyStrategy(BaseStrategy):
    NAME = "StrategyName"
    STRATEGY_TYPE = StrategyType.A  # A-H naming
    DIMENSIONS = ['D1', 'D2', 'D3', 'D4']
    DIRECTION = 'long'  # 'long', 'short', or 'both'

    def filter(self, symbol, df, tier1_data=None, tier3_data=None) -> bool: ...
    def calculate_dimensions(self, symbol, df) -> List[ScoringDimension]: ...
    def calculate_entry_exit(self, symbol, df, dims, score, tier) -> Tuple[float, float, float]: ...
    def build_match_reasons(self, symbol, df, dims, score, tier) -> List[str]: ...
    def calculate_position_pct(self, tier: str, regime: str = 'neutral') -> float: ...  # v5.0 regime-adaptive
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

- **v6.0 AI Regime Detection**: Phase 1 now uses Tavily + AI for regime classification
- **v6.0 30-Slot Screening**: Phase 2 screens 30 candidates with duplicate handling
- **v6.0 Tiered Sector Penalty**: Top=0%, 2nd=-5%, 3rd+=-10%
- **v6.0 Deep Analysis Phase**: Dedicated Phase 4 with Tavily + AI for top 10
- **v5.0 Strategy Naming**: Clean A-H identifiers (removed EP, U&R, DTSS, etc.)
- **v5.0 0-Slot Skip**: Strategies with 0 slots in regime table are skipped entirely
- **kimi-k2.5**: No `response_format` support - use regex JSON extraction
- **yfinance**: Wikipedia blocks (403), use Slickcharts for stock lists
- **Memory**: Keep under 500MB, batch processing in 50s
- **Server**: Port 19801 only (security group restriction)
- **Cron**: 3 AM ET daily: `0 3 * * 1-5 cd /path && python scheduler.py >> /var/log/trade_scanner.log 2>&1`
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
