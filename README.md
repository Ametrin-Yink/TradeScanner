# Trade Scanner

Automated US stock trading opportunity scanner analyzing stocks with market cap > $2B daily using 6 trading strategies. It generates web-based reports with AI-powered analysis.

## Features

- **6 Trading Strategies**: MomentumBreakout, PullbackEntry, SupportBounce, RangeShort, DoubleTopBottom, CapitulationRebound
- **4-Dimension Scoring**: Each strategy uses 4 specific dimensions (e.g., PQ/BS/VC/TC for MomentumBreakout)
- **3-Tier Pre-Calculation**: Tier 1 (universal), Tier 2 (lazy strategy), Tier 3 (market data)
- **5-Phase Workflow**: Data prep → Sentiment → Screening → AI Analysis → Report → Notifications
- **Unified Scoring**: 0-15 point system across 4 dimensions per strategy
- **Tier-Based Position Sizing**: S (20%), A (10%), B (5%), C (reject)
- **AI Analysis**: DashScope integration for candidate ranking
- **Web Reports**: Interactive HTML reports
- **Automated Scheduling**: Runs daily at 3:00 AM ET

## Architecture

```
core/
├── strategies/          # 6 strategy plugins
│   ├── momentum_breakout.py    # PQ, BS, VC, TC dimensions
│   ├── pullback_entry.py       # TI, RC, VC, BONUS dimensions
│   ├── support_bounce.py       # SQ, VD, RB dimensions
│   ├── range_short.py          # TQ, RL, VC dimensions
│   ├── double_top_bottom.py    # PL, TS, VC dimensions
│   └── capitulation_rebound.py # MO, EX, VC dimensions
├── stock_universe.py    # Stock database management
├── premarket_prep.py    # Phase 0: DB init, Tier 1/3, market cap filter
├── market_analyzer.py   # Phase 1: Market sentiment
├── screener.py          # Phase 2: Strategy screening with cache
├── selector.py          # Phase 3a: AI scoring
├── ai_confidence_scorer.py # Phase 3b: Confidence scoring
├── analyzer.py          # Phase 3c: Deep AI analysis
├── reporter.py          # Phase 4: HTML report
└── notifier.py          # Phase 5: WeChat/Discord

config/
├── settings.json        # Configuration
└── secrets.json       # API keys (gitignored)

data/
├── market_data.db       # SQLite database
└── charts/            # Generated charts

nasdaq_stocklist_screener.csv  # Static universe (~2,800 symbols)
web/reports/                 # HTML reports (15 max, rolling)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize stock database (run once)
python -c "from core.stock_universe import initialize_stock_database; initialize_stock_database()"

# Run test scan (uses provided symbols, skips DB init)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Run full 5-phase workflow
python scheduler.py

# Phase 0 only (universe sync + Tier 1/3 pre-calc)
python -c "from core.premarket_prep import PreMarketPrep; PreMarketPrep().run_phase0()"

# Start web server
python api/server.py
```

## 5-Phase Workflow

| Phase | Component | Duration | Description |
|-------|-----------|----------|-------------|
| 0 | PreMarketPrep | 15-20 min | Initialize DB, fetch Tier 3, calculate Tier 1, market cap filter |
| 1 | MarketAnalyzer | 2-3 min | Market sentiment + strategy allocation |
| 2 | Screener | 10-15 min | Strategy screening with cached data |
| 3 | Analyzer | 15-20 min | AI analysis of top 10 candidates |
| 4 | Reporter | 2-3 min | HTML report generation |
| 5 | Notifier | 1 min | WeChat + Discord notifications |

| **Total** | | **~45-60 min** | |


## Strategy Dimensions

| Strategy | Dimensions | Description |
|----------|-----------|-------------|
| MomentumBreakout | PQ, BS, VC, TC | Platform Quality, Breakout Strength, Volume Confirmation, Trend Context |
| PullbackEntry | TI, RC, VC, BONUS | Trend Intensity, Retracement Composite, Volume, Bonus |
| SupportBounce | SQ, VD, RB | Support Quality, Volume Dynamics, Rebound |
| RangeShort | TQ, RL, VC | Trend Quality, Resistance Level, Volume |
| DoubleTopBottom | PL, TS, VC | Proximity Level, Test Strength, Volume |
| CapitulationRebound | MO, EX, VC | Momentum Extension, Extension Level, Volume |

## 3-Tier Pre-Calculation

**Tier 1 (Universal)**: Calculated for ALL symbols at 3 AM
- Price, Volume, EMAs (8/21/50/200), ATR/ADR
- Returns (3m/6m/12m/5d), RS scores, 55-week metrics
- Stored in `tier1_cache` table

**Tier 2 (Strategy-Specific)**: Calculated LAZY during screening
- VCP detection, S/R levels
- RSI divergence, EMA slopes
- Only for candidates passing Tier 1

**Tier 3 (Market Data)**: Fetched once at 3 AM
- SPY, QQQ, IWM (benchmarks)
- VIX, UVXY (volatility)
- Sector ETFs (XLK, XLF, XLE, etc.)
- Stored in `tier3_cache` as pickled DataFrames

## Automated Schedule

```cron
# Run at 3:00 AM ET (before market open)
0 3 * * 1-5 cd /path/to/trade-scanner && python scheduler.py >> /var/log/trade_scanner.log 2>&1
```

## License

Private project - All rights reserved.
