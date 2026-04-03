# Daily Report Generation Workflow

This document describes the complete 6-phase workflow for generating daily trading opportunity reports.

**Version**: 6.0  
**Last Updated**: 2026-04-04

---

## Overview

The Trade Scanner runs daily at 3 AM ET to analyze US stocks with market cap >=$2B and generate an HTML report with the top 30 trading opportunities (top 10 with deep analysis).

## What's New in v6.0

- **AI-Powered Regime Detection**: Phase 1 now uses Tavily + AI to classify market regime
- **30 Slot Screening**: Expanded from 10 to 30 candidates with duplicate handling
- **Tiered Sector Penalty**: Top stock = 0%, 2nd = -5%, 3rd+ = -10%
- **Deep Analysis Phase**: Phase 4 dedicated to Tavily + AI deep analysis for top 10
- **6-Phase Workflow**: Added dedicated Phase 4 for deep analysis

---

## 3-Tier Pre-Calculation Architecture

**Tier 1 (Universal Metrics)**: Calculated for ALL symbols at 3 AM
- Price, Volume, EMAs (8/21/50/200), ATR/ADR
- Returns (3m/6m/12m/5d), RS scores, 52-week metrics
- **NEW v5.0**: accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction
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

---

## 6-Phase Pipeline Architecture

```
Phase 0: Data Preparation (15-20 min)
├── Sync stock universe from CSV
├── Fetch Tier 3 market data (SPY, VIX, ETFs)
├── Fetch market data for all symbols
├── Update market cap from yfinance
├── Filter stocks by market cap (>=$2B)
└── Calculate Tier 1 universal metrics for qualifying stocks

Phase 1: AI Market Regime Detection (3-5 min) [NEW]
├── Load SPY and VIX from Tier 3 cache
├── Search Tavily for market news
├── AI classifies regime from technical + news data
└── Get allocation from regime table

Phase 2: Strategy Screening (10-15 min)
├── Load cached Tier 1/3 data
├── Apply 8 strategy plugins with regime-based slot allocation
├── Skip strategies with 0 slots for current regime
├── Handle duplicates (keep highest technical score per symbol)
├── Lazy Tier 2 calculations for candidates
└── Score 0-15 points across 4 dimensions, determine tiers

Phase 3: AI Confidence Scoring (15-20 min)
├── AI scores top 30 candidates in batches
├── Apply tiered sector penalty (0%/-5%/-10%)
└── Return scored candidates

Phase 4: Deep Analysis (10-15 min) [NEW]
├── Select top 10 by AI confidence
├── Tavily search for each stock's news
├── AI deep analysis with technical + news context
└── Return enriched top 10

Phase 5: Report Generation (2-3 min)
├── Generate Plotly charts for top 10
├── Build HTML report (top 30 + deep analysis for top 10)
└── Save to web/reports/

Phase 6: Push Notifications (1 min)
├── Send Discord webhook with AI regime info
└── Send WeChat webhook
```

---

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

5. **Tier 1 Pre-Calculation** (v5.0 enhanced):
   - Calculate universal metrics for qualifying stocks
   - Store in `tier1_cache` table
   - Fields: price, EMAs, ATR/ADR, returns, RS scores, 52-week metrics
   - **NEW**: accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction

**Output**: Cached Tier 1/3 data ready for screening

**Key Files**:
- `core/premarket_prep.py`: PreMarketPrep class
- `core/stock_universe.py`: StockUniverseManager class
- `data/db.py`: Database with tier1_cache, tier3_cache tables

---

### Phase 1: AI Market Regime Detection (core/market_regime.py, core/market_analyzer.py)

**Purpose**: Determine market regime using AI analysis of technical data + Tavily news

**Process**:
1. Load SPY and VIX data from Tier 3 cache
2. Calculate technical context (SPY above EMA200, EMA50 trend)
3. **Search Tavily** for market news (3 queries)
4. **Call AI** to classify regime from technical + news data
5. AI returns one of 6 regimes with confidence and reasoning
6. Validate: VIX > 30 always overrides to extreme_vix
7. Get allocation from `REGIME_ALLOCATION_TABLE`

**Phase 1 Allocation Table** (30 total slots):

| Strategy | A | B | C | D | E | F | G | H |
|----------|---|---|---|---|---|---|---|---|
| **bull_strong** | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 |
| **bull_moderate** | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 |
| **neutral** | 6 | 5 | 5 | 4 | 4 | 0 | 3 | 3 |
| **bear_moderate** | 4 | 4 | 4 | 5 | 5 | 2 | 0 | 6 |
| **bear_strong** | 0 | 0 | 4 | 6 | 6 | 8 | 0 | 6 |
| **extreme_vix** | 0 | 0 | 0 | 3 | 3 | 12 | 0 | 12 |

**Output**: Market regime string + strategy allocation dict + AI confidence + AI reasoning

**Key Files**:
- `core/market_regime.py`: MarketRegimeDetector class with `detect_regime_ai()`
- `core/market_analyzer.py`: MarketAnalyzer class with `analyze_for_regime()`

