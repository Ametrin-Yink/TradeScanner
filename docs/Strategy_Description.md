# Strategy Description

Precise specifications for all 8 trading strategies.

**Version**: 5.0  
**Last Updated**: 2025-04  

---

## Table of Contents

1. [Common Framework](#common-framework)
2. [Strategy A: MomentumBreakout](#strategy-a-momentumbreakout)
3. [Strategy B: PullbackEntry](#strategy-b-pullbackentry)
4. [Strategy C: SupportBounce](#strategy-c-supportbounce)
5. [Strategy E1: DistributionTop](#strategy-e1-distributiontop)
6. [Strategy E2: AccumulationBottom](#strategy-e2-accumulationbottom)
7. [Strategy F: CapitulationRebound](#strategy-f-capitulationrebound)
8. [Strategy G: EarningsGap](#strategy-g-earningsgap)
9. [Strategy H: RelativeStrengthLong](#strategy-h-relativestrengthlong)
10. [Phase 1 Allocation Table](#phase-1-allocation-table)
11. [Technical Indicators Reference](#technical-indicators-reference)

---

## Change Log from v4.0

| Strategy | Status | Summary |
|----------|--------|---------|
| A: MomentumBreakout | Modified | Multi-pattern CQ replaces VCP-only PQ; TC promoted to primary gate; bonus pool added |
| B: PullbackEntry | Unchanged | No changes |
| C: SupportBounce | Modified | SPY gate removed; regime-adaptive position sizing added; reclaim window widened |
| D: RangeShort | Removed | Absorbed into E1 DistributionTop as sector-weak pattern |
| E: DoubleTopBottom | Split | Separated into E1 (short) and E2 (long) with independent 4D scoring |
| F: CapitulationRebound | Modified | VIX filter inverted; now fires in VIX 15–35 window |
| G: EarningsGap | New | Post-earnings gap continuation, both directions |
| H: RelativeStrengthLong | New | RS divergence longs in bear/neutral regimes |

---

## Common Framework

### Scoring System

All strategies use unified 0–15 point scoring. Strategies with bonus pools may produce raw scores above 15; these are clamped to 15.0 for tier calculation.

| Total Score | Tier | Base Position % | Description |
|-------------|------|-----------------|-------------|
| 12.00–15.00 | S | 20% | Exceptional setup |
| 9.00–11.99 | A | 10% | Qualified setup |
| 7.00–8.99 | B | 5% | Marginal setup |
| < 7.00 | C | 0% | Reject |

### Regime-Adaptive Position Sizing

Strategies marked with (regime-adaptive) multiply their base position % by a regime scalar. This is applied after tier calculation.

| SPY Regime | Scalar | Long strategies | Short strategies |
|------------|--------|-----------------|------------------|
| Bull (SPY > EMA50 > EMA200) | 1.0× | Full size | 0.3× |
| Neutral (SPY between EMAs) | 0.8× | 80% size | 0.8× |
| Bear (SPY < EMA50 < EMA200) | 0.5× | 50% size | 1.0× |
| Extreme (VIX > 30) | 0.3× | 30% size except F, H | 0.5× |

> Strategy F and H are exempt from the extreme regime scalar reduction — they are designed specifically for that environment.

### Linear Interpolation Formula

```
score = X + (value - A) / (B - A) * (Y - X)
```
Where: value ∈ [A, B] → score ∈ [X, Y]

### Entry/Exit Framework

**Stop Loss Methods**:
1. **Structure stop**: Base/level low − ATR buffer
2. **EMA-based**: EMA21 − ATR
3. **Fixed**: Entry − 1.2×ATR

**Trailing Stops (4-stage)**:
- **Stage 1→2**: Price reaches entry + 1×risk → move stop to breakeven
- **Stage 2→3**: Price reaches entry + 2.5×risk → lock stop at entry + 1×risk
- **Stage 3→4**: Price reaches entry + 4×risk → Chandelier = highest_high − 3×ATR
- **Stage 4 (extended)**: Price > 1.20×EMA21 → trail EMA8 daily

**Short-side trailing stops (inverted)**:
- **Stage 1→2**: Price reaches entry − 1×risk → move stop to breakeven
- **Stage 2→3**: Price reaches entry − 2.5×risk → lock stop at entry − 1×risk
- **Stage 3→4**: Chandelier = lowest_low + 3×ATR

### Technical Indicators Reference

**ATR (Average True Range)**
```
TR = max(high − low, |high − close_prev|, |low − close_prev|)
ATR14 = SMA(TR, 14)
```

**EMA (Exponential Moving Average)**
```
multiplier = 2 / (period + 1)
EMA_today = Close × multiplier + EMA_yesterday × (1 − multiplier)
```

**RSI (Relative Strength Index)**
```
RS = SMA(gain, 14) / SMA(loss, 14)
RSI = 100 − (100 / (1 + RS))
```

**CLV (Close Location Value)**
```
CLV = (close − low) / (high − low)
# 0 = closed at low, 1 = closed at high
```

**RS Percentile (Relative Strength vs SPY)**
```
RS_raw = stock_return_63d / SPY_return_63d
RS_percentile = percentile_rank(RS_raw, universe_63d_returns)
```

**Linear Interpolation Helper**
```python
def interpolate(value, min_val, max_val, min_score, max_score):
    if value <= min_val: return min_score
    if value >= max_val: return max_score
    return min_score + (value - min_val) / (max_val - min_val) * (max_score - min_score)
```

---

## Strategy A: MomentumBreakout

**Type**: Long Only  
**Version**: 5.0 (modified from 4.0)  
**Regime**: Bull primary; neutral weak  
**Dimensions**: TC, CQ, BS, VC + Bonus Pool  
**Description**: Multi-pattern momentum breakout. Any consolidation type qualifies; VCP is rewarded as a bonus. RS-gated trend context is the primary filter.

### Tier 1 Pre-Filter (strategy-specific)

| Filter | Condition |
|--------|-----------|
| RS percentile | ≥ 50th (hard gate) |
| Price vs EMA200 | Price > EMA200 |
| 3-month return | ≥ −20% |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K shares |
| EMA slope | Not required |
| ADR | Not required |

### Scoring Dimensions

| Dimension | Max | Role | Hard gate? |
|-----------|-----|------|------------|
| TC — Trend Context | 5.0 | RS strength, EMA alignment, 52w position | Yes — RS < 50th = reject |
| CQ — Consolidation Quality | 4.0 | Pattern type, duration, tightness | Yes — no pattern = reject |
| BS — Breakout Strength | 4.0 | Breakout %, energy ratio | No |
| VC — Volume Confirmation | 4.0 | Base contraction + breakout surge + CLV | No |
| Bonus Pool | +3.0 | VCP, sector, earnings, accumulation | No |
| **Raw cap** | **20.0** → displayed as **15.0** | | |

### Dimension 1: TC (Trend Context)

**Hard gate**: RS percentile < 50th → return TC = 0, skip symbol.

**RS Strength (0–2.0 pts)**

| RS Percentile | Score |
|---------------|-------|
| ≥ 90th | 2.0 |
| 75th–90th | 1.5–2.0 (interpolate) |
| 60th–75th | 1.0–1.5 (interpolate) |
| 50th–60th | 0.5–1.0 (interpolate) |
| < 50th | 0 → hard reject |

**EMA Structure (0–2.0 pts)**

| Condition | Score |
|-----------|-------|
| Price > EMA50 × 1.05 | +1.0 |
| Price > EMA200 | +0.5 |
| EMA50 > EMA200 | +0.5 |

**52-Week High Proximity (0–1.0 pts)**

| Distance from 52w high | Score |
|------------------------|-------|
| ≤ 5% | 1.0 |
| 5%–15% | 1.0–0.0 (interpolate) |
| > 15% | 0 |

**TC Max: 5.0**

### Dimension 2: CQ (Consolidation Quality)

**Hard gate**: No consolidation detected → return CQ = 0, reject.

**Step 1 — Detect pattern (priority order, first match wins)**

| Pattern | Requirements | Quality Score |
|---------|-------------|---------------|
| VCP | 15–60d, range < 12%, >50% days in ±2.5% band, last 5d vol < 70% avg, ≥2 contraction waves | 0.80–1.00 |
| High tight flag | Prior move ≥ 30% in ≤ 8w, pullback 8–30%, flag 2–6w, no gap-downs > 1×ATR | 0.61–0.72 |
| Flat base | Range < 15%, EMA21 slope < 0.3×ATR/5d, duration 3–15w | 0.55–0.75 |
| Ascending base | ≥ 3 higher lows, range 10–25%, duration 4–12w | 0.62 |
| Loose base | Range < 20%, duration ≥ 10d | 0.15–0.40 |
| None | — | 0 → hard reject |

**Step 2 — Score CQ**

Base pattern score (0–3.0 pts):
```
cq_base = pattern_quality_score × 3.0
```

Duration quality (0–1.0 pts):

| Duration | Score |
|----------|-------|
| 3–10 weeks | 1.0 |
| 2–3 weeks | 0.4–1.0 (interpolate) |
| 10–15 weeks | 1.0–0.5 (interpolate) |
| < 2 weeks | 0.2 |
| > 15 weeks | 0.3 |

```
CQ = min(cq_base + cq_duration, 4.0)
```

**CQ Max: 4.0**

### Dimension 3: BS (Breakout Strength)

**Breakout % above pivot (0–2.5 pts)**

| Breakout % | Score |
|------------|-------|
| ≥ 5% | 2.5 |
| 3%–5% | 2.0–2.5 (interpolate) |
| 2%–3% | 1.5–2.0 (interpolate) |
| 1%–2% | 0.5–1.5 (interpolate) |
| < 1% | 0–0.5 (interpolate) |

**Energy ratio — today vol / avg20d vol (0–1.5 pts)**

| Energy Ratio | Score |
|--------------|-------|
| ≥ 3.0× | 1.5 |
| 2.0–3.0× | 1.0–1.5 (interpolate) |
| 1.5–2.0× | 0.5–1.0 (interpolate) |
| 1.0–1.5× | 0–0.5 (interpolate) |
| < 1.0× | 0 |

**BS Max: 4.0**

### Dimension 4: VC (Volume Confirmation)

**Base volume behavior — last 5d of base / avg20d before base (0–2.0 pts)**

| Base Vol Ratio | Score |
|----------------|-------|
| < 0.50 | 2.0 |
| 0.50–0.65 | 1.5–2.0 (interpolate) |
| 0.65–0.80 | 0.8–1.5 (interpolate) |
| 0.80–1.00 | 0.2–0.8 (interpolate) |
| > 1.00 | 0 |

**Breakout volume — breakout day / avg20d (0–1.5 pts)**

| Breakout Vol | Score |
|--------------|-------|
| ≥ 3.0× | 1.5 |
| 2.0–3.0× | 1.0–1.5 (interpolate) |
| 1.5–2.0× | 0.5–1.0 (interpolate) |
| < 1.5× | 0–0.5 (interpolate) |

**CLV on breakout bar (0–0.5 pts)**

| CLV | Score |
|-----|-------|
| ≥ 0.85 | 0.5 |
| 0.65–0.85 | 0–0.5 (interpolate) |
| < 0.65 | 0 |

**VC Max: 4.0**

### Bonus Pool (0–3.0 pts, capped)

| Bonus | Max | Condition |
|-------|-----|-----------|
| VCP structure | 2.0 | Pattern = VCP; score = vol_contraction quality + range_contraction quality + wave count |
| Sector leadership | 0.5 | Sector ETF RS ≥ 80th AND sector ETF > EMA50 |
| Earnings catalyst | 0.5 | 7–21 days to earnings report |
| Accumulation divergence | 0.5 | OBV rising while price flat during base (linreg divergence) |

```
total_bonus = min(vcp_bonus + sector_bonus + earnings_bonus + accum_bonus, 3.0)
final_score = min(TC + CQ + BS + VC + total_bonus, 15.0)
```

### Entry/Exit Rules

**Entry trigger** (all required):

| Condition | Requirement |
|-----------|-------------|
| Price | > pivot_high × 1.01 |
| Volume | > avg20d × 1.5 (prefer 2.0×) |
| CLV | ≥ 0.65 |
| Time | Prefer after 10:30 AM ET |

> High tight flag exception: allow entry on first up-day after flag low even with volume as low as 1.3× — flag volume confirmation often lags one day.

**Stop loss**:
```python
if pattern in ('vcp', 'flat_base', 'ascending_base'):
    stop = platform_low × 0.98
elif pattern == 'high_tight_flag':
    stop = flag_low × 0.985
elif pattern == 'loose_base':
    stop = entry − 1.5 × ATR
stop = max(stop, entry × 0.92)   # floor: never more than 8% below entry
```

**Target**:
```
target = entry + 3.0 × (entry − stop)   # 3R baseline
# S-tier with raw score > 16: extend to 4R
```

**Trailing stops**: 4-stage common framework.

---

## Strategy B: PullbackEntry

**Type**: Long Only  
**Version**: 4.0 (unchanged)  
**Regime**: Bull primary; neutral good  
**Dimensions**: TI, RC, VC, BONUS  
**Description**: Institutional-grade pullback to EMA support in an established uptrend.

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| EMA21 slope | Positive (S_norm > 0) |
| Price vs EMA21 | Price > EMA21 |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K shares |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| TI | 5.0 | Trend Intensity — EMA21 slope normalized by ATR |
| RC | 5.0 | Retracement Composite — range, EMA8 support, gaps |
| VC | 5.0 | Volume Confirmation — dry up + surge pattern |
| BONUS | 2.0 | Sector resonance, no gap veto |

### Dimension 1: TI (Trend Intensity)

```
S_norm = (EMA21_today − EMA21_5d) / ATR14
```

| S_norm | Score |
|--------|-------|
| > 1.2 | 5.0 |
| 0.8–1.2 | 4.0–5.0 (interpolate) |
| 0.4–0.8 | 2.0–4.0 (interpolate) |
| 0–0.4 | 0–2.0 (interpolate) |
| < 0 | 0 → reject |

**EMA touch penalty**: −0.5 per EMA21 touch in last 20 days, capped at −1.0 (reduced from −1.5 in v4.0 to avoid over-penalizing healthy trends).

### Dimension 2: RC (Retracement Composite)

**Requirements**: Price > EMA21; pullback range < 8% from high; price within 1.5% of EMA8.

| Factor | Score |
|--------|-------|
| Range tightness (< 5% = 2.0, 5–8% = 1.0–2.0) | 0–2.0 |
| EMA8 support quality (within 1% = 2.0, 1–1.5% = 1.0–2.0) | 0–2.0 |
| No gap-down > 0.8×ATR in pullback | 0–1.0 |

### Dimension 3: VC (Volume Confirmation)

```
Volume_Dry  = vol_today / vol_20d < 0.7
Volume_Surge = vol_today / vol_20d > 1.5
```

| Pattern | Score |
|---------|-------|
| Dry up + surge | 5.0 |
| Surge only | 3.0 |
| Dry up only | 2.0 |
| Neither | 0 |

### Dimension 4: BONUS

| Factor | Score |
|--------|-------|
| Sector ETF alignment (sector > EMA21 + positive slope) | 0–1.0 |
| No gap-down veto (no gap > 1.5×ATR in last 5d) | 0–1.0 |

### Entry/Exit Rules

**Entry**: Price > EMA21 with positive slope; first touch or retest of EMA8/21; volume dry-up or surge present.

**Stop loss**:
```python
stop = min(
    five_day_low,
    EMA21 − ATR,
    entry − 1.2 × ATR
)
```

**Target**: `entry + 3.0 × (entry − stop)`

**Trailing stops**: 4-stage common framework (Stage 4 uses EMA5 instead of EMA8).

---

## Strategy C: SupportBounce

**Type**: Long Only (regime-adaptive)  
**Version**: 5.0 (modified from 4.0)  
**Regime**: Neutral primary; bull good; bear reduced size  
**Dimensions**: SQ, VD, RB  
**Description**: False breakdown below a proven support level followed by swift reclaim. Operates in all regimes with position size scaled to risk environment. SPY hard gate removed.

### Key Changes from v4.0

- `SPY > EMA200` hard gate removed — strategy now fires in bear markets at reduced position size
- Reclaim window widened: 1–5 days scored continuously (was binary 3d cliff)
- Depth range expanded: 2–10% (was 3–7%)
- Regime scalar applied to final position size (see Common Framework)

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Price vs EMA50 | Price within 15% above or below EMA50 |
| Support level | ≥ 2 prior touches at level in last 60d |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K shares |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| SQ | 4.0 | Support Quality — EMA structure, touch history |
| VD | 5.0 | Volume Dynamics — climax, dry-up, surge sequence |
| RB | 6.0 | Rebound — depth, reclaim speed, sector alignment |

### Dimension 1: SQ (Support Quality)

**EMA structure scoring**:

| Condition | Score |
|-----------|-------|
| Price > EMA50 AND EMA8 > EMA21 | 4.0 |
| Price > EMA50 only | 2.5 |
| Price < EMA50 AND EMA8 > EMA21 (bear bounce) | 1.5 |
| Neither (broken trend) | 0 |

> v5.0 change: bear bounces now score 1.5 instead of 0. This enables the strategy to fire in bear regimes at reduced size.

**Touch history bonus**: +0.5 if support has ≥ 4 prior touches in last 90 days (strong established level). Not capped — adds to base score up to SQ max of 4.0.

### Dimension 2: VD (Volume Dynamics)

**Pattern**: Climax selloff → dry-up → surge on reclaim

| Pattern | Score |
|---------|-------|
| Climax + dry-up + surge | 5.0 |
| Dry-up + surge | 4.0 |
| Surge only | 2.5 |
| Dry-up only | 1.5 |
| None | 0 |

**Climax definition**: Any single down-day with volume > 2.5× avg20d within the false breakdown window (last 5 days).

### Dimension 3: RB (Rebound)

**Depth scoring (0–2.5 pts)**:

Optimal false breakdown: stock dips below support, creates fear, then reclaims.

| Depth below support | Score |
|--------------------|-------|
| 2%–4% | 2.0–2.5 (interpolate, peak at 3%) |
| 4%–7% | 2.5–1.5 (interpolate, degrades with depth) |
| 7%–10% | 1.5–0.5 (interpolate) |
| < 2% | 0.5–2.0 (interpolate; too shallow) |
| > 10% | 0 (structure likely broken) |

**Reclaim speed (0–2.5 pts)**:

```
reclaim_days = days from undercut low to close above support
```

| Reclaim Days | Score |
|--------------|-------|
| 1 day | 2.5 |
| 2 days | 2.0 |
| 3 days | 1.5 |
| 4 days | 1.0 |
| 5 days | 0.5 |
| > 5 days | 0 |

**Sector alignment (0–1.0 pts)**:

| Condition | Score |
|-----------|-------|
| Sector ETF above EMA21 | 1.0 |
| Sector ETF between EMA21 and EMA50 | 0.5 |
| Sector ETF below EMA50 | 0 |

**RB Max: 6.0**

### Entry/Exit Rules

**Entry**: Price closes above support level; volume ≥ 1.5×avg20d on reclaim day; within 5-day reclaim window.

**Stop loss**:
```python
stop = max(
    undercut_low − 0.3 × ATR,
    entry × 0.95
)
```

**Target**:
```
target = entry + 2.5 × (entry − stop)   # 2.5R
# In bear regime: reduce to 2.0R (mean reversion target, not trend continuation)
```

**Position sizing**: Base tier size × regime scalar (see Common Framework).

---

## Strategy E1: DistributionTop

**Type**: Short Only  
**Version**: 5.0 (new — split from E: DoubleTopBottom + absorbs D: RangeShort logic)  
**Regime**: Neutral primary; bear primary; bull sector-weak only  
**Dimensions**: TQ, RL, DS, VC  
**Description**: Short stocks forming distribution tops at multi-week highs, in downtrending sectors or bear market environments. Incorporates the sector-weak pattern from retired RangeShort strategy.

### Market Environment Rules

| SPY Regime | Action |
|------------|--------|
| Bull (SPY > EMA50 > EMA200) | Only allow if stock's sector ETF < EMA50 (sector-weak exception) |
| Neutral | Full operation |
| Bear | Full operation, prefer higher position size |
| Extreme VIX | Allow but cap at Tier B (5%) — patterns unreliable in panic |

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Price vs EMA50 | Price ≤ EMA50 × 1.05 (not strongly extended above) |
| EMA alignment | EMA8 ≤ EMA21 × 1.02 (not in strong uptrend) |
| Near recent high | Price within 8% of 60d high |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K shares |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| TQ | 4.0 | Trend Quality — EMA alignment, sector weakness |
| RL | 4.0 | Resistance Level — touch quality, interval, width |
| DS | 4.0 | Distribution Signs — volume, price action at top |
| VC | 3.0 | Volume Confirmation — breakdown surge |
| **Total** | **15.0** | |

### Dimension 1: TQ (Trend Quality)

**EMA alignment (0–2.5 pts)**:

| Condition | Score |
|-----------|-------|
| Price < EMA50 AND EMA8 < EMA21 | 2.5 |
| Price < EMA50 only | 1.5 |
| Price > EMA50 but EMA8 < EMA21 (rolling over) | 1.0 |
| Price > EMA50 AND EMA8 > EMA21 | 0 → reject unless sector-weak |

**Sector weakness (0–1.5 pts)**:

| Condition | Score |
|-----------|-------|
| Sector ETF < EMA50 AND declining | 1.5 |
| Sector ETF between EMA50 and EMA200 | 0.8 |
| Sector ETF > EMA50 | 0 (unless bull market exception already granted) |

**TQ Max: 4.0**

### Dimension 2: RL (Resistance Level)

**Touch count (0–1.5 pts)**:

| Touches at resistance in last 90d | Score |
|-----------------------------------|-------|
| ≥ 5 | 1.5 |
| 4 | 1.2 |
| 3 | 0.8 |
| 2 | 0.3 |
| < 2 | 0 |

**Interval quality (0–1.5 pts)**:
Minimum 5 days between touches (reduced from 10d in original E — more realistic).

| Avg days between touches | Score |
|--------------------------|-------|
| ≥ 14d | 1.5 |
| 7–14d | 0.8–1.5 (interpolate) |
| 5–7d | 0.3–0.8 (interpolate) |
| < 5d | 0 |

**Level width (0–1.0 pts)**:
Width = price range of resistance zone.

| Width | Score |
|-------|-------|
| 1.0–2.5×ATR | 1.0 |
| 0.5–1.0×ATR | 0.5 |
| > 3×ATR | 0.3 (too wide, level unclear) |

**RL Max: 4.0**

### Dimension 3: DS (Distribution Signs)

Distribution is the process of institutional selling disguised as sideways price action near a top. Detect it via volume and price behavior.

**Heavy volume on up-days at resistance (0–2.0 pts)**:
Count up-days in the resistance zone where volume > 1.5×avg20d.

| Heavy-vol up-days in zone | Score |
|---------------------------|-------|
| ≥ 3 | 2.0 |
| 2 | 1.3 |
| 1 | 0.6 |
| 0 | 0 |

**Price action exhaustion (0–2.0 pts)**:

| Signal | Score |
|--------|-------|
| Shooting star / bearish engulfing candle at level | +1.0 |
| Failed breakout above level (closed back below same day) | +1.0 |
| Multiple wicks above level (≥ 2 in last 10d) | +0.5 |
| Gap-up that faded to close below open | +0.5 |

Cap at 2.0 pts regardless of combination.

**DS Max: 4.0**

### Dimension 4: VC (Volume Confirmation)

**Breakdown volume surge — breakdown day / avg20d (0–2.0 pts)**:

| Breakdown Vol | Score |
|---------------|-------|
| ≥ 2.5× | 2.0 |
| 1.8–2.5× | 1.3–2.0 (interpolate) |
| 1.2–1.8× | 0.5–1.3 (interpolate) |
| < 1.2× | 0 |

**Follow-through (0–1.0 pts)**:
Score +1.0 if breakdown is confirmed by a second down-day on above-average volume within 2 sessions.

**VC Max: 3.0**

### Entry/Exit Rules

**Entry trigger** (all required):
- Price breaks below resistance level (closes < level − 0.3×ATR)
- Volume ≥ 1.5×avg20d on breakdown bar
- CLV ≤ 0.35 (closed in lower portion of bar)
- Not within 5 days of earnings (gap risk)

**Stop loss**:
```python
stop = min(
    resistance_high + 0.5 × ATR,   # just above the zone
    entry × 1.04                    # max 4% above entry
)
```

**Target**:
```
target = entry − 2.5 × (stop − entry)   # 2.5R
# Preferred target: next major support level if closer than 2.5R
```

**Trailing stops**: Short-side 4-stage common framework.

---

## Strategy E2: AccumulationBottom

**Type**: Long Only  
**Version**: 5.0 (new — split from E: DoubleTopBottom)  
**Regime**: Bear primary; extreme good; neutral weak  
**Dimensions**: TQ, AL, AS, VC  
**Description**: Long stocks forming accumulation bases at multi-week lows, showing signs of institutional buying in bear or recovery environments. The mirror of E1.

### Market Environment Rules

| SPY Regime | Action |
|------------|--------|
| Bull | Skip — MomentumBreakout (A) and PullbackEntry (B) dominate |
| Neutral | Allow weak signals only (B-tier max) |
| Bear | Full operation |
| Extreme VIX | Full operation — high-conviction setups only (A-tier min) |

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Near recent low | Price within 8% of 60d low |
| Volume | Avg 20d volume ≥ 200K shares (require more liquidity — catching falling knives is dangerous in illiquid names) |
| Market cap | ≥ $3B (higher than standard — bear market quality filter) |
| Listed age | > 180 days (no recent IPOs) |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| TQ | 4.0 | Trend Quality — EMA structure, oversold level |
| AL | 4.0 | Accumulation Level — touch quality, interval |
| AS | 4.0 | Accumulation Signs — volume and price behavior at low |
| VC | 3.0 | Volume Confirmation — reversal surge |
| **Total** | **15.0** | |

### Dimension 1: TQ (Trend Quality)

This dimension measures how overdone the decline is and how early the turn might be. The worse the EMA picture, the higher the oversold score — unlike other long strategies where good EMA alignment is rewarded.

**Oversold EMA state (0–2.5 pts)**:

| Condition | Score |
|-----------|-------|
| Price < EMA50 AND EMA8 < EMA21 (confirmed downtrend) | 2.5 |
| Price < EMA50 only | 1.5 |
| Price < EMA200 but EMA8 crossing EMA21 (early reversal) | 2.0 |

**RSI oversold level (0–1.5 pts)**:

| RSI | Score |
|-----|-------|
| < 25 | 1.5 |
| 25–30 | 1.0–1.5 (interpolate) |
| 30–35 | 0.5–1.0 (interpolate) |
| 35–40 | 0–0.5 (interpolate) |
| > 40 | 0 |

**TQ Max: 4.0**

### Dimension 2: AL (Accumulation Level)

Mirror of E1 RL but applied to support/lows.

**Touch count (0–1.5 pts)**:

| Touches at support in last 90d | Score |
|--------------------------------|-------|
| ≥ 5 | 1.5 |
| 4 | 1.2 |
| 3 | 0.8 |
| 2 | 0.3 |
| < 2 | 0 |

**Interval quality (0–1.5 pts)**:

| Avg days between touches | Score |
|--------------------------|-------|
| ≥ 14d | 1.5 |
| 7–14d | 0.8–1.5 (interpolate) |
| 5–7d | 0.3–0.8 (interpolate) |
| < 5d | 0 |

**Level width (0–1.0 pts)**:

| Width | Score |
|-------|-------|
| 1.0–2.5×ATR | 1.0 |
| 0.5–1.0×ATR | 0.5 |
| > 3×ATR | 0.3 |

**AL Max: 4.0**

### Dimension 3: AS (Accumulation Signs)

Mirror of E1 DS — detecting institutional buying quietly while price oscillates at the bottom.

**Low-volume down-days at support (0–2.0 pts)**:
Count down-days in the support zone where volume < 0.7×avg20d. Low-vol selling = no real pressure.

| Low-vol down-days in zone | Score |
|---------------------------|-------|
| ≥ 3 | 2.0 |
| 2 | 1.3 |
| 1 | 0.6 |
| 0 | 0 |

**Price action strength (0–2.0 pts)**:

| Signal | Score |
|--------|-------|
| Hammer / bullish engulfing candle at level | +1.0 |
| Failed breakdown below level (closed back above same day) | +1.0 |
| Multiple long lower wicks at level (≥ 2 in last 10d) | +0.5 |
| Gap-down that reversed to close above open | +0.5 |

Cap at 2.0 pts.

**AS Max: 4.0**

### Dimension 4: VC (Volume Confirmation)

**Reversal surge — best up-day in zone / avg20d (0–2.0 pts)**:

| Reversal Vol | Score |
|--------------|-------|
| ≥ 2.5× | 2.0 |
| 1.8–2.5× | 1.3–2.0 (interpolate) |
| 1.2–1.8× | 0.5–1.3 (interpolate) |
| < 1.2× | 0 |

**Follow-through (0–1.0 pts)**:
+1.0 if reversal is confirmed by a second up-day on above-average volume within 2 sessions.

**VC Max: 3.0**

### Entry/Exit Rules

**Entry trigger** (all required):
- Price closes above support level (closes > level + 0.3×ATR)
- Volume ≥ 1.5×avg20d on reversal bar
- CLV ≥ 0.60 (closed in upper portion of bar)
- Not within 5 days of earnings

**Stop loss**:
```python
stop = max(
    support_low − 0.5 × ATR,
    entry × 0.94    # max 6% below entry (wider than usual — bottoms are messy)
)
```

**Target**:
```
target = entry + 2.0 × (entry − stop)   # 2.0R baseline
# Preferred target: EMA50 if within 15% above entry
# In extreme regime: reduce to 1.5R — partial take at resistance
```

**Trailing stops**: 4-stage common framework. In extreme regime use Stage 2 trigger at +1.5×risk (tighter — extreme rebounds fail often).

---

## Strategy F: CapitulationRebound

**Type**: Long Only  
**Version**: 5.0 (modified from 4.0)  
**Regime**: Extreme primary; bear good  
**Dimensions**: MO, EX, VC  
**Description**: Individual stock capitulation bottom detection using extreme RSI, price extension, and volume climax. Exempt from extreme-regime position size reduction.

### Key Changes from v4.0

- VIX filter inverted: VIX < 15 = REJECT (no fear = no capitulation); VIX 15–35 = full operation; VIX > 35 = Tier B max (5%) — extreme panic creates false bottoms
- RSI threshold tightened: hard gate raised from RSI < 20 to RSI < 22 to widen the candidate pool modestly
- Position size exempt from extreme-regime 0.3× scalar

### Pre-Filter Requirements

ALL must be true:
- RSI < 22 (extreme oversold)
- Price < EMA50 − 4×ATR (extended below; was 5× in v4.0)
- ≥ 2 gaps down in last 5 days (acceleration)
- Dollar volume > $50M avg20d (liquidity)
- Listed > 50 days (no recent IPOs)
- VIX between 15 and 35 (if VIX < 15: reject; if VIX > 35: Tier B cap)

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| MO | 5.0 | Momentum Overextension — RSI, price vs EMA50 |
| EX | 6.0 | Extension Level — distance from EMA50, gaps |
| VC | 4.0 | Volume Confirmation — climax candle |
| **Total** | **15.0** | |

### Dimension 1: MO (Momentum Overextension)

**RSI scoring (0–3.0 pts)**:

| RSI | Score |
|-----|-------|
| < 12 | 3.0 |
| 12–15 | 2.5–3.0 (interpolate) |
| 15–18 | 2.0–2.5 (interpolate) |
| 18–22 | 1.0–2.0 (interpolate) |

**Price vs EMA50 distance (0–2.0 pts)**:

```
dist_pct = (EMA50 − price) / EMA50 × 100
```

| Distance | Score |
|----------|-------|
| > 25% | 2.0 |
| 20–25% | 1.5–2.0 (interpolate) |
| 15–20% | 1.0–1.5 (interpolate) |
| 10–15% | 0.5–1.0 (interpolate) |
| < 10% | 0 |

**MO Max: 5.0**

### Dimension 2: EX (Extension Level)

**ATR-based extension (0–3.0 pts)**:

```
atr_extension = (EMA50 − price) / ATR14
```

| ATR Extension | Score |
|---------------|-------|
| > 8× | 3.0 |
| 6–8× | 2.0–3.0 (interpolate) |
| 4–6× | 1.0–2.0 (interpolate) |
| < 4× | 0–1.0 (interpolate) |

**Gap acceleration bonus (0–2.0 pts)**:
Count gap-down days in last 5 sessions (open < prior close × 0.99).

| Gap-down days in 5d | Score |
|---------------------|-------|
| ≥ 4 | 2.0 |
| 3 | 1.5 |
| 2 | 1.0 |

**Consecutive down-day streak (0–1.0 pts)**:

| Consecutive down-days | Score |
|-----------------------|-------|
| ≥ 7 | 1.0 |
| 5–6 | 0.6 |
| 3–4 | 0.3 |

**EX Max: 6.0**

### Dimension 3: VC (Volume Confirmation)

**Volume climax ratio — today / avg20d (0–3.0 pts)**:

| Volume Ratio | Score |
|--------------|-------|
| > 5.0× | 3.0 |
| 4.0–5.0× | 2.5–3.0 (interpolate) |
| 3.0–4.0× | 2.0–2.5 (interpolate) |
| 2.0–3.0× | 1.0–2.0 (interpolate) |
| 1.5–2.0× | 0.3–1.0 (interpolate) |
| < 1.5× | 0 |

**Capitulation candle bonus (+1.0 pt)**:
Award if CLV > 0.65 AND volume > 1.5×avg20d on the same day. Indicates intraday reversal after panic — the stock found buyers before close.

**VC Max: 4.0**

### Entry/Exit Rules

**Entry**: End-of-day close (EOD only — no intraday entry on capitulation day).

**Stop loss**:
```
stop = entry − 2.0 × ATR
```

**Target**:
```
target = EMA50   # mean reversion, not trend continuation
```

**Time stop**: Exit if price has not moved toward target by > 5% within 10 trading days.

**Trailing stops**: Standard 4-stage, but Stage 2 trigger reduced to entry + 1.5×risk — capitulation rebounds can reverse sharply.

---

## Strategy G: EarningsGap

**Type**: Long or Short (direction set by gap direction + confirmation)  
**Version**: 5.0 (new)  
**Regime**: Bull/neutral primary (long); neutral/bear (short)  
**Dimensions**: GS, QC, TC, VC  
**Description**: Post-earnings gap continuation plays. Enters after the gap has held for 1–2 days, confirming institutional conviction rather than chasing the initial reaction.

### Concept

Earnings gaps create their own momentum independent of market regime. A stock that gaps up 8% on earnings and holds above the gap zone for a day has demonstrated institutional demand at the new price level. The entry is the continuation, not the initial gap.

Two valid setups:
- **Gap-up continuation (long)**: Stock gaps up, consolidates 1–2 days at/above gap zone, then breaks higher.
- **Gap-down continuation (short)**: Stock gaps down, bounces weakly for 1–2 days (stays below gap zone), then resumes lower.

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Earnings gap | Gap ≥ 5% on earnings day (open vs prior close) |
| Days since earnings | 1–5 trading days (fresh gap only) |
| Dollar volume on gap day | > $100M (high-attention event) |
| Market cap | ≥ $2B |
| Price | > $10 (avoid low-priced volatile names) |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| GS | 5.0 | Gap Strength — size, type, initial reaction quality |
| QC | 4.0 | Quality of Consolidation — how price behaved post-gap |
| TC | 3.0 | Trend Context — pre-earnings trend, sector |
| VC | 3.0 | Volume Confirmation — gap day vol, consolidation vol |
| **Total** | **15.0** | |

### Direction Determination

```python
if gap_pct > 0 and price_holding_above_gap_zone:
    direction = 'LONG'
elif gap_pct < 0 and price_failing_to_reclaim_gap_zone:
    direction = 'SHORT'
else:
    return None   # ambiguous — skip
```

Gap zone = range between prior close and gap open.

### Dimension 1: GS (Gap Strength)

**Gap size (0–2.5 pts)**:

| Gap % | Score |
|-------|-------|
| ≥ 15% | 2.5 |
| 10–15% | 2.0–2.5 (interpolate) |
| 7–10% | 1.5–2.0 (interpolate) |
| 5–7% | 0.5–1.5 (interpolate) |

**Gap type — earnings beat quality (0–1.5 pts)**:

| Condition | Score |
|-----------|-------|
| Beat on revenue AND EPS, raised guidance | 1.5 |
| Beat on EPS only | 0.8 |
| Beat on revenue only | 0.6 |
| In-line (gap due to relief) | 0.3 |
| Miss with gap-down | 0.8 (gap-down setups: miss + guidance cut = strong short) |

> Use yfinance or Tavily earnings data for beat/miss classification.

**Initial gap bar quality (0–1.0 pts)**:

| Condition | Score |
|-----------|-------|
| CLV ≥ 0.75 on gap day (long) | 1.0 |
| CLV ≤ 0.25 on gap day (short) | 1.0 |
| Neutral CLV | 0.4 |

**GS Max: 5.0**

### Dimension 2: QC (Quality of Consolidation)

The 1–3 day post-gap behavior is the most important signal. Good gaps hold tight; bad gaps immediately give back.

**Gap zone hold (0–2.5 pts)**:

For long setups:
| Post-gap behavior | Score |
|-------------------|-------|
| Price stays within 2% above gap zone for 1–3d | 2.5 |
| Price dips into gap zone but recovers same day | 1.5 |
| Price fills > 50% of gap | 0 |

For short setups (mirror):
| Post-gap behavior | Score |
|-------------------|-------|
| Price stays within 2% below gap zone for 1–3d | 2.5 |
| Price bounces into gap zone but fails same day | 1.5 |
| Price recovers > 50% of gap | 0 |

**Consolidation tightness (0–1.5 pts)**:
High-low range of consolidation days as % of gap size.

| Range / Gap size | Score |
|-----------------|-------|
| < 20% | 1.5 (very tight) |
| 20–40% | 1.0–1.5 (interpolate) |
| 40–60% | 0.5–1.0 (interpolate) |
| > 60% | 0 (sloppy) |

**QC Max: 4.0**

### Dimension 3: TC (Trend Context)

**Pre-earnings trend alignment (0–2.0 pts)**:

For long setups:
| Condition | Score |
|-----------|-------|
| Stock was above EMA50 before earnings | +1.0 |
| RS percentile > 60th before earnings | +1.0 |

For short setups (inverted):
| Condition | Score |
|-----------|-------|
| Stock was below EMA50 before earnings | +1.0 |
| RS percentile < 40th before earnings | +1.0 |

**Sector alignment (0–1.0 pts)**:

| Condition | Score |
|-----------|-------|
| Sector ETF trending same direction as gap | 1.0 |
| Sector ETF neutral | 0.5 |
| Sector ETF opposing gap direction | 0 |

**TC Max: 3.0**

### Dimension 4: VC (Volume Confirmation)

**Gap day volume (0–2.0 pts)**:

| Gap day vol / avg20d | Score |
|----------------------|-------|
| ≥ 5× | 2.0 |
| 3–5× | 1.5–2.0 (interpolate) |
| 2–3× | 1.0–1.5 (interpolate) |
| 1–2× | 0–1.0 (interpolate) |

**Consolidation volume behavior (0–1.0 pts)**:

| Pattern | Score |
|---------|-------|
| Volume declining each day post-gap (healthy cooldown) | 1.0 |
| Volume flat | 0.5 |
| Volume increasing on quiet days (erratic) | 0 |

**VC Max: 3.0**

### Entry/Exit Rules

**Entry trigger** (all required):
- 1–5 days after earnings gap
- For long: price breaks above consolidation high with volume ≥ 1.5×avg20d
- For short: price breaks below consolidation low with volume ≥ 1.5×avg20d
- Not on earnings day itself (gap too volatile to enter)

**Stop loss**:
```python
# Long
stop = gap_open × 0.98   # just below gap zone
stop = max(stop, entry × 0.93)

# Short
stop = gap_open × 1.02   # just above gap zone
stop = min(stop, entry × 1.07)
```

**Target**:
```
# Long: 3R from entry
target = entry + 3.0 × (entry − stop)

# Short: 2.5R from entry (earnings shorts tend to bounce)
target = entry − 2.5 × (stop − entry)
```

**Time stop**: If no progress toward target within 5 trading days, exit. Earnings gaps either work quickly or fail.

---

## Strategy H: RelativeStrengthLong

**Type**: Long Only  
**Version**: 5.0 (new)  
**Regime**: Bear primary; extreme good; neutral weak  
**Dimensions**: RD, SH, CQ, VC  
**Description**: Buys stocks demonstrating extreme relative strength against a weak or declining broad market. These are the institutional accumulation stories — defensive sector rotations, turnaround narratives, sector leaders — that hold up or make new highs while SPY is selling off. Explicitly designed as the bear-market long engine.

### Concept

In bear markets, not everything goes down. At any given time, 5–15% of stocks are in strong uptrends regardless of SPY. These are not random — they represent deliberate institutional positioning in names that offer either safety (dividends, defensive revenues) or a compelling growth narrative that overrides macro. Buying these is low-risk because their relative strength is itself a form of risk management: an RS leader in a bear market has a natural bid.

### Market Environment Gate

**Hard gate**: Only activate when SPY is in one of:
- Bear regime (SPY < EMA50 AND EMA50 < EMA200)
- Neutral regime with declining EMA50
- Extreme VIX regime

Skip entirely in bull regime — MomentumBreakout handles bull leaders.

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| RS percentile vs SPY (63d) | ≥ 80th (strict — only true leaders qualify) |
| SPY regime | Bear or neutral-declining (hard gate) |
| Price vs 52w high | Within 15% of 52w high |
| Price vs EMA200 | Price > EMA200 (stock must be in its own uptrend) |
| Market cap | ≥ $3B (quality filter — large caps hold RS in bear markets better) |
| Avg 20d volume | ≥ 200K shares |

### Scoring Dimensions

| Dimension | Max | Description |
|-----------|-----|-------------|
| RD | 6.0 | RS Divergence — how far stock diverges from SPY |
| SH | 4.0 | Structure Health — stock's own technical picture |
| CQ | 3.0 | Consolidation Quality — how it's handling the market weakness |
| VC | 2.0 | Volume Confirmation — accumulation pattern |
| **Total** | **15.0** | |

### Dimension 1: RD (RS Divergence)

This is the core dimension. The more extreme the divergence from SPY, the higher the score.

**RS percentile (0–3.0 pts)**:

| RS Percentile (63d vs universe) | Score |
|---------------------------------|-------|
| ≥ 95th | 3.0 |
| 90th–95th | 2.5–3.0 (interpolate) |
| 85th–90th | 1.5–2.5 (interpolate) |
| 80th–85th | 0.5–1.5 (interpolate) |
| < 80th | 0 → pre-filter catches this |

**Absolute divergence — stock return vs SPY return over 20d (0–2.0 pts)**:

```
divergence = stock_return_20d − SPY_return_20d
```

| Divergence | Score |
|------------|-------|
| > +15% | 2.0 |
| +10–15% | 1.5–2.0 (interpolate) |
| +5–10% | 0.8–1.5 (interpolate) |
| +2–5% | 0.3–0.8 (interpolate) |
| < +2% | 0 |

**Consistency — RS rank stability over last 10d (0–1.0 pts)**:
Score 1.0 if RS percentile has been ≥ 75th for all of last 10 trading days (not a one-day spike).

**RD Max: 6.0**

### Dimension 2: SH (Structure Health)

The stock must be technically sound in its own right — RS alone is not enough.

**EMA alignment (0–2.0 pts)**:

| Condition | Score |
|-----------|-------|
| Price > EMA21 > EMA50 > EMA200 (full stack) | 2.0 |
| Price > EMA50 > EMA200 | 1.5 |
| Price > EMA200 only | 0.8 |
| Price < EMA200 | 0 → reject |

**52-week high proximity (0–1.5 pts)**:

| Distance from 52w high | Score |
|------------------------|-------|
| Within 5% | 1.5 |
| 5–10% | 1.0–1.5 (interpolate) |
| 10–15% | 0.5–1.0 (interpolate) |
| > 15% | 0 |

**Recent trend (0–0.5 pts)**:
Score 0.5 if 5d return > 0 (stock is still going up, not just declining less than SPY).

**SH Max: 4.0**

### Dimension 3: CQ (Consolidation Quality)

How the stock is handling the broad market weakness. A leader should be consolidating tightly rather than chopping wildly.

**Volatility vs SPY (0–1.5 pts)**:
```
relative_volatility = stock_ATR_pct / SPY_ATR_pct
# ATR_pct = ATR14 / price
```

| Relative Volatility | Score |
|--------------------|-------|
| < 0.8 (calmer than SPY) | 1.5 |
| 0.8–1.2 | 0.8–1.5 (interpolate) |
| 1.2–1.8 | 0.2–0.8 (interpolate) |
| > 1.8 | 0 (too volatile — not a RS leader, just a bouncing stock) |

**Base quality during SPY weakness (0–1.5 pts)**:
Measure the stock's price range % during the last 10d of SPY weakness.

| Stock range % in last 10d | Score |
|---------------------------|-------|
| < 5% (holding tight) | 1.5 |
| 5–8% | 1.0–1.5 (interpolate) |
| 8–12% | 0.5–1.0 (interpolate) |
| > 12% | 0 |

**CQ Max: 3.0**

### Dimension 4: VC (Volume Confirmation)

**Accumulation pattern (0–2.0 pts)**:
In last 15 days, compare up-day average volume vs down-day average volume.

```
accum_ratio = avg_volume_on_up_days / avg_volume_on_down_days
```

| Accumulation Ratio | Score |
|--------------------|-------|
| > 2.0 | 2.0 (strong buying on up-days) |
| 1.5–2.0 | 1.5–2.0 (interpolate) |
| 1.2–1.5 | 0.8–1.5 (interpolate) |
| 1.0–1.2 | 0.3–0.8 (interpolate) |
| < 1.0 | 0 (distribution pattern — not a true RS leader) |

**VC Max: 2.0**

### Entry/Exit Rules

**Entry trigger** (all required):
- RS percentile ≥ 80th for 5+ consecutive days
- Price > EMA21 with positive slope
- Volume on entry day ≥ 1.2×avg20d (modest requirement — RS leaders tend to trade quietly)
- Preferably entering on a pullback day when SPY is down (buy the dip in a relative sense)

**Stop loss**:
```python
stop = max(
    EMA50 × 0.99,           # just below EMA50 (if stock loses EMA50, RS story is over)
    entry × 0.93            # max 7% below entry
)
```

**Target**:
```
# Primary: 3R from entry
target = entry + 3.0 × (entry − stop)

# Secondary: trail and hold if SPY starts recovering
# When SPY crosses back above EMA21, transition to trailing stop immediately
# — the RS advantage disappears in a recovery and stock may underperform
```

**Regime exit rule**: If SPY regime shifts from bear to neutral with EMA50 turning up, move immediately to Stage 3 trailing stop (Chandelier) regardless of P&L stage. The edge disappears when the market recovers.

**Trailing stops**: 4-stage common framework. Apply regime exit rule above as an override.

---

## Phase 1 Allocation Table

Phase 1 market sentiment analysis determines slot allocation per strategy. The AI should reference this table when generating allocation. Total slots = 10 across all strategies.

| Regime | A | B | C | E1 | E2 | F | G | H | Notes |
|--------|---|---|---|----|----|---|---|---|-------|
| Bull strong | 3 | 3 | 1 | 0 | 0 | 0 | 2 | 0 | Long bias max |
| Bull moderate | 3 | 2 | 1 | 0 | 0 | 0 | 2 | 1 | Small H allocation |
| Neutral | 2 | 2 | 2 | 1 | 1 | 0 | 1 | 1 | Balanced |
| Bear moderate | 1 | 1 | 1 | 2 | 2 | 1 | 0 | 2 | Bear/RS focus |
| Bear strong | 0 | 0 | 1 | 2 | 2 | 2 | 0 | 3 | Short + RS + cap |
| Extreme VIX | 0 | 0 | 0 | 1 | 1 | 4 | 0 | 3 | Capitulation focus |

> Strategies with 0 slots skip Phase 2 screening entirely — no computation wasted.

---

## Maintenance Log

| Date | Change |
|------|--------|
| 2025-04 | v5.0 — 8-strategy bundle; A redesigned; C adaptive; D removed; E split; F VIX fixed; G and H added |
| 2025-04 | v4.0 — 6 strategies, actual dimensions aligned with codebase |
| 2025-04 | v3.5 — 3-tier pre-calculation architecture |
| 2025-03 | v2.1 — Expert suggestions implementation |
| 2025-03 | v2.0 — 4D scoring system unification |
