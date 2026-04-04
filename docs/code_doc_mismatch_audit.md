# Code vs Documentation Mismatch Audit

**Generated**: 2026-04-04
**Document Version**: Strategy_Description_v5.md
**Code Version**: v6.0 (current codebase)

---

## Executive Summary

| Metric | Count |
|--------|-------|
| Total strategies audited | 8 |
| Total mismatches found | 15+ |
| Critical mismatches | 5 |
| Medium mismatches | 6 |
| Low mismatches | 8 |

**Key Finding**: Strategy A (MomentumBreakout) and Strategy H (RelativeStrengthLong) have the most significant mismatches, with multiple dimension scoring caps incorrectly implemented. Strategy G (EarningsGap) also has a moderate mismatch.

---

## Global/Tier 1 Pre-Filter Mismatches

| Filter | Document | Code | Status | Impact |
|--------|----------|------|--------|--------|
| Market Cap | ≥ $2B | ≥ $2B | ✅ Match | None |
| Price Range | $2-$3000 | $2-$3000 | ✅ Match | None |
| Avg Volume | ≥ 100K | ≥ 100K | ✅ Match | None |
| Category | stocks, ETFs | stocks, ETFs | ✅ Match | None |

**Note**: Strategy-specific pre-filters documented in v5.md are checked below per-strategy.

---

## Tier 2 Pre-Calculation Mismatches

| Metric | Document | Code Location | Status |
|--------|----------|---------------|--------|
| RS Percentile | 63d vs SPY weighted | `premarket_prep.py` | ✅ Match |
| EMAs (8/21/50/200) | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| ADR/ATR | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| 52-week metrics | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| Accumulation ratio 15d | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| Days to earnings | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| Gap 1d % | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| SPY regime | Cached in tier1_cache | `premarket_prep.py` | ✅ Match |
| Tier 3 market data | Cached in tier3_cache | `premarket_prep.py` | ✅ Match |

---

## Strategy A: MomentumBreakout

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Location | Severity |
|--------|-----------|------------|----------|----------|
| RS percentile (hard gate) | ≥ 50th | ≥ 50th | `filter()` line 56 | ✅ Match |
| Price > EMA200 | Required | **NOT CHECKED** | filter() | **Medium** |
| 3-month return ≥ -20% | Required | **NOT CHECKED** | filter() | Low |
| Market cap | ≥ $2B | Assumed pre-filtered | N/A | ✅ Match |
| Avg 20d volume ≥ 100K | Required | **NOT CHECKED** | filter() | Low |
| ADR ≥ 1.5% | Required | ✅ 1.5% | filter() line 76 | ✅ Match |
| EMA50 slope | "Not required" | **Uptrend required** | filter() line 87 | **Stricter** |
| Distance from 52w high | <15% (scoring) | **<10% (filter)** | filter() line 96 | **Stricter** |
| $50M dollar volume | Not mentioned | **Required** | filter() line 71 | **Extra** |

### Dimension Scoring Mismatches

#### TC Dimension (Trend Context)

| Component | Doc Score | Code Score | Doc Threshold | Code Threshold | Severity |
|-----------|-----------|------------|---------------|----------------|----------|
| Max Score | 5.0 | 5.0 | N/A | N/A | ✅ Match |
| RS Strength | 0-2.0 (percentile-based) | 0-1.0 (return-based) | See table below | Different | **Medium** |
| EMA Structure | 0-2.0 (3 conditions) | **0-2.0 (proximity-based)** | See below | Distance % | **Different** |
| 52w High Proximity | 0-1.0 | **0-2.0** | ≤5%=1.0, 5-15%=linear | ≤3%=2.0, 3-5%=linear | **Mismatch** |
| CLV Bonus | **Not in TC** | 0-1.0 | N/A | >0.85=1.0 | **Extra** |

**RS Strength - Documentation** (percentile-based):
| RS Percentile | Score |
|---------------|-------|
| ≥ 90th | 2.0 |
| 75th–90th | 1.5–2.0 |
| 60th–75th | 1.0–1.5 |
| 50th–60th | 0.5–1.0 |
| < 50th | 0 → hard reject |

