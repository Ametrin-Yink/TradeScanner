"""Simple filter debug for specific strategies."""
import pandas as pd
from data.db import Database
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators

db = Database()
fetcher = DataFetcher(db=db)

# Get some symbols
symbols = db.get_active_stocks()[:20]

print("Testing filter conditions for Strategies A, B, C\n")

for symbol in symbols:
    df, _ = fetcher._get_cached_data(symbol)
    if df is None or len(df) < 50:
        print(f"{symbol}: No data")
        continue

    # Test date filter
    backtest_dt = pd.Timestamp('2026-01-02')
    df = df[df.index <= backtest_dt]
    if len(df) < 50:
        print(f"{symbol}: Insufficient data after filter ({len(df)})")
        continue

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]
    avg_volume = df['volume'].tail(20).mean()

    print(f"\n{symbol}: price=${current_price:.2f}, vol={avg_volume:.0f}, len={len(df)}")

    # Strategy A (MomentumBreakout) checks
    ema200 = ind.indicators.get('ema', {}).get('ema200')
    ema200_str = f"{ema200:.2f}" if ema200 else "None"
    price_above_ema200 = current_price > ema200 if ema200 else "N/A"
    print(f"  Strat A: EMA200={ema200_str}, Price>EMA200={price_above_ema200}")

    # Strategy B (PullbackEntry) checks
    ema21 = ind.indicators.get('ema', {}).get('ema21')
    ti_data = ind.calculate_normalized_ema_slope(market_atr_median=1.0)
    rc_data = ind.calculate_retracement_structure()
    ema21_str = f"{ema21:.2f}" if ema21 else "None"
    ti_score = ti_data.get('score', 0)
    rc_score = rc_data.get('total_score', 0)
    print(f"  Strat B: EMA21={ema21_str}, TI={ti_score:.2f}, RC={rc_score:.2f}")

    # Check if price is below EMA21 (pullback condition)
    if ema21:
        below_ema21 = current_price < ema21
        print(f"         Price<EMA21: {below_ema21}")

    # Strategy C (SupportBounce) checks
    ema50 = ind.indicators.get('ema', {}).get('ema50')
    ema50_str = f"{ema50:.2f}" if ema50 else "None"
    print(f"  Strat C: EMA50={ema50_str}")
