# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated US stock trading opportunity scanner analyzing stocks with market cap >=$2B daily using 8 trading strategies. Generates web-based reports with AI-powered analysis.

## Architecture (v6.0)

**8 Strategy Plugins** (`core/strategies/`) - A-H Naming:

| Letter | Strategy | Type | Description |
|--------|----------|------|-------------|
| A | MomentumBreakout | Long | Multi-pattern CQ, TC gate, bonus pool |
| B | PullbackEntry | Long | EMA pullback with 4D scoring |
| C | SupportBounce | Long | False breakdown reclaim |
| D | DistributionTop | Short | Distribution tops (merged RangeShort + DTB) |
| E | AccumulationBottom | Long | Accumulation bottoms |
| F | CapitulationRebound | Long | VIX 15-35 window, extreme exempt |
| G | EarningsGap | Both | Post-earnings gap continuation |
| H | RelativeStrengthLong | Long | RS leaders in bear markets |

**7-Phase Workflow** (runs at 3 AM ET):
| Phase | Component | Duration | Description |
|-------|-----------|----------|-------------|
| 0 | PreMarketPrep | 15-20 min | Init stock DB, Tier 1/3 pre-calc, market cap filter |
| 1 | AIMarketRegime | 3-5 min | Tavily + AI regime detection |
| 2 | StrategyScreener | 10-15 min | Screen 30 slots, duplicate handling |
| 3 | AIScoring | 5-10 min | Top 30 selection, parallel AI (configurable workers) |
| 4 | DeepAnalysis | 10-15 min | Tavily + AI deep analysis for top 10 |
| 5 | ReportGenerator | 2-3 min | HTML report (top 30 table + top 10 deep) |
| 6 | MultiNotifier | 1 min | WeChat + Discord notifications |

**Regime-Based Allocation** (30 slots):

| Regime | A | B | C | D | E | F | G | H | Total |
|--------|---|---|---|---|---|---|---|---|-------|
| bull_strong | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| bull_moderate | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| neutral | 6 | 5 | 5 | 4 | 4 | 0 | 3 | 3 | 30 |
| bear_moderate | 4 | 4 | 4 | 5 | 5 | 2 | 0 | 6 | 30 |
| bear_strong | 0 | 0 | 4 | 6 | 6 | 8 | 0 | 6 | 30 |
| extreme_vix | 0 | 0 | 0 | 3 | 3 | 12 | 0 | 12 | 30 |

Position sizing scales by regime: bull=1.0x/0.3x, neutral=0.8x, bear_moderate/bear_strong=0.5x long, extreme_vix=0.3x (F,H exempt at 1.0x).

## 3-Tier Pre-Calculation

**Tier 1** (ALL symbols): Price, Volume, EMAs 8/21/50/200, ATR/ADR, returns, RS scores, 52-week metrics. Stored in `tier1_cache`.
**Tier 2** (LAZY): VCP, S/R levels, RSI divergence, EMA slopes. Calculated only for candidates passing Tier 1.
**Tier 3** (Market data): SPY, QQQ, IWM, VIXY, UVXY, sector ETFs. Pickled in `tier3_cache`.

## Scoring System

0-15 points, 4 dimensions per strategy. Tiers: S (12+, 20%), A (9+, 10%), B (7+, 5%), C (<7, reject). Linear interpolation for boundaries. Tiered sector penalty: Top=0%, 2nd=-5%, 3rd+=-10%.

## Key Files

- `scheduler.py` - Main entry point, 7-phase workflow orchestration
- `core/strategies/` - 8 strategy plugins extending `base_strategy.py`
- `core/screener.py` - Multi-strategy screening with regime-aware allocation
- `core/market_regime.py` - Regime detection + allocation tables
- `core/market_analyzer.py` - Phase 1: AI + Tavily market analysis
- `core/ai_confidence_scorer.py` - Phase 3: Top 30 selection
- `core/analyzer.py` - Phase 4: Deep analysis for top 10
- `core/reporter.py` - Phase 5: HTML report generation
- `core/notifier.py` - Phase 6: Discord + WeChat webhooks
- `core/premarket_prep.py` - Phase 0: DB init, Tier 1/3 calculation
- `core/fetcher.py` - yfinance data fetching
- `core/indicators.py` - Technical indicators (VCP, RSI, EMA, etc.)
- `core/stock_universe.py` - Stock database management
- `data/db.py` - SQLite database layer
- `api/server.py` - Flask API on port 19801

## Commands

```bash
pip install -r requirements.txt

# Test scan (skips universe sync)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Full workflow
python scheduler.py
python scheduler.py --force  # skip trading day check

# Phase 0 only
python -c "from core.premarket_prep import run_premarket_prep; run_premarket_prep()"

# Web server
python api/server.py

# Tests
python -m pytest tests/ -v
python -m pytest tests/test_screener.py -v  # single file

ss -tlnp | grep 19801
```

## Critical Patterns

**Stock DB**:
```python
from core.stock_universe import StockUniverseManager, initialize_stock_database
initialize_stock_database()
stocks = StockUniverseManager().get_stocks(min_market_cap=2e9)
```

**Strategy Plugin**:
```python
class MyStrategy(BaseStrategy):
    NAME = "StrategyName"
    STRATEGY_TYPE = StrategyType.A
    DIMENSIONS = ['D1', 'D2', 'D3', 'D4']
    DIRECTION = 'long'  # 'long', 'short', or 'both'
    def filter(self, symbol, df, tier1_data=None, tier3_data=None) -> bool: ...
    def calculate_dimensions(self, symbol, df) -> List[ScoringDimension]: ...
    def calculate_entry_exit(self, symbol, df, dims, score, tier) -> Tuple[float, float, float]: ...
    def build_match_reasons(self, symbol, df, dims, score, tier) -> List[str]: ...
    def calculate_position_pct(self, tier: str, regime: str = 'neutral') -> float: ...
```

**Cache Access**:
```python
from data.db import db
tier1 = db.get_tier1_cache('AAPL')  # dict with price, EMAs, RS, etc.
spy_df = db.get_tier3_cache('SPY')  # DataFrame
```

**Secrets** (from `config/secrets.json`):
```python
from config.settings import settings
settings.get_secret('dashscope.api_key')
settings.get_secret('tavily.api_key')
```

## Important Notes

- **Server**: 32GB RAM - no memory constraints, can increase batch sizes or parallel workers
- **0-slot strategies are skipped** entirely for the current regime
- **kimi-k2.5**: No `response_format` support - use regex JSON extraction
- **yfinance**: Wikipedia blocks (403), use Slickcharts for stock lists
- **Server**: Flask port 19801, external URL `http://47.90.229.136:19801`
- **Subagent Deadlock Detection**: Implement timeout/watchdog. Kill tasks hanging >5 min.

## Documentation Alignment Rule

**Rule**: `docs/Strategy_Description.md` must match actual code.

- Entry/exit rules must match `calculate_entry_exit()` implementation
- Dimension names must match `DIMENSIONS` class variable exactly
- No intraday terminology (code uses daily data)
- Before committing: verify entry/exit rules, dimension names, scoring formulas
