# Strategy Description

Precise specifications for all 6 trading strategies.

**Version**: 4.0  
**Last Updated**: 2025-04

---

## Table of Contents

1. [Common Framework](#common-framework)
2. [Strategy A: MomentumBreakout](#strategy-a-momentumbreakout)
3. [Strategy B: PullbackEntry](#strategy-b-pullbackentry)
4. [Strategy C: SupportBounce](#strategy-c-supportbounce)
5. [Strategy D: RangeShort](#strategy-d-rangeshort)
6. [Strategy E: DoubleTopBottom](#strategy-e-doubletopbottom)
7. [Strategy F: CapitulationRebound](#strategy-f-capitulationrebound)

---


## Common Framework


### Scoring System

All strategies use unified 0-15 point scoring across 4 dimensions.

| Total Score | Tier | Position % | Description |
|-------------|------|------------|-------------|
| 12.00-15.00 | S | 20% | Exceptional setup |
| 9.00-11.99 | A | 10% | Qualified setup |
| 7.00-8.99 | B | 5% | Marginal setup |
| < 7.00 | C | 0% | Reject |

### Linear Interpolation Formula
```
score = X + (value - A) / (B - A) * (Y - X)
```
Where: value ∈ [A, B] → score ∈ [X, Y]

### Entry/Exit Framework
**Stop Loss Methods**:
1. **Platform/Level stop**: Platform low - ATR buffer
2. **EMA-based**: EMA21 - ATR
3. **Fixed**: Entry - 1.2×ATR

**Trailing Stops**:
- **Stage 2**: Lock profit at entry + 2.5×risk
- **Stage 3**: Chandelier = highest_high - 3×ATR
- **Stage 4**: EMA8 trail when price > 1.20×EMA21

---

## Strategy A: MomentumBreakout

**Type**: Long Only  
**Dimensions**: PQ, BS, VC, TC  
**Description**: VCP platform + volume breakout with RS bonus

### Scoring Dimensions (4D)

| Dimension | Max | Weight | Description |
|-----------|-------|--------|-------------|
| PQ | 5.0 | 33% | Platform Quality (tightness, concentration, contraction) |
| BS | 5.0 | 33% | Breakout Strength (breakout %, energy) |
| VC | 5.0 | 33% | Volume Confirmation (contraction + surge) |
| TC | 5.0 | bonus | Trend Context (EMA distance, 52w high, CLV) |

### Dimension 1: PQ (Platform Quality)

**Pattern Detection**:
- 15-60 day consolidation range
- Range < 12% of price
- >50% days within ±2.5% band (concentration)
- Volume contraction: last 5d < 70% of platform avg

**Scoring**:
| Factor | Score |
|--------|-------|
| Tightness (<4% = 2.0, 4-8% = 1.0-2.0, 8-12% = 0-1.0) | 0-2.0 |
| Concentration (>70% = 1.5, 50-70% = 0.5-1.5) | 0-1.5 |
| Contraction Quality (>0.8 = 1.5, 0.5-0.8 = 0.5-1.5) | 0-1.5 |

### Dimension 2: BS (Breakout Strength)

**Scoring**:
| Factor | Score |
|--------|-------|
| Breakout % (>4% = 3.0, 2-4% = 2.0-3.0) | 0-3.0 |
| Energy Ratio (>2.0 = 2.0, 1.0-2.0 = 0-2.0) | 0-2.0 |

### Dimension 3: VC (Volume Confirmation)

**Pattern**:
- Volume contraction during platform
- Volume surge on breakout (>2.0×20d SMA)

**Scoring**:
| Pattern | Score |
|---------|-------|
| Climax contraction + surge | 5.0 |
| Moderate contraction + surge | 3.0-5.0 |
| Surge only | 2.0-3.0 |

### Dimension 4: TC (Trend Context)

**Components**:
- EMA50 distance (closer = higher score)
- 52-week high proximity (<3% = 2.0, 3-5% = 0-2.0)
- CLV (>0.85 = 1.0, 0.65-0.85 = 0-1.0)
- RS bonus: +0-1.0 based on RS percentile

### Entry/Exit Rules

**Entry**:
- Price > platform high + 2%
- Volume > 2.0×20d SMA
- CLV >= 0.75
- Within 20% of EMA50
- Within 10% of 52w high

**Stop Loss**:
```
stop = platform_low × 0.98  # 2% buffer below platform
```

**Target**:
```
target = entry + 3 × (entry - stop)  # 3R
```

---

## Strategy B: PullbackEntry

**Type**: Long Only  
**Dimensions**: TI, RC, VC, BONUS  
**Description**: Institutional grade pullback to EMA support

### Scoring Dimensions (4D)

| Dimension | Max | Description |
|-----------|-----|-------------|
| TI | 5.0 | Trend Intensity (EMA21 slope normalized by ATR) |
| RC | 5.0 | Retracement Composite (range, EMA8 support, gaps) |
| VC | 5.0 | Volume Confirmation (dry up + surge pattern) |
| BONUS | 2.0 | Sector resonance, no gap veto |

### Dimension 1: TI (Trend Intensity)

**Formula**:
```
S_norm = (EMA21_today - EMA21_5d) / ATR14
```

**Scoring**:
| S_norm | Score |
|--------|-------|
| > 1.2 | 5.0 (Vertical expansion) |
| 0.8-1.2 | 4.0-5.0 |
| 0.4-0.8 | 2.0-4.0 |
| 0-0.4 | 0-2.0 |
| < 0 | 0 |

**EMA Touch Penalty**: -0.5 per EMA21 touch in last 20 days (max -1.5)

### Dimension 2: RC (Retracement Composite)

**Requirements**:
- Price > EMA21 (bull trend)
- EMA8 penetration: price within 1.5% of EMA8
- Pullback range < 8% from high

**Scoring**:
| Factor | Score |
|--------|-------|
| Range tightness (<5% = 2.0, 5-8% = 1.0-2.0) | 0-2.0 |
| EMA8 support quality (within 1% = 2.0) | 0-2.0 |
| No gap down > 0.8 ATR | 0-1.0 |

### Dimension 3: VC (Volume Confirmation)
**Pattern**:
- Volume_Dry: vol_today / vol_20d < 0.7
- Volume_Surge: vol_today / vol_20d > 1.5

**Scoring**:
| Pattern | Score |
|---------|-------|
| Dry up + surge | 5.0 |
| Surge only | 3.0 |
| Dry up only | 2.0 |
| Neither | 0 |

### Dimension 4: BONUS

| Factor | Score |
|--------|-------|
| Sector ETF alignment | 0-1.0 |
| No gap veto | 0-1.0 |

### Entry/Exit Rules

**Entry**:
- Price > EMA21 with positive slope
- First touch or retest of EMA8/21
- Volume confirmation (dry + surge)

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
- **Stage 2**: Lock at entry + 2.5×risk
- **Stage 3**: Chandelier at highest_high - 3×ATR
- **Stage 4**: EMA5 trail if price > 1.20×EMA21

---

## Strategy C: SupportBounce

**Type**: Long Only  
**Dimensions**: SQ, VD, RB  
**Description**: Support level false breakdown and rebound

### Scoring Dimensions (3D)

| Dimension | Max | Description |
|-----------|-----|-------------|
| SQ | 4.0 | Support Quality (price > EMA50, EMA8 > EMA21) |
| VD | 5.0 | Volume Dynamics (climax + dry + surge) |
| RB | 6.0 | Rebound (pattern depth, reclaim speed) |

### Dimension 1: SQ (Support Quality)

**Requirements**:
- Price > EMA50 (primary trend)
- EMA8 > EMA21 (secondary trend)

**Scoring**:
| Condition | Score |
|-----------|-------|
| Both | 4.0 |
| Price > EMA50 only | 2.0 |
| Neither | 0 |

### Dimension 2: VD (Volume Dynamics)

**Pattern**: Climax down → Dry up → Surge on reclaim

**Scoring**:
| Pattern | Score |
|---------|-------|
| Climax + dry + surge | 5.0 |
| Dry + surge | 4.0 |
| Surge only | 3.0 |
| Dry only | 2.0 |
| None | 0 |

### Dimension 3: RB (Rebound)

**Components**:
- Pattern depth (3-7% optimal)
- Reclaim within 3 days
- Sector ETF support

**Scoring**:
| Factor | Score |
|--------|-------|
| Depth (3-7% = 3.0, 1-3% or 7-10% = 1-3.0) | 0-3.0 |
| Fast reclaim (<3d) | 2.0 |
| Sector alignment | 0-1.0 |

### Entry/Exit Rules

**Entry**:
- Price reclaims support level
- Volume surge (>1.5×avg)
- Close above support
- SPY > EMA200 (no rebound in downtrend)

**Stop Loss**:
```
stop = max(
    undercut_low - 0.3 × ATR,
    entry × 0.95
)
```

**Target**: Support level + 2.0×risk

---

## Strategy D: RangeShort

**Type**: Short Only  
**Dimensions**: TQ, RL, VC  
**Description**: Short at resistance in bearish/neutral markets

### Scoring Dimensions (3D)

| Dimension | Max | Description |
|-----------|-----|-------------|
| TQ | 4.0 | Trend Quality (EMA200, short environment) |
| RL | 5.0 | Resistance Level (touches, interval, width) |
| VC | 6.0 | Volume Confirmation (distribution pattern) |

### Market Environment Filter

**Pre-filter** (SPY context):
- If SPY > EMA200: Skip (no shorts in bull)
- If SPY < EMA200 OR flat: Proceed

### Dimension 1: TQ (Trend Quality)

**Requirements**:
- Price < EMA50 (downtrend)
- EMA8 < EMA21

**Scoring** (inverted from long):
| Condition | Score |
|-----------|-------|
| Both | 4.0 |
| Price < EMA50 only | 2.0 |
| Neither | 0 |

### Dimension 2: RL (Resistance Level)

**Components**:
- Min 3 touches at resistance
- Min 3 days between touches (stability)
- Width 1.5-2.5×ATR

**Scoring**:
| Factor | Score |
|--------|-------|
| Touch count (3+=2.0) | 0-2.0 |
| Interval quality (>3d) | 0-2.0 |
| Width (1.5-2.5×ATR optimal) | 0-1.0 |

### Dimension 3: VC (Volume Confirmation)

**Pattern**: Distribution volume at top → Breakdown surge

**Scoring**:
| Pattern | Score |
|---------|-------|
| Distribution + breakdown | 6.0 |
| Distribution only | 4.0 |
| Breakdown only | 2.0 |
| Neither | 0 |

### Entry/Exit Rules

**Entry**:
- Price at resistance (<3% from level)
- SPY not in strong uptrend
- Risk:Reward > 1.5

**Stop Loss**:
```
stop = min(
    resistance_level + 0.3 × ATR,
    entry × 1.03
)
```

**Target**: Entry - 2.5×risk

---

## Strategy E: DoubleTopBottom

**Type**: Long/Short (bidirectional)  
**Dimensions**: PL, TS, VC  
**Description**: Distribution top / Accumulation bottom with side grading

### Scoring Dimensions (3D)

| Dimension | Max | Description |
|-----------|-----|-------------|
| PL | 5.0 | Proximity Level (distance from 60d high/low) |
| TS | 6.0 | Test Strength (touches, interval, confirmation) |
| VC | 4.0 | Volume Confirmation (exhaustion, intensity) |

### Direction Determination

```
If price near 60d high + weakness: SHORT (distribution)
If price near 60d low + strength: LONG (accumulation)
```

### Dimension 1: PL (Proximity Level)

**Scoring**:
| Distance | Score |
|----------|-------|
| < 1% | 3.0 |
| 1-2% | 2.0-3.0 (interpolate) |
| 2-3% | 1.0-2.0 (interpolate) |
| > 3% | 0 |

### Dimension 2: TS (Test Strength)

**Components**:
- Touch count (>3)
- Interval (>10 days, Expert B)
- Left/right side (Expert A): Left = Tier B max

**Scoring**:
| Factor | Score |
|--------|-------|
| 3+ touches | 2.0 |
| Proper interval (>10d) | 2.0 |
| Confirmation | 2.0 |

**Left Side Penalty**: Max Tier B (5%) for left side signals

### Dimension 3: VC (Volume Confirmation)

**Components**:
- Exhaustion gap (Expert C): +2.0 if detected
- Institutional intensity (Expert D): >1.5×avg

**Scoring**:
| Factor | Score |
|--------|-------|
| Volume spike (>1.5×) | 2.0 |
| Exhaustion gap | +2.0 |
| Intensity factor | 0-2.0 |

### Entry/Exit Rules

**Entry**:
- **Short**: Price near 60d high, EMA8 < EMA21, weakness signs
- **Long**: Price near 60d low, EMA8 > EMA21, strength signs

**Stop Loss**:
```
# For short
stop = 60d_high + 0.5 × ATR

# For long
stop = 60d_low - 0.5 × ATR
```

**Position Limits**:
- Left side signals: Tier B max (5%)
- Right side signals: Full Tier S (20%)

---

## Strategy F: CapitulationRebound


**Type**: Long Only  
**Dimensions**: MO, EX, VC  
**Description**: Capitulation bottom detection with volume climax

### Scoring Dimensions (3D)

| Dimension | Max | Description |
|-----------|-----|-------------|
| MO | 5.0 | Momentum Overextension (RSI, price vs EMA50) |
| EX | 6.0 | Extension Level (distance from EMA50, gaps) |
| VC | 4.0 | Volume Confirmation (climax detection) |

### Pre-filter Requirements

ALL must be true:
- RSI < 20 (extreme oversold)
- Price < EMA50 - 5×ATR (extended below)
- ≥2 gaps in last 5 days (acceleration)
- Volume > $50M (liquidity)
- Listed > 50 days

**VIX Filter** (Expert C):
- VIX > 30 and rising: REJECT all signals
- VIX > 25: Tier B max (5%)

### Dimension 1: MO (Momentum Overextension)

**Components**:
- RSI < 20 (score 3.0, 20-25 = 2.0-3.0, 25-30 = 1.0-2.0)
- Price vs EMA50 distance (>20% below = +2.0)

**Scoring**:
| RSI | Score |
|-----|-------|
| < 15 | 3.0 |
| 15-20 | 2.0-3.0 |
| 20-25 | 1.0-2.0 |
| 25-30 | 0.5-1.0 |

### Dimension 2: EX (Extension Level)

**Distance from EMA50**:
```
Distance_pct = |Price - EMA50| / EMA50 × 100
```
**Scoring**:
| Distance | Score |
|----------|-------|
| > 20% | 3.0 |
| 15-20% | 2.0-3.0 |
| 10-15% | 1.0-2.0 |
| < 10% | 0-1.0 |
**Gaps Bonus** (Expert C):
| Gaps in 5d | Score |
|------------|-------|
| 4+ | 2.0 |
| 3 | 1.5 |
| 2 | 1.0 |
### Dimension 3: VC (Volume Confirmation)
**Volume Climax** (Expert A):
| Volume Ratio | Score |
|------------|-------|
| > 4.0× | 4.0 |
| 3.0-4.0 | 3.0 |
| 2.0-3.0 | 1.5 |
| 1.5-2.0 | 0.5 |
**Capitulation Candle** (CLV > 0.7 + Volume > 1.5×): +2.0

### Entry/Exit Rules

**Entry** (End-of-Day):
- ALL pre-filter conditions met
- RSI < 20
- Price < EMA50 - 5×ATR
- Volume > 4×20d average

**Entry Price**:
```
entry = close_price  # EOD close
```

**Stop Loss**:
```
stop = entry - 2.0 × ATR
```

**Target**:
```
target = EMA50  # Mean reversion to EMA50
```

**Time Stop**:
```
If no move toward target within 10 days: exit
```

---

## Technical Indicators Reference

### ATR (Average True Range)
```
TR = max(high - low, |high - close_prev|, |low - close_prev|)
ATR14 = SMA(TR, 14)
```

### EMA (Exponential Moving Average)
```
multiplier = 2 / (period + 1)
EMA_today = Close × multiplier + EMA_yesterday × (1 - multiplier)
```

### RSI (Relative Strength Index)
```
RS = SMA(gain, 14) / SMA(loss, 14)
RSI = 100 - (100 / (1 + RS))
```

### CLV (Close Location Value)
```
CLV = (close - low) / (high - low)
```
dicates close position in daily range (0=low, 1=high)
### Linear Interpolation
```python
def interpolate(value, min_val, max_val, min_score, max_score):
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
| 2025-04 | v4.0 - Updated to match codebase (6 strategies, actual dimensions) |
| 2025-04 | v3.5 - Added 3-tier pre-calculation architecture |
| 2025-04 | v3.0 - Strategy rename, dimension alignment |
| 2025-03 | v2.1 - Expert suggestions implementation |
| 2025-03 | v2.0 - 4D scoring system unification |
