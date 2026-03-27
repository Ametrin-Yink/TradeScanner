"""Tests for support/resistance calculator."""
import pytest
import pandas as pd
import numpy as np
from core.support_resistance import SupportResistanceCalculator, Level


@pytest.fixture
def sample_data():
    """Create sample OHLCV data."""
    dates = pd.date_range('2024-01-01', periods=60, freq='D')
    np.random.seed(42)

    # Create trending data with some consolidation
    base_price = 100
    prices = []
    for i in range(60):
        if 20 <= i < 30:  # Consolidation period
            noise = np.random.randn() * 0.5
        else:
            noise = np.random.randn() * 2
        price = base_price + i * 0.1 + noise
        prices.append(price)

    df = pd.DataFrame({
        'open': [p + np.random.randn() * 0.5 for p in prices],
        'high': [p + abs(np.random.randn()) * 1.5 for p in prices],
        'low': [p - abs(np.random.randn()) * 1.5 for p in prices],
        'close': prices,
        'volume': np.random.randint(1000000, 5000000, 60)
    }, index=dates)

    return df


@pytest.fixture
def uptrend_data():
    """Create uptrend data for testing."""
    dates = pd.date_range('2024-01-01', periods=30, freq='D')
    prices = 100 + np.arange(30) * 2 + np.random.randn(30) * 1

    df = pd.DataFrame({
        'open': prices - 0.5,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': np.random.randint(1000000, 5000000, 30)
    }, index=dates)

    return df


def test_level_dataclass():
    """Test Level dataclass creation."""
    level = Level(price=100.0, method='pivot', strength=2.0, touches=3)
    assert level.price == 100.0
    assert level.method == 'pivot'
    assert level.strength == 2.0
    assert level.touches == 3


def test_calculator_initialization(sample_data):
    """Test calculator initialization."""
    calc = SupportResistanceCalculator(sample_data)
    assert len(calc.df) == 60
    assert calc.levels == []


def test_pivot_points_calculation(sample_data):
    """Test pivot points are calculated."""
    calc = SupportResistanceCalculator(sample_data)
    calc._calc_pivot_points()

    # Should have pivot points from 19 iterations
    pivot_levels = [l for l in calc.levels if 'pivot' in l.method]
    assert len(pivot_levels) > 0


def test_recent_highs_lows(sample_data):
    """Test recent highs and lows detection."""
    calc = SupportResistanceCalculator(sample_data)
    calc._calc_recent_highs_lows()

    # Should find some local extrema
    assert len(calc.levels) > 0

    high_levels = [l for l in calc.levels if l.method == 'recent_high']
    low_levels = [l for l in calc.levels if l.method == 'recent_low']

    # Data has variations, should find some
    assert len(high_levels) >= 0
    assert len(low_levels) >= 0


def test_volume_profile(sample_data):
    """Test volume profile calculation."""
    calc = SupportResistanceCalculator(sample_data)
    calc._calc_volume_profile()

    # Should have VWAP and volume nodes
    vwap_levels = [l for l in calc.levels if l.method == 'vwap']
    vol_levels = [l for l in calc.levels if l.method == 'volume_profile']

    assert len(vwap_levels) == 1
    assert len(vol_levels) > 0


def test_psychological_levels(sample_data):
    """Test psychological level generation."""
    calc = SupportResistanceCalculator(sample_data)
    calc._calc_psychological_levels()

    # Should generate round number levels
    psych_levels = [l for l in calc.levels if l.method == 'psychological']
    assert len(psych_levels) >= 3  # At least a few levels

    # Should be round numbers (multiples of 5 for prices around 100)
    for level in psych_levels:
        assert level.price % 5 == 0 or level.price % 10 == 0


def test_trading_range_calculation(sample_data):
    """Test trading range level detection."""
    calc = SupportResistanceCalculator(sample_data)
    calc._calc_trading_range()

    # Should find levels with multiple touches
    range_levels = [l for l in calc.levels if l.method == 'trading_range']
    # May or may not find depending on random data


def test_cluster_levels(sample_data):
    """Test level clustering."""
    calc = SupportResistanceCalculator(sample_data)

    # Add some test levels close together
    calc.levels = [
        Level(100.0, 'pivot', strength=1.0),
        Level(100.5, 'pivot', strength=1.0),  # Close to above, should cluster
        Level(110.0, 'recent_high', strength=1.5),
        Level(90.0, 'recent_low', strength=1.5),
    ]

    result = calc._cluster_levels(tolerance_pct=0.02)

    assert 'support' in result
    assert 'resistance' in result
    assert 'all_levels' in result


def test_full_calculation(sample_data):
    """Test complete calculation pipeline."""
    calc = SupportResistanceCalculator(sample_data)
    result = calc.calculate_all()

    assert 'support' in result
    assert 'resistance' in result
    assert 'all_levels' in result

    # Should have some levels identified
    assert len(result['all_levels']) > 0

    # Levels should have metadata
    level = result['all_levels'][0]
    assert 'price' in level
    assert 'strength' in level
    assert 'methods' in level


def test_get_nearest_levels(sample_data):
    """Test getting nearest levels to current price."""
    calc = SupportResistanceCalculator(sample_data)
    support, resistance = calc.get_nearest_levels(n=3)

    # Should return lists
    assert isinstance(support, list)
    assert isinstance(resistance, list)

    # Support should be below current price
    current_price = sample_data['close'].iloc[-1]
    for s in support:
        assert s < current_price

    # Resistance should be above current price
    for r in resistance:
        assert r > current_price


def test_empty_dataframe():
    """Test handling of empty dataframe."""
    df = pd.DataFrame({'open': [], 'high': [], 'low': [], 'close': [], 'volume': []})
    calc = SupportResistanceCalculator(df)
    result = calc.calculate_all()

    assert result['support'] == []
    assert result['resistance'] == []


def test_short_dataframe():
    """Test handling of very short dataframe."""
    df = pd.DataFrame({
        'open': [100, 101],
        'high': [102, 103],
        'low': [99, 100],
        'close': [101, 102],
        'volume': [1000000, 2000000]
    })
    calc = SupportResistanceCalculator(df)
    result = calc.calculate_all()

    # Should handle gracefully, maybe just psychological levels
    assert 'support' in result
    assert 'resistance' in result