---

### Phase 2: Strategy Screening (screener.py)

**Purpose**: Apply 8 strategy plugins using cached Tier 1/3 data with regime-based allocation (30 slots)

**Strategies** (8 total, A-H):

| Letter | Strategy | Type | Dimensions | Description |
|--------|----------|------|------------|-------------|
| A | MomentumBreakout | Long | TC, CQ, BS, VC | Multi-pattern momentum |
| B | PullbackEntry | Long | TI, RC, VC, BONUS | EMA pullback with trend |
| C | SupportBounce | Long | SQ, VD, RB | False breakdown reclaim |
| D | DistributionTop | Short | TQ, RL, DS, VC | Distribution tops |
| E | AccumulationBottom | Long | TQ, AL, AS, VC | Accumulation bottoms |
| F | CapitulationRebound | Long | MO, EX, VC | Capitulation detection |
| G | EarningsGap | Both | GS, QC, TC, VC | Post-earnings gaps |
| H | RelativeStrengthLong | Long | RD, SH, CQ, VC | RS leaders in bears |

**Process**:
1. Load cached Tier 1 data from database
2. Load cached Tier 3 data (SPY, VIX, ETFs)
3. Get regime allocation from Phase 1 (30 total slots)
4. **Skip strategies with 0 slots** for current regime
5. For each active strategy:
   - Apply pre-filters using Tier 1 data
   - **Diagnostic logging**: Log filter decisions (PASS/REJ per symbol)
   - For candidates passing filters:
     - Calculate lazy Tier 2 metrics (VCP, S/R, divergence)
     - Calculate dimensions using `calculate_dimensions()`
     - Score 0-15 points across 4 dimensions
     - Determine tier (S: 12+, A: 9+, B: 7+, C: <7)
6. Select candidates per strategy from allocation table
7. **Handle duplicates**: Keep highest technical score per symbol
8. Return up to 30 unique candidates
9. Apply regime-adaptive position sizing

**Regime-Adaptive Position Sizing**:

| Regime | Long Scalar | Short Scalar | Notes |
|--------|-------------|--------------|-------|
| bull_strong | 1.0× | 0.3× | Full size longs |
| bull_moderate | 1.0× | 0.3× | Full size longs |
| neutral | 0.8× | 0.8× | Reduced both sides |
| bear_moderate | 0.5× | 1.0× | Reduced longs, full shorts |
| bear_strong | 0.5× | 1.0× | Reduced longs, full shorts |
| extreme_vix | 0.3× | 0.5× | F and H exempt (full size) |

**Output**: List of StrategyMatch objects with regime-adaptive position sizes

**Key Files**:
- `core/screener.py`: StrategyScreener class
- `core/strategies/*.py`: Strategy plugins (8 files)

---

### Phase 3: AI Confidence Scoring (selector.py, ai_confidence_scorer.py)

**Purpose**: AI-score top 30 candidates with tiered sector penalty

**Process**:

#### Step 3a: AI Scoring (ai_confidence_scorer.py)
1. Prepare batch of up to 30 candidates for AI analysis
2. Build prompt with technical snapshots and regime context
3. Call DashScope API
4. Parse JSON response for confidence scores (0-100)
5. Return ScoredCandidate objects

#### Step 3b: Sector Penalty (ai_confidence_scorer.py)
**NEW Tiered Penalty**:
- Highest confidence per sector: **0%** (no penalty)
- Second highest: **-5%**
- Third and beyond: **-10%**

Example: 3 Tech stocks with confidence 85, 80, 75
- AAPL (85): stays 85 (top, no penalty)
- MSFT (80): becomes 76 (-5%)
- GOOGL (75): becomes 67.5 → 68 (-10%)

#### Step 3c: Selection (selector.py)
1. Sort by adjusted confidence
2. Return top 30 ScoredCandidate objects

**Output**: Top 30 scored opportunities with sector-adjusted confidence

**Key Files**:
- `core/selector.py`: CandidateSelector with `select_top_30()`
- `core/ai_confidence_scorer.py`: AIConfidenceScorer with `_apply_sector_penalties()`

---

### Phase 4: Deep Analysis (analyzer.py)

**Purpose**: Tavily + AI deep analysis for top 10 candidates

**Process**:

#### Step 4a: Select Top 10
1. Take top 10 from Phase 3 by AI confidence score

#### Step 4b: Tavily Search (per stock)
For each of the top 10:
1. Search Tavily for stock-specific news
2. Queries: "{SYMBOL} stock news today analysis", "{SYMBOL} earnings outlook forecast"
3. Compile news summary

#### Step 4c: AI Deep Analysis (parallel)
For each candidate with news data:
1. Build detailed analysis prompt with:
   - Technical snapshot (entry, stop, target)
   - Market regime context
   - Tavily news summary
2. Call DashScope AI for deep analysis
3. Extract insights:
   - Technical outlook
   - News sentiment
   - Key catalysts
   - Risk level
