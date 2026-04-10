# Strategy Description v8.0

**Version**: 8.0 | **Updated**: 2026-04-09 | **Strategy F updated to v8.0** | **Strategies**: 8 (A-H, A has A1/A2 sub-modes)

---

## Common Framework

### Indicators

| Indicator   | Formula                                                      |
| ----------- | ------------------------------------------------------------ | -------- | --- | -------- | --- |
| ATR14       | SMA(TR, 14); TR = max(H−L,                                   | H−C_prev | ,   | L−C_prev | )   |
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

**Type**: Long | **Regime**: Bull, neutral | **Max Raw**: 18.5 (A1) / 17.5 (A2) | **Dimensions**: TC(5) + CQ(4) + BS or CP(4) + VC(4) + Bonus(0.5-1.5)

A has two internal sub-modes. A-slots are filled by A1 first; remaining slots use A2.

### Pre-filter (shared)

| Filter          | Condition                          |
| --------------- | ---------------------------------- |
| RS_pct          | ≥ 50th (hard gate, both A1/A2)     |
| Price           | > EMA200                           |
| 3-month return  | ≥ −20%                             |
| Market cap      | ≥ $2B (Phase 0 prefilter)          |
| Avg vol 20d     | ≥ 100K                             |
| Pivot proximity | ≤ 3% above platform_high (A2 only) |

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

| Pattern         | Requirements                                                                            | Base Score |
| --------------- | --------------------------------------------------------------------------------------- | ---------- |
| VCP             | 21–60d, range<12%, >50% days ±2.5%, last 5d vol<70% avg, ≥2 progressively smaller waves | 0.80–1.00  |
| High tight flag | Prior +80% in ≤8w, pullback 10–25%, flag 3–5w, vol dry-up                               | 0.61–0.72  |
| Flat base       | Range<15%, EMA21 slope<0.3×ATR/5d, 5–15w (35–105d), vol dry-up                          | 0.55–0.75  |
| Ascending       | ≥3 higher lows, range 10–25%, 4–12w, prior advance ≥20%                                 | 0.62       |
| Loose           | Range<20%, ≥21d                                                                         | 0.15–0.40  |

```
cq_base = pattern_score × 3.0
duration_bonus: 3–10w=1.0, 2–3w=0.4–1.0, 10–15w=0.5–1.0, <2w=0.2, >15w=0.3
CQ = min(cq_base + duration_bonus, 4.0)
```

### A1: BS — Breakout Strength (max 4.0)

Price-only breakout measurement. Volume moved to VC.

| Breakout % above pivot | Score   |
| ---------------------- | ------- |
| ≥5%                    | 4.0     |
| 3–5%                   | 3.0–4.0 |
| 2–3%                   | 2.0–3.0 |
| 1–2%                   | 1.0–2.0 |
| 0–1%                   | 0.5–1.0 |
| ≤0%                    | 0       |

### A2: CP — Compression Score (max 4.0) _(replaces BS)_

A2 triggers when price is still inside base. CP measures price compression only (volume in VC).

| Range contraction (last 5d range / 20d ATR) | Score | Wave count | Score |
| ------------------------------------------- | ----- | ---------- | ----- |
| <50%                                        | 1.5   | ≥3 waves   | 1.5   |
| 50–70%                                      | 0.8   | 2 waves    | 0.8   |
| >70%                                        | 0     | 1 wave     | 0.3   |

| Proximity to pivot | Score                 |
| ------------------ | --------------------- |
| <1.5%              | 1.0                   |
| 1.5–3%             | 0.5–1.0 (interpolate) |
| >3%                | 0                     |

`CP = range_score + wave_score + proximity_score (max 4.0)`

### VC — Volume Confirmation (max 4.0)

**A1 VC:**

| Base vol (last 5d / avg20d) | Score       | Breakout vol | Score   | CLV       | Score   |
| --------------------------- | ----------- | ------------ | ------- | --------- | ------- |
| <0.50                       | 1.5         | >=3.0x       | 1.5     | >=0.85    | 1.0     |
| 0.50-0.65                   | 1.0-1.5     | 2-3x         | 1.0-1.5 | 0.70-0.85 | 0.5-1.0 |
| 0.65-0.80                   | 0.5-1.0     | 1.5-2x       | 0.5-1.0 | 0.50-0.70 | 0.2-0.5 |
| 0.80-1.00                   | 0.2-0.5     | 1-1.5x       | 0-0.5   | <0.50     | 0       |
| >1.00                       | 0.2 (floor) | <1.0x        | 0       |           |         |

