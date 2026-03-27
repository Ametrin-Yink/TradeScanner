"""Tests for technical indicators."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.indicators import TechnicalIndicators, IndicatorValues, calculate_indicators_for_symbol


@pytest.fixture
def sample_data():
    """Create sample OHLCV data for testing."""
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # Create trending data
    base = 100
    trend = np.linspace(0, 20, 100)
    noise = np.random.randn(100) * 2

    closes = base + trend + noise
    highs = closes + abs(np.random.randn(100)) * 2
    lows = closes - abs(np.random.randn(100)) * 2
    opens = closes - np.random.randn(100) * 0.5

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': np.random.randint(1000000, 5000000, 100)
    }, index=dates)

    return df


@pytest.fixture
def uptrend_data():
    """Create clear uptrend data."""
    dates = pd.date_range('2024-01-01', periods=60, freq='D')

    # Strong uptrend
    closes = 100 + np.arange(60) * 1.5 + np.random.randn(60) * 0.5
    highs = closes + 1
    lows = closes - 1

    df = pd.DataFrame({
        'open': lows,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': np.random.randint(1000000, 5000000, 60)
    }, index=dates)

    return df


@pytest.fixture
def downtrend_data():
    """Create clear downtrend data."""
    dates = pd.date_range('2024-01-01', periods=60, freq='D')

    # Strong downtrend
    closes = 100 - np.arange(60) * 1.5 + np.random.randn(60) * 0.5
    highs = closes + 1
    lows = closes - 1

    df = pd.DataFrame({
        'open': highs,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': np.random.randint(1000000, 5000000, 60)
    }, index=dates)

    return df


def test_indicator_initialization(sample_data):
    """Test TechnicalIndicators initialization."""
    calc = TechnicalIndicators(sample_data)

    assert len(calc.df) == 100
    assert calc.indicators == {}


def test_calculate_emas(sample_data):
    """Test EMA calculations."""
    calc = TechnicalIndicators(sample_data)
    emas = calc._calculate_emas()

    assert 'ema8' in emas
    assert 'ema21' in emas
    assert 'ema50' in emas

    assert emas['ema8'] is not None
    assert emas['ema21'] is not None
    assert emas['ema50'] is not None

    # EMAs should be different values
    assert emas['ema8'] != emas['ema21']
    assert emas['ema21'] != emas['ema50']


def test_calculate_atr(sample_data):
    """Test ATR calculation."""
    calc = TechnicalIndicators(sample_data)
    atr_data = calc._calculate_atr()

    assert 'atr' in atr_data
    assert 'atr_pct' in atr_data
    assert atr_data['atr'] is not None
    assert atr_data['atr_pct'] is not None

    # ATR should be positive
    assert atr_data['atr'] > 0
    assert atr_data['atr_pct'] > 0


def test_calculate_adr(sample_data):
    """Test ADR calculation."""
    calc = TechnicalIndicators(sample_data)
    adr_data = calc._calculate_adr()

    assert 'adr' in adr_data
    assert 'adr_pct' in adr_data
    assert adr_data['adr'] is not None
    assert adr_data['adr_pct'] is not None

    # ADR should be positive
    assert adr_data['adr'] > 0
    assert adr_data['adr_pct'] > 0


def test_calculate_rsi(sample_data):
    """Test RSI calculation."""
    calc = TechnicalIndicators(sample_data)
    rsi_data = calc._calculate_rsi()

    assert 'rsi' in rsi_data
    assert rsi_data['rsi'] is not None

    # RSI should be between 0 and 100
    assert 0 <= rsi_data['rsi'] <= 100


def test_calculate_volume_metrics(sample_data):
    """Test volume metrics calculation."""
    calc = TechnicalIndicators(sample_data)
    volume_data = calc._calculate_volume_metrics()

    assert 'volume_sma' in volume_data
    assert 'current_volume' in volume_data
    assert 'volume_ratio' in volume_data
    assert 'volume_spike' in volume_data

    assert volume_data['volume_sma'] is not None
    assert volume_data['current_volume'] is not None
    assert volume_data['volume_ratio'] is not None
    assert isinstance(volume_data['volume_spike'], (bool, np.bool_))


def test_calculate_price_metrics(sample_data):
    """Test price metrics calculation."""
    calc = TechnicalIndicators(sample_data)
    metrics = calc._calculate_price_metrics()

    assert 'current_price' in metrics
    assert 'high_20d' in metrics
    assert 'low_20d' in metrics
    assert 'high_60d' in metrics
    assert 'gaps_5d' in metrics

    assert metrics['current_price'] > 0
    assert metrics['high_20d'] >= metrics['low_20d']


def test_calculate_all(sample_data):
    """Test full calculation pipeline."""
    calc = TechnicalIndicators(sample_data)
    indicators = calc.calculate_all()

    assert 'ema' in indicators
    assert 'atr' in indicators
    assert 'adr' in indicators
    assert 'rsi' in indicators
    assert 'volume' in indicators
    assert 'price_metrics' in indicators


def test_calculate_all_insufficient_data():
    """Test handling of insufficient data."""
    df = pd.DataFrame({
        'open': [100, 101],
        'high': [102, 103],
        'low': [99, 100],
        'close': [101, 102],
        'volume': [1000000, 2000000]
    })

    calc = TechnicalIndicators(df)
    indicators = calc.calculate_all()

    assert indicators == {}


def test_get_summary(sample_data):
    """Test summary generation."""
    calc = TechnicalIndicators(sample_data)
    summary = calc.get_summary()

    assert isinstance(summary, IndicatorValues)
    assert summary.ema8 is not None
    assert summary.ema21 is not None
    assert summary.ema50 is not None
    assert summary.atr is not None
    assert summary.adr is not None
    assert summary.adr_pct is not None
    assert summary.rsi is not None


def test_is_above_ema(uptrend_data):
    """Test EMA position check."""
    calc = TechnicalIndicators(uptrend_data)

    assert calc.is_above_ema(50) == True
    assert calc.is_above_ema(21) == True


def test_is_uptrend(uptrend_data, downtrend_data):
    """Test trend detection."""
    uptrend_calc = TechnicalIndicators(uptrend_data)
    downtrend_calc = TechnicalIndicators(downtrend_data)

    assert uptrend_calc.is_uptrend() is True
    assert downtrend_calc.is_uptrend() is False


def test_get_trend_strength(uptrend_data, downtrend_data):
    """Test trend strength calculation."""
    uptrend_calc = TechnicalIndicators(uptrend_data)
    downtrend_calc = TechnicalIndicators(downtrend_data)

    up_strength = uptrend_calc.get_trend_strength()
    down_strength = downtrend_calc.get_trend_strength()

    # Uptrend should have positive strength
    assert up_strength > 0

    # Downtrend should have negative strength
    assert down_strength < 0


def test_calculate_indicators_for_symbol_success(sample_data):
    """Test convenience function."""
    result = calculate_indicators_for_symbol('AAPL', sample_data)

    assert result is not None
    assert result['symbol'] == 'AAPL'
    assert 'ema' in result
    assert 'atr' in result
    assert 'last_price' in result


def test_calculate_indicators_for_symbol_failure():
    """Test error handling in convenience function."""
    # Empty DataFrame should fail gracefully
    df = pd.DataFrame()

    result = calculate_indicators_for_symbol('INVALID', df)

    # Should return None on failure
    assert result is None


def test_rsi_overbought():
    """Test RSI in overbought condition (price keeps rising)."""
    dates = pd.date_range('2024-01-01', periods=20, freq='D')

    # Strong upward movement
    closes = 100 + np.arange(20) * 5  # Steady rise
    df = pd.DataFrame({
        'open': closes - 1,
        'high': closes + 2,
        'low': closes - 2,
        'close': closes,
        'volume': [1000000] * 20
    }, index=dates)

    calc = TechnicalIndicators(df)
    rsi_data = calc._calculate_rsi()

    # RSI should be high in strong uptrend
    assert rsi_data['rsi'] > 50


def test_rsi_oversold():
    """Test RSI in oversold condition (price keeps falling)."""
    dates = pd.date_range('2024-01-01', periods=20, freq='D')

    # Strong downward movement
    closes = 100 - np.arange(20) * 5
    df = pd.DataFrame({
        'open': closes + 1,
        'high': closes + 2,
        'low': closes - 2,
        'close': closes,
        'volume': [1000000] * 20
    }, index=dates)

    calc = TechnicalIndicators(df)
    rsi_data = calc._calculate_rsi()

    # RSI should be low in strong downtrend
    assert rsi_data['rsi'] < 50
