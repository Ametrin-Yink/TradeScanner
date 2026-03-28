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
