"""Test RS_percentile computation and caching.

Tests that rs_raw, rs_percentile, and rs_consecutive_days_80 are populated
in tier1_cache after a batch fetch (TDD: test first, then implement).
"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from pathlib import Path

from core.fetcher import DataFetcher
from data.db import Database


def _make_mock_batch_df(symbols, n_days=65):
    """Create mock MultiIndex DataFrame like yfinance.download returns.

    Args:
        symbols: List of ticker symbols
        n_days: Number of trading days (must be >= 63 for RS_raw)
    """
    dates = pd.date_range('2025-01-01', periods=n_days, freq='D')
    data = {}

    for sym in symbols:
        base = 100.0
        trend_map = {
            'AAPL': 2.0,      # strong uptrend -> highest RS_raw
            'MSFT': 0.8,      # mild uptrend  -> medium RS_raw
            'GOOGL': -0.3,    # downtrend     -> negative RS_raw
            'NVDA': 1.5,      # uptrend       -> second highest
            'AMZN': 0.2,      # slight uptrend
        }
        trend = trend_map.get(sym, 0.0)

        # Build deterministic close prices with noise
        rng = np.random.default_rng(42)
        closes = [base + j * trend + rng.normal(0, 0.5) for j in range(n_days)]
        opens = [c - rng.uniform(0, 0.5) for c in closes]
        highs = [c + rng.uniform(0, 0.8) for c in closes]
        lows = [c - rng.uniform(0, 0.8) for c in closes]
        volumes = [int(1_000_000 + j * 1000) for j in range(n_days)]

        data[(sym, 'Open')] = opens
        data[(sym, 'High')] = highs
        data[(sym, 'Low')] = lows
        data[(sym, 'Close')] = closes
        data[(sym, 'Volume')] = volumes

    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def test_rs_percentile_populated_after_fetch(tmp_path):
    """rs_percentile should be populated in tier1_cache after a batch fetch."""
    db_path = tmp_path / "test.db"
    db = Database(db_path=db_path)

    # Seed stocks
    symbols = ['AAPL', 'MSFT', 'GOOGL']
    for sym in symbols:
        db.add_stock(sym, sym, 'Technology')

    # Mock yf.download to return deterministic data
    mock_df = _make_mock_batch_df(symbols)

    with patch('core.fetcher.yf.download', return_value=mock_df):
        fetcher = DataFetcher(db=db)
        results = fetcher.fetch_multiple(symbols, period='5d')

    # Sanity — fetch_multiple returned results
    assert len(results) == 3

    # ---- Assertions ----
    for sym in symbols:
        cache = db.get_tier1_cache(sym)
        assert cache is not None, f"No tier1_cache for {sym}"
        assert cache.get('rs_raw') is not None, \
            f"rs_raw should not be None for {sym}"
        assert cache.get('rs_percentile') is not None, \
            f"rs_percentile should not be None for {sym}"
        assert cache.get('rs_consecutive_days_80') is not None, \
            f"rs_consecutive_days_80 should not be None for {sym}"

    # Ranking should follow trend strength
    caches = {sym: db.get_tier1_cache(sym) for sym in symbols}
    assert caches['AAPL']['rs_raw'] > caches['MSFT']['rs_raw']
    assert caches['MSFT']['rs_raw'] > caches['GOOGL']['rs_raw']
    assert caches['AAPL']['rs_percentile'] >= caches['MSFT']['rs_percentile']
    assert caches['MSFT']['rs_percentile'] >= caches['GOOGL']['rs_percentile']