**A2 VC:**

| Last 5d avg vol / avg20d | Score | CLV last 5d avg | Score |
| ------------------------ | ----- | --------------- | ----- |
| <50%                     | 3.0   | ≥0.70           | +1.0  |
| 50–65%                   | 2.0   | <0.70           | 0     |
| 65–80%                   | 1.0   |                 |       |
| >80%                     | 0     |                 |       |

### Bonus Pool

| Bonus                   | Max | Condition                               |
| ----------------------- | --- | --------------------------------------- |
| Sector leadership       | 0.5 | Sector ETF RS≥80th AND >EMA50 (A1 only) |
| Earnings catalyst       | 0.5 | 7–21 days to earnings (A1 only)         |
| Accumulation divergence | 0.5 | OBV rising while price flat (A1 only)   |
| Position strength       | 0.5 | Price in top 30% of 60d range (A2 only) |

### Entry / Exit

**Entry (A1)**: Price>pivot×1.01, Vol>1.5×avg20d, CLV≥0.65, prefer after 10:30 AM ET
**Entry (A2)**: Entry at platform_high (pivot breakout level). Reject if no volume dry-up (vol_5d/vol_20d ≥0.80)

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

**Type**: Long | **Regime**: Bull, neutral | **Max Raw**: 20.0 | **Dimensions**: TI(5) + RC(8) + VC(5) + BONUS(2)

### Pre-filter

Phase 0 already filters: market cap >= $2B, price $2-$3000, volume >= 100K.
Phase 0.5 filters: price > EMA21, S_norm > 0 (uptrend confirmed).

Strategy filter: price >= EMA21 \* 0.98 (2% tolerance for pullback wicks).

### TI — Trend Intensity (max 5.0)

`S_norm = (EMA21_today − EMA21_5d) / ATR14`

| S_norm  | Score   |
| ------- | ------- |
| >1.2    | 5.0     |
| 0.8–1.2 | 4.0–5.0 |
| 0.4–0.8 | 2.0–4.0 |
| 0–0.4   | 0–2.0   |
| <0      | 0       |

Penalty: −0.5 per EMA21 touch in 20d (max −1.0)

### RC — Retracement Composite (max 8.0)

Requirements: pullback > 1.5% from recent high (shallow pullbacks score 0 on depth).

| Factor                   | Condition              | Score    |
| ------------------------ | ---------------------- | -------- |
| Range tightness          | <4%                    | 3.0      |
|                          | 4–8%                   | 1.0–3.0  |
|                          | >8% (broken structure) | −2.0–1.0 |
| EMA8 support             | Within 1.5%            | 2.0      |
|                          | Penetration deeper     | 0–2.0    |
| No gap-down in pullback  | Gap <0.8×ATR           | 1.0      |
| Pullback depth           | >=5%                   | 1.0      |
|                          | 3–5%                   | 0.5–1.0  |
|                          | 1.5–3%                 | 0–0.5    |
|                          | <1.5%                  | 0        |
| Reversal candle patterns | 2+ signals             | 1.0      |
|                          | 1 signal               | 0.5      |
|                          | 0 signals              | 0        |

Reversal signals: hammer (lower shadow >= 2x body + CLV > 0.5), bullish engulfing, strong CLV (> 0.7).

### VC — Volume Confirmation (max 5.0)

| Factor               | Condition                    | Score   |
| -------------------- | ---------------------------- | ------- |
| Volume dry-up        | V_dry < 0.7                  | 2.0     |
|                      | V_dry 0.7–0.9                | 1.0–2.0 |
|                      | V_dry 0.9–1.0                | 0–1.0   |
| Volume surge         | V_surge > 1.5                | 3.0     |
|                      | V_surge 1.2–1.5              | 0–3.0   |
|                      | V_surge 1.0–1.2              | 0–1.5   |
| Distribution penalty | V_surge > 1.5 AND price down | −1.0    |

Distribution day: volume surging on a down-day signals institutional selling, not accumulation.

### BONUS (max 2.0)

