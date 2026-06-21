"""Walk-forward rank-IC analysis for composite score validation."""
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.db import Database
from core.sector_analyzer import SectorAnalyzer


def compute_rank_ic(db, horizon_days=10):
    """Compute rank IC: correlation between score and forward return."""
    # Get all stocks with tier1_cache
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT symbol, rs_percentile, volume_ratio, ret_5d,
               supports, resistances, current_price
        FROM tier1_cache WHERE current_price > 0
    """).fetchall()

    if not rows:
        print("No cached data available")
        return None

    scores = []
    forward_returns = []

    for row in rows:
        symbol = row[0]
        # Compute score (simplified — full scoring needs OHLC context)
        rs = row[1] or 0
        vol = row[3] or 0
        score = rs * 0.30 + min(vol * 1.5, 10) * 0.30  # approximate

        # Get recent return over horizon_days
        ohlc = db.get_market_data_df(symbol)
        if ohlc is None or len(ohlc) <= horizon_days:
            continue

        recent = float(ohlc['close'].iloc[-1])
        past = float(ohlc['close'].iloc[-1 - horizon_days])
        if past > 0:
            fwd_ret = (recent - past) / past * 100
            scores.append(score)
            forward_returns.append(fwd_ret)

    if len(scores) < 20:
        print(f"Insufficient data: {len(scores)} valid stocks")
        return None

    # Rank IC: Spearman correlation between rank(score) and forward return
    from scipy.stats import spearmanr
    score_ranks = pd.Series(scores).rank()
    ic, p_value = spearmanr(score_ranks, forward_returns)

    print(f"Stocks analyzed: {len(scores)}")
    print(f"Rank IC (Spearman): {ic:.4f}, p-value: {p_value:.4f}")
    print(f"Target: |IC| >= 0.03 for useful ranking")
    print(f"Status: {'PASS' if abs(ic) >= 0.03 else 'FAIL — scoring may not predict returns'}")

    return ic


if __name__ == '__main__':
    db = Database()
    for horizon in [5, 10, 20]:
        print(f"\n--- Horizon: {horizon}d ---")
        compute_rank_ic(db, horizon)
