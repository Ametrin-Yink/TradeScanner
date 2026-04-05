"""Tests for market regime v7.0 hardening."""
import pytest
import pandas as pd
from core.market_regime import MarketRegimeDetector


class TestMarketRegimeV7:
    """Test regime hardening."""

    def test_hard_rule_bear_floor(self):
        """SPY < EMA50 + IWM < EMA200 should floor at bear_moderate."""
        detector = MarketRegimeDetector()

        # Create mock data: SPY below EMA50, IWM below EMA200
        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining trend (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]  # Declining
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM declining trend (below EMA200)
        iwm_prices = [200 - i * 0.3 for i in range(200)]  # Declining
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # Mock AI calls neutral
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('neutral', spy_data, iwm_data)

        assert result == 'bear_moderate', f"Should floor at bear_moderate, got {result}"

    def test_hard_rule_allows_bear_strong(self):
        """Hard rules should allow bear_strong, only floor bull/neutral."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining trend (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM declining trend (below EMA200)
        iwm_prices = [200 - i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI calls bear_strong - should be allowed
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('bear_strong', spy_data, iwm_data)

        assert result == 'bear_strong', f"Should allow bear_strong, got {result}"

    def test_hard_rule_bull_strong_override(self):
        """SPY < EMA50 + IWM < EMA200 should override bull_strong."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining trend (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM declining trend (below EMA200)
        iwm_prices = [200 - i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI incorrectly calls bull_strong
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('bull_strong', spy_data, iwm_data)

        assert result == 'bear_moderate', f"Should override bull_strong to bear_moderate, got {result}"

    def test_hard_rule_bull_moderate_override(self):
        """SPY < EMA50 + IWM < EMA200 should override bull_moderate."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining trend (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM declining trend (below EMA200)
        iwm_prices = [200 - i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI incorrectly calls bull_moderate
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('bull_moderate', spy_data, iwm_data)

        assert result == 'bear_moderate', f"Should override bull_moderate to bear_moderate, got {result}"

    def test_hard_rule_no_override_when_conditions_not_met(self):
        """No override when SPY >= EMA50 or IWM >= EMA200."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY uptrend (above EMA50)
        spy_prices = [400 + i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM uptrend (above EMA200)
        iwm_prices = [150 + i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI calls bull_strong - should pass through
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('bull_strong', spy_data, iwm_data)

        assert result == 'bull_strong', f"Should pass through bull_strong, got {result}"

    def test_hard_rule_only_spY_below_not_enough(self):
        """SPY < EMA50 alone is not enough - need IWM < EMA200 too."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM uptrend (above EMA200)
        iwm_prices = [150 + i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI calls neutral - should pass through since IWM is strong
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('neutral', spy_data, iwm_data)

        assert result == 'neutral', f"Should pass through neutral when only SPY is weak, got {result}"

    def test_hard_rule_only_iwm_below_not_enough(self):
        """IWM < EMA200 alone is not enough - need SPY < EMA50 too."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY uptrend (above EMA50)
        spy_prices = [400 + i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # IWM declining (below EMA200)
        iwm_prices = [200 - i * 0.3 for i in range(200)]
        iwm_df = pd.DataFrame({'close': iwm_prices}, index=dates)

        # AI calls bull_strong - should pass through since SPY is strong
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('bull_strong', spy_data, iwm_data)

        assert result == 'bull_strong', f"Should pass through bull_strong when only IWM is weak, got {result}"

    def test_hard_rule_missing_iwm_data(self):
        """Handle missing IWM data gracefully."""
        detector = MarketRegimeDetector()

        dates = pd.date_range('2024-01-01', periods=200, freq='D')

        # SPY declining (below EMA50)
        spy_prices = [450 - i * 0.5 for i in range(200)]
        spy_df = pd.DataFrame({'close': spy_prices}, index=dates)

        # Empty IWM data
        iwm_df = pd.DataFrame()

        # AI calls neutral - should pass through since IWM data is missing
        spy_data = {'price': spy_prices[-1], 'ema50': spy_prices[-50]}
        iwm_data = iwm_df

        result = detector._apply_hard_rules('neutral', spy_data, iwm_data)

        assert result == 'neutral', f"Should pass through when IWM data is missing, got {result}"
