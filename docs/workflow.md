# Daily Report Generation Workflow

This document describes the complete workflow for generating daily trading opportunity reports.

## Overview

The Trade Scanner runs daily to analyze all US stocks with market cap >$2B and generate an HTML report with the top 10 trading opportunities. The process involves data fetching, strategy screening, market analysis, AI scoring, and report generation.

## Pipeline Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Fetcher   │───▶│  Screener   │───▶│   Market    │───▶│   AI Score  │───▶│   Report    │
│  (>2B mcap) │    │ (6 strategies)│   │  Analyzer   │    │  (Top 10)   │    │  (HTML)     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │                  │
       ▼                  ▼                  ▼                  ▼                  ▼
   yfinance API    Strategy plugins    SPY trend/sector   DashScope AI     plotly charts
   SQLite cache     15-point scoring    Market sentiment   Sector penalty   HTML template
```

## Detailed Workflow

### Phase 1: Data Fetching (fetcher.py)

**Purpose**: Fetch daily OHLCV data for all symbols (market cap >$2B)

**Process**:
1. Load symbol list from database (market cap >$2B)
2. Process in batches of 50 symbols (memory optimization)
3. For each symbol:
   - Check SQLite cache for existing data
   - Fetch only new data from yfinance (incremental update)
   - Store 150 trading days of history
   - 0.5s delay between requests (rate limiting)

**Output**: Cached DataFrames for all symbols (~20-25 min cached, ~70-80 min first run)

**Key Files**:
- `core/fetcher.py`: DataFetcher class
- `data/stocks.db`: SQLite cache

---

### Phase 2: Strategy Screening (screener.py)

**Purpose**: Apply 6 strategy plugins to find matching stocks

**Strategies** (6 total):
| Strategy | Type | Description |
|----------|------|-------------|
| MomentumBreakout | Long | VCP + momentum with RS bonus |
| PullbackEntry | Long | EMA pullback with RC scoring |
| SupportBounce | Long | Upthrust & rebound |
| RangeShort | Short | Range breakdown |
| DoubleTopBottom | Both | Distribution/accumulation with stricter short confirmation |
| CapitulationRebound | Long | Capitulation reversal with volume climax |

**Process**:
1. Initialize all 6 strategy plugins
2. For each strategy:
   - Apply pre-filters (volume, ATR, proximity to levels)
   - Run `filter()` method for detailed checks
   - Calculate dimensions using `calculate_dimensions()`
   - Score 0-15 points across 4 dimensions
   - Determine tier (S: 12+, A: 9+, B: 7+, C: <7)
3. Collect all StrategyMatch objects

**Output**: List of StrategyMatch objects with scores, entry/stop/target prices

**Key Files**:
- `core/screener.py`: StrategyScreener class
- `core/strategies/*.py`: Strategy plugins

---

### Phase 3: Market Analysis (market_analyzer.py)

**Purpose**: Determine overall market sentiment and SPY trend

**Process**:
1. Fetch SPY data
2. Calculate:
   - SPY position vs EMA20/EMA50
   - VIX level (if available)
   - Sector performance (top 3, bottom 3)
3. Determine sentiment: `strong_bullish` | `bullish` | `neutral` | `bearish` | `strong_bearish`

**Output**: Market sentiment string + sentiment reasoning

**Key Files**:
- `core/market_analyzer.py`: MarketAnalyzer class

---

### Phase 4: Candidate Selection & AI Scoring (selector.py, ai_confidence_scorer.py)

**Purpose**: Select top 30 candidates and apply AI confidence scoring

**Process**:

#### Step 4a: Initial Selection (selector.py)
1. Sort all matches by score (descending)
2. Apply filters:
   - Skip Tier C (<7 points)
   - Skip if SPY in strong opposite trend
   - Skip recent failures
3. Return top 30 candidates

#### Step 4b: AI Confidence Scoring (ai_confidence_scorer.py)
1. Prepare batch of 30 candidates for AI analysis
2. Build prompt with:
   - Candidate technical snapshots
   - Market sentiment context
   - Scoring criteria (setup quality, trend alignment, R:R, volume)
3. Call DashScope API (qwen-max model)
4. Parse JSON response for confidence scores (0-100)
5. **Apply sector concentration penalty**:
   - 1-2 stocks per sector: 0% penalty
   - 3 stocks: -5% penalty
   - 4 stocks: -10% penalty
   - 5+ stocks: -15% penalty
6. Sort by final confidence score
7. Return top 10 ScoredCandidate objects

**Output**: Top 10 opportunities with AI confidence scores

**Key Files**:
- `core/selector.py`: CandidateSelector class
- `core/ai_confidence_scorer.py`: AIConfidenceScorer class

---

### Phase 5: Deep Analysis (analyzer.py)

**Purpose**: Generate AI insights for each top opportunity

**Process**:
For each of the top 10 candidates:
1. Fetch recent news (Tavily API)
2. Build analysis prompt with:
   - Technical data (price, EMAs, volume)
   - Strategy match details
   - Market sentiment
   - Recent news
3. Call DashScope AI for analysis
4. Extract structured fields:
   - `ai_reasoning`: Why this setup works
   - `catalyst`: Near-term catalyst
   - `risk_factors`: Key risks
   - `position_size`: small/normal/large
   - `time_frame`: short-term/swing/long-term
   - `alternative_scenario`: What could go wrong

**Output**: List of AnalyzedOpportunity objects with AI insights

**Key Files**:
- `core/analyzer.py`: OpportunityAnalyzer class

---

### Phase 6: Report Generation (reporter.py)

**Purpose**: Generate final HTML report with charts

**Process**:
1. Generate Plotly K-line charts for top 10:
   - 3-month daily candles
   - Entry/stop/target levels
   - EMA lines
   - Volume bars
2. Build HTML report with:
   - Header: Scan date/time, market sentiment
   - Market Overview: SPY trend, sector performance
   - Top 10 Opportunities:
     - Symbol & strategy
     - Entry/Stop/Target prices
     - R:R ratio
     - AI confidence score
     - AI reasoning
     - Risk factors
     - K-line chart
   - Candidate Pool: All Tier A/S matches
   - Scan Statistics: Success/failure counts
3. Save to `reports/report_YYYY-MM-DD.html`
4. Cleanup old reports (keep 15 days)

**Output**: HTML report file path

**Key Files**:
- `core/reporter.py`: ReportGenerator class
- `core/plotly_charts.py`: Chart generation
- `reports/`: Output directory

---

## Execution Schedule

### Manual Run
```bash
# Full scan (all >$2B market cap stocks)
python scheduler.py

# Test scan (3 stocks only)
python scheduler.py --test --symbols AAPL,MSFT,NVDA
```

### Automated Schedule
Recommended cron schedule (US market hours):
```
# Run at 6:00 PM ET (after market close)
0 18 * * 1-5 cd /path/to/trade-scanner && python scheduler.py
```

---

## Performance Metrics

| Phase | Time (Cached) | Time (First Run) |
|-------|---------------|------------------|
| Data Fetching | ~5 min | ~60 min |
| Strategy Screening | ~5 min | ~5 min |
| Market Analysis | ~1 min | ~1 min |
| AI Scoring | ~3 min | ~3 min |
| Deep Analysis | ~5 min | ~5 min |
| Report Generation | ~2 min | ~2 min |
| **Total** | **~20-25 min** | **~70-80 min** |

---

## Output Artifacts

### Report File
- **Location**: `reports/report_YYYY-MM-DD.html`
- **Format**: Self-contained HTML with embedded charts
- **Retention**: 15 days (automatically cleaned up)

### Chart Files
- **Location**: `reports/charts/YYYYMMDD/*.png`
- **Format**: Static PNG charts
- **Retention**: 15 days

### Database
- **Location**: `data/stocks.db`
- **Contents**: Historical price data, scan logs, failure tracking
- **Retention**: 150 trading days

---

## Error Handling

| Failure Point | Handling |
|--------------|----------|
| Data fetch fails | Log failure, continue with other symbols |
| AI API timeout | Retry once, use fallback scoring |
| Chart generation fails | Skip chart, include text-only entry |
| HTML build fails | Generate fallback template with error info |
| No candidates | Generate "no opportunities" report |

---

## Configuration

Key settings in `config/settings.py`:
- `max_workers`: 1 (memory optimization)
- `batch_size`: 50 symbols
- `max_history_days`: 150 trading days
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
ls -la reports/report_$(date +%Y-%m-%d).html

# Check server status (if running web server)
ss -tlnp | grep 19801
```
