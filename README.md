# Trade Scanner

Automated US stock trading opportunity scanner using 6 institutional-grade trading strategies.

## Overview

Trade Scanner analyzes 2000+ US stocks daily using technical analysis to identify high-probability trading setups. It generates web-based reports with AI-powered analysis and sends notifications via Discord/WeChat.

## Features

- **6 Trading Strategies**: MomentumBreakout, PullbackEntry, SupportBounce, RangeShort, DoubleTopBottom, CapitulationRebound
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
├── screener.py          # Main screening engine
├── fetcher.py           # Data fetching (yfinance)
├── indicators.py        # Technical indicators
├── analyzer.py          # AI analysis
└── reporter.py          # HTML report generation

config/
├── stocks.py            # Stock universe (517 symbols)
├── settings.json        # Configuration
└── secrets.json         # API keys (gitignored)

data/
├── stocks.db            # SQLite database
└── charts/              # Generated charts

web/reports/             # HTML reports (15 max, rolling)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run test scan (10 symbols)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Run full scan (all 517 stocks)
python scheduler.py

# Start web server
python api/server.py
```

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
- [策略描述.md](策略描述.md) - Detailed strategy formulas (Chinese)
- [docs/STOCK_MANAGEMENT.md](docs/STOCK_MANAGEMENT.md) - Stock management procedures

## Performance

- **Full Scan**: ~70-80 minutes (first run), ~20-25 minutes (cached)
- **Memory**: Under 500MB peak usage
- **Stocks**: 517 active symbols

## License

Private project - All rights reserved.
