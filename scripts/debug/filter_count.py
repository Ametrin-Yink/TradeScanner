"""Count stocks passing each filter condition."""
import pandas as pd
from data.db import Database
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators

db = Database()
fetcher = DataFetcher(db=db)

symbols = db.get_active_stocks()
backtest_dt = pd.Timestamp('2026-01-02')

# Stats counters
total = 0
has_data = 0
price_ok = 0
volume_ok = 0
data_len_ok = 0
ti_positive = 0
rc_positive = 0
gap_valid = 0
all_pass = 0

# Also track TI score distribution
ti_scores = []

for symbol in symbols:
    total += 1
    df, _ = fetcher._get_cached_data(symbol)
    if df is None:
        continue
    has_data += 1

    df = df[df.index <= backtest_dt]
    if len(df) < 50:
        continue
    data_len_ok += 1

    current_price = df['close'].iloc[-1]
    if current_price < 2.0 or current_price > 3000.0:
        continue
    price_ok += 1

    avg_volume = df['volume'].tail(20).mean()
    if avg_volume < 100000:
        continue
    volume_ok += 1

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    # TI score
    ti_data = ind.calculate_normalized_ema_slope(market_atr_median=1.0)
    ti_score = ti_data.get('score', 0)
    ti_scores.append(ti_score)

    if ti_score <= 0:
        continue
    ti_positive += 1

    # RC score
    rc_data = ind.calculate_retracement_structure()
    rc_score = rc_data.get('total_score', 0)
    if rc_score <= 0:
        continue
    rc_positive += 1

    # Gap veto
    gap_data = ind.estimate_gap_impact()
    if not gap_data.get('is_valid', True):
        continue
    gap_valid += 1

    all_pass += 1

print(f"Total symbols: {total}")
print(f"Has data: {has_data}")
print(f"Price OK ($2-$3000): {price_ok}")
print(f"Volume OK (>=100K): {volume_ok}")
print(f"Data len OK (>=50): {data_len_ok}")
print(f"TI score > 0: {ti_positive}")
print(f"RC score > 0: {rc_positive}")
print(f"Gap valid: {gap_valid}")
print(f"ALL PASS: {all_pass}")

# TI score distribution
if ti_scores:
    print(f"\nTI Score distribution:")
    print(f"  Mean: {sum(ti_scores)/len(ti_scores):.2f}")
    print(f"  Max: {max(ti_scores):.2f}")
    print(f"  > 0: {sum(1 for s in ti_scores if s > 0)}")
    print(f"  > 0.4: {sum(1 for s in ti_scores if s > 0.4)}")
    print(f"  > 0.8: {sum(1 for s in ti_scores if s > 0.8)}")
    print(f"  > 1.2: {sum(1 for s in ti_scores if s > 1.2)}")
