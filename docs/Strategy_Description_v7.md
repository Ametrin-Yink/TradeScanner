# Strategy Description v7.0

**Version**: 7.0 | **Updated**: 2026-04 | **Strategies**: 8 (A–H, A has A1/A2 sub-modes)

---

## Common Framework

### Indicators

| Indicator   | Formula                                                      |
| ----------- | ------------------------------------------------------------ |
| ATR14       | SMA(TR, 14); TR = max(H−L, \|H−C_prev\|, \|L−C_prev\|)       |
| EMA(n)      | C × m + EMA_prev × (1−m); m = 2/(n+1)                        |
| RSI14       | 100 − 100/(1 + SMA(gain,14)/SMA(loss,14))                    |
| CLV         | (close − low) / (high − low)                                 |
| S_norm      | (EMA21_today − EMA21_5d) / ATR14                             |
| RS_pct      | percentile_rank(stock_63d_return / SPY_63d_return, universe) |
| accum_ratio | sum(vol on up-days, 15d) / sum(vol on down-days, 15d)        |
| dollar_vol  | close × avg_volume_20d                                       |

### Scoring & Tiers

Scores are **normalized** before tier thresholds are applied:

```python
normalized = (raw_score / strategy_max) * 15.0
```

| Normalized | Tier | Base Position |
| ---------- | ---- | ------------- |
| ≥ 12.0     | S    | 20%           |
| ≥ 9.0      | A    | 10%           |
| ≥ 7.0      | B    | 5%            |
| < 7.0      | C    | 0%            |

### Regime-Adaptive Position Sizing

| Regime        | Long | Short | Exemptions  |
| ------------- | ---- | ----- | ----------- |
| bull_strong   | 1.0× | 0.3×  | —           |
| bull_moderate | 1.0× | 0.3×  | —           |
| neutral       | 0.8× | 0.8×  | —           |
| bear_moderate | 0.5× | 1.0×  | —           |
| bear_strong   | 0.5× | 1.0×  | —           |
| extreme_vix   | 0.3× | 0.5×  | F, H → 1.0× |

### Trailing Stops (4-stage)

| Stage      | Trigger            | Stop Action            |
| ---------- | ------------------ | ---------------------- |
| 1→2        | +1×risk            | Move to breakeven      |
| 2→3        | +2.5×risk          | Hold at +1×risk        |
| 3→4        | +4×risk            | Chandelier: HH − 3×ATR |
| 4 extended | Price > 1.20×EMA21 | Trail EMA8 daily       |

Short-side: inverted. Chandelier = LL + 3×ATR.

### Linear Interpolation

```python
def interp(v, lo, hi, s_lo, s_hi):
    if v <= lo: return s_lo
    if v >= hi: return s_hi
    return s_lo + (v - lo) / (hi - lo) * (s_hi - s_lo)
```

---

## Allocation Table

Phase 1 AI regime → 30 slots total. A-slots filled by A1 first, then A2.

| Regime        | A   | B   | C   | D   | E   | F   | G   | H   |
| ------------- | --- | --- | --- | --- | --- | --- | --- | --- |
| bull_strong   | 8   | 6   | 4   | 0   | 0   | 0   | 8   | 4   |
| bull_moderate | 8   | 6   | 4   | 0   | 0   | 0   | 8   | 4   |
| neutral       | 6   | 5   | 5   | 4   | 4   | 0   | 3   | 3   |
| bear_moderate | 4   | 4   | 4   | 5   | 5   | 2   | 0   | 6   |
| bear_strong   | 2   | 0   | 4   | 6   | 6   | 8   | 0   | 4   |
| extreme_vix   | 0   | 0   | 0   | 3   | 3   | 12  | 0   | 12  |

Strategies with 0 slots skip Phase 2 entirely.

---

## Strategy A: MomentumBreakout

**Type**: Long | **Regime**: Bull, neutral | **Max Raw**: 18.5 | **Dimensions**: TC(5) + CQ(4) + BS or CP(4) + VC(4) + Bonus(1.5)

A has two internal sub-modes. A-slots are filled by A1 first; remaining slots use A2.

### Pre-filter (shared)

