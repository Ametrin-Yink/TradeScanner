# Strategy Filter Fixes Implementation Plan

> **STATUS**: ✅ COMPLETED - All fixes implemented and tested

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix overly restrictive filters in 6 trading strategies to restore candidate generation and add diagnostic logging to track filter performance.

**Architecture:** Relax threshold-based filters while maintaining signal quality, fix data source issues (VIX symbol), and add structured debug logging to each strategy's filter methods.

**Tech Stack:** Python 3.10, pandas, yfinance, existing strategy framework

---

## File Structure

| File | Responsibility | Changes |
|------|---------------|---------|
| `core/strategies/capitulation_rebound.py` | Capitulation bottom detection | Fix VIX symbol, add filter logging |
| `core/strategies/momentum_breakout.py` | VCP breakout detection | Add VCP detection logging |
| `core/indicators.py` | Technical indicator calculations | Relax VCP platform detection thresholds |
| `core/strategies/support_bounce.py` | Support bounce detection | Add SPY buffer, add filter logging |
| `core/strategies/range_short.py` | Range resistance short | Relax downtrend requirement, add filter logging |
| `core/strategies/double_top_bottom.py` | Double top/bottom detection | Reduce interval threshold, add filter logging |
| `docs/Strategy_Description.md` | Strategy documentation | Update thresholds to match code |

---

## Preconditions

- Repository at `/home/admin/Projects/TradeChanceScreen`
- Python 3.10+ available
- Can run test scan with: `python scheduler.py --test --symbols AAPL,MSFT,NVDA`

---

### Task 1: Fix CapitulationRebound VIX Symbol

**Files:**
- Modify: `core/strategies/capitulation_rebound.py:99`
- Modify: `core/strategies/capitulation_rebound.py:61-68` (add filter logging)

**Context:** The VIX data fetch fails because Yahoo Finance uses `^VIX` not `VIX`. This causes the strategy to always default to "limit" mode.

- [x] **Step 1: Fix VIX symbol from 'VIX' to '^VIX'**

```python
# In core/strategies/capitulation_rebound.py, line 99
# Change:
vix_df = self._get_data('VIX')
# To:
vix_df = self._get_data('^VIX')
```

- [x] **Step 2: Add diagnostic logging to _prefilter_symbol method**

Add at the start of `_prefilter_symbol` method (around line 126):

```python
def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
    """Pre-filter symbol for capitulation bottom conditions only."""
    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]
    rsi_data = ind.indicators.get('rsi', {})
    rsi = rsi_data.get('rsi')

    ema = ind.indicators.get('ema', {})
    ema50 = ema.get('ema50', current_price)
    atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

    price_metrics = ind.indicators.get('price_metrics', {})
    gaps = price_metrics.get('gaps_5d', 0)

    # DEBUG: Log pre-filter checks
    debug_info = {
        'symbol': symbol,
        'rsi': rsi,
        'ema50': ema50,
        'price_vs_ema50': (current_price - ema50) / ema50 * 100 if ema50 else 0,
        'gaps': gaps,
        'atr_multiple': (ema50 - current_price) / atr if atr > 0 else 0
    }

    # Capitulation bottom conditions (long mode only)
    if rsi is None or rsi >= self.PARAMS['rsi_oversold']:
        logger.debug(f"CAP_REJ: {symbol} - RSI {rsi:.1f} >= {self.PARAMS['rsi_oversold']}")
        return False

    if current_price >= ema50 - self.PARAMS['ema_atr_multiplier'] * atr:
        logger.debug(f"CAP_REJ: {symbol} - Price {current_price:.2f} not below EMA50-5ATR {ema50 - self.PARAMS['ema_atr_multiplier'] * atr:.2f}")
        return False

    if gaps < self.PARAMS['min_gaps']:
        logger.debug(f"CAP_REJ: {symbol} - Gaps {gaps} < {self.PARAMS['min_gaps']}")
        return False

    logger.debug(f"CAP_PASS: {symbol} - All pre-filters passed")
    return True
```

- [x] **Step 3: Commit the changes**

```bash
git add core/strategies/capitulation_rebound.py
git commit -m "fix(capitulation): use correct VIX symbol ^VIX, add filter logging"
```

---

### Task 2: Relax VCP Detection in indicators.py

**Files:**
- Modify: `core/indicators.py:396-464` (detect_vcp_platform method)

