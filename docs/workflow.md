# Daily Report Generation Workflow

This document describes the complete 5-phase workflow for generating daily trading opportunity reports.

## Overview

The Trade Scanner runs daily at 3 AM ET to analyze US stocks with market cap >=$2B and generate an HTML report with the top 10 trading opportunities.

## 3-Tier Pre-Calculation Architecture

**Tier 1 (Universal Metrics)**: Calculated for ALL symbols at 3 AM
- Price, Volume, EMAs (8/21/50/200), ATR/ADR
- Returns (3m/6m/12m/5d), RS scores, 52-week metrics
- Stored in `tier1_cache` table
- Used by ALL strategies

**Tier 2 (Strategy-Specific)**: Calculated LAZY during screening
- VCP platform detection, S/R levels
- RSI divergence, EMA slopes
- Only calculated for candidates passing Tier 1 filters
- Expensive calculations deferred until needed

**Tier 3 (Market Data)**: Fetched once at 3 AM, shared
- SPY, QQQ, IWM (benchmarks)
- VIXY, UVXY (volatility)
- XLK, XLF, XLE, etc. (sectors)
- Stored in `tier3_cache` table as pickled DataFrames

## 5-Phase Pipeline Architecture

```
Phase 0: Data Preparation (15-20 min)
├── Sync stock universe from CSV
├── Fetch Tier 3 market data (SPY, VIX, ETFs)
├── Fetch market data for all symbols
├── Update market cap from yfinance
├── Filter stocks by market cap (>=$2B)
└── Calculate Tier 1 universal metrics for qualifying stocks

Phase 1: Market Sentiment (2-3 min)
├── Tavily API search for market news
├── DashScope AI sentiment analysis
├── Determine market regime (bullish/bearish/neutral)
└── AI-driven strategy allocation (slots per strategy)

Phase 2: Strategy Screening (10-15 min)
├── Load cached Tier 1/3 data
├── Apply 6 strategy plugins with pre-filtering
├── Lazy Tier 2 calculations for candidates
└── Score 0-15 points across 4 dimensions, determine tiers

Phase 3: AI Analysis (15-20 min)
├── Select top 30 candidates
├── AI confidence scoring (batch)
├── Select top 10 by confidence
└── Deep AI analysis per candidate (parallel)

Phase 4: Report Generation (2-3 min)
├── Generate Plotly charts
├── Build HTML report
└── Save to web/reports/

Phase 5: Push Notifications (1 min)
├── Send Discord webhook
└── Send WeChat webhook
```

## Detailed Workflow

### Phase 0: Data Preparation (premarket_prep.py)

**Purpose**: Prepare all data before market opens

**Process**:
1. **Universe Sync**:
   - Load stocks from `nasdaq_stocklist_screener.csv` (category='stocks')
   - Add market index ETFs (category='market_index_etf')
   - Store in `stocks` table with category and market_cap

2. **Tier 3 Data Fetch**:
   - Fetch SPY, QQQ, IWM (benchmarks)
   - Fetch VIXY, UVXY (volatility)
   - Fetch sector ETFs (XLK, XLF, XLE, etc.)
   - Cache as pickled DataFrames in `tier3_cache`

3. **Market Data Update**:
   - Incremental fetch from yfinance for all symbols
   - Store in `market_data` table
   - 0.5s delay between requests (rate limiting)

4. **Pre-Filter Criteria**:
   - Market cap >= $2B (fetched from yfinance)
   - Price between $2-$3000 (from latest market data)
   - Average 20-day volume >= 100K
   - Result: ~1,800-2,000 qualifying stocks

5. **Tier 1 Pre-Calculation**:
   - Calculate universal metrics for qualifying stocks
   - Store in `tier1_cache` table
   - Fields: price, EMAs, ATR/ADR, returns, RS scores, 52-week metrics

**Output**: Cached Tier 1/3 data ready for screening

**Key Files**:
- `core/premarket_prep.py`: PreMarketPrep class
- `core/stock_universe.py`: StockUniverseManager class
- `data/db.py`: Database with tier1_cache, tier3_cache tables