| Filter         | Condition          |
| -------------- | ------------------ |
| RS_pct         | ≥ 50th (hard gate) |
| Price          | > EMA200           |
| 3-month return | ≥ −20%             |
| Market cap     | ≥ $2B              |
| Avg vol 20d    | ≥ 100K             |

### TC — Trend Context (max 5.0)

| RS_pct  | Score   | EMA Structure    | Score | 52w High proximity | Score    |
| ------- | ------- | ---------------- | ----- | ------------------ | -------- |
| ≥90th   | 2.0     | Price>EMA50×1.05 | +1.0  | ≤5%                | 1.0      |
| 75–90th | 1.5–2.0 | Price>EMA200     | +0.5  | 5–15%              | interp→0 |
| 60–75th | 1.0–1.5 | EMA50>EMA200     | +0.5  | >15%               | 0        |
| 50–60th | 0.5–1.0 |                  |       |                    |          |
| <50th   | reject  |                  |       |                    |          |

### CQ — Consolidation Quality (max 4.0)

Pattern detection (first match wins):

| Pattern         | Requirements                                                      | Base Score |
| --------------- | ----------------------------------------------------------------- | ---------- |
| VCP             | 15–60d, range<12%, >50% days ±2.5%, last 5d vol<70% avg, ≥2 waves | 0.80–1.00  |
| High tight flag | Prior +30% in ≤8w, pullback 8–30%, flag 2–6w                      | 0.61–0.72  |
| Flat base       | Range<15%, EMA21 slope<0.3×ATR/5d, 3–15w                          | 0.55–0.75  |
| Ascending       | ≥3 higher lows, range 10–25%, 4–12w                               | 0.62       |
| Loose           | Range<20%, ≥10d                                                   | 0.15–0.40  |

```
cq_base = pattern_score × 3.0
duration_bonus: 3–10w=1.0, 2–3w=0.4–1.0, 10–15w=0.5–1.0, <2w=0.2, >15w=0.3
CQ = min(cq_base + duration_bonus, 4.0)
```

### A1: BS — Breakout Strength (max 4.0)

| Breakout % above pivot | Score   | Vol / avg20d | Score   |
| ---------------------- | ------- | ------------ | ------- |
| ≥5%                    | 2.5     | ≥3.0×        | 1.5     |
| 3–5%                   | 2.0–2.5 | 2–3×         | 1.0–1.5 |
| 2–3%                   | 1.5–2.0 | 1.5–2×       | 0.5–1.0 |
| 1–2%                   | 0.5–1.5 | 1–1.5×       | 0–0.5   |
| <1%                    | 0–0.5   | <1×          | 0       |

### A2: CP — Compression Score (max 4.0) _(replaces BS)_

A2 triggers when price is still inside base, within 3% of pivot. CP replaces BS.

| Vol contraction (last 5d avg / avg20d) | Score | Range contraction (last 5d range / 20d ATR) | Score |
| -------------------------------------- | ----- | ------------------------------------------- | ----- |
| <50%                                   | 1.5   | <50%                                        | 1.5   |
| 50–65%                                 | 0.8   | 50–70%                                      | 0.8   |
| 65–80%                                 | 0.3   | 70–90%                                      | 0.3   |
| >80%                                   | 0     | >90%                                        | 0     |

Wave count bonus: +1.0 if ≥3 contraction waves detected.
Proximity gate: within 1.5% of pivot = full score; 1.5–3% = interpolate to 0; >3% = reject A2.

`CP = vol_score + range_score + wave_bonus (max 4.0)`

### VC — Volume Confirmation (max 4.0)

**A1 VC:**

| Base vol (last 5d / avg20d) | Score       | Breakout vol | Score   | CLV       | Score |
| --------------------------- | ----------- | ------------ | ------- | --------- | ----- |
| <0.65                       | 2.0         | ≥3×          | 1.5     | ≥0.85     | 0.5   |
| 0.65–0.80                   | 0.8–2.0     | 2–3×         | 1.0–1.5 | 0.65–0.85 | 0–0.5 |
| 0.80–1.00                   | 0.2–0.8     | 1.5–2×       | 0.5–1.0 | <0.65     | 0     |
| >1.00                       | 0.2 (floor) | <1.5×        | 0–0.5   |           |       |

**A2 VC:**