**RS Strength - Code** (return-based, lines 465-494):
| RS 3m/6m/12m weighted | Bonus |
|-----------------------|-------|
| > 0.50 | 1.0 |
| 0.30-0.50 | 0.5-1.0 |
| < 0.30 | 0-0.5 |

#### CQ Dimension (Consolidation Quality) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **4.0** | **5.0** | **Critical** |
| Duration quality | 0-1.0 pts (documented) | **NOT IMPLEMENTED** | Medium |
| Pattern scoring | Quality × 3.0 | Base scores (4.5, 4.0, 3.5, etc.) | Different |

**Pattern Detection Comparison:**

| Pattern | Doc Quality Range | Code Base Score |
|---------|-------------------|-----------------|
| VCP | 0.80-1.00 | 4.0 |
| HTF | 0.61-0.72 | 4.5 |
| Flat base | 0.55-0.75 | 3.5 |
| Ascending base | 0.62 | 3.0 |
| Loose base | 0.15-0.40 | 0.5-2.5 |

#### BS Dimension (Breakout Strength) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **4.0** | **5.0** | **Critical** |

**Breakout % Scoring:**
| Breakout % | Doc Score | Code Score |
|------------|-----------|------------|
| ≥ 5% | 2.5 | >4% = 3.0 |
| 3-5% | 2.0-2.5 | N/A (2-4% interpolated) |
| 2-3% | 1.5-2.0 | 2-4% interpolated |
| 1-2% | 0.5-1.5 | <2% scaled |
| < 1% | 0-0.5 | N/A |

**Energy Ratio Scoring:**
| Energy Ratio | Doc Score | Code Score |
|--------------|-----------|------------|
| ≥ 3.0× | 1.5 | >2.0 = 2.0 |
| 2.0-3.0× | 1.0-1.5 | 1.0-2.0 interpolated |
| 1.5-2.0× | 0.5-1.0 | 0-1.0 interpolated |
| 1.0-1.5× | 0-0.5 | N/A |
| < 1.0× | 0 | N/A |

#### VC Dimension (Volume Confirmation) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **4.0** | **5.0** | **Critical** |
| CLV component | **0-0.5 in VC** | **NOT IN VC** (moved to TC) | **Wrong** |

**Volume Contraction:**
| Base Vol Ratio | Doc Score | Code Score |
|----------------|-----------|------------|
| < 0.50 | 2.0 | <0.50 = 2.0 ✅ |
| 0.50-0.65 | 1.5-2.0 | 0.50-0.70 interpolated |
| 0.65-0.80 | 0.8-1.5 | 0.70-0.90 interpolated |
| 0.80-1.00 | 0.2-0.8 | N/A |
| > 1.00 | 0 | >0.70 = linear decline |

**Breakout Volume:**
| Volume Ratio | Doc Score | Code Score |
|--------------|-----------|------------|
| ≥ 3.0× | 1.5 | >3.0 = 3.0 |
| 2.0-3.0× | 1.0-1.5 | 2.0-3.0 interpolated |
| 1.5-2.0× | 0.5-1.0 | <2.0 = scaled |
| < 1.5× | 0-0.5 | N/A |

### Bonus Pool Mismatches

| Bonus Type | Doc Max | Code Max | Implemented? |
|------------|---------|----------|--------------|
| VCP structure | 2.0 (vol_contraction + range_contraction + wave_count) | 1.0 (pattern score only) | ⚠️ Partial |
| Sector leadership | 0.5 (ETF RS ≥ 80th AND > EMA50) | **NOT IMPLEMENTED** | ❌ No |
| Earnings catalyst | 0.5 (7-21 days to earnings) | **NOT IMPLEMENTED** | ❌ No |
| Accumulation divergence | 0.5 (OBV rising while price flat) | **NOT IMPLEMENTED** | ❌ No |
| Multi-timeframe alignment | **Not in docs** | 0.25 (price > EMA20 > EMA50) | **Extra** |

### Entry/Exit Mismatches

| Rule | Document | Code | Severity |
|------|----------|------|----------|
| Stop loss logic | Pattern-specific (vcp/flat/ascending: 0.98, htf: 0.985, loose: -1.5 ATR) | **All patterns: 0.98** | Medium |
| Stop floor | entry × 0.92 max 8% | **NOT IMPLEMENTED** | Medium |
| Target | 3R baseline, 4R for S-tier | **Fixed 3R only** | Low |