---

### Phase 1: Market Sentiment (market_analyzer.py)

**Purpose**: Determine overall market sentiment and strategy allocation

**Process**:
1. Tavily API search for recent market news
2. Build prompt with news context
3. Call DashScope AI for sentiment analysis
4. Determine sentiment: `bullish` | `bearish` | `neutral`
5. AI-driven strategy allocation (determines slots per strategy)

**Output**: Market sentiment string + strategy allocation dict

**Key Files**:
- `core/market_analyzer.py`: MarketAnalyzer class

---

### Phase 2: Strategy Screening (screener.py)

**Purpose**: Apply 6 strategy plugins using cached Tier 1/3 data

**Strategies** (6 total):
| Strategy | Type | Dimensions | Description |
|----------|------|------------|-------------|
| MomentumBreakout | Long | PQ, BS, VC, TC | VCP platform + volume breakout |
| PullbackEntry | Long | TI, RC, VC, BONUS | EMA pullback with trend scoring |
| SupportBounce | Long | SQ, VD, RB | Support level false breakdown |
| RangeShort | Short | TQ, RL, VC | Range resistance short |
| DoubleTopBottom | Both | PL, TS, VC | Distribution top / accumulation bottom |
| CapitulationRebound | Long | MO, EX, VC | Capitulation bottom detection |

**Process**:
1. Load cached Tier 1 data from database
2. Load cached Tier 3 data (SPY, VIX, ETFs)
3. For each strategy:
   - Apply pre-filters using Tier 1 data (market cap, price, volume, EMAs)
   - For candidates passing filters:
     - Calculate lazy Tier 2 metrics (VCP, S/R, divergence)
     - Calculate dimensions using `calculate_dimensions()`
     - Score 0-15 points across 4 dimensions
     - Determine tier (S: 12+, A: 9+, B: 7+, C: <7)
4. Collect all StrategyMatch objects

**Output**: List of StrategyMatch objects with scores, entry/stop/target prices

**Key Files**:
- `core/screener.py`: StrategyScreener class
- `core/strategies/*.py`: Strategy plugins

---

### Phase 3: AI Analysis

**Purpose**: Select top 10 candidates and apply deep AI analysis

**Process**:

#### Step 3a: Candidate Selection (selector.py)
1. Sort all matches by score (descending)
2. Apply filters:
   - Skip Tier C (<7 points)
   - Skip recent failures
3. Return top 30 candidates

#### Step 3b: AI Confidence Scoring (ai_confidence_scorer.py)
1. Prepare batch of 30 candidates for AI analysis
2. Build prompt with technical snapshots
3. Call DashScope API
4. Parse JSON response for confidence scores (0-100)
5. Apply sector concentration penalty
6. Sort by final confidence score
7. Return top 10 ScoredCandidate objects

#### Step 3c: Deep Analysis (analyzer.py)
For each of the top 10 candidates:
1. Fetch recent news (Tavily API)
2. Build analysis prompt with technical data
3. Call DashScope AI for analysis
4. Extract structured fields (reasoning, catalyst, risks, position size)

**Output**: Top 10 opportunities with AI confidence scores and insights

**Key Files**:
- `core/selector.py`: CandidateSelector class
- `core/ai_confidence_scorer.py`: AIConfidenceScorer class
- `core/analyzer.py`: OpportunityAnalyzer class

---

### Phase 4: Report Generation (reporter.py)

**Purpose**: Generate final HTML report with charts

**Process**:
1. Generate Plotly K-line charts for top 10
2. Build HTML report with:
   - Header: Scan date/time, market sentiment
   - Market Overview: SPY trend, sector performance
   - Top 10 Opportunities with charts
   - Candidate Pool: All Tier A/S matches
   - Scan Statistics
3. Save to `web/reports/report_YYYY-MM-DD.html`
4. Cleanup old reports (keep 15 days)

**Output**: HTML report file path

**Key Files**:
- `core/reporter.py`: ReportGenerator class
- `web/reports/`: Output directory