| Last 5d avg vol / avg20d | Score | CLV last 5d avg | Score |
| ------------------------ | ----- | --------------- | ----- |
| <50%                     | 3.0   | ≥0.70           | +1.0  |
| 50–65%                   | 2.0   | <0.70           | 0     |
| 65–80%                   | 1.0   |                 |       |
| >80%                     | 0     |                 |       |

### Bonus Pool (max 1.5)

| Bonus                   | Max | Condition                                       |
| ----------------------- | --- | ----------------------------------------------- |
| Sector leadership       | 0.5 | Sector ETF RS≥80th AND >EMA50                   |
| Earnings catalyst       | 0.5 | 7–21 days to earnings                           |
| Accumulation divergence | 0.5 | OBV rising while price flat (linreg divergence) |

### Entry / Exit

**Entry (A1)**: Price>pivot×1.01, Vol>1.5×avg20d, CLV≥0.65, prefer after 10:30 AM ET  
**Entry (A2)**: Price within 3% of pivot, Vol dry-up confirmed, wait for pivot break to execute

**Stop**:

```python
if pattern in ('vcp', 'flat_base', 'ascending'): stop = platform_low × 0.98
elif pattern == 'high_tight_flag':               stop = flag_low × 0.985
elif pattern == 'loose':                         stop = entry − 1.5×ATR
stop = max(stop, entry × 0.92)  # 8% floor
```

**Target**: `entry + 3.0 × (entry − stop)`; extend to 4R if S-tier

---

## Strategy B: PullbackEntry

**Type**: Long | **Regime**: Bull, neutral | **Max Raw**: 17.0 | **Dimensions**: TI(5) + RC(5) + VC(5) + BONUS(2)

### Pre-filter

| Filter      | Condition  |
| ----------- | ---------- |
| EMA21 slope | S_norm > 0 |
| Price       | > EMA21    |
| Market cap  | ≥ $2B      |
| Avg vol 20d | ≥ 100K     |

### TI — Trend Intensity (max 5.0)

`S_norm = (EMA21_today − EMA21_5d) / ATR14`

| S_norm  | Score   |
| ------- | ------- |
| >1.2    | 5.0     |
| 0.8–1.2 | 4.0–5.0 |
| 0.4–0.8 | 2.0–4.0 |
| 0–0.4   | 0–2.0   |
| <0      | reject  |

Penalty: −0.5 per EMA21 touch in 20d (max −1.0)

### RC — Retracement Composite (max 5.0)

Requirements: Price>EMA21, pullback<8% from high, price within 1.5% of EMA8.

| Factor                  | Condition    | Score   |
| ----------------------- | ------------ | ------- |
| Range tightness         | <5%          | 2.0     |
|                         | 5–8%         | 1.0–2.0 |
| EMA8 support            | Within 1%    | 2.0     |
|                         | 1–1.5%       | 1.0–2.0 |
| No gap-down in pullback | Gap <0.8×ATR | 1.0     |

### VC — Volume Confirmation (max 5.0)

`Volume_Dry = vol_today/vol_20d < 0.7` | `Volume_Surge = vol_today/vol_20d > 1.5`

| Pattern        | Score |
| -------------- | ----- |
| Dry-up + surge | 5.0   |
| Surge only     | 3.0   |
| Dry-up only    | 2.0   |
| Neither        | 0     |

### BONUS (max 2.0)

| Factor               | Score | Condition                                                            |
| -------------------- | ----- | -------------------------------------------------------------------- |
| Sector ETF           | 0–1.0 | Sector ETF > EMA21 + positive slope                                  |
| Momentum persistence | 0–1.0 | Stock 5d return > SPY 5d return by >2% → 1.0; by 1–2% → 0.5; ≤0% → 0 |

### Entry / Exit

**Entry**: Price>EMA21 positive slope; first touch/retest EMA8/21; vol dry-up or surge  
**Stop**: `min(five_day_low, EMA21−ATR, entry−1.2×ATR)`  
**Target**: `entry + 3.0 × (entry − stop)` | Stage 4 trailing uses EMA5

---

## Strategy C: SupportBounce

**Type**: Long | **Regime**: Neutral, bull, bear | **Max Raw**: 15.0 | **Dimensions**: SQ(4) + VD(5) + RB(6)