4. Enrich candidate with deep_analysis and news_summary attributes

**Output**: Top 10 opportunities with detailed AI + Tavily analysis

**Key Files**:
- `core/analyzer.py`: OpportunityAnalyzer with `analyze_top_10_deep()`

---

### Phase 5: Report Generation (reporter.py)

**Purpose**: Generate final HTML report with top 30 and deep analysis for top 10

**Process**:
1. Generate Plotly K-line charts for top 10
2. Build HTML report with:
   - Header: Scan date/time, market regime, AI confidence
   - Market Overview: SPY trend, VIX level, AI regime reasoning
   - Phase 1 Allocation: Slots per strategy for detected regime
   - Top 30 Opportunities table (all scored candidates)
   - Top 10 Deep Analysis with:
     - Charts and position sizes
     - Tavily news summary
     - AI deep analysis (technical outlook, sentiment, catalysts, risks)
   - Candidate Pool: All Tier A/S matches
   - Scan Statistics
3. Save to `web/reports/report_YYYY-MM-DD.html`
4. Cleanup old reports (keep 15 days)

**Output**: HTML report file path

**Key Files**:
- `core/reporter.py`: ReportGenerator class
- `web/reports/`: Output directory

---

### Phase 6: Push Notifications (notifier.py)

**Purpose**: Send notifications to WeChat and Discord

**Process**:
1. Build summary message with top opportunities
2. Include detected regime and AI confidence in header
3. Include AI reasoning summary
4. Send Discord webhook (rich embed)
5. Send WeChat webhook (markdown)

**Output**: Notification delivery status

**Key Files**:
- `core/notifier.py`: DiscordNotifier, WeChatNotifier, MultiNotifier classes

---

## Execution Schedule

### Manual Run
```bash
# Full 6-phase workflow (all >$2B market cap stocks)
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
| Phase 1 | ~3-5 min | Tavily search + AI regime detection |
| Phase 2 | ~10-15 min | Strategy screening with 30 slots, duplicate handling |
| Phase 3 | ~15-20 min | AI scoring 30 candidates, sector penalty |
| Phase 4 | ~10-15 min | Tavily + AI deep analysis for top 10 |
| Phase 5 | ~2-3 min | Report generation (top 30 + deep analysis) |
| Phase 6 | ~1 min | Push notifications with AI info |
| **Total** | **~60-75 min** | Complete 6-phase workflow |

---

## Database Schema

### Core Tables
- `stocks` - symbol, name, sector, **category** (stocks/market_index_etf), **market_cap**, is_active
- `market_data` - OHLCV data by symbol/date
- `scan_results` - scan history
- `system_status` - last scan info

### Pre-calculation Tables
- `universe_sync` - sync history (date, added, removed, total)
- `tier1_cache` - universal metrics (symbol, price, EMAs, RS, etc.) + **v5.0 columns** (accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction, spy_regime)
- `tier3_cache` - market data (SPY, VIX, ETFs as pickled DataFrames)
- `workflow_status` - **6-phase** execution tracking with durations

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
| Regime detection fails | Default to 'neutral' regime |
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

# Check current regime (from Tier 1 cache)
sqlite3 data/market_data.db "SELECT spy_regime FROM tier1_cache WHERE symbol='SPY' ORDER BY date DESC LIMIT 1;"
```

---

## Migration Notes (v5.0 → v6.0)

### Workflow Changes
- **Phase 1**: Now uses Tavily + AI for regime detection (was deterministic technical)
- **Phase 2**: Now screens 30 slots with duplicate handling (was 10 slots)
- **NEW Phase 4**: Dedicated deep analysis phase with Tavily + AI for top 10
- **Phase 5**: Report now includes top 30 table + deep analysis for top 10
- **Phase 6**: Notifications include AI regime confidence and reasoning

### Sector Penalty Changes
- **Old**: -5% per duplicate beyond 2
- **New**: Top = 0%, 2nd = -5%, 3rd+ = -10%

### API Usage Changes
- **Tavily**: Now called in Phase 1 (market news) AND Phase 4 (per-stock news)
- **DashScope AI**: Now called in Phase 1 (regime), Phase 3 (scoring), Phase 4 (deep analysis)

---

## Migration Notes (v4.0 → v5.0)

### Database Migration
Run Tier 1 migration on existing database:
```python
from data.db import Database
db = Database()
db.migrate_tier1_cache_v5()
```

### Strategy Changes
- **Removed**: RangeShort, DoubleTopBottom (logic moved to D and E)
- **New**: DistributionTop (D), AccumulationBottom (E), EarningsGap (G), RelativeStrengthLong (H)
- **Modified**: MomentumBreakout (A), SupportBounce (C), CapitulationRebound (F)
- **Unchanged**: PullbackEntry (B)

### Workflow Changes
- Phase 1 now uses regime detection (no Tavily/DashScope calls)
- Allocation is deterministic from regime table
- Position sizes scale with regime
- Strategies with 0 slots are skipped entirely
