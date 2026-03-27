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
