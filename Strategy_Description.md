# Strategy Description

Precise specifications for reproducing all 6 trading strategies.

**Version**: 3.0  
**Last Updated**: 2026-04-01

---

## Table of Contents

1. [Common Framework](#common-framework)
2. [Strategy A: MomentumBreakout](#strategy-a-momentumbreakout)
3. [Strategy B: PullbackEntry](#strategy-b-pullbackentry)
4. [Strategy C: SupportBounce](#strategy-c-supportbounce)
5. [Strategy D: RangeShort](#strategy-d-rangeshort)
6. [Strategy E: DoubleTopBottom](#strategy-e-doubletopbottom)
7. [Strategy F: CapitulationRebound](#strategy-f-capitulationrebound)
8. [Technical Indicators Reference](#technical-indicators-reference)

---

## Common Framework

### Scoring System

All strategies use unified 0-15 point scoring across 4 dimensions:

| Total Score | Tier | Position Size | Description |
|-------------|------|---------------|-------------|
| 12.00-15.00 | S | 20% | Exceptional setup |
| 9.00-11.99 | A | 10% | Qualified setup |
| 7.00-8.99 | B | 5% | Marginal setup |
| <7.00 | C | 0% | Reject |

**Linear Interpolation Formula**:
```
score = X + (value - A) / (B - A) * (Y - X)
```
Where: value ∈ [A, B] → score ∈ [X, Y]

### Entry/Exit Framework

**Position Sizing**: Tier-based (S=20%, A=10%, B=5%)
**Initial Stop**: Technical level or ATR-based
**Trailing Stop**: 4-stage system
1. Fixed stop at entry
2. Chandelier: 3× ATR(22) from highest high
3. EMA21 trail when price > 2 ATR above
4. EMA8/10 trail for final phase

---

## Strategy A: MomentumBreakout

**Type**: Long Only  
**Description**: VCP pattern + momentum breakout with RS ranking

### Scoring Dimensions (4D)

| Dimension | Max Score | Weight | Description |
|-----------|-----------|--------|-------------|
| RS | 5.0 | 33% | Relative strength ranking |
| VCP | 5.0 | 33% | Volatility contraction pattern quality |
| VC | 5.0 | 33% | Volume confirmation |
| Bonus | +2.0 | - | Sector resonance, RS resilience |

### Dimension 1: RS (Relative Strength)

**Formula**:
```
RS_Score = 0.4 × R3m + 0.3 × R6m + 0.3 × R12m

R3m  = (Close_today - Close_63d) / Close_63d
R6m  = (Close_today - Close_126d) / Close_126d
R12m = (Close_today - Close_252d) / Close_252d
```

**Scoring**:
| RS Percentile | Score |
|---------------|-------|
| >90th | 5.0 |
| 75th-90th | 3.0-5.0 (interpolate) |
| 50th-75th | 1.0-3.0 (interpolate) |
| <50th | 0 |

**RS Resilience Bonus** (market down scenario):
```
If SPY_5d_return < -2%:
    Relative_perf = Stock_5d_return - SPY_5d_return
    If Relative_perf > 5%: +1.5
    If 0% < Relative_perf <= 5%: interpolate 0-1.5
    If Relative_perf <= 0%: 0
```

### Dimension 2: VCP (Volatility Contraction Pattern)

**Pattern Requirements**:
- Base: 15-30 day consolidation
- Width contraction: Each subsequent range < previous
- Volume contraction: Each subsequent phase lower volume
- Tightness: Last 5 days ADR < 2× ATR

**Scoring**:
| Factor | Score |
|--------|-------|
| Width contraction (3 phases) | 0-2.0 |
| Volume contraction (3 phases) | 0-2.0 |
| Tightness (ADR/ATR ratio) | 0-1.0 |

### Dimension 3: VC (Volume Confirmation)

**Breakout Volume Requirement**:
| Volume vs 20d Avg | Score |
|-------------------|-------|
| >3.0x | 5.0 |
| 2.0x-3.0x | 3.0-5.0 (interpolate) |
| 1.5x-2.0x | 1.0-3.0 (interpolate) |
| <1.5x | 0 |

### Entry/Exit Rules

**Entry**:
- Price breaks above pivot (highest high of consolidation)
- Volume > 1.5x 20-day average
- Price within 3% of breakout level

**Stop Loss**:
```
stop = max(
    pivot_low - 0.5 × ATR14,
    entry × 0.93
)
```

**Target**:
```
target = entry + 3 × (entry - stop)
```

---

## Strategy B: PullbackEntry

**Type**: Long Only  
**Description**: Pullback to rising EMA with 4D scoring

### Scoring Dimensions (4D)

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| TI | 5.0 | Trend intensity (EMA slope) |
| RS | 5.0 | Retracement structure |
| VC | 5.0 | Volume confirmation |
| Bonus | +2.0 | Sector resonance, gap analysis |

### Dimension 1: TI (Trend Intensity)

**Formula**:
```
S_norm = (EMA21_today - EMA21_5d) / ATR14

Where:
EMA21_today = EMA(Close, 21) current value
EMA21_5d    = EMA(Close, 21) 5 days ago
ATR14       = 14-day Average True Range
```

**Scoring**:
| S_norm | Score |
|--------|-------|
| >1.2 | 5.0 (Vertical expansion) |
| 0.8-1.2 | 4.0-5.0 (interpolate) |
| 0.4-0.8 | 2.0-4.0 (interpolate) |
| 0-0.4 | 0-2.0 (interpolate) |
| ≤0 | 0 (Filter out) |

**EMA Touch Penalty**:
```
If EMA21 touches (low ≤ EMA21 < close) in last 20 days:
    Deduct 0.5 per touch after first (max 1.5)
```

### Dimension 2: RS (Retracement Structure)

**Structure Requirements**:
- Price > EMA21 (bullish trend)
- EMA8 penetration: Price within 1.5% below EMA8
- Range: High-low over pullback < 8%

**Scoring**:
| Factor | Score |
|--------|-------|
| Range tightness (<5% = 2.0, 5-8% = 1.0-2.0) | 0-2.0 |
| EMA8 support quality | 0-2.0 |
| No gap down > 0.8 ATR | 0-1.0 |

### Dimension 3: VC (Volume Confirmation)

**Dry Up + Surge Pattern**:
```
Volume_Dry = Volume_today / Volume_20d_avg < 0.7
Volume_Surge = Volume_today / Volume_20d_avg > 1.5
```

**Scoring**:
| Pattern | Score |
|---------|-------|
| Dry up (<0.7x) then surge (>1.5x) | 5.0 |
| Only surge (>1.5x) | 3.0 |
| Dry up only (<0.7x) | 2.0 |
| Neither | 0 |

### Entry/Exit Rules

**Entry**:
- Price above EMA21 with positive slope
- First touch or retest of EMA8/21
- Volume confirmation

**Stop Loss**:
```
stop_candidates = [
    platform_low (5-day low),
    EMA21 - ATR,
    entry - 1.2 × ATR
]
stop = min(stop_candidates)
```

**Trailing Stops** (4-stage):
```python
# Stage 2: Lock profit
lock_trigger = entry + 2.5 × risk
lock_stop = entry + 0.5 × risk

# Stage 3: Trend exit
chandelier = highest_high - 3 × ATR

# Stage 4: Acceleration
if price > EMA21 × 1.20:
    use EMA5 as trail
```

---

## Strategy C: SupportBounce

**Type**: Long Only  
**Description**: Upthrust & rebound from support with test quality scoring

### Scoring Dimensions (4D)

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| TQ | 4.0 | Trend quality |
| VS | 5.0 | Volume signal (core) |
| PD | 3.0 | Pattern depth |
| TS | 3.0 | Test strength |

### Dimension 1: TQ (Trend Quality)

**Requirements**:
- Primary trend: Price > EMA50
- Secondary trend: EMA8 > EMA21

**Scoring**:
| Condition | Score |
|-----------|-------|
| Price > EMA50, EMA8 > EMA21 | 4.0 |
| Price > EMA50 only | 2.0 |
| Neither | 0 |

### Dimension 2: VS (Volume Signal) - Core Dimension

**Pattern**:
- Shakeout: High volume break below support
- Recovery: Volume dry up + surge on reclaim

**Scoring**:
| Volume Pattern | Score |
|----------------|-------|
| Climax down + dry up + surge | 5.0 |
| Dry up + surge | 4.0 |
| Surge only | 3.0 |
| Dry up only | 2.0 |
| No pattern | 0 |

### Dimension 3: PD (Pattern Depth)

**Depth Calculation**:
```
Depth_pct = (Support_level - Low) / Support_level × 100
```

**Scoring**:
| Depth | Score |
|-------|-------|
| 3-7% | 3.0 (optimal) |
| 1-3% or 7-10% | 1.5-3.0 (interpolate) |
| <1% or >10% | 0 |

### Dimension 4: TS (Test Strength)

**Requirements**:
- Support tested ≥2 times
- Interval between tests ≥3 days
- Reclaim within 3 days

**Scoring**:
| Factor | Score |
|--------|-------|
| 2+ tests | 1.0 |
| Proper interval (≥3d) | 1.0 |
| Fast reclaim (<3d) | 1.0 |

### Entry/Exit Rules

**Entry**:
- Price reclaims support level
- Volume surge (>1.5x avg)
- Close above support

**Stop Loss**:
```
stop = max(
    undercut_low - 0.3 × ATR,
    entry × 0.95
)
```

---

## Strategy D: RangeShort

**Type**: Short Only  
**Description**: Range bottom support breakdown

### Scoring Dimensions (4D)

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| TQ | 4.0 | Trend quality (opposite for short) |
| VS | 5.0 | Volume signal (core) |
| PD | 3.0 | Pattern depth |
| RW | 3.0 | Relative weakness |

### Market Direction Filter

**Pre-filter** (SPY context):
```
If SPY > EMA50 and trending up: reduce short exposure
If SPY < EMA50 or flat: proceed
```

### Dimension 1: TQ (Trend Quality)

**Short Trend Requirements**:
- Price < EMA50 (downtrend)
- EMA8 < EMA21

**Scoring** (inverted from long):
| Condition | Score |
|-----------|-------|
| Price < EMA50, EMA8 < EMA21 | 4.0 |
| Price < EMA50 only | 2.0 |
| Neither | 0 |

### Dimension 2: VS (Volume Signal)

**Distribution Pattern**:
- Heavy volume at range top (distribution)
- Volume dry up at bottom (lack of support)
- Breakdown volume surge

**Scoring**:
| Pattern | Score |
|---------|-------|
| Distribution + breakdown surge | 5.0 |
| Breakdown surge only | 3.0 |
| Distribution only | 2.0 |
| Neither | 0 |

### Dimension 3: PD (Pattern Depth)

**Range Quality**:
```
Range_Width = Range_high - Range_low
Width_vs_ATR = Range_Width / ATR14
```

**Veto Condition**:
```
If Width_vs_ATR > 1.5: VETO (no profit space)
```

**Scoring**:
| Width/ATR | Score |
|-----------|-------|
| 0.8-1.2 | 3.0 (optimal) |
| 0.5-0.8 or 1.2-1.5 | 1.0-3.0 (interpolate) |
| <0.5 | 0 (too tight) |

### Dimension 4: RW (Relative Weakness)

**Formula**:
```
RW = Stock_return_5d - SPY_return_5d
```

**Scoring**:
| RW | Score |
|----|-------|
| < -5% (underperforming) | 3.0 |
| -5% to -2% | 1.0-3.0 (interpolate) |
| > -2% | 0 |

### Entry/Exit Rules

**Entry**:
- Break below support on increased volume
- SPY not in strong uptrend
- Risk:Reward > 1.5

**Stop Loss**:
```
stop = min(
    range_high,
    entry + 1.5 × ATR
)
```

**Time Decay Exit**:
```
If days_at_level > 5 with < 1% movement:
    Consider exit (stuck trade)
```

---

## Strategy E: DoubleTopBottom

**Type**: Long/Short (bidirectional)  
**Description**: Distribution top / accumulation bottom pattern

### Scoring Dimensions (4D)

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| TQ | 4.0 | Trend quality |
| VS | 5.0 | Volume signal |
| PD | 3.0 | Pattern development |
| TS | 3.0 | Test strength (max 3 tests) |

### Direction Determination

```
If price > EMA50 and pattern near highs: SHORT (distribution)
If price < EMA50 and pattern near lows: LONG (accumulation)
```

### Dimension 1: TQ (Trend Quality)

**Scoring**:
| Condition | Score |
|-----------|-------|
| Clear trend direction | 4.0 |
| Mixed/sideways | 2.0 |
| Against trend | 0 |

### Dimension 2: VS (Volume Signal)

**Distribution (Top) Pattern**:
- High volume first top
- Lower volume second top
- Breakdown volume surge

**Accumulation (Bottom) Pattern**:
- High volume first bottom
- Lower volume second bottom
- Breakout volume surge

**Scoring**:
| Pattern Quality | Score |
|-----------------|-------|
| Classic volume pattern | 5.0 |
| Partial match | 2.0-4.0 |
| No pattern | 0 |

### Dimension 3: PD (Pattern Development)

**Time Requirement**:
```
Min_days_between_tests = 20
Max_days_between_tests = 120
```

**Scoring**:
| Factor | Score |
|--------|-------|
| Proper time window | 1.0 |
| RSI divergence | 1.0 |
| Price level similarity (<5% diff) | 1.0 |

### Dimension 4: TS (Test Strength)

**Test Count** (capped at 3 for scoring):
```
score = min(test_count, 3) × 1.0
```

**Test Quality Requirements**:
- Interval ≥3 days between tests
- Price within 5% of previous test

### Entry/Exit Rules

**Entry**:
- Break of neckline (line connecting lows for top, highs for bottom)
- Minimum 2 tests at level
- Volume confirmation on break

**Stop Loss**:
```
# For short (distribution)
stop = second_top_high + 0.5 × ATR

# For long (accumulation)
stop = second_bottom_low - 0.5 × ATR
```

---

## Strategy F: CapitulationRebound

**Type**: Long Only  
**Description**: Parabolic capitulation reversal

### Scoring Dimensions (4D)

| Dimension | Max Score | Description |
|-----------|-----------|-------------|
| TQ | 4.0 | Trend exhaustion |
| VS | 5.0 | Volume climax |
| PD | 3.0 | Pattern depth |
| MC | 3.0 | Market context |

### Pre-filter Requirements

**Capitulation Criteria** (at least 3 of 5):
```
□ 1-month return > 50% (large cap) or > 200% (small cap)
□ Consecutive up days ≥ 3
□ Gap ups ≥ 2 in run
□ Volume increasing days ≥ 2
□ Price > 10 ATR above EMA50
```

### Dimension 1: TQ (Trend Exhaustion)

**Momentum Calculation**:
```
Momentum_score = min(abs(R1m), 100) / 100 × 4.0

Where R1m is 1-month return
```

**Scoring**:
| R1m | Score |
|-----|-------|
| >100% (small) / >50% (large) | 4.0 |
| 50-100% / 30-50% | 2.0-4.0 |
| <50% / <30% | 0-2.0 |

### Dimension 2: VS (Volume Climax)

**Climax Detection**:
```
Volume_vs_20d = Volume_today / Volume_20d_avg
Consecutive_increasing = days with increasing volume
```

**Scoring**:
| Pattern | Score |
|---------|-------|
| Volume climax + exhaustion | 5.0 |
| High volume (>3x) | 4.0 |
| Above average (>2x) | 2.0 |
| Normal volume | 0 |

### Dimension 3: PD (Pattern Depth)

**Extension Measurement**:
```
Extension = (Price_high - EMA50) / EMA50 × 100
Extension_ATR = (Price_high - EMA50) / ATR
```

**Scoring**:
| Extension | Score |
|-----------|-------|
| >50% price, >10 ATR | 3.0 |
| 30-50% price, 7-10 ATR | 2.0 |
| 20-30% price, 5-7 ATR | 1.0 |
| <20% | 0 |

### Dimension 4: MC (Market Context)

**Market Filter**:
```
If SPY extended (>10% above EMA200): +1.0
If VIX elevated (>25): +1.0
If Sector rotation negative: +1.0
```

### Entry/Exit Rules

**Entry** (choose one):

1. **Opening Range Break**:
   - First 5-minute candle
   - Break below opening range low
   - Volume > 2x average

2. **VWAP Rejection**:
   - First pullback to VWAP
   - Rejection (red candle)
   - Entry on break of pullback low

**Stop Loss**:
```
stop = day_high + 0.3 × ATR
```

**Target**:
```
# Primary: EMA8
# Secondary: EMA21 (if very weak)
```

**Time Stop**:
```
If no move within 3 days: exit
```

---

## Technical Indicators Reference

### Common Calculations

**ATR (Average True Range)**:
```
TR = max(high - low, |high - close_prev|, |low - close_prev|)
ATR14 = SMA(TR, 14)
```

**EMA (Exponential Moving Average)**:
```
EMA_today = (Close × multiplier) + (EMA_yesterday × (1 - multiplier))
multiplier = 2 / (period + 1)
```

**ADR (Average Daily Range)**:
```
ADR = SMA(high - low, 20)
ADR_pct = ADR / close × 100
```

**RSI (Relative Strength Index)**:
```
RS = SMMA(gain, 14) / SMMA(loss, 14)
RSI = 100 - (100 / (1 + RS))
```

**CLV (Close Location Value)**:
```
CLV = (close - low) / (high - low)
```

**Chandelier Exit**:
```
Chandelier = highest_high_since_entry - multiplier × ATR
```

### Linear Interpolation Function

```python
def interpolate(value, min_val, max_val, min_score, max_score):
    """Linear interpolation for scoring boundaries."""
    if value <= min_val:
        return min_score
    if value >= max_val:
        return max_score
    return min_score + (value - min_val) / (max_val - min_val) * (max_score - min_score)
```

---

## Maintenance Log

| Date | Change |
|------|--------|
| 2026-04-01 | v3.0 - Merged 8 strategies to 6, renamed to English |
| 2026-03-28 | v2.2 - Added bidirectional pattern for Range/DTSS |
| 2026-03-20 | v2.1 - Extracted scoring_utils module |
| 2026-03-15 | v2.0 - Unified 4D scoring system |
