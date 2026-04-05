# Strategy Description

Precise specifications for all 8 trading strategies.

**Version**: 6.0  
**Last Updated**: 2026-04

---

## Table of Contents

1. [Common Framework](#common-framework)
2. [Strategy A: MomentumBreakout](#strategy-a-momentumbreakout)
3. [Strategy B: PullbackEntry](#strategy-b-pullbackentry)
4. [Strategy C: SupportBounce](#strategy-c-supportbounce)
5. [Strategy D: DistributionTop](#strategy-d-distributiontop)
6. [Strategy E: AccumulationBottom](#strategy-e-accumulationbottom)
7. [Strategy F: CapitulationRebound](#strategy-f-capitulationrebound)
8. [Strategy G: EarningsGap](#strategy-g-earningsgap)
9. [Strategy H: RelativeStrengthLong](#strategy-h-relativestrengthlong)
10. [Allocation Table](#allocation-table)

---

## Common Framework

### Scoring & Tiers

| Score | Tier | Position |
|-------|------|----------|
| 12–15 | S | 20% |
| 9–11.99 | A | 10% |
| 7–8.99 | B | 5% |
| < 7 | C | 0% |

### Regime-Adaptive Position Sizing

| Regime | Long | Short | Exemptions |
|--------|------|-------|------------|
| bull_strong | 1.0× | 0.3× | None |
| bull_moderate | 1.0× | 0.3× | None |
| neutral | 0.8× | 0.8× | None |
| bear_moderate | 0.5× | 1.0× | None |
| bear_strong | 0.5× | 1.0× | None |
| extreme_vix | 0.3× | 0.5× | F, H get 1.0× |

### Linear Interpolation

```python
def interpolate(value, min_val, max_val, min_score, max_score):
    if value <= min_val: return min_score
    if value >= max_val: return max_score
    return min_score + (value - min_val) / (max_val - min_val) * (max_score - min_score)
```

### Indicators

```
ATR14: SMA of TR where TR = max(H−L, |H−C_prev|, |L−C_prev|)
EMA: multiplier = 2/(period+1); EMA = C×mult + EMA_prev×(1−mult)
RSI14: 100 − 100/(1 + RS); RS = SMA(gain,14)/SMA(loss,14)
CLV: (close − low) / (high − low)
RS_percentile: percentile_rank(stock_63d_return / SPY_63d_return, universe)
```

### Trailing Stops (4-stage)

| Stage | Trigger | Action |
|-------|---------|--------|
| 1→2 | +1×risk | Stop to breakeven |
| 2→3 | +2.5×risk | Stop at +1×risk |
| 3→4 | +4×risk | Chandelier = HH − 3×ATR |
| 4 (extended) | Price > 1.20×EMA21 | Trail EMA8 daily |

Short-side inverted. Chandelier = LL + 3×ATR.

---

## Strategy A: MomentumBreakout

**Type**: Long | **Regime**: Bull, neutral weak | **Dimensions**: TC(5), CQ(4), BS(4), VC(4) + Bonus(3)

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| RS percentile | ≥ 50th (hard gate) |
| Price > EMA200 | Required |
| 3-month return | ≥ −20% |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K |

### TC (Trend Context) — Max 5.0

**RS Strength (0–2.0)**: ≥90th=2.0, 75–90th=1.5–2.0, 60–75th=1.0–1.5, 50–60th=0.5–1.0, <50th=0→reject

**EMA Structure (0–2.0)**: Price>EMA50×1.05=+1.0, Price>EMA200=+0.5, EMA50>EMA200=+0.5

**52w High (0–1.0)**: ≤5%=1.0, 5–15%=interpolate, >15%=0

### CQ (Consolidation Quality) — Max 4.0

**Pattern detection** (first match wins):

| Pattern | Requirements | Score Range |
|---------|--------------|-------------|
| VCP | 15–60d, range<12%, >50% days ±2.5%, last 5d vol<70% avg, ≥2 waves | 0.80–1.00 |
| High tight flag | Prior +30% in ≤8w, pullback 8–30%, flag 2–6w | 0.61–0.72 |
| Flat base | Range<15%, EMA21 slope<0.3×ATR/5d, 3–15w | 0.55–0.75 |
| Ascending | ≥3 higher lows, range 10–25%, 4–12w | 0.62 |
| Loose | Range<20%, ≥10d | 0.15–0.40 |

```
cq_base = pattern_score × 3.0
Duration: 3–10w=1.0, 2–3w=0.4–1.0, 10–15w=0.5–1.0, <2w=0.2, >15w=0.3
CQ = min(cq_base + duration, 4.0)
```

### BS (Breakout Strength) — Max 4.0

| Breakout % | Score | Energy Ratio (vol/avg20d) | Score |
|------------|-------|---------------------------|-------|
| ≥5% | 2.5 | ≥3.0× | 1.5 |
| 3–5% | 2.0–2.5 | 2–3× | 1.0–1.5 |
| 2–3% | 1.5–2.0 | 1.5–2× | 0.5–1.0 |
| 1–2% | 0.5–1.5 | 1–1.5× | 0–0.5 |
| <1% | 0–0.5 | <1× | 0 |

### VC (Volume Confirmation) — Max 4.0

| Base Vol (last 5d/avg20d) | Score | Breakout Vol | Score | CLV | Score |
|---------------------------|-------|--------------|-------|-----|-------|
| <0.50 | 2.0 | ≥3× | 1.5 | ≥0.85 | 0.5 |
| 0.50–0.65 | 1.5–2.0 | 2–3× | 1.0–1.5 | 0.65–0.85 | 0–0.5 |
| 0.65–0.80 | 0.8–1.5 | 1.5–2× | 0.5–1.0 | <0.65 | 0 |
| 0.80–1.00 | 0.2–0.8 | <1.5× | 0–0.5 | | |
| >1.00 | 0 | | | | |

### Bonus Pool — Max 3.0

| Bonus | Max | Condition |
|-------|-----|-----------|
| VCP structure | 2.0 | vol_contraction + range_contraction + wave_count |
| Sector leadership | 0.5 | Sector ETF RS≥80th AND >EMA50 |
| Earnings catalyst | 0.5 | 7–21 days to earnings |
| Accumulation divergence | 0.5 | OBV rising, price flat (linreg divergence) |

### Entry/Exit

**Entry**: Price>pivot×1.01, Vol>1.5×avg20d, CLV≥0.65, prefer after 10:30 AM ET

**Stop**:
```python
if pattern in ('vcp', 'flat_base', 'ascending_base'): stop = platform_low × 0.98
elif pattern == 'high_tight_flag': stop = flag_low × 0.985
elif pattern == 'loose_base': stop = entry − 1.5 × ATR
stop = max(stop, entry × 0.92)  # floor: max 8% below entry
```

**Target**: `entry + 3.0 × (entry − stop)` (extend to 4R if S-tier, raw>16)

---

## Strategy B: PullbackEntry

**Type**: Long | **Regime**: Bull, neutral | **Dimensions**: TI(5), RC(5), VC(5), BONUS(2)

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| EMA21 slope | Positive (S_norm > 0) |
| Price > EMA21 | Required |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K |

### TI (Trend Intensity) — Max 5.0

```
S_norm = (EMA21_today − EMA21_5d) / ATR14
```

| S_norm | Score |
|--------|-------|
| >1.2 | 5.0 |
| 0.8–1.2 | 4.0–5.0 |
| 0.4–0.8 | 2.0–4.0 |
| 0–0.4 | 0–2.0 |
| <0 | 0→reject |

Penalty: −0.5 per EMA21 touch in 20d, max −1.0

### RC (Retracement Composite) — Max 5.0

Requirements: Price>EMA21, pullback<8% from high, price within 1.5% of EMA8

| Factor | Score |
|--------|-------|
| Range tightness (<5%=2.0, 5–8%=1.0–2.0) | 0–2.0 |
| EMA8 support (within 1%=2.0, 1–1.5%=1.0–2.0) | 0–2.0 |
| No gap-down >0.8×ATR in pullback | 0–1.0 |

### VC (Volume Confirmation) — Max 5.0

```
Volume_Dry = vol_today/vol_20d < 0.7
Volume_Surge = vol_today/vol_20d > 1.5
```

| Pattern | Score |
|---------|-------|
| Dry up + surge | 5.0 |
| Surge only | 3.0 |
| Dry up only | 2.0 |
| Neither | 0 |

### BONUS — Max 2.0

| Factor | Score |
|--------|-------|
| Sector ETF > EMA21 + positive slope | 0–1.0 |
| No gap-down veto (no gap >1.5×ATR in 5d) | 0–1.0 |

### Entry/Exit

**Entry**: Price>EMA21 positive slope; first touch/retest of EMA8/21; volume dry-up or surge

**Stop**: `min(five_day_low, EMA21−ATR, entry−1.2×ATR)`

**Target**: `entry + 3.0 × (entry − stop)`

**Trailing**: Stage 4 uses EMA5 instead of EMA8

---

## Strategy C: SupportBounce

**Type**: Long (regime-adaptive) | **Regime**: Neutral, bull, bear | **Dimensions**: SQ(4), VD(5), RB(6)

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Price vs EMA50 | Within ±15% |
| Support level | ≥2 touches in 60d |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K |

### SQ (Support Quality) — Max 4.0

| EMA Structure | Score |
|---------------|-------|
| Price>EMA50 AND EMA8>EMA21 | 4.0 |
| Price>EMA50 only | 2.5 |
| Price<EMA50 AND EMA8>EMA21 (bear bounce) | 1.5 |
| Neither | 0 |

Bonus: +0.5 if ≥4 prior touches in 90d (capped at 4.0)

### VD (Volume Dynamics) — Max 5.0

| Pattern | Score |
|---------|-------|
| Climax + dry-up + surge | 5.0 |
| Dry-up + surge | 4.0 |
| Surge only | 2.5 |
| Dry-up only | 1.5 |
| None | 0 |

Climax: down-day vol>2.5×avg20d within last 5d

### RB (Rebound) — Max 6.0

**Depth (0–2.5)**: 2–4%=2.0–2.5 (peak 3%), 4–7%=1.5–2.5, 7–10%=0.5–1.5, <2%=0.5–2.0, >10%=0

**Reclaim speed (0–2.5)**: 1d=2.5, 2d=2.0, 3d=1.5, 4d=1.0, 5d=0.5, >5d=0

**Sector (0–1.0)**: Sector>EMA21=1.0, EMA21–EMA50=0.5, <EMA50=0

### Entry/Exit

**Entry**: Close>support+0.3×ATR, Vol≥1.5×avg20d, CLV≥0.60, not within 5d of earnings

**Stop**: `max(support_low−0.5×ATR, entry×0.94)`

**Target**: `entry + 2.5 × (entry − stop)` (2.0R in bear)

---

## Strategy D: DistributionTop

**Type**: Short | **Regime**: Neutral, bear, bull (sector-weak only) | **Dimensions**: TQ(4), RL(4), DS(4), VC(3)

### Market Rules

| Regime | Action |
|--------|--------|
| Bull | Only if sector ETF < EMA50 |
| Neutral | Full operation |
| Bear | Full operation |
| Extreme VIX | Tier B max (5%) |

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Price vs EMA50 | ≤ EMA50×1.05 |
| EMA8 | ≤ EMA21×1.02 |
| Near 60d high | Within 8% |
| Market cap | ≥ $2B |
| Avg 20d volume | ≥ 100K |

### TQ (Trend Quality) — Max 4.0

| EMA Alignment | Score |
|---------------|-------|
| Price<EMA50 AND EMA8<EMA21 | 2.5 |
| Price<EMA50 only | 1.5 |
| Price>EMA50 but EMA8<EMA21 | 1.0 |
| Price>EMA50 AND EMA8>EMA21 | 0 |

| Sector | Score |
|--------|-------|
| Sector ETF < EMA50 declining | 1.5 |
| Sector ETF EMA50–EMA200 | 0.8 |
| Sector ETF > EMA50 | 0 |

### RL (Resistance Level) — Max 4.0

| Touches (90d) | Score | Interval | Score | Width | Score |
|---------------|-------|----------|-------|-------|-------|
| ≥5 | 1.5 | ≥14d | 1.5 | 1–2.5×ATR | 1.0 |
| 4 | 1.2 | 7–14d | 0.8–1.5 | 0.5–1×ATR | 0.5 |
| 3 | 0.8 | 5–7d | 0.3–0.8 | >3×ATR | 0.3 |
| 2 | 0.3 | <5d | 0 | | |
| <2 | 0 | | | | |

### DS (Distribution Signs) — Max 4.0

| Heavy-vol up-days | Score |
|-------------------|-------|
| ≥3 | 2.0 |
| 2 | 1.3 |
| 1 | 0.6 |

Price action (cap 2.0): shooting star/engulfing=+1.0, failed breakout=+1.0, multiple wicks=+0.5, faded gap-up=+0.5

### VC (Volume Confirmation) — Max 3.0

| Breakdown Vol | Score | Follow-through | Score |
|---------------|-------|----------------|-------|
| ≥2.5× | 2.0 | +1.0 if 2nd down-day in 2 sessions |
| 1.8–2.5× | 1.3–2.0 | |
| 1.2–1.8× | 0.5–1.3 | |
| <1.2× | 0 | |

### Entry/Exit

**Entry**: Close<resistance−0.3×ATR, Vol≥1.5×avg20d, CLV≤0.35, not within 5d of earnings

**Stop**: `min(resistance_high+0.5×ATR, entry×1.05)`

**Target**: `entry − 2.5 × (stop − entry)`

---

## Strategy E: AccumulationBottom

**Type**: Long | **Regime**: Bear, extreme, neutral weak | **Dimensions**: TQ(4), AL(4), AS(4), VC(3)

### Market Rules

| Regime | Action |
|--------|--------|
| Bull | Skip |
| Neutral | B-tier max |
| Bear | Full operation |
| Extreme VIX | A-tier min |

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Near 60d low | Within 8% |
| Avg 20d volume | ≥ 200K |
| Market cap | ≥ $3B |
| Listed age | >180 days |

### TQ (Trend Quality) — Max 4.0

| EMA Structure | Score |
|---------------|-------|
| Price<EMA50 AND EMA8<EMA21 | 2.5 |
| Price<EMA50 only | 1.5 |
| Price<EMA200, EMA8 crossing EMA21 | 2.0 |
| Price>EMA50 | 0 |

### AL (Accumulation Level) — Max 4.0

| Touches (90d) | Score | Interval | Score | Width | Score |
|---------------|-------|----------|-------|-------|-------|
| ≥5 | 1.5 | ≥14d | 1.5 | 1–2.5×ATR | 1.0 |
| 4 | 1.2 | 7–14d | 0.8–1.5 | 0.5–1×ATR | 0.5 |
| 3 | 0.8 | 5–7d | 0.3–0.8 | >3×ATR | 0.3 |
| 2 | 0.3 | <5d | 0 | | |

### AS (Accumulation Signs) — Max 4.0

| Up-day vol ratio | Score |
|------------------|-------|
| >2.0 | 2.0 |
| 1.5–2.0 | 1.5–2.0 |
| 1.2–1.5 | 0.8–1.5 |
| 1.0–1.2 | 0.3–0.8 |

Price action (cap 2.0): hammer/bullish engulfing=+1.0, failed breakdown=+1.0, higher lows=+0.5, tight range=+0.5

### VC (Volume Confirmation) — Max 3.0

| Breakout Vol | Score | Follow-through | Score |
|--------------|-------|----------------|-------|
| ≥2.5× | 2.0 | +1.0 if 2nd up-day in 2 sessions |
| 1.8–2.5× | 1.3–2.0 | |
| 1.2–1.8× | 0.5–1.3 | |
| <1.2× | 0 | |

### Entry/Exit

**Entry**: Close>resistance+0.3×ATR, Vol≥1.5×avg20d, CLV≥0.60, not within 5d of earnings

**Stop**: `max(support_low−0.5×ATR, entry×0.94)`

**Target**: `entry + 2.5 × (entry − stop)` (EMA50 if within 15%)

---

## Strategy F: CapitulationRebound

**Type**: Long | **Regime**: VIX 15–35 (reject <15, Tier B if >35) | **Dimensions**: MO(5), EX(6), VC(4)

**EXTREME_EXEMPT**: True (exempt from extreme_vix 0.3× scalar)

### Pre-Filter

| Filter | Condition |
|--------|-----------|
| RSI | < 22 |
| Price vs EMA50 | < EMA50 − 4×ATR |
| Gaps down | ≥2 in last 5d |
| Dollar volume | >$50M avg20d |
| Listed | >50 days |
| VIX | 15–35 (reject <15, Tier B if >35) |

### MO (Momentum Overextension) — Max 5.0

| RSI | Score | Dist from EMA50 | Score |
|-----|-------|-----------------|-------|
| <12 | 3.0 | >25% | 2.0 |
| 12–15 | 2.5–3.0 | 20–25% | 1.5–2.0 |
| 15–18 | 2.0–2.5 | 15–20% | 1.0–1.5 |
| 18–22 | 1.0–2.0 | 10–15% | 0.5–1.0 |
| >22 | 0 | <10% | 0 |

### EX (Extension Level) — Max 6.0

| ATR Extension (EMA50−price)/ATR | Score |
|---------------------------------|-------|
| >8× | 3.0 |
| 6–8× | 2.0–3.0 |
| 4–6× | 1.0–2.0 |
| <4× | 0–1.0 |

| Gap-down days (5d) | Score | Down-day streak | Score |
|--------------------|-------|-----------------|-------|
| ≥4 | 2.0 | ≥7 | 1.0 |
| 3 | 1.5 | 5–6 | 0.6 |
| 2 | 1.0 | 3–4 | 0.3 |

### VC (Volume Confirmation) — Max 4.0

| Vol Ratio | Score |
|-----------|-------|
| >5× | 3.0 |
| 4–5× | 2.5–3.0 |
| 3–4× | 2.0–2.5 |
| 2–3× | 1.0–2.0 |
| 1.5–2× | 0.3–1.0 |
| <1.5× | 0 |

Bonus: +1.0 if CLV>0.65 AND vol>1.5×avg20d (capitulation candle)

### Entry/Exit

**Entry**: EOD close only

**Stop**: `entry − 2.0 × ATR`

**Target**: EMA50 (mean reversion)

**Time stop**: Exit if not +5% toward target in 10 days

---

## Strategy G: EarningsGap

**Type**: Long/Short | **Regime**: Bull/neutral (long), neutral/bear (short) | **Dimensions**: GS(5), QC(4), TC(3), VC(3)

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| Earnings gap | ≥5% on earnings day |
| Days since earnings | 1–5 |
| Dollar volume (gap day) | >$100M |
| Market cap | ≥$2B |
| Price | >$10 |

### Direction

```python
if gap_pct > 0 and price_holding_above_gap_zone: direction = 'LONG'
elif gap_pct < 0 and price_holding_below_gap_zone: direction = 'SHORT'
else: reject
```

### GS (Gap Strength) — Max 5.0

| Gap % | Score (Long) | Score (Short) |
|-------|--------------|---------------|
| ≥10% | 3.0 | 2.5 |
| 7–10% | 2.0–3.0 | 2.0–2.5 |
| 5–7% | 1.0–2.0 | 1.5–2.0 |
| <5% | 0 | 0 |

Gap type: Beat/miss vs est=+1.0, guidance change=+1.0, one-time event=+0.5

### QC (Quality of Consolidation) — Max 4.0

| Days | Long Score | Short Score |
|------|------------|-------------|
| 1–2 | 2.0 | 2.0 |
| 3–4 | 1.5 | 1.5 |
| 5+ | 0.5 | 0.5 |

Range (0–1.5): <3%=1.5, 3–5%=1.0, 5–8%=0.5, >8%=0

### TC (Trend Context) — Max 3.0

| Pre-earnings trend | Score |
|--------------------|-------|
| Aligned with gap (uptrend+gap up) | 2.0 |
| Neutral | 1.0 |
| Counter-trend | 0.5 |

Sector alignment: +1.0 if sector confirms gap direction

### VC (Volume Confirmation) — Max 3.0

| Gap Day Vol | Score | Consolidation Vol | Score |
|-------------|-------|-------------------|-------|
| >5×avg20d | 2.0 | Below average | 1.0 |
| 3–5× | 1.5 | Average | 0.5 |
| 2–3× | 1.0 | Above average | 0 |
| <2× | 0 | | |

### Entry/Exit

**Entry**: Break of consolidation high (long) / low (short); Vol≥1.5×avg20d

**Stop** (Long): `max(consolidation_low−0.5×ATR, gap_open×0.95)`
**Stop** (Short): `min(consolidation_high+0.5×ATR, gap_open×1.05)`

**Target**: `entry ± 2.5 × (entry − stop)`

---

## Strategy H: RelativeStrengthLong

**Type**: Long | **Regime**: Bear, neutral | **Dimensions**: RD(4), SH(4), CQ(3), VC(2)

**EXTREME_EXEMPT**: True

### Tier 1 Pre-Filter

| Filter | Condition |
|--------|-----------|
| RS percentile | ≥80th for 5+ consecutive days |
| Price vs EMA21 | > EMA21 |
| Market cap | ≥$3B |
| Avg 20d volume | ≥200K |

### RD (RS Divergence) — Max 4.0

| RS Percentile | Score |
|---------------|-------|
| ≥95th | 4.0 |
| 90–95th | 3.0–4.0 |
| 85–90th | 2.0–3.0 |
| 80–85th | 1.0–2.0 |
| <80th | 0 |

SPY divergence (0–1.5, add to RS score):

| Stock 10d return − SPY 10d return | Score |
|-----------------------------------|-------|
| >+10% | 1.5 |
| +5–10% | 1.0–1.5 |
| +2–5% | 0.5–1.0 |
| <+2% | 0 |

### SH (Support Holding) — Max 4.0

| Support during SPY down | Score |
|-------------------------|-------|
| No SPY down-day in 10d | 1.0 |
| Held above EMA8 | 1.5 |
| Held above EMA21 | 1.0 |
| Brief EMA21 break, reclaimed | 0.5 |
| Closed below EMA21 | 0 |

### CQ (Consolidation Quality) — Max 3.0

| Relative Volatility (stock_ATR/SPY_ATR) | Score |
|-----------------------------------------|-------|
| <0.8 | 1.5 |
| 0.8–1.2 | 0.8–1.5 |
| 1.2–1.8 | 0.2–0.8 |
| >1.8 | 0 |

| 10d Range | Score |
|-----------|-------|
| <5% | 1.5 |
| 5–8% | 1.0–1.5 |
| 8–12% | 0.5–1.0 |
| >12% | 0 |

### VC (Volume Confirmation) — Max 2.0

| Accum Ratio (up-day vol / down-day vol) | Score |
|-----------------------------------------|-------|
| >2.0 | 2.0 |
| 1.5–2.0 | 1.5–2.0 |
| 1.2–1.5 | 0.8–1.5 |
| 1.0–1.2 | 0.3–0.8 |
| <1.0 | 0 |

### Entry/Exit

**Entry**: RS≥80th 5+ days, Price>EMA21 positive slope, Vol≥1.2×avg20d, prefer SPY down day

**Stop**: `max(EMA50×0.99, entry×0.93)`

**Target**: `entry + 3.0 × (entry − stop)`

**Regime exit**: If SPY crosses above EMA21 (bear→neutral), move to Stage 3 trailing stop

---

## Allocation Table

Phase 1 AI regime detection → 30 slots total.

| Regime | A | B | C | D | E | F | G | H | Total |
|--------|---|---|---|---|---|---|---|---|-------|
| bull_strong | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| bull_moderate | 8 | 6 | 4 | 0 | 0 | 0 | 8 | 4 | 30 |
| neutral | 6 | 5 | 5 | 4 | 4 | 0 | 3 | 3 | 30 |
| bear_moderate | 4 | 4 | 4 | 5 | 5 | 2 | 0 | 6 | 30 |
| bear_strong | 0 | 0 | 4 | 6 | 6 | 8 | 0 | 6 | 30 |
| extreme_vix | 0 | 0 | 0 | 3 | 3 | 12 | 0 | 12 | 30 |

> Strategies with 0 slots skip Phase 2 screening entirely.
