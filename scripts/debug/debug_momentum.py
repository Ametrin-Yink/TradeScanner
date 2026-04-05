"""Detailed debug for Strategy A: MomentumBreakout."""
import pandas as pd
from data.db import Database
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators

db = Database()
fetcher = DataFetcher(db=db)

symbols = db.get_active_stocks()
backtest_dt = pd.Timestamp('2026-01-02')

# Strategy A parameters
PARAMS = {
    'min_rs_percentile': 50,
    'min_listing_days': 60,
    'platform_lookback': (15, 60),
    'max_range_pct': 0.12,
    'concentration_threshold': 0.50,
    'volume_contraction_vs_platform': 0.70,
    'breakout_pct': 0.02,
    'clv_threshold': 0.75,
    'breakout_volume_vs_20d_sma': 2.0,
}

# Counters for each rejection stage
total = 0
rs_pass = 0
data_len_pass = 0
ema200_pass = 0
ret3m_pass = 0
volume_pass = 0
vcp_pass = 0
volume_contr_pass = 0
breakout_pass = 0
clv_pass = 0
vol_ratio_pass = 0
all_pass = 0

# Detailed rejection tracking
rejection_stages = {
    'rs_gate': [],
    'data_len': [],
    'ema200': [],
    'ret_3m': [],
    'avg_volume': [],
    'vcp_platform': [],
    'volume_contraction': [],
    'breakout_pct': [],
    'clv': [],
    'volume_ratio': [],
    'passed': []
}

for symbol in symbols:
    total += 1
    df, _ = fetcher._get_cached_data(symbol)
    if df is None:
        continue

    df = df[df.index <= backtest_dt]
    if len(df) < 50:
        continue

    # Get phase0_data (RS percentile)
    tier1 = db.get_tier1_cache(symbol)
    if not tier1:
        continue

    rs_pct = tier1.get('rs_percentile', 0) or 0
    ret_3m = (tier1.get('ret_3m', 0) or 0) / 100.0  # Convert % to decimal

    # Stage 1: RS gate
    if rs_pct < PARAMS['min_rs_percentile']:
        rejection_stages['rs_gate'].append((symbol, rs_pct))
        continue
    rs_pass += 1

    # Stage 2: Data length
    if len(df) < PARAMS['min_listing_days']:
        rejection_stages['data_len'].append(symbol)
        continue
    data_len_pass += 1

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Stage 3: EMA200
    ema200 = ind.indicators.get('ema', {}).get('ema200')
    if ema200 is None or current_price <= ema200:
        rejection_stages['ema200'].append((symbol, current_price, ema200))
        continue
    ema200_pass += 1

    # Stage 4: 3m return
    if ret_3m < -0.20:
        rejection_stages['ret_3m'].append((symbol, ret_3m))
        continue
    ret3m_pass += 1

    # Stage 5: Avg volume
    avg_volume_20d = df['volume'].tail(20).mean()
    if avg_volume_20d < 100_000:
        rejection_stages['avg_volume'].append((symbol, avg_volume_20d))
        continue
    volume_pass += 1

    # Stage 6: VCP Platform
    platform = ind.detect_vcp_platform(
        lookback_range=PARAMS['platform_lookback'],
        max_range_pct=PARAMS['max_range_pct'],
        concentration_threshold=PARAMS['concentration_threshold']
    )
    if platform is None or not platform.get('is_valid'):
        rejection_stages['vcp_platform'].append(symbol)
        continue
    vcp_pass += 1

    # Stage 7: Volume contraction
    if platform['volume_contraction_ratio'] > PARAMS['volume_contraction_vs_platform']:
        rejection_stages['volume_contraction'].append((symbol, platform['volume_contraction_ratio']))
        continue
    volume_contr_pass += 1

    # Stage 8: Breakout pct
    platform_high = platform['platform_high']
    breakout_pct = (current_price - platform_high) / platform_high
    if breakout_pct < PARAMS['breakout_pct']:
        rejection_stages['breakout_pct'].append((symbol, breakout_pct))
        continue
    breakout_pass += 1

    # Stage 9: CLV
    clv = ind.calculate_clv()
    if clv < PARAMS['clv_threshold']:
        rejection_stages['clv'].append((symbol, clv))
        continue
    clv_pass += 1

    # Stage 10: Volume ratio
    current_volume = df['volume'].iloc[-1]
    volume_ratio = current_volume / avg_volume_20d if avg_volume_20d > 0 else 0
    if volume_ratio < PARAMS['breakout_volume_vs_20d_sma']:
        rejection_stages['volume_ratio'].append((symbol, volume_ratio))
        continue
    vol_ratio_pass += 1

    all_pass += 1
    rejection_stages['passed'].append(symbol)

print("="*70)
print("STRATEGY A: MOMENTUM BREAKOUT - DETAILED FILTER ANALYSIS")
print("="*70)
print(f"\nTotal symbols tested: {total}")
print(f"\n=== PASS THROUGH EACH STAGE ===")
print(f"  RS >= 50%:           {rs_pass} ({rs_pass/total*100:.1f}%)")
print(f"  Data >= 60 days:     {data_len_pass} ({data_len_pass/total*100:.1f}%)")
print(f"  Price > EMA200:      {ema200_pass} ({ema200_pass/total*100:.1f}%)")
print(f"  3m return >= -20%:   {ret3m_pass} ({ret3m_pass/total*100:.1f}%)")
print(f"  Avg vol >= 100K:     {volume_pass} ({volume_pass/total*100:.1f}%)")
print(f"  VCP platform valid:  {vcp_pass} ({vcp_pass/total*100:.1f}%)")
print(f"  Volume contraction:  {volume_contr_pass} ({volume_contr_pass/total*100:.1f}%)")
print(f"  Breakout >= 2%:      {breakout_pass} ({breakout_pass/total*100:.1f}%)")
print(f"  CLV >= 0.75:         {clv_pass} ({clv_pass/total*100:.1f}%)")
print(f"  Volume ratio >= 2x:  {vol_ratio_pass} ({vol_ratio_pass/total*100:.1f}%)")
print(f"\n  ALL PASSED: {all_pass}")

print(f"\n=== REJECTION BREAKDOWN ===")
for stage, items in rejection_stages.items():
    if items:
        print(f"\n{stage}: {len(items)} rejections")
        if len(items) <= 5:
            for item in items:
                print(f"    {item}")
        else:
            print(f"    First 5: {items[:5]}")
            print(f"    Last 5: {items[-5:]}")