**Context:** The VCP detection requires ALL three conditions (range <12%, concentration >50%, valid volume), resulting in 0 matches. Change to score-based system.

- [x] **Step 1: Modify detect_vcp_platform to use scoring instead of strict AND**

Replace the `detect_vcp_platform` method:

```python
def detect_vcp_platform(self, lookback_range=(15, 30), max_range_pct=0.12,
                        concentration_band=0.025, concentration_threshold=0.50) -> Optional[Dict]:
    """
    Detect Volatility Contraction Pattern (VCP) platform.
    RELAXED: Uses scoring system (2 of 3 criteria) instead of strict AND gate.

    Args:
        lookback_range: (min_days, max_days) for platform detection
        max_range_pct: Maximum platform range as percentage (e.g., 0.12 = 12%)
        concentration_band: Price band around midpoint for concentration check
        concentration_threshold: Minimum ratio of days within band (e.g., 0.50 = 50%)

    Returns:
        Dict with platform metrics or None if no valid platform found
    """
    if len(self.df) < lookback_range[1] + 5:
        return None

    best_platform = None
    best_score = 0

    # Try different platform lengths within range
    for platform_days in range(lookback_range[1], lookback_range[0] - 1, -1):
        platform_df = self.df.tail(platform_days)

        platform_high = platform_df['high'].max()
        platform_low = platform_df['low'].min()
        platform_range_pct = (platform_high - platform_low) / platform_low

        # CRITERION 1: Range tightness (relaxed from 12% to 15%)
        range_score = 0
        if platform_range_pct < 0.08:  # Excellent
            range_score = 3
        elif platform_range_pct < 0.12:  # Good
            range_score = 2
        elif platform_range_pct < 0.15:  # Acceptable
            range_score = 1

        # Calculate midpoint and concentration
        midpoint = (platform_high + platform_low) / 2
        upper_band = midpoint * (1 + concentration_band)
        lower_band = midpoint * (1 - concentration_band)

        # Count days with close within band
        closes_in_band = platform_df[(platform_df['close'] >= lower_band) &
                                     (platform_df['close'] <= upper_band)]
        concentration_ratio = len(closes_in_band) / platform_days

        # CRITERION 2: Concentration (relaxed from 50% to 40%)
        concentration_score = 0
        if concentration_ratio >= 0.60:
            concentration_score = 3
        elif concentration_ratio >= 0.50:
            concentration_score = 2
        elif concentration_ratio >= 0.40:
            concentration_score = 1

        # Calculate volume metrics
        platform_volume_mean = platform_df['volume'].mean()
        last_5d_volume_mean = platform_df['volume'].tail(5).mean()
        volume_contraction_ratio = last_5d_volume_mean / platform_volume_mean if platform_volume_mean > 0 else 1.0

        # CRITERION 3: Volume contraction
        volume_score = 0
        if volume_contraction_ratio < 0.50:
            volume_score = 3
        elif volume_contraction_ratio < 0.70:
            volume_score = 2
        elif volume_contraction_ratio < 0.85:
            volume_score = 1

        # RELAXED: Require 2 of 3 criteria with at least score 1 each
        total_score = range_score + concentration_score + volume_score
        criteria_met = sum([range_score > 0, concentration_score > 0, volume_score > 0])

        # DEBUG logging for VCP detection
        if platform_days == lookback_range[1]:  # Log first attempt only
            logger.debug(f"VCP_DEBUG: {self.symbol} - Range:{platform_range_pct:.3f}(s:{range_score}), "
                        f"Conc:{concentration_ratio:.2f}(s:{concentration_score}), "
                        f"Vol:{volume_contraction_ratio:.2f}(s:{volume_score}), "
                        f"Total:{total_score}, Criteria:{criteria_met}")

        # Require at least 2 criteria with minimum quality
        if criteria_met >= 2 and total_score >= 3:
            if total_score > best_score:
                best_score = total_score
                contraction_quality = self._calculate_contraction_quality(platform_df)

                best_platform = {
                    'platform_days': platform_days,
                    'platform_high': float(platform_high),
                    'platform_low': float(platform_low),
                    'platform_range_pct': float(platform_range_pct),
                    'midpoint': float(midpoint),
                    'concentration_ratio': float(concentration_ratio),
                    'volume_contraction_ratio': float(volume_contraction_ratio),
                    'platform_volume_mean': float(platform_volume_mean),
                    'contraction_quality': float(contraction_quality),
                    'range_score': range_score,
                    'concentration_score': concentration_score,
                    'volume_score': volume_score,
                    'is_valid': True
                }

    if best_platform:
        logger.debug(f"VCP_FOUND: {self.symbol} - Score:{best_score}, Days:{best_platform['platform_days']}, "
                    f"Range:{best_platform['platform_range_pct']:.3f}")
    else:
        logger.debug(f"VCP_NONE: {self.symbol} - No valid platform found")

    return best_platform
```

