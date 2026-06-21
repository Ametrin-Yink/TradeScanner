# Trade Scanner

Sector-first US stock trading scanner — daily AI-powered analysis across 13 curated sectors (~340 stocks), generating an HTML dashboard with technical trade setups.

## How It Works

1. **Market Overview** — SPY/VIX data + AI macro analysis with web search
2. **Sector Analysis** — 13 sectors analyzed in parallel with AI web search for drivers/risks/outlook
3. **Stock Highlights** — Technical screening per sector: Breakout, Near Support/Resistance, Strong Momentum, Good R/R
4. **Entry/Stop/Target** — Chart-aligned S/R levels (60-bar window, order=2 swing detection), proximity-capped entries
5. **Report** — Single HTML file with amber-palette dashboard, interactive charts, Active vs Pullback Watch split

## Quick Start

```bash
python scheduler.py --force      # Run full daily scan
python -m pytest tests/e2e/ -v   # Run E2E tests
python api/server.py             # Start API + dashboard (port 19801)
```

## Architecture

```
scheduler.py          # Daily orchestrator: market → sectors → highlights → report
core/
├── sector_analyzer.py   # AI sector analysis + stock highlight selection
├── reporter.py          # HTML report generator
├── swing_detector.py    # S/R detection + stop/target calculation
├── tag_manager.py       # Sector tag CRUD and stock assignment
├── ai_client.py         # DeepSeek V4 Pro wrapper with web search tool-calling
├── fetcher.py           # Market data fetcher (yfinance)
├── indicators.py        # Technical indicators (EMA, ATR, RS, etc.)
└── constants.py         # Sector ↔ ETF mappings
api/
├── server.py            # Flask API: scan, OHLC data, tag/config CRUD
└── config_api.py        # Tag/sector REST endpoints
data/
└── db.py                # SQLite: stocks, market_data, tier1_cache, tags, etf_cache
config/
├── portfolio_config.yaml # Account value, risk %, entry distance thresholds
├── settings.py           # API keys, paths, web port
├── stocks.py             # Static stock reference list
└── delisted.py           # Known delisted symbols
web/
├── dashboard.html       # SPA: Today / Tags / Reports / Config tabs
├── js/                  # ES modules: app, api, tags, today, reports, config
├── css/                 # Dashboard styles
└── reports/             # Generated HTML reports (report_YYYY-MM-DD.html)
tests/
└── e2e/                 # End-to-end pytest suite
```

## Sectors

Software, Semiconductors, Quantum Computing, Nuclear Energy, Photonics, Space, Memory, Drone, Robot, Rare Earth, Neocloud, Fintech, Crypto

Stocks are assigned to sectors via the Tags tab in the web dashboard. Each sector has a benchmark ETF for relative strength and trend data.

## Technical Setup Types

| Setup           | Entry Logic                     | Horizon           |
| --------------- | ------------------------------- | ----------------- |
| Breakout        | Current price (momentum)        | Swing (5-20d)     |
| Strong Momentum | Current price (trend-following) | Position (10-40d) |
| Near Support    | Nearest support zone within 10% | Swing (5-20d)     |
| Near Resistance | Current price                   | Swing (5-20d)     |
| Good R/R        | Current price                   | Swing (5-20d)     |

Entry prices are capped at 10% from current price (`max_entry_distance_pct` in portfolio_config.yaml). Breakout and Strong Momentum always use current price — they're momentum trades, not pullback entries.

## Report Features

- **Active Setups** — entries at or near current price, actionable now
- **Pullback Watch** — entries >5% below current price, wait for pullback
- **Interactive charts** — click any symbol to see OHLC candlesticks with S/R levels
- **Sector bar chart** — daily performance at a glance, click to drill into details
- **AI analysis** — sector outlook, key drivers, risks per sector

## AI

Uses DeepSeek V4 Pro via `core/ai_client.py` with web search tool-calling. Sector analysis runs in parallel (4 threads). Market overview and sector outlook are search-enabled; focus summary reasoning is not.

## Server

- Flask API on port 19801
- API key auth for all endpoints
- Tailscale Funnel for remote access: `https://ametrin-maco.tail81da69.ts.net/reports/`
- Scan endpoint triggers full pipeline; scheduled via `scheduler.py` (can be cron'd)

## License

Private project — All rights reserved.