### Pre-filter

| Filter          | Condition                  |
| --------------- | -------------------------- |
| Price vs EMA50  | Within ±15%                |
| Support touches | ≥3 in 60d **OR** ≥2 in 30d |
| Market cap      | ≥ $2B                      |
| Avg vol 20d     | ≥ 100K                     |

### SQ — Support Quality (max 4.0)

| EMA Structure                            | Score |
| ---------------------------------------- | ----- |
| Price>EMA50 AND EMA8>EMA21               | 4.0   |
| Price>EMA50 only                         | 2.5   |
| Price<EMA50 AND EMA8>EMA21 (bear bounce) | 1.5   |
| Neither                                  | 0     |

Bonus: +0.5 if ≥4 prior touches in 90d (capped at 4.0)

### VD — Volume Dynamics (max 5.0)

Climax = down-day vol > 2.5×avg20d within last 5d.

| Pattern                 | Score |
| ----------------------- | ----- |
| Climax + dry-up + surge | 5.0   |
| Dry-up + surge          | 4.0   |
| Surge only              | 2.5   |
| Dry-up only             | 1.5   |
| None                    | 0     |

### RB — Rebound (max 6.0)

**Depth (0–2.5)**: Hard gate: depth must be ≥2% to score at all.

| Depth | Score                |
| ----- | -------------------- |
| <2%   | 0 (hard gate)        |
| 2–4%  | 2.0–2.5 (peak at 3%) |
| 4–7%  | 1.5–2.5              |
| 7–10% | 0.5–1.5              |
| >10%  | 0                    |

**Reclaim speed (0–2.5)**:

| Days to reclaim support | Score |
| ----------------------- | ----- |
| 1d                      | 2.5   |
| 2d                      | 2.0   |
| 3d                      | 1.5   |
| 4d                      | 1.0   |
| ≥5d                     | 0     |

**Sector (0–1.0)**: Sector>EMA21=1.0, EMA21–EMA50=0.5, <EMA50=0

### Entry / Exit

**Entry**: Close>support+0.3×ATR, Vol≥1.5×avg20d, CLV≥0.60, not within 5d of earnings  
**Stop**: `max(support_low−0.5×ATR, entry×0.94)`  
**Target**: `entry + 2.5 × (entry − stop)` (2.0R in bear)

---

## Strategy D: DistributionTop

**Type**: Short | **Regime**: Neutral, bear; bull only if sector ETF<EMA50 | **Max Raw**: 15.0 | **Dimensions**: TQ(4) + RL(4) + DS(4) + VC(3)

### Pre-filter

| Filter         | Condition     |
| -------------- | ------------- |
| Price vs EMA50 | ≤ EMA50×1.05  |
| EMA8           | ≤ EMA21×1.02  |
| Near 60d high  | Within 8%     |
| Market cap     | ≥ $2B         |
| Avg vol 20d    | ≥ 100K        |
| Dollar volume  | > $30M avg20d |

### TQ — Trend Quality (max 4.0)

| EMA Alignment              | Score | Sector ETF       | Score |
| -------------------------- | ----- | ---------------- | ----- |
| Price<EMA50 AND EMA8<EMA21 | 2.5   | <EMA50 declining | 1.5   |
| Price<EMA50 only           | 1.5   | EMA50–EMA200     | 0.8   |
| Price>EMA50 but EMA8<EMA21 | 1.0   | >EMA50           | 0     |
| Price>EMA50 AND EMA8>EMA21 | 0     |                  |       |

### RL — Resistance Level (max 4.0)

| Touches (90d) | Score | Interval | Score   | Width     | Score |
| ------------- | ----- | -------- | ------- | --------- | ----- |
| ≥5            | 1.5   | ≥14d     | 1.5     | 1–2.5×ATR | 1.0   |
| 4             | 1.2   | 7–14d    | 0.8–1.5 | 0.5–1×ATR | 0.5   |
| 3             | 0.8   | 5–7d     | 0.3–0.8 | >3×ATR    | 0.3   |
| 2             | 0.3   | <5d      | 0       |           |       |

### DS — Distribution Signs (max 4.0)

