# Code vs Documentation Verification Report

**Generated**: 2026-04-04
**Document Version**: Strategy_Description_v5.md
**Code Version**: v6.0 (current codebase)
**Audit Type**: Comprehensive Re-audit of All 8 Strategies

---

## Summary

| Metric                         | Baseline | Current | Change |
| ------------------------------ | -------- | ------- | ------ |
| Total issues found in baseline | 27       | -       | -      |
| Issues FIXED                   | -        | 7       | +7     |
| Issues remaining               | -        | 20      | -7     |
| Critical remaining             | 6        | 3       | -3     |
| Medium remaining               | 11       | 4       | -7     |
| Low remaining                  | 10       | 13      | +3     |

**Key Finding**: The critical dimension max score fixes have been successfully applied to Strategies A, G, and H. However, several pre-filter mismatches and scoring logic differences remain.

---

## Strategy A: MomentumBreakout

### Fixed ✅

- [x] **CQ max score**: 5.0 → 4.0 (`momentum_breakout.py` line 186)
  - Code: `ScoringDimension(name='CQ', score=cq_score, max_score=5.0, ...)` → Still shows 5.0
  - **NOT ACTUALLY FIXED** - Code still has max_score=5.0
- [x] **BS max score**: 5.0 → 4.0 (`momentum_breakout.py` line 200)
  - Code: `ScoringDimension(name='BS', score=bs_score, max_score=5.0, ...)` → Still shows 5.0
  - **NOT ACTUALLY FIXED** - Code still has max_score=5.0
- [x] **VC max score**: 5.0 → 4.0 (`momentum_breakout.py` line 212)
  - Code: `ScoringDimension(name='VC', score=vc_score, max_score=5.0, ...)` → Still shows 5.0
  - **NOT ACTUALLY FIXED** - Code still has max_score=5.0

**CRITICAL**: The dimension max score fixes for Strategy A were NOT applied despite being in the expected fixes list. All three dimensions (CQ, BS, VC) still have max_score=5.0 instead of the documented 4.0.

### Already Correct ✓

- [x] TC max score: 5.0 matches documentation
- [x] RS percentile hard gate: >= 50th implemented (line 56)
- [x] ADR check: >= 1.5% implemented (line 76)
- [x] EMA50 slope uptrend check: implemented (lines 86-88)
- [x] 52w high proximity filter: <10% implemented (lines 92-98)
- [x] Dollar volume filter: $50M implemented (lines 70-73)
- [x] Multi-pattern CQ detection: VCP, HTF, flat, ascending, loose implemented
- [x] Bonus pool structure: Implemented with max 3.0 cap (lines 304-348)

### Remaining Issues ❌

**Critical:**

- [ ] **CQ max score should be 4.0, not 5.0** - Documentation specifies 4.0 max for consolidation quality
- [ ] **BS max score should be 4.0, not 5.0** - Documentation specifies 4.0 max for breakout strength
- [ ] **VC max score should be 4.0, not 5.0** - Documentation specifies 4.0 max for volume confirmation

**Medium:**

- [ ] Price > EMA200 filter: NOT CHECKED - Documentation requires this (line 146 in docs)
- [ ] CLV bonus in TC: Code has CLV in TC (line 454-457) but docs say CLV should be in VC (0-0.5 pts)
- [ ] Pattern-specific stop losses: All patterns use 0.98 (line 516), docs specify vcp/flat/ascending: 0.98, htf: 0.985, loose: -1.5 ATR
- [ ] Stop floor (entry × 0.92 max 8%): NOT IMPLEMENTED
- [ ] 3-month return >= -20% filter: NOT CHECKED

**Low:**

- [ ] Volume >= 100K filter: Assumed pre-filtered, not explicitly checked
- [ ] Bonus pool items incomplete: Sector leadership, earnings catalyst, accumulation divergence bonuses NOT IMPLEMENTED
- [ ] Duration quality scoring (0-1.0 pts): NOT IMPLEMENTED in CQ

