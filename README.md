# Trade Scanner

Automated US stock trading opportunity scanner using 6 institutional-grade trading strategies.

## Overview

Trade Scanner analyzes 2000+ US stocks daily using technical analysis to identify high-probability trading setups. It generates web-based reports with AI-powered analysis and sends notifications via Discord/WeChat.

## Features

- **6 Trading Strategies**: MomentumBreakout, PullbackEntry, SupportBounce, RangeShort, DoubleTopBottom, CapitulationRebound
- **3-Tier Pre-Calculation**: Tier 1 (universal), Tier 2 (lazy strategy), Tier 3 (market data)
- **5-Phase Workflow**: Data prep → Sentiment → Screening → AI Analysis → Report → Notifications
- **Unified Scoring**: 0-15 point system across 4 dimensions per strategy
- **Tier-Based Position Sizing**: S (20%), A (10%), B (5%), C (reject)
- **AI Analysis**: Alibaba DashScope integration for candidate ranking
- **Web Reports**: Interactive HTML reports with charts
- **Automated Scheduling**: Runs daily at 6:00 AM ET

## Architecture

```
core/
├── strategies/          # 6 strategy plugins
│   ├── momentum_breakout.py
│   ├── pullback_entry.py
│   ├── support_bounce.py
│   ├── range_short.py
│   ├── double_top_bottom.py
│   └── capitulation_rebound.py
├── stock_universe.py    # Universe sync from Finviz
├── premarket_prep.py    # Phase 0: Tier 1/3 pre-calculation
├── screener.py          # Phase 2: Strategy screening with cache
├── market_analyzer.py   # Phase 1: Market sentiment
├── fetcher.py           # Data fetching (yfinance)
├── indicators.py        # Technical indicators
├── selector.py          # Phase 3a: AI scoring
├── analyzer.py          # Phase 3b: Deep AI analysis
├── reporter.py          # Phase 4: HTML report generation
└── notifier.py          # Phase 5: WeChat/Discord notifications

config/
├── stocks.py            # Stock universe loader
├── settings.json        # Configuration
└── secrets.json         # API keys (gitignored)

data/
├── market_data.db       # SQLite database
│   ├── stocks           # Symbol list
│   ├── market_data      # OHLCV data
│   ├── tier1_cache      # Universal metrics
│   ├── tier3_cache      # Market data (SPY/VIX/ETFs)
│   ├── universe_sync    # Sync history
│   └── workflow_status  # Execution tracking
└── charts/              # Generated charts

web/reports/             # HTML reports (15 max, rolling)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run test scan (uses provided symbols, skips universe sync)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Run full 6-phase workflow (all >$2B market cap stocks)
python scheduler.py

# Phase 0 only (universe sync + Tier 1/3 pre-calc)
python -c "from core.premarket_prep import run_premarket_prep; run_premarket_prep()"

# Start web server
python api/server.py
```

## 5-Phase Workflow

| Phase | Component | Duration | Description |
|-------|-----------|----------|-------------|
| 0 | PreMarketPrep | 15-20 min | Universe sync (Finviz), Tier 1/3 pre-calculation |
| 1 | MarketAnalyzer | 2-3 min | Sentiment analysis (Tavily + AI) |
| 2 | StrategyScreener | 10-15 min | Screen with cached Tier 1/3 data |
| 3 | OpportunityAnalyzer | 15-20 min | Deep AI analysis of top 10 |
| 4 | ReportGenerator | 2-3 min | HTML report generation |
| 5 | MultiNotifier | 1 min | WeChat + Discord notifications |

## 3-Tier Pre-Calculation

**Tier 1 (Universal)**: Calculated for ALL symbols at 6 AM
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

## Strategy Summary

| Strategy | Type | Description |
|----------|------|-------------|
| MomentumBreakout | Long | VCP + momentum breakout with volume confirmation |
| PullbackEntry | Long | EMA pullback with 4D scoring (TI/RS/VC/Bonus) |
| SupportBounce | Long | Upthrust & rebound from support |
| RangeShort | Short | Range bottom support breakdown |
| DoubleTopBottom | Both | Distribution top / accumulation bottom |
| CapitulationRebound | Long | Parabolic capitulation reversal |

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guidelines and architecture
- [docs/workflow.md](docs/workflow.md) - Detailed workflow documentation
- [docs/Strategy_Description.md](docs/Strategy_Description.md) - Detailed strategy formulas and specifications
- [docs/STOCK_MANAGEMENT.md](docs/STOCK_MANAGEMENT.md) - Stock management procedures

## Performance

- **Total Workflow**: ~45-60 minutes (with pre-calculation)
- **Phase 0 (Data Prep)**: ~15-20 minutes (once daily at 6 AM)
- **Phases 1-5**: ~30-40 minutes
- **Memory**: Under 500MB peak usage
- **Stocks**: Dynamic universe (market cap >$2B, ~2500 stocks)

## Automated Schedule

Recommended cron schedule (US market hours):
```
# Run at 6:00 AM ET (before market open)
0 6 * * 1-5 cd /path/to/trade-scanner && python scheduler.py >> /var/log/trade_scanner.log 2>&1
```

## License

Private project - All rights reserved.