| Heavy-vol up-days (vol>1.5×avg, closes lower) | Score |
| --------------------------------------------- | ----- |
| ≥3                                            | 2.0   |
| 2                                             | 1.3   |
| 1                                             | 0.6   |

Price action (cap 2.0): shooting star/bearish engulfing=+1.0, failed breakout=+1.0, multiple upper wicks=+0.5, faded gap-up=+0.5

### VC — Volume Confirmation (max 3.0)

| Breakdown vol / avg20d | Score   | Follow-through                         |
| ---------------------- | ------- | -------------------------------------- |
| ≥2.5×                  | 2.0     | +1.0 if 2nd down-day within 2 sessions |
| 1.8–2.5×               | 1.3–2.0 |                                        |
| 1.2–1.8×               | 0.5–1.3 |                                        |
| <1.2×                  | 0       |                                        |

### Entry / Exit

**Entry**: Close<resistance−0.3×ATR, Vol≥1.5×avg20d, CLV≤0.35, not within 5d of earnings  
**Stop**: `min(resistance_high+0.5×ATR, entry×1.05)`  
**Target**: `entry − 2.5 × (stop − entry)`

---

## Strategy E: AccumulationBottom

**Type**: Long | **Regime**: Bear, extreme, neutral weak | **Max Raw**: 15.0 | **Dimensions**: TQ(4) + AL(4) + AS(4) + VC(3)

**Market rules**: Bull → skip; Neutral → B-tier max; Bear → full; Extreme VIX → A-tier min.

### Pre-filter

| Filter       | Condition  |
| ------------ | ---------- |
| Near 60d low | Within 10% |
| Avg vol 20d  | ≥ 150K     |
| Market cap   | ≥ $2.5B    |
| Listed age   | > 180 days |

### TQ — Trend Quality (max 4.0)

| EMA Structure                     | Score |
| --------------------------------- | ----- |
| Price<EMA50 AND EMA8<EMA21        | 2.5   |
| Price<EMA200, EMA8 crossing EMA21 | 2.0   |
| Price<EMA50 only                  | 1.5   |
| Price>EMA50                       | 0     |

### AL — Accumulation Level (max 4.0)

| Touches (90d) | Score | Min interval | Score   | Width     | Score |
| ------------- | ----- | ------------ | ------- | --------- | ----- |
| ≥5            | 1.5   | ≥14d         | 1.5     | 1–2.5×ATR | 1.0   |
| 4             | 1.2   | 7–14d        | 0.8–1.5 | 0.5–1×ATR | 0.5   |
| 3             | 0.8   | 5–7d         | 0.3–0.8 | >3×ATR    | 0.3   |
| 2             | 0.3   | <5d          | 0       |           |       |

### AS — Accumulation Signs (max 4.0)

| Up-day vol ratio (up-day vol / avg20d) | Score   |
| -------------------------------------- | ------- |
| >2.0×                                  | 2.0     |
| 1.5–2.0×                               | 1.5–2.0 |
| 1.2–1.5×                               | 0.8–1.5 |
| 1.0–1.2×                               | 0.3–0.8 |

Price action (cap 2.0): hammer/bullish engulfing=+1.0, failed breakdown=+1.0, higher lows=+0.5, tight range=+0.5

### VC — Volume Confirmation (max 3.0)

| Breakout vol / avg20d | Score   | Follow-through                       |
| --------------------- | ------- | ------------------------------------ |
| ≥2.5×                 | 2.0     | +1.0 if 2nd up-day within 2 sessions |
| 1.8–2.5×              | 1.3–2.0 |                                      |
| 1.2–1.8×              | 0.5–1.3 |                                      |
| <1.2×                 | 0       |                                      |

### Entry / Exit

**Entry**: Close>resistance+0.3×ATR, Vol≥1.5×avg20d, CLV≥0.60, not within 5d of earnings  
**Stop**: `max(support_low−0.5×ATR, entry×0.94)`  
**Target**: `entry + 2.5 × (entry − stop)` (cap at EMA50 if within 15%)

---

## Strategy F: CapitulationRebound

**Type**: Long | **Regime**: VIX 15–35 | **Max Raw**: 15.0 | **Dimensions**: MO(5) + EX(6) + VC(4)  
**EXTREME_EXEMPT**: True (exempt from 0.3× scalar)