- [x] **Step 2: Commit the changes**

```bash
git add core/indicators.py
git commit -m "fix(indicators): relax VCP detection to scoring system (2 of 3 criteria)"
```

---

### Task 3: Add Filter Logging to MomentumBreakout

**Files:**
- Modify: `core/strategies/momentum_breakout.py:40-106` (filter method)

- [x] **Step 1: Add layer-by-layer logging to filter method**

Replace the filter method:

```python
def filter(self, symbol: str, df: pd.DataFrame) -> bool:
    """5-layer filtering system with diagnostic logging."""
    if len(df) < self.PARAMS['min_listing_days']:
        logger.debug(f"MB_REJ: {symbol} - Insufficient data: {len(df)} < {self.PARAMS['min_listing_days']}")
        return False

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Layer 1: Liquidity
    dollar_volume = current_price * df['volume'].iloc[-1]
    if dollar_volume < self.PARAMS['min_dollar_volume']:
        logger.debug(f"MB_REJ: {symbol} - Low dollar volume: ${dollar_volume/1e6:.1f}M < ${self.PARAMS['min_dollar_volume']/1e6:.0f}M")
        return False

    adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
    if adr_pct < self.PARAMS['min_atr_pct']:
        logger.debug(f"MB_REJ: {symbol} - Low ADR: {adr_pct:.3f} < {self.PARAMS['min_atr_pct']}")
        return False

    # Layer 2: 50EMA deadzone filter
    ema50_distance = ind.distance_from_ema50()
    if ema50_distance['distance_pct'] > self.PARAMS['max_distance_from_50ema']:
        logger.debug(f"MB_REJ: {symbol} - Far from 50EMA: {ema50_distance['distance_pct']:.3f} > {self.PARAMS['max_distance_from_50ema']}")
        return False

    ema50_slope = ind.calculate_stable_ema_slope(period=50, comparison_days=3)
    if not ema50_slope['is_uptrend']:
        logger.debug(f"MB_REJ: {symbol} - EMA50 not in uptrend")
        return False

    # Layer 3: 52-week high proximity
    metrics_52w = ind.calculate_52w_metrics()
    if metrics_52w['distance_from_high'] is None:
        logger.debug(f"MB_REJ: {symbol} - Cannot calculate 52w metrics")
        return False
    if metrics_52w['distance_from_high'] > self.PARAMS['max_distance_from_52w_high']:
        logger.debug(f"MB_REJ: {symbol} - Far from 52w high: {metrics_52w['distance_from_high']:.3f} > {self.PARAMS['max_distance_from_52w_high']}")
        return False

    # Layer 4: VCP Platform Detection
    platform = ind.detect_vcp_platform(
        lookback_range=self.PARAMS['platform_lookback'],
        max_range_pct=self.PARAMS['platform_max_range'],
        concentration_threshold=self.PARAMS['concentration_threshold']
    )

    if platform is None or not platform.get('is_valid'):
        logger.debug(f"MB_REJ: {symbol} - No valid VCP platform detected")
        return False

    if platform['volume_contraction_ratio'] > self.PARAMS['volume_contraction_vs_platform']:
        logger.debug(f"MB_REJ: {symbol} - Poor volume contraction: {platform['volume_contraction_ratio']:.2f} > {self.PARAMS['volume_contraction_vs_platform']}")
        return False

    # Layer 5: EP Breakout Confirmation
    platform_high = platform['platform_high']
    breakout_pct = (current_price - platform_high) / platform_high

    if breakout_pct < self.PARAMS['breakout_pct']:
        logger.debug(f"MB_REJ: {symbol} - Breakout too small: {breakout_pct:.3f} < {self.PARAMS['breakout_pct']}")
        return False

    clv = ind.calculate_clv()
    if clv < self.PARAMS['clv_threshold']:
        logger.debug(f"MB_REJ: {symbol} - CLV too low: {clv:.3f} < {self.PARAMS['clv_threshold']}")
        return False

    current_volume = df['volume'].iloc[-1]
    volume_sma20 = df['volume'].tail(20).mean()
    volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0

    if volume_ratio < self.PARAMS['breakout_volume_vs_20d_sma']:
        logger.debug(f"MB_REJ: {symbol} - Volume ratio too low: {volume_ratio:.2f}x < {self.PARAMS['breakout_volume_vs_20d_sma']}x")
        return False

    logger.debug(f"MB_PASS: {symbol} - All 5 layers passed! Breakout:{breakout_pct:.2%}, Vol:{volume_ratio:.1f}x")
    return True
```