| Factor               | Score | Condition                                                           |
| -------------------- | ----- | ------------------------------------------------------------------- |
| Sector leadership    | 0–1.0 | Sector ETF RS>=80th AND >EMA50 → 0.7–1.0; RS>=80th only → 0.3       |
| Momentum persistence | 0–1.0 | Stock 5d return > SPY 5d return by >2% → 1.0; by 1–2% → 0.5; else 0 |

### Entry / Exit

**Entry**: Price within EMA21 \* 0.98 tolerance; pullback > 3% from recent high preferred; vol dry-up or surge; reversal candle patterns scored in RC
**Stop**: `min(five_day_low, EMA21−ATR, entry−1.2×ATR)`
**Target**: `entry + 3.0 × (entry − stop)` | Stage 4 trailing uses EMA5

---

## Strategy C: SupportBounce

**Type**: Long | **Regime**: Neutral, bull, bear | **Max Raw**: 15.0 | **Dimensions**: SQ(4) + VD(5) + RB(6)

### Pre-filter

Phase 0.5 lightweight filter: support exists AND price within 10% of support.
Full validation (touches, EMA50, ADR, volume) happens in Phase 1 filter.

| Filter      | Condition                      |
| ----------- | ------------------------------ |
| Support     | At least 1 support below price |
| Depth       | ≤ 10% from nearest support     |
| Market cap  | ≥ $2B                          |
| Avg vol 20d | ≥ 100K                         |

### SQ — Support Quality (max 4.0)

| Factor          | Condition        | Score           |
| --------------- | ---------------- | --------------- |
| Touch frequency | ≥3 touches       | 2.0 (× recency) |
|                 | 2 touches        | 1.3 (× recency) |
|                 | 1 touch          | 0.7 (× recency) |
| Bounce strength | avg ≥2.0%        | 2.0             |
|                 | avg ≥1.0%        | 1.3             |
|                 | avg >0%          | 0.7             |
| Sector alpha    | ETF near support | 1.0 (bonus)     |

Recency decay: ≤30d=1.0, ≤60d=0.7, ≤90d=0.5, >90d=0.3.

Note: Distance scoring moved to RB to avoid double-counting.

### VD — Volume Dynamics (max 5.0)

Three-phase additive scoring:

**Phase 1 — Breakdown Volume** (max 1.5): Volume on the breakdown dip.
Low volume = false breakdown = bullish. High volume = real breakdown = 0.

| Vol ratio (breakdown day / avg20d) | Score |
| ---------------------------------- | ----- |
| <0.8x                              | 1.5   |
| 0.8–1.0x                           | 1.0   |
| ≥1.5x                              | 0     |

**Phase 2 — Dry-up** (max 1.5): Current volume vs avg20d.

| Vol ratio | Score                 |
| --------- | --------------------- |
| <0.4x     | 1.5                   |
| 0.4–0.6x  | 1.0–1.5 (interpolate) |
| ≥0.6x     | 0                     |

**Phase 3 — Surge** (max 2.0): Recent volume expansion on reclaim.

| Vol ratio | Score                 |
| --------- | --------------------- |
| ≥3.0x     | 2.0                   |
| 2.0–3.0x  | 1.0–2.0 (interpolate) |
| <2.0x     | 0                     |

VD = sum of phase scores (capped at 5.0).

Veto: If current vol >2.0x avg20d AND CLV <0.30 → falling knife → reject.

### RB — Rebound (max 6.0)

**Reclaim timing (0–2.0)**:

| Days since false breakdown | Score                 |
| -------------------------- | --------------------- |
| ≤1d                        | 2.0                   |
| 2–3d                       | 1.0–1.5 (interpolate) |
| ≥4d                        | 0 (expired)           |

**Candle shape (0–1.0)**: Lower shadow / total range.

| Shadow % | Score        |
| -------- | ------------ |
| ≥60%     | 1.0 (hammer) |
| 40–60%   | 0.7          |
| 30–40%   | 0.4          |
| <30%     | 0            |

**CLV position (0–1.0)**:

| CLV     | Score |
| ------- | ----- |
| ≥0.7    | 1.0   |
| 0.5–0.7 | 0.7   |
| 0.4–0.5 | 0.4   |
| <0.4    | 0     |