### Pre-filter

| Filter              | Condition                                               |
| ------------------- | ------------------------------------------------------- |
| RSI14               | < 25                                                    |
| Price vs EMA50      | < EMA50 − 3×ATR                                         |
| Gaps down OR streak | ≥2 gap-downs in last 5d **OR** ≥5 consecutive down-days |
| Dollar volume       | > $50M avg20d                                           |
| Listed              | > 50 days                                               |
| VIX                 | 15–35 (reject <15; Tier B cap if >35)                   |

### MO — Momentum Overextension (max 5.0)

| RSI14 | Score   | Distance below EMA50 | Score   |
| ----- | ------- | -------------------- | ------- |
| <12   | 3.0     | >25%                 | 2.0     |
| 12–15 | 2.5–3.0 | 20–25%               | 1.5–2.0 |
| 15–18 | 2.0–2.5 | 15–20%               | 1.0–1.5 |
| 18–25 | 0.5–2.0 | 10–15%               | 0.5–1.0 |
| >25   | 0       | <10%                 | 0       |

### EX — Extension Level (max 6.0)

| (EMA50 − price) / ATR | Score   | Gap-down days (5d) | Score | Down-day streak | Score |
| --------------------- | ------- | ------------------ | ----- | --------------- | ----- |
| >8×                   | 3.0     | ≥4                 | 2.0   | ≥7              | 1.0   |
| 6–8×                  | 2.0–3.0 | 3                  | 1.5   | 5–6             | 0.6   |
| 4–6×                  | 1.0–2.0 | 2                  | 1.0   | 3–4             | 0.3   |
| <4×                   | 0–1.0   |                    |       |                 |       |

### VC — Volume Confirmation (max 4.0)

| Vol / avg20d | Score   |
| ------------ | ------- |
| >5×          | 3.0     |
| 4–5×         | 2.5–3.0 |
| 3–4×         | 2.0–2.5 |
| 2–3×         | 1.0–2.0 |
| 1.5–2×       | 0.3–1.0 |
| <1.5×        | 0       |

Bonus: +1.0 if CLV>0.65 AND vol>1.5×avg20d (capitulation candle confirmation)

### Entry / Exit

**Entry**: EOD close only  
**Stop**: `entry − 2.0×ATR`  
**Target**: EMA50 (mean reversion)  
**Time stop**: Exit if not +5% toward target within 10 days

---

## Strategy G: EarningsGap

**Type**: Long/Short | **Regime**: Bull/neutral (long), neutral/bear (short) | **Max Raw**: 15.0 | **Dimensions**: GS(5) + QC(4) + TC(3) + VC(3)

### Pre-filter

| Filter                  | Condition                   |
| ----------------------- | --------------------------- |
| Earnings gap            | ≥5% on earnings day         |
| Days since earnings     | See eligibility table below |
| Dollar volume (gap day) | > $100M                     |
| Market cap              | ≥ $2B                       |
| Price                   | > $10                       |

**Eligibility by gap size:**

| Gap Size | Max Days Eligible |
| -------- | ----------------- |
| ≥10%     | 1–5               |
| 7–10%    | 1–3               |
| 5–7%     | 1–2               |

**Direction**:

```python
if gap_pct > 0 and price_holding_above_gap_zone: direction = 'LONG'
elif gap_pct < 0 and price_holding_below_gap_zone: direction = 'SHORT'
else: reject
```

### GS — Gap Strength (max 5.0)

| Gap % | Long    | Short   | Gap type bonus         |
| ----- | ------- | ------- | ---------------------- |
| ≥10%  | 3.0     | 2.5     | Beat/miss vs est: +1.0 |
| 7–10% | 2.0–3.0 | 2.0–2.5 | Guidance change: +1.0  |
| 5–7%  | 1.0–2.0 | 1.5–2.0 | One-time event: +0.5   |

### QC — Quality of Consolidation (max 4.0)

| Days since gap | Score | Consolidation range | Score |
| -------------- | ----- | ------------------- | ----- |
| 1–2            | 2.0   | <3%                 | 1.5   |
| 3–4            | 1.5   | 3–5%                | 1.0   |
| 5+             | 0.5   | 5–8%                | 0.5   |
|                |       | >8%                 | 0     |