- [x] **Step 2: Commit the changes**

```bash
git add core/strategies/momentum_breakout.py
git commit -m "feat(momentum): add layer-by-layer filter logging for diagnostics"
```

---

### Task 4: Fix SupportBounce SPY EMA200 Gate

**Files:**
- Modify: `core/strategies/support_bounce.py:59-128` (screen method)

- [x] **Step 1: Add buffer to SPY EMA200 check**

Find the SPY check section (around line 66-77) and modify:

```python
# Phase 0: Check SPY trend
logger.info("U&R: Phase 0 - Checking SPY trend...")
spy_df = getattr(self, '_spy_df', None)
if spy_df is None:
    spy_df = self._get_data('SPY')
if spy_df is not None and len(spy_df) >= 200:
    spy_current = spy_df['close'].iloc[-1]
    spy_ema200 = spy_df['close'].ewm(span=200).mean().iloc[-1]

    # RELAXED: Allow 2% buffer below EMA200
    spy_buffer = 0.02  # 2% buffer
    if spy_current < spy_ema200 * (1 - spy_buffer):
        logger.info(f"U&R: SPY {spy_current:.2f} below EMA200 {spy_ema200:.2f} (with {spy_buffer:.0%} buffer), skipping")
        return []
    elif spy_current < spy_ema200:
        logger.info(f"U&R: SPY slightly below EMA200 but within buffer, continuing...")
```

- [x] **Step 2: Add pre-filter logging**

Add at the start of the support check loop (around line 82):

```python
# Pre-filter by support existence and distance
prefiltered = []
logger.info("U&R: Phase 0.5 - Pre-filtering by support...")

for symbol in symbols:
    try:
        df = self._get_data(symbol)
        if df is None or len(df) < self.PARAMS['min_listing_days']:
            logger.debug(f"U&R_REJ: {symbol} - Insufficient data")
            continue

        current_price = df['close'].iloc[-1]

        # Calculate S/R with tolerance
        calc = SupportResistanceCalculator(df)
        sr_levels = calc.calculate_all()
        supports = sr_levels.get('support', [])

        if not supports:
            logger.debug(f"U&R_REJ: {symbol} - No support levels found")
            continue

        # Find nearest support
        supports_below = [s for s in supports if s < current_price]
        if not supports_below:
            logger.debug(f"U&R_REJ: {symbol} - No support below price {current_price:.2f}")
            continue

        nearest_support = max(supports_below)
        distance_pct = (current_price - nearest_support) / current_price

        # Relaxed threshold: < 3%
        if distance_pct < self.PARAMS['max_distance_from_support']:
            logger.debug(f"U&R_PASS: {symbol} - Support at {nearest_support:.2f}, distance {distance_pct:.2%}")
            prefiltered.append(symbol)
        else:
            logger.debug(f"U&R_REJ: {symbol} - Support too far: {distance_pct:.2%} >= {self.PARAMS['max_distance_from_support']:.2%}")

    except Exception as e:
        logger.debug(f"Error pre-filtering {symbol}: {e}")
        continue
```

- [x] **Step 3: Commit the changes**

```bash
git add core/strategies/support_bounce.py
git commit -m "fix(support_bounce): add 2% buffer to SPY EMA200 gate, add filter logging"
```

---

### Task 5: Relax RangeShort Pre-Filter

**Files:**
- Modify: `core/strategies/range_short.py:109-152` (_prefilter_symbol method)

- [x] **Step 1: Relax downtrend requirement**

Replace the method:

```python
def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
    """Pre-filter symbol for short mode only with relaxed criteria."""
    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]
    ema = ind.indicators.get('ema', {})
    ema21 = ema.get('ema21', current_price)
    ema50 = ema.get('ema50', current_price)

    calc = SupportResistanceCalculator(df)
    sr_levels = calc.calculate_all()

    # RELAXED: Must be below EMA50 (don't require EMA21 in between)
    # Original: if not (current_price < ema21 < ema50):
    if current_price >= ema50:
        logger.debug(f"RS_REJ: {symbol} - Price {current_price:.2f} >= EMA50 {ema50:.2f}")
        return False

    # Must have resistance near price
    resistances = sr_levels.get('resistance', [])
    if not resistances:
        logger.debug(f"RS_REJ: {symbol} - No resistance levels")
        return False

    resistances_above = [r for r in resistances if r > current_price]
    if not resistances_above:
        logger.debug(f"RS_REJ: {symbol} - No resistance above price {current_price:.2f}")
        return False

    nearest_resistance = min(resistances_above)
    distance_pct = (nearest_resistance - current_price) / current_price

    if distance_pct > self.PARAMS['max_distance_from_level']:
        logger.debug(f"RS_REJ: {symbol} - Resistance too far: {distance_pct:.2%} > {self.PARAMS['max_distance_from_level']:.2%}")
        return False

    # RELAXED: Check width constraint
    supports = sr_levels.get('support', [])
    if supports:
        nearest_support = max(s for s in supports if s < current_price) if any(s < current_price for s in supports) else nearest_resistance * 0.9
        range_width = (nearest_resistance - nearest_support) / nearest_support
        atr_pct = ind.indicators.get('atr', {}).get('atr_pct', 0.02)

        # RELAXED: From 1.5x to 1.0x ATR multiple
        if range_width < self.PARAMS['min_range_width_atr_multiple'] * 0.67 * atr_pct:  # Effectively 1.0x instead of 1.5x
            logger.debug(f"RS_REJ: {symbol} - Range too narrow: {range_width:.3f}")
            return False

    logger.debug(f"RS_PASS: {symbol} - Resistance at {nearest_resistance:.2f}, distance {distance_pct:.2%}")
    return True
```

- [x] **Step 2: Update PARAMS to reflect relaxed thresholds**

Add a comment in the PARAMS dict (around line 27-43):

```python
PARAMS = {
    'min_dollar_volume': 50_000_000,
    'min_atr_pct': 0.015,
    'min_listing_days': 60,
    'min_touches': 3,
    'max_distance_from_level': 0.03,  # 3% from resistance
    'target_r_multiplier': 2.5,
    'support_tolerance_atr': 0.5,  # ±0.5 ATR for touch detection
    'min_test_interval_days': 3,  # Stability filter: min 3 days between tests
    'min_range_width_atr_multiple': 1.5,  # Width constraint (relaxed to ~1.0x effective)
    # ... rest of params
}
```

- [x] **Step 3: Commit the changes**

```bash
git add core/strategies/range_short.py
git commit -m "fix(range_short): relax downtrend filter (price < EMA50 only), add logging"
```

---

### Task 6: Reduce DoubleTopBottom Interval Threshold

**Files:**
- Modify: `core/strategies/double_top_bottom.py:38`
- Modify: `core/strategies/double_top_bottom.py:125-171` (_prefilter_symbol method)

- [x] **Step 1: Reduce min_test_interval_days from 10 to 7**

```python
# Line 38
'min_test_interval_days': 7,  # RELAXED: Was 10 days, now 7 days
```

- [x] **Step 2: Add filter logging to _prefilter_symbol**