**Depth quality (0–1.0)**: Distance from support (replaces SQ distance scoring).

| Depth | Score |
| ----- | ----- |
| <1%   | 1.0   |
| 1–2%  | 0.7   |
| 2–5%  | 0.4   |
| ≥5%   | 0     |

Hard gate: depth must be ≥2% for RB to score at all.

**Sector alignment (0–1.0)**: Sector ETF vs its EMA50.

| ETF vs EMA50 | Score |
| ------------ | ----- |
| >EMA50+2%    | 1.0   |
| EMA50±2%     | 0.5   |
| <EMA50−2%    | 0     |

### Entry / Exit

**Entry**: Reclaim confirmation: if false breakdown ≤1d ago, enter at prior candle close. Otherwise limit at `nearest_support + 0.1×ATR`.

**Stop**: Breakdown wick low − 0.25×ATR. Fallback: `support − 0.5×ATR`.

**Target**: Nearest resistance or `entry + 2.0×(entry − stop)`, whichever is closer.

---

## Strategy D: DistributionTop

**Type**: Short | **Regime**: Neutral, bear; bull only if sector ETF<EMA50 | **Max Raw**: 15.0 | **Dimensions**: TQ(4) + RL(4) + DS(4) + VC(3)

### Pre-filter (v7.1)

| Filter        | Condition                               |
| ------------- | --------------------------------------- |
| Market regime | Neutral/bear, or bull with sector<EMA50 |
| Avg vol 20d   | ≥ 100K (liquidity gate)                 |
| Prior trend   | ≥ 25% rally from 52w low                |
| Resistance    | Exists above current price              |

_Removed in v7.1: market_cap (dead code), dollar_volume (redundant), ADR (moved to VC scoring), EMA8/EMA21 (replaced by EMA50 slope in TQ), 8%-from-60d-high (redundant with screen pre-filter at 10%), Price vs EMA50 distance (moved to scoring)._

### TQ — Trend Quality (max 4.0)

EMA alignment (0-2.0) + EMA50 slope (0-0.5) + sector weakness (0-1.0) + prior trend (0-0.5):

| EMA Alignment              | Score |
| -------------------------- | ----- |
| Price<EMA50 AND EMA8<EMA21 | 2.0   |
| Price<EMA50 only           | 1.2   |
| Price>EMA50 but EMA8<EMA21 | 0.8   |
| Price>EMA50 AND EMA8>EMA21 | 0     |

| EMA50 Slope (10d change) | Score |
| ------------------------ | ----- |
| Declining (<=0%)         | 0.5   |
| Flat (0-2%)              | 0.3   |
| Rising (>2%)             | 0     |

| Sector ETF vs EMA50 | Score |
| ------------------- | ----- |
| Sector ETF < EMA50  | 1.0   |
| No sector data      | 0.3   |
| Sector ETF > EMA50  | 0     |

| 6-month return | Score |
| -------------- | ----- |
| > 20%          | 0.5   |
| 10-20%         | 0.3   |
| <= 10%         | 0     |

### RL — Resistance Level (max 4.0)

Resistance from phase0 pre-calculation (unified 5-method SupportResistanceCalculator). No local peak detection.

| Touches (90d) | Score | Interval | Score   | Width     | Score |
| ------------- | ----- | -------- | ------- | --------- | ----- |
| ≥5            | 1.5   | ≥14d     | 1.5     | <0.5×ATR  | 1.0   |
| 4             | 1.2   | 7–14d    | 0.8–1.5 | 1–2.5×ATR | 1.0   |
| 3             | 0.8   | 5–7d     | 0.3–0.8 | 0.5–1×ATR | 0.5   |
| 2             | 0.3   | <5d      | 0       | >3×ATR    | 0.3   |

### DS — Distribution Signs (max 4.0)

| Heavy-vol lower-close at resistance (vol>1.5xavg, close<open) | Score |
| ------------------------------------------------------------- | ----- |
| ≥3                                                            | 2.0   |
| 2                                                             | 1.3   |
| 1                                                             | 0.6   |

Price action (cap 2.0): shooting star (upper shadow>=2x body, CLV>0.7)=+1.0, long upper wick (>=3x body)=+1.0, failed breakout (high>resistance, close<resistance)=+1.0, faded gap-up (gap>0.5%, close in lower 30% range)=+0.5.

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

