import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import numpy as np
from core.data_validator import validate_ohlc, validate_ticker_active


def test_validate_ohlc_good_data():
    df = pd.DataFrame({
        'open': [100.0, 101.0],
        'high': [102.0, 103.0],
        'low': [99.0, 100.0],
        'close': [101.0, 102.0],
        'volume': [1000000, 1200000],
    })
    warnings = validate_ohlc(df)
    assert warnings == []


def test_validate_ohlc_high_low():
    df = pd.DataFrame({
        'open': [100.0],
        'high': [99.0],
        'low': [101.0],
        'close': [100.0],
        'volume': [1000000],
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('high' in w.lower() or 'low' in w.lower() for w in warnings)


def test_validate_ohlc_close_outside():
    df = pd.DataFrame({
        'open': [100.0],
        'high': [102.0],
        'low': [99.0],
        'close': [105.0],
        'volume': [1000000],
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('close' in w.lower() for w in warnings)


def test_validate_ohlc_nan():
    df = pd.DataFrame({
        'open': [100.0, np.nan],
        'high': [102.0, 103.0],
        'low': [99.0, 100.0],
        'close': [101.0, 102.0],
        'volume': [1000000, 1200000],
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('nan' in w.lower() or 'null' in w.lower() or 'missing' in w.lower() for w in warnings)


def test_validate_ohlc_zero_volume():
    df = pd.DataFrame({
        'open': [100.0],
        'high': [102.0],
        'low': [99.0],
        'close': [101.0],
        'volume': [0],
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('volume' in w.lower() or 'zero' in w.lower() for w in warnings)


def test_validate_ohlc_extreme_gap():
    df = pd.DataFrame({
        'open': [100.0, 118.0],
        'high': [102.0, 120.0],
        'low': [99.0, 117.0],
        'close': [101.0, 119.0],
        'volume': [1000000, 1200000],
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('gap' in w.lower() for w in warnings)


def test_validate_ohlc_stale_prices():
    rng = np.random.default_rng(42)
    closes = [100.0] * 28 + [100.01] * 2
    df = pd.DataFrame({
        'open': [c - 0.1 for c in closes],
        'high': [c + 0.2 for c in closes],
        'low': [c - 0.2 for c in closes],
        'close': closes,
        'volume': [1000000] * len(closes),
    })
    warnings = validate_ohlc(df)
    assert len(warnings) >= 1
    assert any('stale' in w.lower() or 'unique' in w.lower() or 'flat' in w.lower() for w in warnings)


def test_validate_ticker_active_true():
    result = validate_ticker_active('AAPL')
    assert result is True


def test_validate_ticker_active_false():
    result = validate_ticker_active('SNDK')
    assert result is False
