"""Check if any stocks are actually breaking out (price near/at platform high)."""
import pandas as pd
from data.db import Database
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators

db = Database()
fetcher = DataFetcher(db=db)

symbols = db.get_active_stocks()
backtest_dt = pd.Timestamp('2026-01-02')

PARAMS = {
    'platform_lookback': (15, 60),
    'max_range_pct': 0.12,
    'concentration_threshold': 0.50,
}

print("Stocks with valid VCP platforms and their breakout status:\n")
print(f"{'Symbol':<10} {'Price':<10} {'Plat High':<10} {'Breakout%':<10} {'CLV':<8} {'Vol Ratio':<10} {'Status'}")
print("-"*80)

for symbol in symbols[:500]:  # Sample first 500
    df, _ = fetcher._get_cached_data(symbol)
    if df is None:
        continue

    df = df[df.index <= backtest_dt]
    if len(df) < 60:
        continue

    tier1 = db.get_tier1_cache(symbol)
    if not tier1:
        continue

    rs_pct = tier1.get('rs_percentile', 0) or 0
    if rs_pct < 50:
        continue

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]
    ema200 = ind.indicators.get('ema', {}).get('ema200')

    if ema200 is None or current_price <= ema200:
        continue

    # Check VCP platform
    platform = ind.detect_vcp_platform(
        lookback_range=PARAMS['platform_lookback'],
        max_range_pct=PARAMS['max_range_pct'],
        concentration_threshold=PARAMS['concentration_threshold']
    )

    if platform is None or not platform.get('is_valid'):
        continue

    platform_high = platform['platform_high']
    breakout_pct = (current_price - platform_high) / platform_high

    # CLV
    clv = ind.calculate_clv()

    # Volume ratio
    avg_vol = df['volume'].tail(20).mean()
    current_vol = df['volume'].iloc[-1]
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

    status = ""
    if breakout_pct >= 0.02:
        status = "BREAKOUT!"
    elif breakout_pct >= 0:
        status = "Near breakout"
    else:
        status = "Below platform"

    print(f"{symbol:<10} {current_price:<10.2f} {platform_high:<10.2f} {breakout_pct*100:<10.2f}% {clv:<8.3f} {vol_ratio:<10.2f}x {status}")