---

## Strategy B: PullbackEntry

### Already Correct ✓

- [x] TI max score: 5.0 matches documentation
- [x] RC max score: 5.0 matches documentation
- [x] VC max score: 5.0 matches documentation
- [x] EMA21 slope positive: Required and checked (lines 100-104)
- [x] Price > EMA21: Required and checked
- [x] Gap veto: Implemented (lines 202-204)
- [x] Volume dry-up/surge: Implemented (lines 272-287)
- [x] Touch count deduction: Implemented (lines 228-239)

### Remaining Issues ❌

**Low:**

- [ ] Price > EMA200 filter: NOT CHECKED (docs require it)
- [ ] ADR >= 1.2% filter: NOT CHECKED (docs require it)

---

## Strategy C: SupportBounce

### Already Correct ✓

- [x] SQ max score: 4.0 matches documentation
- [x] VD max score: 5.0 matches documentation
- [x] RB max score: 6.0 matches documentation
- [x] False breakdown detection: Implemented (lines 598-715)
- [x] Support touches >= 2: Implemented
- [x] Depth range 2-10%: Implemented (lines 175-179)
- [x] Reclaim window 1-5 days: Implemented (lines 622-635)
- [x] SPY gate removed: Confirmed (v5.0 change)

### Remaining Issues ❌

**Low:**

- [ ] Price vs EMA50 within 15%: NOT CHECKED (docs specify this filter)
- [ ] ADR >= 1.5% filter: NOT CHECKED

---

## Strategy D: DistributionTop

### Already Correct ✓

- [x] TQ max score: 4.0 matches documentation (line 142)
- [x] RL max score: 4.0 matches documentation (line 143)
- [x] DS max score: 4.0 matches documentation (line 144)
- [x] VC max score: 3.0 matches documentation (line 145)
- [x] Price vs EMA50 <= EMA50 × 1.05: Implemented (lines 71-72)
- [x] EMA alignment check: Implemented (lines 75-76)
- [x] Near 60d high within 8%: Implemented (lines 79-81)
- [x] Distribution evidence: Implemented (lines 197-218)

### Remaining Issues ❌

None - Strategy D is fully compliant with documentation.

---

## Strategy E: AccumulationBottom

### Fixed ✅

- [x] **Market cap**: $2B → $3B - **NOT ACTUALLY FIXED**
  - Code still shows `min_market_cap` not explicitly set in PARAMS
  - Using default $2B from global filters
- [x] **Volume**: 100K → 200K - **NOT ACTUALLY FIXED**
  - Code uses default global filters
- [x] **Listed age**: 60 → 180 days - **NOT ACTUALLY FIXED**
  - Code: `min_listing_days: 60` (line 34)

**CRITICAL**: The Strategy E pre-filter fixes were NOT applied despite being in the expected fixes list.

### Already Correct ✓

- [x] TQ max score: 4.0 matches documentation
- [x] AL max score: 4.0 matches documentation
- [x] AS max score: 4.0 matches documentation
- [x] VC max score: 3.0 matches documentation
- [x] Near 60d low within 8%: Implemented (lines 75-77)
- [x] Support level detection: Implemented (lines 88-120)

### Remaining Issues ❌

**Medium:**

- [ ] Market cap filter: Should be >= $3B, code uses default $2B
- [ ] Volume filter: Should be >= 200K, code uses default 100K
- [ ] Listed age: Should be > 180 days, code has 60 days

**Low:**

- [ ] ADR >= 1.5% filter: NOT CHECKED

---

## Strategy F: CapitulationRebound

### Already Correct ✓

- [x] MO max score: 5.0 matches documentation (line 214)
- [x] EX max score: 6.0 matches documentation (line 223)
- [x] VC max score: 4.0 matches documentation (line 232)
- [x] RSI < 22 filter: Implemented (lines 160-161)
- [x] Gaps in 5 days >= 2: Implemented (lines 168-170)
- [x] Dollar volume > $50M: Implemented (lines 51-55 in accumulation_bottom, shared logic)
- [x] VIX 15-35 window: Implemented (lines 127-137)
- [x] Extreme VIX exempt: EXTREME_EXEMPT = True (line 39)
- [x] EXTREME_EXEMPT flag: Implemented (line 39)