### Strategy A Summary
- Critical issues: 3 (CQ, BS, VC max scores wrong)
- Medium issues: 5 (RS scoring different, EMA structure different, stop loss simplified, CLV wrong dimension, missing price>EMA200)
- Low issues: 3 (bonus pool incomplete, 3m return filter missing, volume filter missing)

---

## Strategy B: PullbackEntry

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| EMA21 slope positive | Required | Required | ✅ Match |
| Price > EMA21 | Required | Required | ✅ Match |
| Price > EMA200 | Required | **Not checked** | Low |
| ADR ≥ 1.2% | Required | **Not checked** | Low |
| Volume ≥ 100K | Required | Assumed pre-filtered | ✅ Match |

### Dimension Scoring Mismatches

| Dimension | Doc Max | Code Max | Severity |
|-----------|---------|----------|----------|
| TI (Trend Intensity) | 5.0 | 5.0 | ✅ Match |
| RC (Risk Context) | 5.0 | 5.0 | ✅ Match |
| VC (Volume Confirmation) | 5.0 | 5.0 | ✅ Match |
| BONUS | 2.0 | 2.0 | ✅ Match |

**Status**: All dimensions match documentation.

### Strategy B Summary
- Critical issues: 0
- Medium issues: 0
- Low issues: 2 (missing price>EMA200, missing ADR check)

---

## Strategy C: SupportBounce

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| Price vs EMA50 | Within 15% | **Not checked** | Low |
| False breakdown | Required | Required | ✅ Match |
| Support touches | ≥ 2 | ≥ 2 | ✅ Match |
| ADR ≥ 1.5% | Required | **Not checked** | Low |

### Dimension Scoring Mismatches

| Dimension | Doc Max | Code Max | Severity |
|-----------|---------|----------|----------|
| SQ (Setup Quality) | 4.0 | 4.0 | ✅ Match |
| VD (Volume Dynamics) | 5.0 | 5.0 | ✅ Match |
| RB (Reclaim Strength) | 6.0 | 6.0 | ✅ Match |

**Status**: All dimensions match documentation.

### Strategy C Summary
- Critical issues: 0
- Medium issues: 0
- Low issues: 2 (EMA50 proximity not filtered, ADR not checked)

---

## Strategy D: DistributionTop

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| Price vs EMA50 | ≤ EMA50 × 1.05 | ≤ EMA50 × 1.05 | ✅ Match |
| EMA alignment | EMA8 ≤ EMA21 × 1.02 | EMA8 ≤ EMA21 × 1.02 | ✅ Match |
| Near 60d high | Within 8% | Within 8% | ✅ Match |
| Distribution evidence | Required | Required | ✅ Match |
| Volume ≥ 150K | Required | Assumed pre-filtered | ✅ Match |

### Dimension Scoring Mismatches

| Dimension | Doc Max | Code Max | Severity |
|-----------|---------|----------|----------|
| TQ (Trend Quality) | 4.0 | 4.0 | ✅ Match |
| RL (Resistance Level) | 4.0 | 4.0 | ✅ Match |
| DS (Distribution Strength) | 4.0 | 4.0 | ✅ Match |
| VC (Volume Confirmation) | 3.0 | 3.0 | ✅ Match |

**Status**: All dimensions match documentation.

### Strategy D Summary
- Critical issues: 0
- Medium issues: 0
- Low issues: 0

---

## Strategy E: AccumulationBottom

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| Near 60d low | Within 8% | Within 8% | ✅ Match |
| Volume ≥ 200K | Required | **100K** | Medium |
| Market cap | ≥ $3B | **$2B** | Medium |
| Listed age | > 180 days | **≥ 60 days** | Medium |
| ADR ≥ 1.5% | Required | **Not checked** | Low |

### Dimension Scoring Mismatches

| Dimension | Doc Max | Code Max | Severity |
|-----------|---------|----------|----------|
| TQ (Trend Quality) | 4.0 | 4.0 | ✅ Match |
| AL (Accumulation Level) | 4.0 | 4.0 | ✅ Match |
| AS (Accumulation Strength) | 4.0 | 4.0 | ✅ Match |
| VC (Volume Confirmation) | 3.0 | 3.0 | ✅ Match |