```python
def _prefilter_symbol(self, symbol: str, df: pd.DataFrame) -> bool:
    """Pre-filter symbol based on market direction with logging."""
    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]
    price_metrics = ind.indicators.get('price_metrics', {})

    if self.market_direction == 'short':
        # Distribution top mode
        high_60d = price_metrics.get('high_60d')
        if high_60d is None:
            logger.debug(f"DTB_REJ: {symbol} - No 60d high available")
            return False

        distance = abs(high_60d - current_price) / current_price
        if distance > self.PARAMS['max_distance_from_level']:
            logger.debug(f"DTB_REJ: {symbol} - Too far from 60d high: {distance:.2%} > {self.PARAMS['max_distance_from_level']:.2%}")
            return False

        # Check for weakness
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', current_price)
        ema21 = ema.get('ema21', current_price)

        weakness = ema8 < ema21 or current_price < ema8
        if not weakness:
            logger.debug(f"DTB_REJ: {symbol} - No weakness signal (EMA8 {ema8:.2f} vs EMA21 {ema21:.2f})")
            return False

        logger.debug(f"DTB_PASS: {symbol} - Near 60d high {high_60d:.2f}, showing weakness")

    else:  # long mode
        # Accumulation bottom mode
        low_60d = price_metrics.get('low_60d')
        if low_60d is None:
            logger.debug(f"DTB_REJ: {symbol} - No 60d low available")
            return False

        distance = abs(current_price - low_60d) / current_price
        if distance > self.PARAMS['max_distance_from_level']:
            logger.debug(f"DTB_REJ: {symbol} - Too far from 60d low: {distance:.2%} > {self.PARAMS['max_distance_from_level']:.2%}")
            return False

        # Check for strength
        ema = ind.indicators.get('ema', {})
        ema8 = ema.get('ema8', current_price)
        ema21 = ema.get('ema21', current_price)

        strength = ema8 > ema21 or current_price > ema8
        if not strength:
            logger.debug(f"DTB_REJ: {symbol} - No strength signal (EMA8 {ema8:.2f} vs EMA21 {ema21:.2f})")
            return False

        logger.debug(f"DTB_PASS: {symbol} - Near 60d low {low_60d:.2f}, showing strength")

    return True
```

- [x] **Step 3: Commit the changes**

```bash
git add core/strategies/double_top_bottom.py
git commit -m "fix(double_top): reduce test interval 10->7 days, add filter logging"
```

---

### Task 7: Update Documentation

**Files:**
- Modify: `docs/Strategy_Description.md` (multiple sections)

- [x] **Step 1: Update MomentumBreakout pre-filter threshold**

Find line ~471 (52w high proximity in pre-filter) and update:

```markdown
### Pre-filter
- 52-week high proximity <25% (relaxed from 10% for more candidates)
- RS > 80 percentile
```

- [x] **Step 2: Update DoubleTopBottom test interval**

Find line ~411 (Test Strength section) and update:

```markdown
**Components:**
- Touch count (>3)
- Interval (>7 days, was 10 days - relaxed for more signals)
- Left/right side (Expert A): Left = Tier B max
```

- [x] **Step 3: Update RangeShort market environment**

Find line ~315-319 and update:

```markdown
### Market Environment Filter

**Pre-filter** (SPY context):
- If SPY > EMA200: Skip (no shorts in bull)
- If SPY < EMA200 OR flat (±0.3%): Proceed

Note: Now allows sector-level shorts even if SPY is flat
```

- [x] **Step 4: Commit the changes**

```bash
git add docs/Strategy_Description.md
git commit -m "docs: update thresholds to match relaxed filter implementations"
```

---

### Task 8: Test Run

- [x] **Step 1: Run test scan with a few symbols**

```bash
python scheduler.py --test --symbols AAPL,MSFT,NVDA,TSLA,AMD
```

Expected: Should complete without errors and produce candidates.

- [x] **Step 2: Check log output for debug messages**

```bash
grep -E "(MB_|RS_|U&R_|DTB_|CAP_)" logs/scanner_*.log | head -50
```

Expected: Should see debug messages showing filter decisions.

- [x] **Step 3: Verify VIX fetch works**

```bash
grep -i vix logs/scanner_*.log | head -10
```

Expected: Should not see "possibly delisted" errors for ^VIX.

---

## Post-Implementation Checklist

- [x] All 6 strategies produce debug log output
- [x] VIX symbol corrected to ^VIX
- [x] MomentumBreakout produces >0 candidates
- [x] SupportBounce doesn't skip when SPY slightly below EMA200
- [x] RangeShort pre-filter passes >5% of symbols
- [x] DoubleTopBottom uses 7-day interval
- [x] Documentation updated

---

## Rollback Plan

If issues occur, revert individual commits:
```bash
git revert <commit-hash>  # For each fix if needed
```

Or restore original files from git:
```bash
git checkout HEAD~6 -- core/strategies/capitulation_rebound.py core/indicators.py core/strategies/momentum_breakout.py core/strategies/support_bounce.py core/strategies/range_short.py core/strategies/double_top_bottom.py
```
