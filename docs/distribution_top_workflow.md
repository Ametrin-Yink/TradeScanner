# DistributionTop Strategy D - Workflow Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PHASE 0: PRE-FILTER (screen)                     │
│                                                                         │
│  symbols[] ──┐                                                          │
│              ▼                                                          │
│  ┌──────────────────────────────┐                                       │
│  │ phase0_data[symbol] lookup   │  ← Cached from screener pre-calc      │
│  │   current_price, high_60d    │                                        │
│  └──────────────┬───────────────┘                                       │
│                 ▼                                                       │
│  ┌──────────────────────────────┐                                       │
│  │ Distance from 60d high ≤ 10% │  (high_60d - price) / high_60d ≤ 0.10│
│  └──────────────┬───────────────┘                                       │
│                 ▼                                                       │
│  ┌──────────────────────────────┐                                       │
│  │ _get_data(symbol) → DataFrame│  ← Only fetch for survivors           │
│  └──────────────┬───────────────┘                                       │
│                 ▼                                                       │
│  ┌──────────────────────────────┐                                       │
│  │ filter(symbol, df)           │  ← Full filter (detailed below)      │
│  └──────────────┬───────────────┘                                       │
│                 ▼                                                       │
│  prefiltered symbols[] ──► screen(prefiltered) ──► calculate_dimensions │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                     FILTER: Candidate Screening                         │
│                                                                         │
│  ┌──────────────────────────┐                                           │
│  │ len(df) ≥ 60 days        │  PARAMS.min_listing_days                  │
│  └──────────┬───────────────┘                                           │
│             ▼                                                           │
│  ┌──────────────────────────────────────┐                               │
│  │ MARKET REGIME CHECK                  │                               │
│  │   regime = _current_regime           │  ← Set by screener            │
│  │   if bull_strong/bull_moderate:      │                               │
│  │     └─► _is_sector_weak(symbol, df)──┼──┐                            │
│  │         sector = phase0_data.sector  │  │                            │
│  │         etf = SECTOR_ETFS[sector]    │  │  SECTOR_ETFS dict maps     │
│  │         etf_data = db.get_etf_cache  │  │  sector→ETF (Tech→XLK)    │
│  │         ema50 = etf.close.ewm(50)    │  │                            │
│  │         return price < ema50 ◄───────┘  │  Returns bool              │
│  │     if NOT weak → REJECT             │  │                            │
│  └──────────┬───────────────────────────┘  │                            │
│             ▼                              │                            │
│  ┌──────────────────────────┐              │                            │
│  │ market_cap ≥ $2B         │  ← phase0_data.market_cap                 │
│  └──────────┬───────────────┘              │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ avg_volume(20d) ≥ 100K           │  df.volume.tail(20).mean()       │
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ dollar_volume ≥ $30M             │  price × avg_volume ≥ 30M        │
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ ADR% ≥ 1.5%                      │  TechnicalIndicators.adr_pct     │
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ price ≤ EMA50 × 1.05             │  Not strongly extended above 50  │
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ EMA8 ≤ EMA21 × 1.02              │  Not in strong uptrend           │
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ price within 8% of 60d high      │  (high_60d - price)/high_60d≤0.08│
│  └──────────┬───────────────────────┘      │                            │
│             ▼                              │                            │
│  ┌──────────────────────────────────┐      │                            │
│  │ resistance exists above price    │  ← phase0_data.resistances[]     │
│  └──────────────────────────────────┘      │                            │
└────────────────────────────────────────────┼────────────────────────────┘
                                             │
                                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  CALCULATE_DIMENSIONS: 4D Scoring                        │