**Status**: All dimensions match documentation.

### Strategy E Summary
- Critical issues: 0
- Medium issues: 3 (stricter requirements not implemented)
- Low issues: 1 (ADR not checked)

---

## Strategy F: CapitulationRebound

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| RSI | < 22 | < 22 | ✅ Match |
| Price vs EMA50 | < EMA50 - 4×ATR | **< EMA50 - 5×ATR** | Low |
| Gaps in 5 days | ≥ 2 | ≥ 2 | ✅ Match |
| Dollar volume | > $50M | > $50M | ✅ Match |
| VIX | 15-35 | 15-35 | ✅ Match |
| Extreme VIX | Exempt from position reduction | **Exempt** | ✅ Match |

### Dimension Scoring Mismatches

| Dimension | Doc Max | Code Max | Severity |
|-----------|---------|----------|----------|
| MO (Momentum Oversold) | 5.0 | 5.0 | ✅ Match |
| EX (Exhaustion Evidence) | 6.0 | 6.0 | ✅ Match |
| VC (Volume Climax) | 4.0 | 4.0 | ✅ Match |

**Status**: All dimensions match documentation.

### Strategy F Summary
- Critical issues: 0
- Medium issues: 0
- Low issues: 1 (ATR multiplier 5× vs 4×)

---

## Strategy G: EarningsGap

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| Earnings gap | ≥ 5% | ≥ 5% | ✅ Match |
| Days since earnings | 1-5 trading days | 1-5 trading days | ✅ Match |
| Dollar volume | > $100M | > $100M | ✅ Match |
| Market cap | ≥ $2B | ≥ $2B | ✅ Match |
| Price | > $10 | **> $2** | Medium |

### Dimension Scoring Mismatches

#### TC Dimension - MEDIUM

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **3.0** | **4.0** | Medium |

Other dimensions:
| Dimension | Doc Max | Code Max | Status |
|-----------|---------|----------|--------|
| GS (Gap Strength) | 5.0 | 5.0 | ✅ Match |
| QC (Quality Confirmation) | 4.0 | 4.0 | ✅ Match |
| VC (Volume Confirmation) | 3.0 | 3.0 | ✅ Match |

### Strategy G Summary
- Critical issues: 0
- Medium issues: 2 (TC max score wrong, price filter too loose)
- Low issues: 0

---

## Strategy H: RelativeStrengthLong

### Pre-Filtering Mismatches

| Filter | Doc Value | Code Value | Severity |
|--------|-----------|------------|----------|
| RS percentile | ≥ 80th | ≥ 80th | ✅ Match |
| SPY regime | Bear/neutral only | Bear/neutral only | ✅ Match |
| Price vs 52w high | Within 15% | Within 15% | ✅ Match |
| Price > EMA200 | Required | **Not checked** | Low |
| Market cap | ≥ $3B | **$2B** | Medium |
| Volume ≥ 200K | Required | ≥ 200K | ✅ Match |

### Dimension Scoring Mismatches - MULTIPLE CRITICAL

#### RD Dimension (Relative Divergence) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **6.0** | **4.0** | **Critical** |

**Documentation breakdown** (6.0 max):
- RS Divergence: 0-2.0
- Sector Divergence: 0-2.0
- Market Structure: 0-2.0

**Code**: max_score=4.0 (incorrectly capped)

#### SH Dimension (Sector Health)

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | 4.0 | 4.0 | ✅ Match |

#### CQ Dimension (Consolidation Quality) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **3.0** | **4.0** | **Critical** |

#### VC Dimension (Volume Confirmation) - CRITICAL

| Component | Doc Value | Code Value | Severity |
|-----------|-----------|------------|----------|
| Max Score | **2.0** | **3.0** | **Critical** |

### Strategy H Summary
- Critical issues: 3 (RD, CQ, VC dimension max scores wrong)
- Medium issues: 1 (market cap requirement)
- Low issues: 1 (EMA200 filter missing)

---

## Summary Table: All Mismatches by Strategy

