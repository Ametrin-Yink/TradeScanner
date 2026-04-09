# Trade Scanner

Automated US stock trading opportunity scanner analyzing stocks with market cap >= $2B daily using 8 trading strategies. Generates web-based reports with AI-powered analysis.

## Features

- **9 Trading Strategies**: Regime-aware allocation across bull/neutral/bear markets (A1/A2 sub-modes for Strategy A)
- **7-Phase Workflow**: Pre-market prep through multi-channel notifications
- **3-Tier Pre-Calculation**: Universal, lazy strategy-specific, and market data tiers
- **Unified Scoring**: 0-15 point system, 4 dimensions per strategy
- **Regime-Based Allocation**: 30 slots dynamically distributed by market regime
- **AI Analysis**: AI integration with Tavily research
- **Web Reports**: Interactive HTML reports with top 30 table + top 10 deep analysis
- **Automated Scheduling**: Runs daily at 3:00 AM ET

## Architecture

```
core/
├── strategies/              # 9 strategy plugins (A-H with A1/A2 sub-modes)
│   ├── momentum_breakout.py        # A1: Long (confirmed breakout)
│   ├── prebreakout_compression.py  # A2: Long (pre-breakout)
│   ├── pullback_entry.py           # B: Long
│   ├── support_bounce.py           # C: Long
│   ├── distribution_top.py         # D: Short
│   ├── accumulation_bottom.py      # E: Long
│   ├── capitulation_rebound.py     # F: Long
│   ├── earnings_gap.py             # G: Both
│   └── relative_strength_long.py   # H: Long
├── engine/                  # Pipeline workflow engine (Phase 3-4 restructure)
│   ├── pipeline.py                  # PipelineOrchestrator
│   ├── base_phase.py                # PhaseHandler ABC
│   ├── context.py                   # PipelineContext
│   └── phase_handlers/              # Individual phase implementations
├── services/                # Service registry (dependency injection)
│   └── registry.py                  # ServiceRegistry
├── debug/                   # Integrated debug tools
│   └── inspector.py                 # PipelineInspector
├── logging_config.py        # Centralized logging configuration
├── stock_universe.py        # Stock database management
├── premarket_prep.py        # Phase 0: DB init, Tier 1/3, market cap filter
├── market_regime.py         # Regime detection + allocation tables
├── market_analyzer.py       # Phase 1: AI + Tavily market analysis
├── screener.py              # Phase 2: Multi-strategy screening
├── ai_confidence_scorer.py  # Phase 3: Top 30 selection
├── analyzer.py              # Phase 4: Deep analysis for top 10
├── reporter.py              # Phase 5: HTML report generation
├── notifier.py              # Phase 6: Discord + WeChat webhooks
├── fetcher.py               # yfinance data fetching
└── indicators.py            # Technical indicators (VCP, RSI, EMA, etc.)

config/
├── settings.json            # Configuration
└── secrets.json             # API keys (gitignored)

data/
├── market_data.db           # SQLite database
└── charts/                  # Generated charts

api/server.py                # Flask API on port 19801
scheduler.py                 # Main entry point, 7-phase workflow
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Test scan (skips universe sync)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Debug mode with verbose logging and pipeline summary
python scheduler.py --test --symbols AAPL --debug

# Full workflow
python scheduler.py
python scheduler.py --force  # skip trading day check

# Phase 0 only
python -c "from core.premarket_prep import run_premarket_prep; run_premarket_prep()"

# Web server
python api/server.py

# Tests
python -m pytest tests/ -v
```

## 7-Phase Workflow

| Phase | Component        | Duration  | Description                                         |
| ----- | ---------------- | --------- | --------------------------------------------------- |
| 0     | PreMarketPrep    | 15-20 min | Init stock DB, Tier 1/3 pre-calc, market cap filter |
| 1     | AIMarketRegime   | 3-5 min   | Tavily + AI regime detection                        |
| 2     | StrategyScreener | 10-15 min | Screen 30 slots, duplicate handling                 |
| 3     | AIScoring        | 5-10 min  | Top 30 selection, parallel AI                       |
| 4     | DeepAnalysis     | 10-15 min | Tavily + AI deep analysis for top 10                |
| 5     | ReportGenerator  | 2-3 min   | HTML report (top 30 table + top 10 deep)            |
| 6     | MultiNotifier    | 1 min     | WeChat + Discord notifications                      |

## Strategies

| Letter | Strategy               | Type  | Description                      |
| ------ | ---------------------- | ----- | -------------------------------- |
| A1     | MomentumBreakout       | Long  | Confirmed breakout, VCP pattern  |
| A2     | PreBreakoutCompression | Long  | Pre-breakout, range compression  |
| B      | PullbackEntry          | Long  | EMA pullback with 4D scoring     |
| C      | SupportBounce          | Long  | False breakdown reclaim          |
| D      | DistributionTop        | Short | Distribution tops                |
| E      | AccumulationBottom     | Long  | Accumulation bottoms             |
| F      | CapitulationRebound    | Long  | VIX 15-35 window, extreme exempt |
| G      | EarningsGap            | Both  | Post-earnings gap continuation   |
| H      | RelativeStrengthLong   | Long  | RS leaders in bear markets       |

## Regime-Based Allocation (30 slots)

| Regime        | A1  | A2  | B   | C   | D   | E   | F   | G   | H   | Total |
| ------------- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ----- |
| bull_strong   | 4   | 4   | 6   | 4   | 0   | 0   | 0   | 8   | 4   | 30    |
| bull_moderate | 4   | 4   | 6   | 4   | 0   | 0   | 0   | 8   | 4   | 30    |
| neutral       | 3   | 3   | 5   | 5   | 4   | 4   | 0   | 3   | 3   | 30    |
| bear_moderate | 2   | 2   | 4   | 4   | 5   | 5   | 2   | 0   | 6   | 30    |
| bear_strong   | 1   | 1   | 0   | 4   | 6   | 6   | 8   | 0   | 4   | 30    |
| extreme_vix   | 0   | 0   | 0   | 0   | 3   | 3   | 12  | 0   | 12  | 30    |

Position sizing scales by regime: bull=1.0x/0.3x, neutral=0.8x, bear_moderate/bear_strong=0.5x long, extreme_vix=0.3x (F,H exempt at 1.0x).

## Scoring System

0-15 points, 4 dimensions per strategy. Tiers: S (12+, 20%), A (9+, 10%), B (7+, 5%), C (<7, reject). Linear interpolation for boundaries. Tiered sector penalty: Top=0%, 2nd=-5%, 3rd+=-10%.

## Server

- Flask API on port 19801
- Phase 0 runs in subprocess for memory isolation

## Restructure (April 2026)

The project was restructured to improve modularity and maintainability:

- **Service Registry** (`core/services/`): Dependency injection for core services
- **Strategy Plugins** (`core/strategies/`): Dynamic discovery, no hardcoded imports, YAML config
- **Pipeline Engine** (`core/engine/`): Modular workflow with PhaseHandler interface
- **Debug Tools** (`core/debug/`): Integrated pipeline inspection and analysis
- **Centralized Logging** (`core/logging_config.py`): Single logging configuration

See `docs/QUICKSTART.md` for usage examples of the new architecture.

## License

Private project - All rights reserved.
