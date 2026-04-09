# Daily Report Generation Workflow

**Version**: 6.0  
**Last Updated**: 2026-04

---

## Overview

The Trade Scanner runs daily at 3 AM ET to analyze US stocks (market cap ≥$2B) and generate an HTML report with top 30 opportunities (top 10 with deep analysis).

---

## 3-Tier Pre-Calculation Architecture

| Tier                       | What                                                                                                                                                                    | When                  | Stored        |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ------------- |
| Tier 1 (Universal)         | Price, Volume, EMAs (8/21/50/200), ATR/ADR, returns (3m/6m/12m/5d), RS scores, 52w metrics, accum_ratio_15d, days_to_earnings, earnings_date, gap_1d_pct, gap_direction | All symbols at 3 AM   | `tier1_cache` |
| Tier 2 (Strategy-specific) | VCP detection, S/R levels, RSI divergence, EMA slopes                                                                                                                   | Lazy during screening | Not cached    |
| Tier 3 (Market Data)       | SPY, QQQ, IWM, VIXY, UVXY, sector ETFs (pickled DataFrames)                                                                                                             | Once at 3 AM, shared  | `tier3_cache` |

---

## 6-Phase Pipeline

```
Phase 0: Data Prep (15-20 min)
├── Sync stock universe from CSV
├── Fetch Tier 3 market data
├── Update market data (yfinance, 0.5s delay)
├── Filter by market cap (≥$2B), price ($2-$3000), volume (≥100K)
└── Calculate Tier 1 metrics for ~1,800-2,000 qualifying stocks

Phase 1: AI Market Regime (3-5 min)
├── Load SPY, VIX from Tier 3
├── Tavily search (3 market news queries)
├── AI classifies regime (technical + news)
└── Get allocation from regime table (30 slots)

Phase 2: Strategy Screening (10-15 min)
├── Load cached Tier 1/3 data
├── Apply 8 strategies with regime-based allocation
├── Skip strategies with 0 slots
├── Handle duplicates (keep highest technical score)
├── Lazy Tier 2 calculations
├── Score 0-15 points, determine tiers (S:12+, A:9+, B:7+, C:<7)
└── Apply regime-adaptive position sizing

Phase 3: AI Confidence Scoring (15-20 min)
├── AI scores top 30 in batches
├── Apply tiered sector penalty (0%/-5%/-10%)
└── Return scored candidates

Phase 4: Deep Analysis (10-15 min)
├── Select top 10 by confidence
├── Tavily search per stock
├── AI deep analysis (technical + news)
└── Return enriched top 10

Phase 5: Report Generation (2-3 min)
├── Plotly charts for top 10
├── Build HTML (top 30 + deep analysis)
└── Save to web/reports/

Phase 6: Notifications (1 min)
├── Discord webhook (rich embed with AI regime info)
└── WeChat webhook
```

---

## Phase Details

### Phase 0: Data Preparation (premarket_prep.py)

**Outputs**: Cached Tier 1/3 data

**Key Steps**:

1. Load `nasdaq_stocklist_screener.csv` → `stocks` table (category='stocks' or 'market_index_etf')
2. Fetch market data from yfinance (incremental, rate-limited)
3. Pre-filter: market cap ≥$2B, price $2-$3000, avg vol ≥100K
4. Calculate Tier 1 metrics for qualifying stocks

### Phase 1: AI Market Regime (market_regime.py, market_analyzer.py)

**Outputs**: Regime string, allocation dict, AI confidence, reasoning

**Regime Table** (30 slots):

| Regime        | A   | B   | C   | D   | E   | F   | G   | H   |
| ------------- | --- | --- | --- | --- | --- | --- | --- | --- |
| bull_strong   | 8   | 6   | 4   | 0   | 0   | 0   | 8   | 4   |
| bull_moderate | 8   | 6   | 4   | 0   | 0   | 0   | 8   | 4   |
| neutral       | 6   | 5   | 5   | 4   | 4   | 0   | 3   | 3   |
| bear_moderate | 4   | 4   | 4   | 5   | 5   | 2   | 0   | 6   |
| bear_strong   | 0   | 0   | 4   | 6   | 6   | 8   | 0   | 6   |
| extreme_vix   | 0   | 0   | 0   | 3   | 3   | 12  | 0   | 12  |

**Validation**: VIX > 30 → force extreme_vix

### Phase 2: Strategy Screening (screener.py)

**Outputs**: Up to 30 StrategyMatch objects

**Strategies**:

| Letter | Name                 | Type  | Dimensions        |
| ------ | -------------------- | ----- | ----------------- |
| A      | MomentumBreakout     | Long  | TC, CQ, BS, VC    |
| B      | PullbackEntry        | Long  | TI, RC, VC, BONUS |
| C      | SupportBounce        | Long  | SQ, VD, RB        |
| D      | DistributionTop      | Short | TQ, RL, DS, VC    |
| E      | AccumulationBottom   | Long  | TQ, AL, AS, VC    |
| F      | CapitulationRebound  | Long  | MO, EX, VC        |
| G      | EarningsGap          | Both  | GS, QC, TC, VC    |
| H      | RelativeStrengthLong | Long  | RD, SH, CQ, VC    |

**Regime-Adaptive Position Sizing**:

| Regime        | Long | Short | Exemptions    |
| ------------- | ---- | ----- | ------------- |
| bull_strong   | 1.0× | 0.3×  | None          |
| bull_moderate | 1.0× | 0.3×  | None          |
| neutral       | 0.8× | 0.8×  | None          |
| bear_moderate | 0.5× | 1.0×  | None          |
| bear_strong   | 0.5× | 1.0×  | None          |
| extreme_vix   | 0.3× | 0.5×  | F, H get 1.0× |

### Phase 3: AI Confidence Scoring (ai_confidence_scorer.py, selector.py)

**Outputs**: Top 30 ScoredCandidate objects

**Sector Penalty**:

- Top per sector: 0%
- Second: -5%
- Third+: -10%

### Phase 4: Deep Analysis (analyzer.py)

**Outputs**: Top 10 with deep_analysis and news_summary attributes

**Process**: Tavily search → AI analysis → extract insights (technical outlook, sentiment, catalysts, risks)

### Phase 5: Report Generation (reporter.py)

**Outputs**: `web/reports/report_YYYY-MM-DD.html`

**Contents**: Header (regime, AI confidence), Market Overview, Allocation Table, Top 30 Table, Top 10 Deep Analysis, Charts

**Retention**: 15 days

### Phase 6: Notifications (notifier.py)

**Outputs**: Discord + WeChat webhooks with AI regime info

---

## Execution

### Manual

```bash
# Full workflow
python scheduler.py

# Test (specific symbols)
python scheduler.py --test --symbols AAPL,MSFT,NVDA

# Phase 0 only
python -c "from core.premarket_prep import PreMarketPrep; PreMarketPrep().run_phase0()"
```

### Automated

```
0 3 * * 1-5 cd /path && python scheduler.py >> /var/log/trade_scanner.log 2>&1
```

---

## Performance

| Phase     | Duration      |
| --------- | ------------- |
| Phase 0   | 15-20 min     |
| Phase 1   | 3-5 min       |
| Phase 2   | 10-15 min     |
| Phase 3   | 15-20 min     |
| Phase 4   | 10-15 min     |
| Phase 5   | 2-3 min       |
| Phase 6   | 1 min         |
| **Total** | **60-75 min** |

---

## Database Schema

**Core Tables**: `stocks`, `market_data`, `scan_results`, `system_status`

**Pre-calc Tables**: `universe_sync`, `tier1_cache`, `tier3_cache`, `workflow_status`

**Retention**: 280 trading days (price data), daily (cache)

---

## Error Handling

| Failure                | Handling                  |
| ---------------------- | ------------------------- |
| CSV load fails         | Check file exists         |
| Market cap fetch fails | Use existing or skip      |
| Tier 1 calc fails      | Skip symbol               |
| Regime detection fails | Default to 'neutral'      |
| AI timeout             | Retry once, use fallback  |
| Chart gen fails        | Text-only entry           |
| No candidates          | "No opportunities" report |

---

## Configuration (config/settings.py)

- `max_workers`: 2-4
- `batch_size`: 50
- `max_history_days`: 280
- `retention_days`: 15
- `ai.model`: qwen-max
- `ai.timeout`: 60s

---

## Monitoring

```bash
# View logs
tail -f logs/scanner.log

# Check report
ls -la web/reports/report_$(date +%Y-%m-%d).html

# Workflow status
sqlite3 data/market_data.db "SELECT * FROM workflow_status ORDER BY run_date DESC LIMIT 1;"

# Server status
ss -tlnp | grep 19801
```

---

## Output Artifacts

| Artifact    | Location                             | Retention |
| ----------- | ------------------------------------ | --------- |
| HTML Report | `web/reports/report_YYYY-MM-DD.html` | 15 days   |
| Charts      | `data/charts/YYYYMMDD/*.png`         | 15 days   |
| Database    | `data/market_data.db`                | 280 days  |