### TC — Trend Context (max 3.0)

| Pre-earnings trend         | Score |
| -------------------------- | ----- |
| Aligned with gap direction | 2.0   |
| Neutral                    | 1.0   |
| Counter-trend              | 0.5   |

Sector alignment bonus: +1.0 if sector ETF confirms gap direction

### VC — Volume Confirmation (max 3.0)

| Gap day vol / avg20d | Score | Consolidation vol | Score |
| -------------------- | ----- | ----------------- | ----- |
| >5×                  | 2.0   | Below average     | 1.0   |
| 3–5×                 | 1.5   | Average           | 0.5   |
| 2–3×                 | 1.0   | Above average     | 0     |
| <2×                  | 0     |                   |       |

### Entry / Exit

**Entry (Long)**: Break of consolidation high; Vol≥1.5×avg20d  
**Entry (Short)**: Break of consolidation low; Vol≥1.5×avg20d  
**Stop (Long)**: `max(consolidation_low−0.5×ATR, gap_open×0.95)`  
**Stop (Short)**: `min(consolidation_high+0.5×ATR, gap_open×1.05)`  
**Target**: `entry ± 2.5 × (entry − stop)`

---

## Strategy H: RelativeStrengthLong

**Type**: Long | **Regime**: Bear, neutral | **Max Raw**: 13.0 | **Dimensions**: RD(4) + SH(4) + CQ(3) + VC(2)  
**EXTREME_EXEMPT**: True

### Pre-filter

| Filter      | Condition                      |
| ----------- | ------------------------------ |
| RS_pct      | ≥ 80th for ≥5 consecutive days |
| Price       | > EMA21                        |
| Market cap  | ≥ $3B                          |
| Avg vol 20d | ≥ 200K                         |

### RD — RS Divergence (max 4.0, incl. SPY divergence bonus)

| RS_pct  | Score   | Stock 10d return − SPY 10d return | Bonus    |
| ------- | ------- | --------------------------------- | -------- |
| ≥95th   | 4.0     | >+10%                             | +1.5     |
| 90–95th | 3.0–4.0 | +5–10%                            | +1.0–1.5 |
| 85–90th | 2.0–3.0 | +2–5%                             | +0.5–1.0 |
| 80–85th | 1.0–2.0 | <+2%                              | 0        |
| <80th   | 0       |                                   |          |

_(RD capped at 4.0 after bonus)_

### SH — Support Holding (max 4.0)

Evaluated during SPY down-days in last 10d:

| Condition                             | Score |
| ------------------------------------- | ----- |
| Held above EMA8 during SPY weakness   | 1.5   |
| Held above EMA21                      | 1.0   |
| No SPY down-days in 10d (baseline)    | 1.0   |
| Brief EMA21 break, reclaimed same day | 0.5   |
| Closed below EMA21                    | 0     |

### CQ — Consolidation Quality (max 3.0)

| Relative volatility (stock ATR / SPY ATR) | Score   | 10d range | Score   |
| ----------------------------------------- | ------- | --------- | ------- |
| <0.8                                      | 1.5     | <5%       | 1.5     |
| 0.8–1.2                                   | 0.8–1.5 | 5–8%      | 1.0–1.5 |
| 1.2–1.8                                   | 0.2–0.8 | 8–12%     | 0.5–1.0 |
| >1.8                                      | 0       | >12%      | 0       |

### VC — Volume Confirmation (max 2.0)

`accum_ratio = sum(vol, up-days, 15d) / sum(vol, down-days, 15d)`

| accum_ratio | Score   |
| ----------- | ------- |
| >2.0        | 2.0     |
| 1.5–2.0     | 1.5–2.0 |
| 1.2–1.5     | 0.8–1.5 |
| 1.0–1.2     | 0.3–0.8 |
| <1.0        | 0       |

### Entry / Exit

**Entry**: RS≥80th 5+ days, Price>EMA21 positive slope, Vol≥1.2×avg20d; prefer SPY down-day  
**Stop**: `max(EMA50×0.99, entry×0.93)`  
**Target**: `entry + 3.0 × (entry − stop)`  
**Regime exit**: If SPY crosses above EMA21 (bear→neutral), move to Stage 3 trailing stop