**Type**: Long | **Regime**: Bull=full, Neutral=B-tier max, Bear=skip, Extreme VIX=skip | **Max Raw**: 18.0 → normalized to 0-15 | **Dimensions**: TQ(4) + AL(4) + OD(4) + VC(3) + WY(3)

**Support caching**: Support level computed once per symbol in `screen()`, cached in `_support_cache`, reused across filter/dimensions/entry/reasons.

### Pre-filter (v7.1)

| Filter        | Condition                                              |
| ------------- | ------------------------------------------------------ |
| Market regime | Bull=full, Neutral=B-tier, Bear=skip, Extreme VIX=skip |
| History       | ≥ 200 bars                                             |
| ADR           | ≥ 3%                                                   |
| RSI14         | < 40                                                   |
| Near 60d low  | Within 10%                                             |
| Support level | Must exist below price                                 |

_Removed in v7.1: market_cap (Phase 0 prefilter), volume (Phase 0 prefilter)._

### TQ — Trend Quality (max 4.0)

| EMA Structure                  | Score |
| ------------------------------ | ----- |
| Price < EMA21 AND EMA8 > EMA21 | 3.5   |
| Price > EMA8 AND EMA8 < EMA21  | 2.0   |
| Price > EMA50                  | 0.0   |
| Downtrend intact (fallback)    | 0.5   |

_Simplified in v7.1: removed unreachable crossing branch. Rewards early reversal or reclamation, not extended downtrends._

### AL — Accumulation Level (max 4.0)

| Touches (90d) | Score | Min interval | Score   | Width     | Score |
| ------------- | ----- | ------------ | ------- | --------- | ----- |
| ≥5            | 1.5   | ≥14d         | 1.5     | 1–2.5×ATR | 1.0   |
| 4             | 1.2   | 7–14d        | 0.8–1.5 | 0.5–1×ATR | 0.5   |
| 3             | 0.8   | 5–7d         | 0.3–0.8 | >3×ATR    | 0.3   |
| 2             | 0.3   | <5d          | 0       |           |       |

### OD — OBV Divergence (max 4.0) _(replaces AS)_

Cumulative OBV: `if close > prev_close: +vol; elif close < prev_close: -vol; else: unchanged`

30-day rate-of-change comparison:

```
obv_roc = (obv_current - obv_30d) / abs(obv_30d)
price_roc = (price_current - price_30d) / price_30d
divergence = obv_roc - price_roc
```

| Divergence | Score            | Rationale                         |
| ---------- | ---------------- | --------------------------------- |
| > 0.30     | 3.0              | Strong institutional accumulation |
| 0.15–0.30  | 1.5–3.0 (linear) | Moderate accumulation             |
| 0.05–0.15  | 0.5–1.5 (linear) | Weak accumulation                 |
| 0–0.05     | 0                | No divergence                     |
| < 0        | 0                | Distribution (penalty)            |

Confirmation bonus via 10-day OBV slope (linear regression, 0-1.0):

- Positive and rising → +1.0
- Negative or flat → 0

`OD = min(4.0, divergence_score + confirmation_bonus)`

### VC — Volume Confirmation (max 3.0)

| Breakout vol / avg20d | Score   | Follow-through                       |
| --------------------- | ------- | ------------------------------------ |
| ≥2.0×                 | 2.0     | +1.0 if 2nd up-day within 2 sessions |
| 1.5–2.0×              | 1.3–2.0 |                                      |
| 1.2–1.5×              | 0.5–1.3 |                                      |
| <1.2×                 | 0       |                                      |

### WY — Wyckoff Structure (max 3.0) _(new)_

**Spring detection (0-1.5)**: Look back 30 days for bar where `low < support_low` but `close > support_low`. Score by volume ratio vs prior 10-day avg:

- Vol < 0.8x avg → 1.5 (classic spring on low vol)
- Vol 0.8–1.2x avg → 1.0
- Vol > 1.2x avg → 0.5 (reclaim but not clean spring)

**Selling climax (0-1.0)**: Look back 60 days for highest volume bar. If vol > 3x 20-day avg AND lower shadow ≥ 50% of range → 1.0

**Volume contraction in range (0-0.5)**: Compare avg vol on down-days in last 30d vs 60–30d window. If recent < prior × 0.8 → 0.5 (declining selling pressure)