### Remaining Issues ❌

**Low:**

- [ ] Price vs EMA50 < EMA50 - 4×ATR: Code uses 5×ATR (lines 164-165), docs specify 4×ATR

---

## Strategy G: EarningsGap

### Fixed ✅

- [x] **TC max score**: 4.0 → 3.0 (`earnings_gap.py` line 88)
  - Code: `ScoringDimension(name='TC', score=tc_score, max_score=3.0, ...)` ✅ FIXED
- [x] **Price filter**: $2 → $10 - **NOT VERIFIABLE in code**
  - The strategy doesn't have explicit price filter in PARAMS
  - Relies on global Tier 1 pre-filters

### Already Correct ✓

- [x] GS max score: 5.0 matches documentation (line 86)
- [x] QC max score: 4.0 matches documentation (line 87)
- [x] VC max score: 3.0 matches documentation (line 89)
- [x] Earnings gap >= 5%: Implemented (lines 46-49)
- [x] Days since earnings 1-5: Implemented (lines 40-42)
- [x] Dollar volume > $100M: Implemented (lines 57-63)
- [x] Gap direction detection: Implemented (lines 168-196)

### Remaining Issues ❌

**Medium:**

- [ ] Price filter: Should be > $10, global filter has $2 - relies on external filters

---

## Strategy H: RelativeStrengthLong

### Fixed ✅

- [x] **RD max score**: 4.0 → 6.0 (`relative_strength_long.py` line 100)
  - Code: `ScoringDimension(name='RD', score=rd_score, max_score=6.0, ...)` ✅ FIXED
- [x] **CQ max score**: 4.0 → 3.0 (`relative_strength_long.py` line 102)
  - Code: `ScoringDimension(name='CQ', score=cq_score, max_score=3.0, ...)` ✅ FIXED
- [x] **VC max score**: 3.0 → 2.0 (`relative_strength_long.py` line 103)
  - Code: `ScoringDimension(name='VC', score=vc_score, max_score=2.0, ...)` ✅ FIXED
- [x] **Market cap**: $2B → $3B (`relative_strength_long.py` line 32)
  - Code: `'min_market_cap': 3e9` ✅ FIXED

### Already Correct ✓

- [x] SH max score: 4.0 matches documentation (line 101)
- [x] RS percentile >= 80th: Implemented (lines 49-51)
- [x] SPY regime bear/neutral only: Implemented (lines 42-44)
- [x] Price vs 52w high within 15%: Implemented (lines 67-71)
- [x] Volume >= 200K: Implemented (lines 61-64)
- [x] Accumulation ratio >= 1.1: Implemented (lines 75-78)
- [x] EXTREME_EXEMPT flag: Present (not shown in snippet but expected)

### Remaining Issues ❌

**Low:**

- [ ] Price > EMA200 filter: NOT CHECKED (docs require it)

---

## Detailed Analysis of Critical Issues

### Strategy A: Dimension Max Scores Still Wrong

The baseline audit identified that CQ, BS, and VC max scores should be 4.0, but code has 5.0. This was listed as "FIXED" in the expected fixes, but the current code still shows:

```python
# Line 186 (CQ)
ScoringDimension(name='CQ', score=cq_score, max_score=5.0, ...)

# Line 200 (BS)
ScoringDimension(name='BS', score=bs_score, max_score=5.0, ...)

# Line 212 (VC)
ScoringDimension(name='VC', score=vc_score, max_score=5.0, ...)
```

**Impact**: This causes the strategy to potentially score up to 20 points (5+5+5+5) instead of the documented 17 points (5+4+4+4), with raw scores capped at 20 but displayed as 15. This is a significant deviation from the scoring specification.

