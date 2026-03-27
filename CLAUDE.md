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

## Data Sources

- **Stock Lists:** Wikipedia blocks scraping (403) - use Slickcharts (slickcharts.com/sp500, /nasdaq100, /dowjones) for reliable stock lists
- **yfinance:** Use `yfinance.download(threads=False)` for VPS stability, batch requests for 500+ stocks
- **Charts:** Set `matplotlib.use('Agg')` before importing pyplot for headless servers

## Testing

- **Full Scan:** 518 stocks takes ~11 minutes, generates 10-15 candidates typically
- **Server:** Check `ss -tlnp | grep 19801` to verify Flask is listening

## AI API Compatibility

- **kimi-k2.5 via DashScope**: Does NOT support `response_format: {"type": "json_object"}` - use regex to extract JSON instead
- Remove `response_format` parameter and parse JSON from response text with `re.search(r'\{.*\}', content, re.DOTALL)`

## Chart Generation

- **Plotly > matplotlib**: Use Plotly for interactive web charts (zoom, pan, hover tooltips)
- Generate HTML charts with `plotly.graph_objects` and embed via iframe
- Serve charts via `/data/charts/<filename>` endpoint in Flask

## Confidence Scoring

- Use dynamic scoring (0-100) based on: Risk/Reward (20%), Volume (15%), Technicals (25%), S/R Quality (20%), Trend (20%)
- Avoid hardcoded confidence values (70%, 75%) - no differentiation

## UI Design Preferences

- **Financial/Professional style preferred** over "AI" style with gradients/emojis
- Use dark header (#1a1a2e), clean borders, compact spacing
- Color-code confidence: green (high), orange (medium), red (low)

## Stock Data Handling

- **Delisted stocks**: Maintain blacklist in `config/delisted.py`, filter during universe loading
- WBA delisted March 2025 - check for others periodically

## Report Generation

- Pass `all_candidates` (40 items) separately from `opportunities` (10 analyzed) to show Additional Candidates (11-40)
- Use symbol deduplication to avoid overlap between Top 10 and Additional sections