`WY = min(3.0, spring_score + climax_score + contraction_score)`

### Entry / Exit

**Entry**: Support level confirmed; RSI < 40; within 10% of 60d low; Wyckoff signals preferred
**Stop**: `support_low − 0.5 × ATR` (removed 6% fallback)
**Target**: `entry + 2.5 × (entry − stop)` (cap at EMA50 if within 15%)

---

## Strategy F: CapitulationRebound

**Type**: Long | **Regime**: VIX 15–35 | **Max Raw**: 16.5 | **Dimensions**: MO(5.5) + EX(6) + VC(5)
**EXTREME_EXEMPT**: True (exempt from 0.3× scalar)

v8.0 changes: Removed redundant filters (dollar volume, listing days, ADR, basic requirements -- all handled by Phase 0). Removed reversal confirmation as a hard gate (moved to MO bonus only). Replaced EMA distance double-counting in MO with RSI velocity scoring. Removed profit efficiency penalty (dead code). Removed time-based exit. VC max increased to 5.0 with extended volume tiers.

### Pre-filter

| Filter              | Condition                                                      |
| ------------------- | -------------------------------------------------------------- |
| RSI14               | < 25                                                           |
| Price vs EMA50      | < EMA50 − 3×ATR                                                |
| Gaps down OR streak | ≥2 gap-downs in last 5d **OR** ≥5 consecutive down-days        |
| Earnings gap        | Reject single >5% gap-down (likely earnings, not capitulation) |
| VIX                 | 15–35 (reject <15; Tier B cap if >35)                          |

Note: Dollar volume, listing days, ADR, and basic volume checks removed from strategy filter -- Phase 0 handles these universally. Reversal confirmation is no longer a gate; extreme conditions alone can qualify.

### MO — Momentum Overextension (max 5.5)

| RSI14 | Score   |
| ----- | ------- |
| <12   | 3.0     |
| 12–15 | 2.5–3.0 |
| 15–18 | 2.0–2.5 |
| 18–25 | 0.5–2.0 |
| >25   | 0       |

| RSI velocity (10d RSI drop) | Score   |
| --------------------------- | ------- |
| ≥20 points                  | 2.0     |
| 15–20 points                | 1.5–2.0 |
| 10–15 points                | 1.0–1.5 |
| 5–10 points                 | 0.5–1.0 |
| <5 points                   | 0       |

RSI velocity is computed from RSI(14) series: `max(0, RSI_10d_ago − current_RSI)`. Measures speed of panic selling -- fast drops indicate capitulation.

Also: +2.0 for bullish RSI divergence detected. +0.5 for strong reversal candle (body majority or outside day).

Total cap: 5.5

Note: EMA distance in ATR terms was previously scored here (up to +2.0) but removed in v8.0 to eliminate double-counting with EX dimension.

### EX — Extension Level (max 6.0)

| (EMA50 − price) / ATR | Score   | Gap-down days (5d) | Score | Down-day streak | Score |
| --------------------- | ------- | ------------------ | ----- | --------------- | ----- |
| >8×                   | 3.0     | ≥4                 | 2.0   | ≥5              | 1.0   |
| 6–8×                  | 2.0–3.0 | 3                  | 1.5   | 3–4             | 0.5   |
| 4–6×                  | 1.0–2.0 | 2                  | 1.0   |                 |       |
| <4×                   | 0–1.0   |                    |       |                 |       |

### VC — Volume Confirmation (max 5.0)

| Vol / avg20d | Score   |
| ------------ | ------- |
| >8×          | 4.0     |
| 6–8×         | 3.5     |
| 5–6×         | 3.0     |
| 4–5×         | 2.5–3.0 |
| 3–4×         | 2.0–2.5 |
| 2–3×         | 1.0–2.0 |
| 1.5–2×       | 0.3–1.0 |
| <1.5×        | 0       |

Bonus: +1.0 if CLV>0.65 AND vol>1.5×avg20d (capitulation candle confirmation). Total cap: 5.0.

### Entry / Exit

**Entry**: EOD close price
**Stop**: `entry − 2.0×ATR`
**Target**: EMA8 (quick mean reversion), EMA21 as secondary target for partial exits

---

## Strategy G: EarningsGap