| Strategy | Critical | Medium | Low | Total |
|----------|----------|--------|-----|-------|
| A: MomentumBreakout | 3 | 5 | 3 | 11 |
| B: PullbackEntry | 0 | 0 | 2 | 2 |
| C: SupportBounce | 0 | 0 | 2 | 2 |
| D: DistributionTop | 0 | 0 | 0 | 0 |
| E: AccumulationBottom | 0 | 3 | 1 | 4 |
| F: CapitulationRebound | 0 | 0 | 1 | 1 |
| G: EarningsGap | 0 | 2 | 0 | 2 |
| H: RelativeStrengthLong | 3 | 1 | 1 | 5 |
| **TOTAL** | **6** | **11** | **10** | **27** |

---

## Recommendations by Priority

### Critical (Must Fix - Changes Strategy Behavior)

1. **Strategy A**: Change dimension max scores from 5.0 to documented values:
   - CQ: 4.0 (currently 5.0)
   - BS: 4.0 (currently 5.0)
   - VC: 4.0 (currently 5.0)

2. **Strategy H**: Fix all dimension max scores:
   - RD: 6.0 (currently 4.0)
   - CQ: 3.0 (currently 4.0)
   - VC: 2.0 (currently 3.0)

3. **Strategy G**: Fix TC dimension max score from 4.0 to 3.0

### Medium (Should Fix - Significant Behavior Difference)

1. **Strategy A**:
   - Implement complete bonus pool (sector leadership, earnings catalyst, accumulation divergence)
   - Fix CLV location (should be in VC, not TC)
   - Add Price > EMA200 pre-filter
   - Implement pattern-specific stop losses
   - Add 8% stop floor

2. **Strategy E**:
   - Change market cap from $2B to $3B
   - Change volume from 100K to 200K
   - Change listed age from 60 to 180 days

3. **Strategy H**:
   - Change market cap from $2B to $3B

4. **Strategy G**:
   - Change price filter from $2 to $10

5. **Strategy A**:
   - Align RS scoring with documentation (percentile-based vs return-based)
   - Align EMA structure scoring with docs

### Low (Nice to Have - Minor Differences)

1. **Strategy A**: Add 3-month return ≥ -20% filter, add 20d volume check
2. **Strategy B**: Add Price > EMA200, add ADR ≥ 1.2% checks
3. **Strategy C**: Add Price vs EMA50 within 15%, add ADR check
4. **Strategy E**: Add ADR check
5. **Strategy F**: Change ATR multiplier from 5× to 4×
6. **Strategy H**: Add Price > EMA200 check

---

## Appendix: Dimension Max Score Comparison

| Strategy | Dim 1 | Doc | Code | Dim 2 | Doc | Code | Dim 3 | Doc | Code | Dim 4 | Doc | Code |
|----------|-------|-----|------|-------|-----|------|-------|-----|------|-------|-----|------|
| A | TC | 5.0 | 5.0 ✅ | CQ | 4.0 | 5.0 ❌ | BS | 4.0 | 5.0 ❌ | VC | 4.0 | 5.0 ❌ |
| B | TI | 5.0 | 5.0 ✅ | RC | 5.0 | 5.0 ✅ | VC | 5.0 | 5.0 ✅ | - | - | - |
| C | SQ | 4.0 | 4.0 ✅ | VD | 5.0 | 5.0 ✅ | RB | 6.0 | 6.0 ✅ | - | - | - |
| D | TQ | 4.0 | 4.0 ✅ | RL | 4.0 | 4.0 ✅ | DS | 4.0 | 4.0 ✅ | VC | 3.0 | 3.0 ✅ |
| E | TQ | 4.0 | 4.0 ✅ | AL | 4.0 | 4.0 ✅ | AS | 4.0 | 4.0 ✅ | VC | 3.0 | 3.0 ✅ |
| F | MO | 5.0 | 5.0 ✅ | EX | 6.0 | 6.0 ✅ | VC | 4.0 | 4.0 ✅ | - | - | - |
| G | TC | 3.0 | 4.0 ❌ | GS | 5.0 | 5.0 ✅ | QC | 4.0 | 4.0 ✅ | VC | 3.0 | 3.0 ✅ |
| H | RD | 6.0 | 4.0 ❌ | SH | 4.0 | 4.0 ✅ | CQ | 3.0 | 4.0 ❌ | VC | 2.0 | 3.0 ❌ |

**Legend**: ✅ = Match, ❌ = Mismatch

---

*End of Audit Report*