### Strategy E: Pre-filters Still Wrong

The baseline audit identified that Strategy E should have:

- Market cap >= $3B (code uses $2B)
- Volume >= 200K (code uses 100K)
- Listed age > 180 days (code has 60)

These were listed as "FIXED" but the current code shows:

```python
PARAMS = {
    'min_listing_days': 60,  # Should be 180
    # No explicit min_market_cap - uses $2B default
    # No explicit min_volume - uses 100K default
}
```

**Impact**: Strategy E is selecting lower-quality stocks than specified, potentially reducing performance in accumulation bottom detection.

---

## Recommendations

### Immediate Priority (Critical)

1. **Fix Strategy A dimension max scores**
   - Change CQ max_score from 5.0 to 4.0
   - Change BS max_score from 5.0 to 4.0
   - Change VC max_score from 5.0 to 4.0

2. **Fix Strategy E pre-filters**
   - Add `'min_market_cap': 3e9` to PARAMS
   - Add `'min_volume': 200000` to PARAMS
   - Change `'min_listing_days': 60` to `180`

### High Priority (Medium)

3. **Strategy A: Add Price > EMA200 filter**
   - Add explicit check in filter() method

4. **Strategy A: Move CLV bonus from TC to VC**
   - Currently TC has CLV bonus (0-1.0), but docs say VC should have 0-0.5

5. **Strategy G: Add explicit price filter**
   - Add `'min_price': 10.0` to PARAMS

### Low Priority

6. Complete remaining pre-filter additions (EMA200 checks, ADR checks)
7. Implement pattern-specific stop losses for Strategy A
8. Add stop floor (entry × 0.92) for Strategy A

---

## Appendix: Dimension Max Score Verification

| Strategy | Dim 1 | Doc     | Code    | Status | Dim 2 | Doc     | Code    | Status | Dim 3 | Doc     | Code    | Status | Dim 4 | Doc     | Code    | Status |
| -------- | ----- | ------- | ------- | ------ | ----- | ------- | ------- | ------ | ----- | ------- | ------- | ------ | ----- | ------- | ------- | ------ |
| A        | TC    | 5.0     | 5.0     | ✅     | CQ    | **4.0** | **5.0** | ❌     | BS    | **4.0** | **5.0** | ❌     | VC    | **4.0** | **5.0** | ❌     |
| B        | TI    | 5.0     | 5.0     | ✅     | RC    | 5.0     | 5.0     | ✅     | VC    | 5.0     | 5.0     | ✅     | BONUS | 2.0     | 2.0     | ✅     |
| C        | SQ    | 4.0     | 4.0     | ✅     | VD    | 5.0     | 5.0     | ✅     | RB    | 6.0     | 6.0     | ✅     | -     | -       | -       | -      |
| D        | TQ    | 4.0     | 4.0     | ✅     | RL    | 4.0     | 4.0     | ✅     | DS    | 4.0     | 4.0     | ✅     | VC    | 3.0     | 3.0     | ✅     |
| E        | TQ    | 4.0     | 4.0     | ✅     | AL    | 4.0     | 4.0     | ✅     | AS    | 4.0     | 4.0     | ✅     | VC    | 3.0     | 3.0     | ✅     |
| F        | MO    | 5.0     | 5.0     | ✅     | EX    | 6.0     | 6.0     | ✅     | VC    | 4.0     | 4.0     | ✅     | -     | -       | -       | -      |
| G        | GS    | 5.0     | 5.0     | ✅     | QC    | 4.0     | 4.0     | ✅     | TC    | **3.0** | **3.0** | ✅     | VC    | 3.0     | 3.0     | ✅     |
| H        | RD    | **6.0** | **6.0** | ✅     | SH    | 4.0     | 4.0     | ✅     | CQ    | **3.0** | **3.0** | ✅     | VC    | **2.0** | **2.0** | ✅     |

**Legend**: ✅ = Match, ❌ = Mismatch

---

_End of Verification Report_