**Type**: Long/Short | **Regime**: Bull/neutral (long), neutral/bear (short) | **Max Raw**: 15.0 | **Dimensions**: GS(5) + QC(4) + TC(3) + VC(3)

### Pre-filter

| Filter                | Condition                 |
| --------------------- | ------------------------- |
| Post-earnings         | `days_to_earnings < 0`    |
| Earnings gap          | >=5% open-to-prev-close   |
| Gap-day volume        | >=2.0x avg20d (hard gate) |
| RS percentile (long)  | >= 50th                   |
| RS percentile (short) | <= 50th                   |

_Redundant filters removed: market_cap, price, dollar_volume (all handled by Phase 0)._

**Eligibility window by gap size:**

| Gap Size | Max Days Eligible |
| -------- | ----------------- |
| >=10%    | 1-5               |
| 7-10%    | 1-3               |
| 5-7%     | 1-2               |

**Direction**:

```python
if gap_direction == 'up' and rs >= 50th: direction = 'LONG'
elif gap_direction == 'down' and rs <= 50th: direction = 'SHORT'
else: reject
```

### GS -- Gap Strength (max 5.0)

| Gap % | Long    | Short   |
| ----- | ------- | ------- |
| >=10% | 3.0     | 2.5     |
| 7-10% | 2.0-3.0 | 2.0-2.5 |
| 5-7%  | 1.0-2.0 | 1.5-2.0 |

**Earnings surprise bonus (direction-aware, 0-1.0)**:

- Longs: `min(1.0, max(0, surprise_pct) / 0.20)` -- only rewarded for positive surprises
- Shorts: `min(1.0, max(0, -surprise_pct) / 0.20)` -- only rewarded for negative surprises
- Fallback: binary `earnings_beat` flag (+1.0) if surprise_pct unavailable

**Guidance change**: +1.0 if guidance changed. **One-time event**: +0.5. Total capped at 5.0.

### QC -- Quality of Consolidation (max 4.0)

Consolidation = all days AFTER the actual gap day (dynamically identified via `_find_gap_day_index`).

| Consolidation range / gap_open | Score | Consolidation vol / avg20d | Score |
| ------------------------------ | ----- | -------------------------- | ----- |
| <3%                            | 2.5   | <0.8x                      | 1.5   |
| 3-5%                           | 1.5   | 0.8-1.2x                   | 0.8   |
| 5-8%                           | 0.8   | >1.2x                      | 0     |
| >8%                            | 0     |                            |       |

No days-score component (time decay handled by eligibility window filter, avoiding double-counting). Same-day gap (no consolidation yet): partial credit 1.5. Total capped at 4.0.

### TC -- Trend Context (max 3.0)

| Pre-earnings trend           | Score |
| ---------------------------- | ----- |
| Aligned with gap direction   | 2.0   |
| Neutral (price between EMAs) | 1.0   |
| Counter-trend                | 0.5   |

EMA alignment: Long = `price > ema8 > ema21`; Short = `price < ema8 < ema21`.

**Sector alignment bonus**:

- `sector_aligned` True: +1.0
- Sector data available but not aligned: +0.0
- Sector data unavailable: +0.5 (neutral default)

Total capped at 3.0.

### VC -- Volume Confirmation (max 3.0)

| Gap day vol / avg20d | Score | Consolidation vol / avg20d | Score |
| -------------------- | ----- | -------------------------- | ----- |
| >5x                  | 2.0   | <0.8x (dry-up)             | 1.0   |
| 3-5x                 | 1.5   | 0.8-1.2x (average)         | 0.5   |
| 2-3x                 | 1.0   | >1.2x (elevated)           | 0     |
| <2x                  | 0     | No consolidation yet       | 0.5   |

Total capped at 3.0.

### Entry / Exit

**Entry (Long)**: Break of consolidation high
**Entry (Short)**: Break of consolidation low
**Stop (Long)**: `max(consolidation_low - 0.5*ATR, gap_open * 0.95)`
**Stop (Short)**: `min(consolidation_high + 0.5*ATR, gap_open * 1.05)`
**Target**: `entry +/- 2.5 * (entry - stop)`

Gap day's open price (not last day's close) is used for stop buffer calculations. Consolidation identified dynamically via actual gap day detection, not assumed to be last row.

