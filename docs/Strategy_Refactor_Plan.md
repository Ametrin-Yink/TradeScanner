# Trade Scanner — Strategy Refactor Plan v7.0

**Version**: 7.0 (Refactor from v6.0)  
**Date**: 2026-04  
**Status**: Proposal

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Issue Index](#2-issue-index)
3. [Strategy-Level Changes](#3-strategy-level-changes)
   - [A: MomentumBreakout → Split into A1 + A2](#31-strategy-a-momentumbreakout--split-into-a1--a2-pre-breakout)
   - [B: PullbackEntry — Tighten BONUS](#32-strategy-b-pullbackentry--tighten-bonus)
   - [C: SupportBounce — Tighten Pre-filter & RB](#33-strategy-c-supportbounce--tighten-pre-filter--rb)
   - [D: DistributionTop — Add Liquidity Guard](#34-strategy-d-distributiontop--add-liquidity-guard)
   - [E: AccumulationBottom — Loosen Gates](#35-strategy-e-accumulationbottom--loosen-gates)
   - [F: CapitulationRebound — Loosen Pre-filter](#36-strategy-f-capitulationrebound--loosen-pre-filter)
   - [G: EarningsGap — Tighten Time Window](#37-strategy-g-earningsgap--tighten-time-window)
   - [H: RelativeStrengthLong — No Change](#38-strategy-h-relativestrengthlong--no-change)
4. [System-Level Changes](#4-system-level-changes)
   - [Scoring Normalization](#41-scoring-normalization)
   - [Sector Concentration Cap](#42-sector-concentration-cap-phase-2)
   - [Regime Detection Hardening](#43-regime-detection-hardening)
   - [AI Feedback Loop](#44-ai-confidence-feedback-loop)
   - [Stale Data Guard](#45-stale-data-guard-phase-0)
   - [Report Retention](#46-report-retention)
5. [Updated Allocation Table](#5-updated-allocation-table)
6. [Change Summary Matrix](#6-change-summary-matrix)
7. [Implementation Priority](#7-implementation-priority)

---

## 1. Executive Summary

This plan addresses **two categories** of issues found in v6.0:

**Category 1 — Strategy Calibration** (user-identified + analysis):
- Some strategies have criteria so tight they rarely fire (A's VC logic, F's pre-filter, E's combined gates)
- Some strategies are too loose and produce low-quality candidates (C's 2-touch pre-filter, B's BONUS)
- Strategy A detects confirmed breakouts only — no mechanism to capture **pre-breakout compression setups**

**Category 2 — System Architecture** (analysis-identified):
- Scoring tier thresholds are absolute numbers but max raw scores differ across strategies (H almost never reaches S-tier at 12/13; A reaches it at 71%)
- Sector penalty applied too late (Phase 3), after low-quality sector concentration already pollutes the top 30
- Regime detection is a single-point-of-failure with no hard-rule override layer
- No feedback loop to audit AI confidence scoring accuracy over time
- Phase 0 has no stale data guard — bad yfinance bars flow undetected
- Report retention (15 days) makes retrospective analysis impossible

**Net result**: 8 strategies remain. Strategy A gains an internal A2 sub-mode (pre-breakout). No new strategies are added.

---

## 2. Issue Index

| # | Category | Severity | Strategy / Component | Description |
|---|---|---|---|---|
| I-01 | Calibration | High | A | VC dimension penalizes active-base stocks; logic conflicts with breakout intent |
| I-02 | Calibration | High | A | BS requires confirmed breakout — no anticipatory pre-breakout capture |
| I-03 | Calibration | High | F | RSI<22 + EMA50−4×ATR + ≥2 gap-downs simultaneously is near-impossible |
| I-04 | Calibration | Medium | E | Market cap $3B + vol ≥200K + near 60d low too tight in bear regimes |
| I-05 | Calibration | Medium | C | 2-touch pre-filter too easy; 5d reclaim speed too generous; depth gate missing |
| I-06 | Calibration | Medium | B | BONUS rewards absence of weakness (no-gap-veto), not presence of quality |
| I-07 | Calibration | Medium | G | Day 4–5 candidates with small gaps compete equally against fresh day-1 gaps |
| I-08 | Calibration | Low | D | No dollar volume floor — illiquid stocks eligible for short |
| I-09 | Architecture | High | Scoring | Max raw scores differ per strategy; S-tier threshold hits at 71% for A/B but 92% for H |
| I-10 | Architecture | High | Phase 2/3 | Sector penalty fires in Phase 3 after concentration already pollutes top 30 |
| I-11 | Architecture | High | Phase 1 | Regime detection is one AI call with no hard-rule override layer |
| I-12 | Architecture | Medium | Phase 3 | No feedback loop — AI confidence scores never validated against outcomes |
| I-13 | Architecture | Medium | Phase 0 | No stale data guard; bad yfinance bars pass through all phases |
| I-14 | Architecture | Low | Phase 5 | 15-day report retention prevents any retrospective analysis |

---

## 3. Strategy-Level Changes

### 3.1 Strategy A: MomentumBreakout → Split into A1 + A2 (Pre-Breakout)

**Issues addressed**: I-01, I-02

#### Overview

Strategy A is internally split into two sub-modes that share the same slot budget and pre-filter. The regime engine fills A-slots first with A1 (confirmed breakout), then A2 (pre-breakout compression) if insufficient A1 candidates exist. From the allocation table's perspective, A is still one strategy with one slot count.

| | A1: BreakoutConfirmed (current) | A2: PreBreakout (new) |
|---|---|---|
| **Trigger** | Price > pivot, high volume today | Still inside base, within 3% of pivot |
| **BS dimension** | Breakout magnitude + volume surge | Replaced by CP (Compression Score) |
| **VC dimension** | Current table (dry-up before break) | Simplified dry-up-only table |
| **Expected tier** | S/A when strong | B typically (anticipatory discount) |
| **Regime suitability** | Bull/neutral | Bull/neutral/late-bear |

#### A2: Compression Score (CP) — Max 4.0

Replaces the BS dimension for A2 candidates. The VCP bonus from the current bonus pool (2.0 pts) is migrated here as the primary driver.

| Factor | Condition | Score |
|---|---|---|
| **Volume contraction** | Last 5d avg < 50% of 20d avg | 1.5 |
| | Last 5d avg 50–65% of 20d avg | 0.8 |
| | Last 5d avg 65–80% | 0.3 |
| | > 80% | 0 |
| **Range contraction** | Last 5d range < 50% of 20d ATR | 1.5 |
| | 50–70% | 0.8 |
| | 70–90% | 0.3 |
| | > 90% | 0 |
| **Wave count** | ≥ 3 contraction waves detected | +1.0 |
| **Pivot proximity** | Within 1.5% of pivot | Full score |
| | 1.5–3.0% | Interpolate to 0 |
| | > 3.0% | Reject A2 |

**CP = vol_contraction_score + range_contraction_score + wave_bonus (capped at 4.0)**

#### A2: VC Dimension (Simplified) — Max 4.0

| Factor | Condition | Score |
|---|---|---|
| **Base volume dry-up** | Last 5d avg / 20d avg < 50% | 3.0 |
| | 50–65% | 2.0 |
| | 65–80% | 1.0 |
| | > 80% | 0 |
| **CLV quality** | Last 5d average CLV ≥ 0.70 | +1.0 |
| | (closes near highs despite tight range) | |

#### A1 VC Fix

Remove the penalization of base vol ratio > 1.0 for A1 as well. The current table gives 0 for >1.0, which penalizes stocks that stayed active during base formation. For A1, any base volume ratio ≤ 1.0 should be neutral (0.2 minimum), not a disqualifier.

#### Bonus Pool Update

Remove VCP structure bonus (2.0 pts) — migrated into A2's CP dimension. Retain:

| Bonus | Max | Condition |
|---|---|---|
| Sector leadership | 0.5 | Sector ETF RS ≥ 80th AND > EMA50 |
| Earnings catalyst | 0.5 | 7–21 days to earnings |
| Accumulation divergence | 0.5 | OBV rising, price flat (linreg divergence) |

**New bonus max: 1.5 (from 3.0)**. This intentionally reduces A1's max raw to 16.5 (from 17), aligning better with the normalized scoring framework in Section 4.1.

---

### 3.2 Strategy B: PullbackEntry — Tighten BONUS

**Issue addressed**: I-06

The current BONUS awards +1.0 simply for the **absence** of a gap-down in the last 5 days. This rewards mediocrity and inflates B-tier setups into A-tier.

#### Change: Replace No-Gap-Down Veto with Momentum Persistence Bonus

| Factor | Score | Condition |
|---|---|---|
| Sector ETF > EMA21 + positive slope | 0–1.0 | Unchanged |
| **Momentum persistence** | 0–1.0 | Stock 5d return > SPY 5d return by > 2% |
| | 0.5 | Outperforms SPY by 1–2% |
| | 0 | At or below SPY 5d return |

**Rationale**: A pullback entry is only high-quality if the stock is pulling back *less* than the market. Outperforming SPY during a pullback is a direct quality signal; not having a gap-down is not.

---

### 3.3 Strategy C: SupportBounce — Tighten Pre-filter & RB

**Issue addressed**: I-05

#### Pre-filter Change

| Filter | v6.0 | v7.0 |
|---|---|---|
| Support touches | ≥ 2 in 60d | ≥ 3 in 60d **OR** ≥ 2 in 30d (recency matters more than count) |

#### RB (Rebound) Dimension Changes

**Depth gate**: Add hard gate — depth must be ≥ 2% to score at all. Currently depth < 2% can score up to 2.0 in the depth sub-dimension, which rewards stocks that barely touched support.

**Reclaim speed**: Remove 5-day score. A 5-day reclaim is a grind, not a bounce.

| Reclaim speed | v6.0 | v7.0 |
|---|---|---|
| 1d | 2.5 | 2.5 |
| 2d | 2.0 | 2.0 |
| 3d | 1.5 | 1.5 |
| 4d | 1.0 | 1.0 |
| 5d | 0.5 | **0 (removed)** |
| > 5d | 0 | 0 |

**Depth scoring update**:

| Depth | v6.0 | v7.0 |
|---|---|---|
| < 2% | 0.5–2.0 | **0 (hard gate)** |
| 2–4% | 2.0–2.5 | 2.0–2.5 (unchanged) |
| 4–7% | 1.5–2.5 | 1.5–2.5 (unchanged) |
| 7–10% | 0.5–1.5 | 0.5–1.5 (unchanged) |
| > 10% | 0 | 0 |

---

### 3.4 Strategy D: DistributionTop — Add Liquidity Guard

**Issue addressed**: I-08

The current pre-filter has no dollar volume floor, allowing illiquid $2B stocks with thin float to qualify for shorts. Long strategies E and F already have explicit dollar volume gates ($50M, $100M respectively).

#### New Pre-filter Entry

| Filter | Condition |
|---|---|
| Dollar volume | > $30M avg20d (**new**) |

This is intentionally lower than F ($50M) and G ($100M) because short entries on distribution patterns don't require the same intraday liquidity as gap or capitulation plays, but still need minimum tradability.

---

### 3.5 Strategy E: AccumulationBottom — Loosen Gates

**Issue addressed**: I-04

The combined gate of market cap ≥ $3B + volume ≥ 200K + near 60d low is extremely difficult to fill in bear regimes, resulting in 0–1 E-tier candidates even when the regime allocates 4–5 E-slots.

#### Pre-filter Changes

| Filter | v6.0 | v7.0 | Rationale |
|---|---|---|---|
| Market cap | ≥ $3B | ≥ **$2.5B** | Modest reduction; still filters micro-cap junk |
| Avg 20d volume | ≥ 200K | ≥ **150K** | Bear markets compress volume market-wide; 200K is too exclusive |
| Near 60d low | Within 8% | Within **10%** | Accumulation often starts before the final low |

---

### 3.6 Strategy F: CapitulationRebound — Loosen Pre-filter

**Issue addressed**: I-03

The triple requirement of RSI < 22 + price < EMA50 − 4×ATR + ≥ 2 gap-downs in 5 days simultaneously is extremely rare. F has been a near-ghost slot in all but the most extreme crashes.

#### Pre-filter Changes

| Filter | v6.0 | v7.0 | Rationale |
|---|---|---|---|
| RSI | < 22 | < **25** | RSI 22–25 setups are still deeply oversold and valid |
| Price vs EMA50 | < EMA50 − 4×ATR | < EMA50 − **3×ATR** | 4×ATR extension barely exists outside flash crashes |
| Gap-downs | ≥ 2 in last 5d | ≥ 2 in 5d **OR** ≥ 5 consecutive down-days | Sustained selling without gaps is equally exhaustive |

The OR condition on gap-downs is important: a stock can capitulate through continuous grinding down-days without intraday gaps. Both patterns signal selling exhaustion.

**Scoring note**: The EX dimension still rewards the 4×ATR+ cases at maximum scores. Loosening the *gate* does not change the *reward* for extreme extensions.

---

### 3.7 Strategy G: EarningsGap — Tighten Time Window

**Issue addressed**: I-07

G currently accepts days 1–5 post-earnings. The QC dimension already penalizes day 5+ heavily (score drops to 0.5), but stale day-4/5 candidates still compete for slots against fresh day-1 setups.

#### New Eligibility Rules by Gap Size

| Gap Size | Max Days Eligible | Rationale |
|---|---|---|
| ≥ 10% | 1–5 (unchanged) | Large gaps hold their zone longer |
| 7–10% | 1–**3** | Medium gaps lose thesis by day 4 |
| 5–7% | 1–**2** | Small gaps degrade quickly |

This is implemented as a hard eligibility gate in Phase 0 Tier 1 filtering, not a scoring adjustment, so stale small-gap candidates never enter the screening pool.

---

### 3.8 Strategy H: RelativeStrengthLong — No Change

H is well-calibrated. The near-S-tier-impossibility (12/13 = 92%) is addressed by the scoring normalization in Section 4.1, not by changing H's dimensions.

---

## 4. System-Level Changes

### 4.1 Scoring Normalization

**Issue addressed**: I-09

#### Problem

Max raw scores differ across strategies, causing the absolute tier threshold (S≥12) to be structurally easier for some strategies than others:

| Strategy | Max Raw | Points to S-tier | % of max |
|---|---|---|---|
| A (v6.0) | 17 | 12 | 71% |
| B | 17 | 12 | 71% |
| C | 15 | 12 | 80% |
| D | 15 | 12 | 80% |
| E | 15 | 12 | 80% |
| F | 15 | 12 | 80% |
| G | 15 | 12 | 80% |
| H | 13 | 12 | **92%** |

#### Solution: Normalized Scoring

Convert raw scores to a normalized 0–15 scale before applying tier thresholds:

```python
def normalize_score(raw_score, strategy_max):
    return (raw_score / strategy_max) * 15.0

# Tier thresholds apply to normalized score (unchanged values, now consistent)
# S: >= 12  (80% of max)
# A: >= 9   (60% of max)
# B: >= 7   (47% of max)
# C: < 7
```

This means every strategy reaches S-tier at 80% quality, A-tier at 60%, and B-tier at 47% — strategy-agnostic.

#### Updated Max Raw Scores (v7.0)

| Strategy | Dimensions | v6.0 Max | v7.0 Max | Change |
|---|---|---|---|---|
| A1 | TC(5)+CQ(4)+BS(4)+VC(4)+Bonus(1.5) | 17.0 | **18.5** | Bonus pool reduced to 1.5 |
| A2 | TC(5)+CQ(4)+CP(4)+VC(4)+Bonus(1.5) | — | **18.5** | New sub-mode |
| B | TI(5)+RC(5)+VC(5)+BONUS(2) | 17.0 | **17.0** | Unchanged |
| C | SQ(4)+VD(5)+RB(6) | 15.0 | **15.0** | Unchanged |
| D | TQ(4)+RL(4)+DS(4)+VC(3) | 15.0 | **15.0** | Unchanged |
| E | TQ(4)+AL(4)+AS(4)+VC(3) | 15.0 | **15.0** | Unchanged |
| F | MO(5)+EX(6)+VC(4) | 15.0 | **15.0** | Unchanged |
| G | GS(5)+QC(4)+TC(3)+VC(3) | 15.0 | **15.0** | Unchanged |
| H | RD(4)+SH(4)+CQ(3)+VC(2) | 13.0 | **13.0** | Normalized, not changed |

---

### 4.2 Sector Concentration Cap (Phase 2)

**Issue addressed**: I-10

#### Problem

Sector penalty (0%/−5%/−10%) fires in Phase 3 after AI scoring, meaning 6–8 tech stocks can pollute the top 30 before any correction. The penalty then distorts AI confidence on valid setups just because the sector ran hot that day.

#### Solution: Soft Sector Cap in Phase 2

During duplicate resolution in Phase 2, apply a **soft cap of 4 candidates per sector** before writing to the top-30 output. The cap is soft because:
- Candidates beyond the 4-slot cap are not discarded — they are flagged `sector_overflow=True`
- If total candidates < 30 after applying caps, overflow candidates fill remaining slots in ranked order
- The Phase 3 penalty still applies on top of this for fine-tuning

```python
# Phase 2 duplicate resolution (after strategy scoring, before Phase 3)
SECTOR_SOFT_CAP = 4

sector_counts = defaultdict(int)
primary_candidates = []
overflow_candidates = []

for candidate in sorted_candidates:  # sorted by technical score desc
    if sector_counts[candidate.sector] < SECTOR_SOFT_CAP:
        primary_candidates.append(candidate)
        sector_counts[candidate.sector] += 1
    else:
        candidate.sector_overflow = True
        overflow_candidates.append(candidate)

# Fill to 30
final_candidates = primary_candidates
remaining_slots = 30 - len(primary_candidates)
if remaining_slots > 0:
    final_candidates += overflow_candidates[:remaining_slots]
```

---

### 4.3 Regime Detection Hardening

**Issue addressed**: I-11

#### Problem

Phase 1 produces a single regime string from one AI call. A misclassification cascades through all downstream phases. The only existing hard rule is VIX > 30 → force `extreme_vix`.

#### Solution: Extend the Hard Rule Override Layer

Add technical hard rules that override the AI *before* the allocation table is consulted. These are based on objective, pre-calculated Tier 1/3 data:

```python
def apply_regime_overrides(ai_regime, tier3_data):
    spy = tier3_data['SPY']
    iwm = tier3_data['IWM']
    vix = tier3_data['VIX']['close'][-1]

    # Existing rule
    if vix > 30:
        return 'extreme_vix'

    # New rules — floor the regime, never elevate it
    spy_below_ema50 = spy['close'][-1] < spy['ema50'][-1]
    iwm_below_ema200 = iwm['close'][-1] < iwm['ema200'][-1]
    spy_below_ema200 = spy['close'][-1] < spy['ema200'][-1]

    if spy_below_ema200 and iwm_below_ema200:
        # Floor: at minimum bear_moderate
        if ai_regime in ('bull_strong', 'bull_moderate', 'neutral'):
            return 'bear_moderate'

    if spy_below_ema50 and iwm_below_ema200:
        # Floor: at minimum neutral
        if ai_regime in ('bull_strong', 'bull_moderate'):
            return 'neutral'

    return ai_regime  # AI regime stands if no override triggered
```

#### Regime Confidence Blending

When the AI returns a confidence score < 70%, blend allocations between the AI regime and the adjacent safer regime (50/50):

```python
if regime_confidence < 0.70:
    adjacent = get_adjacent_regime(regime, direction='safer')
    allocation = blend_allocations(regime_allocation, adjacent_allocation, ratio=0.5)
```

The "safer" adjacent regime is always the more defensive one (e.g., `bull_strong` → `bull_moderate`, `neutral` → `bear_moderate`).

---

### 4.4 AI Confidence Feedback Loop

**Issue addressed**: I-12

#### Problem

Phase 3 AI scores candidates with no mechanism to validate those scores over time. There is no way to know if AI is systematically overconfident on certain strategy/regime combinations.

#### Solution: Outcome Tracking Table

Add a `ai_confidence_outcomes` table to the database:

```sql
CREATE TABLE ai_confidence_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    regime TEXT NOT NULL,
    ai_confidence REAL NOT NULL,
    normalized_score REAL NOT NULL,
    tier TEXT NOT NULL,
    outcome_5d_return REAL,        -- populated +5 trading days later
    outcome_10d_return REAL,       -- populated +10 trading days later
    outcome_hit_target BOOLEAN,    -- 1 if hit 2R+ target
    outcome_hit_stop BOOLEAN,      -- 1 if stopped out
    populated_date DATE
);
```

**Back-fill job**: Add a nightly task (runs before Phase 0) that fills `outcome_*` fields for records where `scan_date` is 5 or 10 trading days ago and `outcome_5d_return` is still NULL.

**Quarterly audit query**:
```sql
SELECT strategy, regime,
       ROUND(AVG(ai_confidence), 2) as avg_confidence,
       ROUND(AVG(outcome_5d_return), 3) as avg_5d_return,
       ROUND(AVG(CASE WHEN outcome_hit_target THEN 1 ELSE 0 END), 2) as hit_rate
FROM ai_confidence_outcomes
WHERE populated_date IS NOT NULL
GROUP BY strategy, regime
ORDER BY strategy, regime;
```

This enables quarterly recalibration of AI prompts based on which strategy/regime combos are being over- or under-scored.

---

### 4.5 Stale Data Guard (Phase 0)

**Issue addressed**: I-13

#### Problem

Phase 0 calculates Tier 1 metrics at 3 AM from yfinance data. Partial bars, halted stocks, and data vendor glitches can produce stale or incorrect `close` values that flow through all 6 phases undetected.

#### Solution: Post-Tier-1 Staleness Check

After Tier 1 calculation, before any symbol enters the screening pool, validate:

```python
def is_stale(symbol_data, today):
    last_bar_date = symbol_data['date'][-1]
    trading_days_since = count_trading_days(last_bar_date, today)

    # Flag if last bar is more than 1 trading day old
    if trading_days_since > 1:
        return True, f"Last bar {last_bar_date} is {trading_days_since} trading days old"

    # Flag if today's volume is exactly 0 (incomplete bar)
    if symbol_data['volume'][-1] == 0:
        return True, "Zero volume on latest bar"

    # Flag if OHLC values are identical (corrupted bar)
    last = symbol_data
    if last['open'][-1] == last['high'][-1] == last['low'][-1] == last['close'][-1]:
        return True, "OHLC values identical — likely corrupted bar"

    return False, None
```

Stale symbols are logged to `system_status` with reason and excluded from Phase 2 screening. They are not retried within the same run (to avoid delaying the 3 AM pipeline) but are logged for manual review.

---

### 4.6 Report Retention

**Issue addressed**: I-14

#### Change

| Setting | v6.0 | v7.0 |
|---|---|---|
| `retention_days` (HTML reports) | 15 | **60** |

**Rationale**: 60 days covers one quarter of trading. HTML report files are small (< 2MB each). At 60 days × ~22 trading days/month × 2 months = ~44 files, storage impact is negligible. This enables basic retrospective analysis: which regimes produced which strategy distributions, and whether the AI confidence tier rankings held up over a 1–4 week horizon.

---

## 5. Updated Allocation Table

A keeps its slot count. Internal split between A1/A2 is handled by the screener (A1 preferred, A2 fills remaining A-slots). One allocation change: A gains 2 slots in `bear_strong` (capturing late-bear compression setups), offset by reducing H from 6 → 4.

| Regime | A (A1+A2) | B | C | D | E | F | G | H | Total |
|---|---|---|---|---|---|---|---|---|---|
| bull_strong | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| bull_moderate | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| neutral | 6 | 5 | 5 | 4 | 4 | 0 | 3 | 3 | 30 |
| bear_moderate | 4 | 4 | 4 | 5 | 5 | 2 | 0 | 6 | 30 |
| bear_strong | **2** | 0 | 4 | 6 | 6 | 8 | 0 | **4** | 30 |
| extreme_vix | 0 | 0 | 0 | 3 | 3 | 12 | 0 | 12 | 30 |

> **bear_strong change**: A 0→2 (late-bear compression setups), H 6→4. All other rows unchanged.

---

## 6. Change Summary Matrix

| Issue | Component | Type | Change | Effort |
|---|---|---|---|---|
| I-01 | Strategy A — VC | Calibration | Remove >1.0 penalty; separate A2 VC table | Low |
| I-02 | Strategy A — BS | Calibration | Add A2 sub-mode with CP dimension | Medium |
| I-03 | Strategy F — Pre-filter | Calibration | RSI <22→<25; distance 4×→3×ATR; gap-down OR streak | Low |
| I-04 | Strategy E — Pre-filter | Calibration | Market cap $3B→$2.5B; vol 200K→150K; proximity 8→10% | Low |
| I-05 | Strategy C — Pre-filter & RB | Calibration | 2→3 touches; remove 5d reclaim; depth hard gate ≥2% | Low |
| I-06 | Strategy B — BONUS | Calibration | Replace no-gap-veto with momentum persistence vs SPY | Low |
| I-07 | Strategy G — Eligibility | Calibration | Tighten days-eligible by gap size (2d/3d/5d) | Low |
| I-08 | Strategy D — Pre-filter | Calibration | Add dollar volume > $30M gate | Low |
| I-09 | Scoring system | Architecture | Normalize all scores to 0–15 before tier thresholds | Medium |
| I-10 | Phase 2 screener | Architecture | Soft sector cap of 4 per sector before Phase 3 | Medium |
| I-11 | Phase 1 regime | Architecture | Hard rule override layer + confidence blending | Medium |
| I-12 | Phase 3 / DB | Architecture | Add outcome tracking table + back-fill job | High |
| I-13 | Phase 0 | Architecture | Stale data guard post-Tier-1 | Low |
| I-14 | Phase 5 | Architecture | Report retention 15→60 days | Trivial |

---

## 7. Implementation Priority

### Sprint 1 — Quick Wins (Low effort, high impact)

1. **I-14**: Report retention 15→60 days — one config line change
2. **I-13**: Stale data guard in Phase 0 — ~30 lines of Python
3. **I-03**: Strategy F pre-filter loosening — change 3 threshold values
4. **I-04**: Strategy E pre-filter loosening — change 3 threshold values
5. **I-05**: Strategy C tightening — 2 pre-filter changes + RB table edit
6. **I-06**: Strategy B BONUS replacement — rewrite BONUS logic
7. **I-07**: Strategy G eligibility tightening — add gap-size gate in Phase 0
8. **I-08**: Strategy D dollar volume gate — add one pre-filter line

### Sprint 2 — Medium Effort, Structural

9. **I-09**: Score normalization — add `normalize_score()` wrapper, verify tier counts are not dramatically disrupted by backtesting on historical scan results
10. **I-10**: Phase 2 sector cap — add soft-cap logic to duplicate resolution
11. **I-11**: Regime hard overrides — add override function + confidence blending

### Sprint 3 — High Effort, Long-term

12. **I-01 + I-02**: Strategy A split into A1/A2 — new CP dimension, separate VC tables, A2 screener path, allocation logic
13. **I-12**: AI feedback loop — new DB table, back-fill job, quarterly audit query

> **Note on Sprint 3**: The A1/A2 split is the most impactful change but also the most code-touching. Do Sprint 1 and 2 first, run the system for 2–4 weeks, then implement A2 so you have a baseline to compare against.

---

*End of Strategy Refactor Plan v7.0*