│                                                                        │
│  ┌─────────────────── TQ (max 4.0) ───────────────────┐                │
│  │                                                     │                │
│  │  EMA ALIGNMENT (0-2.5)         SECTOR WEAKNESS (0-1.5)              │
│  │  ┌─────────────────────────┐   ┌─────────────────────────────────┐  │
│  │  │ price<EMA50 && EMA8<    │   │ _calculate_sector_weakness()    │  │
│  │  │   EMA21           =2.5  │   │   sector=phase0_data.sector     │  │
│  │  │ price<EMA50 only  =1.5  │   │   etf=SECTOR_ETFS[sector]       │  │
│  │  │ price>EMA50 && EMA8<   │   │   ema50=etf.close.ewm(span=50)  │  │
│  │  │   EMA21           =1.0  │   │                                 │  │
│  │  │ price>EMA50 && EMA8>   │   │   etf_price < ema50 → 1.5       │  │
│  │  │   EMA21           =0.0  │   │   no data            → 0.5      │  │
│  │  └─────────────────────────┘   │   etf_price > ema50 → 0.0       │  │
│  │                                └─────────────────────────────────┘  │
│  │  TQ = min(4.0, ema_score + sector_score)                            │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌─────────────────── RL (max 4.0) ───────────────────┐                │
│  │                                                     │                │
│  │  _detect_resistance_level(df) ◄── df.tail(90)      │                │
│  │  ┌─────────────────────────────┐                    │                │
│  │  │ Find local maxima (peaks):  │                    │                │
│  │  │   for i in 5..len-5:        │  highs[i]==max(   │                │
│  │  │     highs[i]==max(window±5) │    highs[i-5:i+6])│                │
│  │  └──────────┬──────────────────┘                    │                │
│  │             ▼                                       │                │
│  │  ┌─────────────────────────────┐                    │                │
│  │  │ Group peaks within 2.5 ATR  │  atr = TI.atr     │                │
│  │  │ level_high = max(peaks)     │                   │                │
│  │  │ level_low  = min(peaks ≥    │                   │                │
│  │  │   level_high - 2.5*atr)     │                   │                │
│  │  │ touches = count in range    │                   │                │
│  │  │ width_atr = (hi-lo)/atr     │                   │                │
│  │  │ avg_days = mean(diff(idx))  │                   │                │
│  │  └──────────┬──────────────────┘                    │                │
│  │             ▼                                       │                │
│  │  ┌───────── TOUCH COUNT (0-1.5) ─────────┐         │                │
│  │  │ ≥5→1.5 │ 4→1.2 │ 3→0.8 │ 2→0.3 │ <2→0│         │                │
│  │  └───────────────────────────────────────┘         │                │
│  │  +                                                │                │
│  │  ┌───────── INTERVAL SCORE (0-1.5) ──────────────┐│                │
│  │  │ ≥14d → 1.5                                    ││                │
│  │  │ 7-14d → 0.8 + (days-7)/7 × 0.7  (linear)     ││                │
│  │  │ 5-7d  → 0.3 + (days-5)/2 × 0.5  (linear)     ││                │
│  │  │ <5d   → 0.0                                    ││                │
│  │  └───────────────────────────────────────────────┘│                │
│  │  +                                                │                │
│  │  ┌───────── WIDTH SCORE (0-1.0) ─────────────────┐│                │
│  │  │ <0.5 ATR  → 1.0  (very tight)                 ││                │
│  │  │ 1.0-2.5   → 1.0  (tight)                      ││                │
│  │  │ 0.5-1.0   → 0.5  (moderate)                   ││                │
│  │  │ >3.0      → 0.3  (wide)                       ││                │
│  │  └───────────────────────────────────────────────┘│                │
│  │  RL = min(4.0, touch + interval + width)          │                │
│  └───────────────────────────────────────────────────┘                 │
│                                                                        │
│  ┌─────────────────── DS (max 4.0) ───────────────────┐                │
│  │                                                     │                │
│  │  VOLUME DISTRIBUTION (0-2.0)    PRICE EXHAUSTION (0-2.0)            │
│  │  ┌──────────────────────────┐  ┌─────────────────────────────────┐  │
│  │  │ For each day in tail(30):│  │ _detect_price_action_exhaustion │  │
│  │  │   close < open AND       │  │   For each day in tail(10):     │  │
│  │  │   volume > avg20d × 1.5  │  │     if near resistance (±3%):   │  │
│  │  │   AND near resistance    │  │                                 │  │
│  │  │     (within 2% of level) │  │     SHOOTING STAR:              │  │
│  │  └──────────┬───────────────┘  │       upper_shadow ≥ 2× body    │  │
│  │             ▼                  │       AND CLV > 0.7             │  │
│  │  ┌──────────────────────────┐  │                                 │  │
│  │  │ ≥3 days → 2.0            │  │     LONG WICK:                  │  │
│  │  │ 2 days  → 1.3            │  │       upper_shadow ≥ 3× body    │  │
│  │  │ 1 day   → 0.6            │  │                                 │  │
│  │  │ 0 days  → 0.0            │  │     FAILED BREAKOUT:            │  │
│  │  └──────────────────────────┘  │       high > level AND          │  │
│  │                                │       close < level             │  │
│  │                                │                                 │  │
│  │                                │     GAP FADE:                   │  │
│  │                                │       gap up > 0.5% AND         │  │
│  │                                │       close in lower 30% range  │  │
│  │                                │                                 │  │
│  │                                │     ≥3 signals → 2.0            │  │
│  │                                │     2 signals  → 1.5            │  │
│  │                                │     1 signal   → 0.8            │  │
│  │                                │     0 signals  → 0.0            │  │
│  │                                └─────────────────────────────────┘  │
│  │  DS = min(4.0, vol_score + pa_score)                                │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌─────────────────── VC (max 3.0) ───────────────────┐                │
│  │                                                     │                │
│  │  BASE VOLUME SCORE (0-2.0)     FOLLOW-THROUGH (0-1.0)               │
│  │  ┌──────────────────────────┐  ┌─────────────────────────────────┐  │
│  │  │ vol_ratio =              │  │ Check last 2 sessions before    │  │
│  │  │   today_volume / avg20d  │  │ today (df.iloc[-1], df.iloc[-2])│  │
│  │  │                          │  │                                 │  │
│  │  │ ≥2.5× → 2.0              │  │ down_day: close < open          │  │
│  │  │ 1.8-2.5× → 1.3 +         │  │                                 │  │
│  │  │   (ratio-1.8)/0.7×0.7   │  │ count down_days in [-1, -2]     │  │
│  │  │ 1.2-1.8× → 0.5 +         │  │                                 │  │
│  │  │   (ratio-1.2)/0.6×0.8   │  │ if count ≥ 2 → +1.0             │  │
│  │  │ <1.2× → 0.0              │  │                                 │  │
│  │  └──────────────────────────┘  └─────────────────────────────────┘  │
│  │  VC = min(3.0, base_score + follow_through)                          │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  TOTAL RAW SCORE = TQ + RL + DS + VC  (max 15.0)                       │
│  Tier assignment based on score thresholds                              │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                    ENTRY/EXIT CALCULATION                                │
│                                                                         │
│  ┌────────────────── 4 ENTRY CONDITIONS (all must pass) ────────────┐   │
│  │                                                                    │   │
│  │  1. CLOSE < RESISTANCE - 0.3×ATR                                  │   │
│  │     resistance_high = min(resistances above price)                 │   │
│  │     entry_threshold = resistance_high - 0.3 × atr                  │   │
│  │     current_price must be ≤ entry_threshold                        │   │
│  │                                                                    │   │
│  │  2. VOLUME ≥ 1.5× avg20d                                          │   │
│  │     today_volume ≥ avg_volume(20d) × 1.5                          │   │
│  │                                                                    │   │
│  │  3. CLV ≤ 0.35                                                    │   │
│  │     CLV = ((close-low) - (high-close)) / (high-low)               │   │
│  │     CLV ≤ 0.35 means close is in lower portion of daily range     │   │
│  │                                                                    │   │
│  │  4. NOT WITHIN 5 DAYS OF EARNINGS                                 │   │
│  │     days_to_earnings from phase0_data                              │   │
│  │     veto if 0 ≤ days_to_earnings ≤ 5                               │   │
│  │                                                                    │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  If ALL conditions pass:                                                │
│  ┌─────────────────────────────────────────┐                            │
│  │ entry  = current_price (rounded 2dp)    │                            │
│  │ stop   = min(                           │                            │
│  │   resistance_high + 0.5×ATR,            │  ← Two guards             │
│  │   entry × 1.05                          │  ← 5% max loss cap        │
│  │ )                                       │                            │
│  │ risk   = stop - entry                   │                            │
│  │ target = entry - risk × 2.5             │  ← 2.5:1 reward:risk       │
│  └─────────────────────────────────────────┘                            │
│                                                                         │
│  Direction: SHORT (profit when price falls from entry to target)        │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                     DATA FLOW DEPENDENCIES                                │
│                                                                         │
│  ┌─────────────────────┐                                                │
│  │  phase0_data        │  ← Pre-calculated by screener before strategy  │
│  │  ┌───────────────┐  │                                                │
│  │  │ current_price │  │  Used by: filter, TQ, RL, DS, entry           │
│  │  │ high_60d      │  │  Used by: filter (pre-filter)                 │
│  │  │ market_cap    │  │  Used by: filter (cap check)                  │
│  │  │ sector        │  │  Used by: TQ sector_weakness, regime filter   │
│  │  │ resistances[] │  │  Used by: filter, RL, DS, entry               │
│  │  │ days_to_      │  │  Used by: entry (earnings veto)               │
│  │  │  earnings     │  │                                                │
│  │  │ nearest_res_  │  │  Used by: build_match_reasons                 │
│  │  │  distance_pct │  │                                                │
│  │  └───────────────┘  │                                                │
│  └─────────┬───────────┘                                                │
│            ▼                                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐                    │
│  │  SECTOR_ETFS dict   │    │  db.get_etf_cache() │                    │
│  │  Tech → XLK         │    │  Returns DataFrame   │                    │
│  │  Health → XLV       │    │  with 'close' col    │                    │
│  │  Financial→ XLF     │    │                     │                    │
│  │  ... (15 sectors)   │    │  EMA50 = ewm(span=50)│                    │
│  └─────────────────────┘    └─────────────────────┘                    │
│                                                                         │
│  ┌─────────────────────┐                                                │
│  │  _current_regime    │  ← Set by screener (line 757)                 │
│  │  bull_strong        │    from market_regime.py                       │
│  │  bull_moderate      │    SPY/VIX-based regime detection              │
│  │  neutral            │                                                │
│  │  bear_moderate      │                                                │
│  │  bear_strong        │                                                │
│  │  extreme_vix        │                                                │
│  └─────────────────────┘                                                │
└─────────────────────────────────────────────────────────────────────────┘
```