---

## Strategy H: RelativeStrengthLong

**Type**: Long | **Regime**: Bear, neutral | **Max Raw**: 13.0 | **Dimensions**: RD(4) + SH(4) + CQ(3) + VC(2)
**EXTREME_EXEMPT**: True

v7.1 changes: Removed market_cap/volume hard gates (Phase 0 already filters). rs_consecutive_days_80 moved from hard gate to RD bonus. CQ replaced SPY-relative vol with absolute ATR trend. R:R reduced to 2.0x (realistic for bear markets). Added max_hold_days: 20.

### Pre-filter

| Filter | Condition                                           |
| ------ | --------------------------------------------------- |
| Regime | bear_moderate, bear_strong, extreme_vix, or neutral |
| RS_pct | >= 80th (hard gate)                                 |

_Note: Market cap, volume, and RS consecutive days are no longer hard gates. Phase 0 prefilter already enforces market cap >= $2B and volume >= 100K. RS consecutive days is scored as a bonus in RD._

### RD -- RS Divergence (max 4.0, incl. bonuses)

| RS_pct  | Base Score |
| ------- | ---------- |
| >= 95th | 3.0        |
| 90-95th | 2.0-3.0    |
| 85-90th | 1.0-2.0    |
| 80-85th | 0.0-1.0    |
| < 80th  | 0          |

**SPY divergence bonus (0-1.0)**: Stock 10d return - SPY 10d return

| Divergence | Bonus   |
| ---------- | ------- |
| > +10%     | 1.0     |
| +5-10%     | 0.7-1.0 |
| +2-5%      | 0.3-0.7 |
| < +2%      | 0       |

**RS consecutive days >= 80th bonus (0-0.5)**:

| Consecutive days | Bonus |
| ---------------- | ----- |
| >= 10            | 0.5   |
| >= 5             | 0.3   |
| >= 3             | 0.1   |

_(RD capped at 4.0 after all bonuses)_

### SH -- Support Holding (max 4.0)

Evaluated during SPY down-days in last 10d. Code gives proportional credit:

- **EMA8 hold**: full 1.5 if held above EMA8 on ALL down-days; partial = `1.5 * (held_count / num_down_days)`
- **EMA21 hold**: full 1.0 if held above EMA21 on ALL down-days; partial = `1.0 * (held_count / num_down_days)`
- **No SPY down-days in 10d**: baseline 1.0
- **Brief EMA21 break, reclaimed same day**: 0.5
- **Closed below EMA21**: 0

Max possible: 2.5 (EMA8 + EMA21 full hold) + 1.0 baseline = 3.5, but capped by dimension max.

### CQ -- Consolidation Quality (max 3.0)

| ATR trend (5d change) | Score | 10d range | Score   |
| --------------------- | ----- | --------- | ------- |
| Declining >= 15%      | 1.5   | < 5%      | 1.5     |
| Declining 5-15%       | 1.2   | 5-8%      | 1.0-1.5 |
| Stable (+/- 5%)       | 0.8   | 8-12%     | 0.5-1.0 |
| Rising 5-15%          | 0.4   | > 12%     | 0       |
| Rising > 15%          | 0     |           |         |

ATR trend = `(ATR_now - ATR_5d_ago) / ATR_5d_ago`. Measures whether the stock's own volatility is contracting, independent of SPY.

### VC -- Volume Confirmation (max 2.0)

`accum_ratio = sum(vol, up-days, 15d) / sum(vol, down-days, 15d)`

| accum_ratio | Score   |
| ----------- | ------- |
| > 2.0       | 2.0     |
| 1.5-2.0     | 1.5-2.0 |
| 1.2-1.5     | 0.8-1.5 |
| 1.0-1.2     | 0.3-0.8 |
| < 1.0       | 0       |

### Entry / Exit

**Entry**: RS>=80th, Price>EMA21 positive slope; prefer SPY down-day
**Stop**: `max(EMA50 * 0.99, entry * 0.93)`
**Target**: `entry + 2.0 * (entry - stop)`
**Regime exit**: If SPY crosses above EMA21 (bear->neutral), move to Stage 3 trailing stop (tighter: `max(EMA21 * 0.99, low_10d)`)
**Time-stop**: Recommend max 20 hold days for bear market conditions