---

### Phase 5: Push Notifications (notifier.py)

**Purpose**: Send notifications to WeChat and Discord

**Process**:
1. Build summary message with top opportunities
2. Send Discord webhook (rich embed)
3. Send WeChat webhook (markdown)

**Output**: Notification delivery status

**Key Files**:
- `core/notifier.py`: DiscordNotifier, WeChatNotifier, MultiNotifier classes

---

## Execution Schedule

### Manual Run
```bash
# Full 5-phase workflow (all >$2B market cap stocks)
python scheduler.py

# Test scan (uses provided symbols, skips universe sync)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Phase 0 only (universe sync + Tier 1/3 pre-calc)
python -c "from core.premarket_prep import PreMarketPrep; PreMarketPrep().run_phase0()"
```

### Automated Schedule
Recommended cron schedule (US market hours):
```
# Run at 3:00 AM ET (before market open)
0 3 * * 1-5 cd /path/to/trade-scanner && python scheduler.py >> /var/log/trade_scanner.log 2>&1
```

---

## Performance Metrics

| Phase | Duration | Key Activities |
|-------|----------|----------------|
| Phase 0 | ~15-20 min | Universe sync, Tier 1/3 pre-calc, market cap filter |
| Phase 1 | ~2-3 min | Market sentiment + allocation |
| Phase 2 | ~10-15 min | Strategy screening with cache |
| Phase 3 | ~15-20 min | AI scoring and deep analysis |
| Phase 4 | ~2-3 min | Report generation |
| Phase 5 | ~1 min | Push notifications |
| **Total** | **~45-60 min** | Complete workflow |

---

## Database Schema

### Core Tables
- `stocks` - symbol, name, sector, **category** (stocks/market_index_etf), **market_cap**, is_active
- `market_data` - OHLCV data by symbol/date
- `scan_results` - scan history
- `system_status` - last scan info

### Pre-calculation Tables
- `universe_sync` - sync history (date, added, removed, total)
- `tier1_cache` - universal metrics (symbol, price, EMAs, RS, etc.)
- `tier3_cache` - market data (SPY, VIX, ETFs as pickled DataFrames)
- `workflow_status` - 5-phase execution tracking with durations

---

## Output Artifacts

### Report File
- **Location**: `web/reports/report_YYYY-MM-DD.html`
- **Format**: Self-contained HTML with embedded charts
- **Retention**: 15 days (automatically cleaned up)

### Chart Files
- **Location**: `data/charts/YYYYMMDD/*.png`
- **Format**: Static PNG charts
- **Retention**: 15 days

### Database
- **Location**: `data/market_data.db`
- **Contents**: Historical price data, Tier 1/3 cache, scan logs, workflow status
- **Retention**: 280 trading days for price data, daily for cache

---

## Error Handling

| Failure Point | Handling |
|--------------|----------|
| CSV load fails | Check file exists at project root |
| Market cap fetch fails | Use existing market cap or include in pre-filter |
| Tier 1 calc fails | Skip symbol, continue with others |
| Tier 3 fetch fails | Use cached data if available |
| AI API timeout | Retry once, use fallback scoring |
| Chart generation fails | Skip chart, include text-only entry |
| HTML build fails | Generate fallback template with error info |
| No candidates | Generate "no opportunities" report |

---

## Configuration

Key settings in `config/settings.py`:
- `max_workers`: 2-4 for data fetching
- `batch_size`: 50 symbols
- `max_history_days`: 280 trading days
- `retention_days`: 15 days
- `ai.model`: qwen-max
- `ai.timeout`: 60 seconds

---

## Monitoring

Check scan status:
```bash
# View logs
tail -f logs/scanner.log

# Check if report generated
ls -la web/reports/report_$(date +%Y-%m-%d).html

# Check workflow status from database
sqlite3 data/market_data.db "SELECT * FROM workflow_status ORDER BY run_date DESC LIMIT 1;"

# Check server status (if running web server)
ss -tlnp | grep 19801
```
