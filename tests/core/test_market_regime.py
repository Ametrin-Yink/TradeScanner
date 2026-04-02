import pytest
import pandas as pd
import numpy as np
from core.market_regime import MarketRegimeDetector, REGIME_ALLOCATION_TABLE


def test_regime_allocation_table_has_all_regimes():
    """Verify allocation table covers all 6 regimes."""
    expected_regimes = [
        'bull_strong', 'bull_moderate', 'neutral',
        'bear_moderate', 'bear_strong', 'extreme_vix'
    ]
    for regime in expected_regimes:
        assert regime in REGIME_ALLOCATION_TABLE
        # Each regime should have 8 strategies
        assert len(REGIME_ALLOCATION_TABLE[regime]) == 8
        # Total should be 10
        assert sum(REGIME_ALLOCATION_TABLE[regime].values()) == 10


def test_extreme_vix_triggers_regardless_of_spy():
    """VIX > 30 should trigger extreme_vix even if SPY looks bullish."""
    detector = MarketRegimeDetector()

    # Create bullish SPY but extreme VIX
    spy_df = pd.DataFrame({
        'close': [450.0] * 200,
        'high': [455.0] * 200,
        'low': [445.0] * 200
    })
    vix_df = pd.DataFrame({'close': [35.0]})  # Extreme

    regime = detector.detect_regime(spy_df, vix_df)
    assert regime == 'extreme_vix'


def test_bull_strong_detection():
    """SPY > EMA50 > EMA200 with low VIX = bull_strong."""
    detector = MarketRegimeDetector()

    # Create upward trending SPY
    prices = list(range(400, 600))  # Uptrend
    spy_df = pd.DataFrame({
        'close': prices,
        'high': [p + 5 for p in prices],
        'low': [p - 5 for p in prices]
    })
    vix_df = pd.DataFrame({'close': [15.0]})  # Low fear

    regime = detector.detect_regime(spy_df, vix_df)
    assert regime == 'bull_strong'
