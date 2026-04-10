"""Test that CapitulationRebound documentation matches actual code behavior."""
import pytest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
import numpy as np
import re


class TestCapitulationReboundDocumentation:
    """Test that Strategy_Description.md accurately reflects code behavior."""

    @pytest.fixture
    def doc_content(self):
        """Read the Strategy_Description.md file."""
        with open('/home/admin/Projects/TradeChanceScreen/Strategy_Description.md', 'r') as f:
            return f.read()

    def test_documentation_does_not_contain_intraday_rules(self, doc_content):
        """Verify docs don't describe intraday entry rules (5-min candles, VWAP).

        Bug: Documentation previously described intraday entry rules
        (5-minute candles, VWAP rejection) but the code uses daily EOD data.
        """
        # These terms should NOT appear in the documentation
        intraday_terms = [
            r'5-minute',
            r'5min',
            r'VWAP',
            r'vwap',
            r'Opening Range Break',
            r'opening range',
            r'First .* candle',
            r'pullback to VWAP',
            r'Rejection \(red candle\)',
        ]

        capitulation_section = self._extract_capitulation_section(doc_content)

        for term in intraday_terms:
            assert not re.search(term, capitulation_section, re.IGNORECASE), \
                f"Documentation contains intraday term '{term}' in CapitulationRebound section, " \
                f"but code uses daily EOD data"

    def test_documentation_contains_eod_based_entry(self, doc_content):
        """Verify docs describe EOD-based entry rules matching code.

        Code uses:
        - entry = current_price (daily close)
        - stop = current_price - atr * stop_atr_multiplier
        - target = ema50
        - RSI oversold (< 20)
        - Volume climax (> 4x MA20)
        """
        capitulation_section = self._extract_capitulation_section(doc_content)

        # Should describe EOD-based entry concepts
        # Using simple string searches instead of regex for reliability
        eod_terms = [
            'close',  # daily close - appears in "Close price" and "close_price"
            'EMA50',  # target is EMA50
            'RSI',    # RSI oversold condition
            '4x',     # volume > 4x
            'End-of-Day',  # explicitly states EOD based
            'EOD',
        ]

        found_eod_terms = 0
        for term in eod_terms:
            if term in capitulation_section:
                found_eod_terms += 1

        # At least some EOD terms should be present
        assert found_eod_terms >= 3, \
            f"Documentation should describe EOD-based entry rules. " \
            f"Found only {found_eod_terms} EOD terms in CapitulationRebound section. " \
            f"Expected references to: daily close, EMA50, RSI oversold, volume climax"

    def test_code_uses_daily_data_for_entry(self):
        """Verify the actual code uses daily close for entry calculation."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy

        # Read the source code
        import inspect
        source = inspect.getsource(CapitulationReboundStrategy.calculate_entry_exit)

        # Verify entry uses current_price (daily close)
        assert 'current_price' in source, \
            "Entry should be based on current_price (daily close)"
        assert 'df[\'close\'].iloc[-1]' in source or "df['close']" in source, \
            "Entry should use daily close price from dataframe"

        # Verify target uses EMA8 (quick mean reversion) with EMA21 as secondary
        assert 'ema8' in source.lower(), \
            "Target should be based on EMA8 (quick mean reversion)"
        assert 'ema21' in source.lower() or 'ema50' in source.lower(), \
            "Should reference a secondary/longer-term EMA for partial exits"

        # Verify ATR-based stop
        assert 'atr' in source.lower(), \
            "Stop should be ATR-based"
        assert 'stop_atr_multiplier' in source, \
            "Stop should use stop_atr_multiplier parameter"

    def test_code_uses_rsi_oversold_filter(self):
        """Verify code filters based on RSI oversold condition."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy

        import inspect
        source = inspect.getsource(CapitulationReboundStrategy._prefilter_symbol)

        # Verify RSI oversold check
        assert 'rsi_oversold' in source or 'rsi <' in source.lower(), \
            "Code should check for RSI oversold condition"

    def test_code_uses_volume_climax(self):
        """Verify code uses volume climax in scoring."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy

        import inspect
        source = inspect.getsource(CapitulationReboundStrategy._calculate_vc)

        # Verify volume climax check (extended tiers for true capitulation)
        assert 'volume_climax' in source.lower() or 'extreme_volume_climax' in source.lower(), \
            "Code should check for volume climax"
        assert 'volume_ratio' in source, \
            "Code should use volume ratio for scoring"

    def _extract_capitulation_section(self, content):
        """Extract the CapitulationRebound section from the markdown."""
        # Find Strategy F section - match ## but not ###
        match = re.search(
            r'## Strategy F: CapitulationRebound.*?(?=\n## [^#]|\Z)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if match:
            return match.group(0)
        return ""


class TestCapitulationReboundEntryCalculation:
    """Test the actual entry/exit calculation matches documented behavior."""

    @pytest.fixture
    def mock_strategy(self):
        """Create a mock strategy with sample data."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy
        strategy = CapitulationReboundStrategy.__new__(CapitulationReboundStrategy)
        strategy.PARAMS = {
            'stop_atr_multiplier': 2.0,
            'volume_climax_threshold': 4.0,
        }
        return strategy

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame for testing."""
        dates = pd.date_range('2024-01-01', periods=50, freq='D')
        prices = 100 + np.cumsum(np.random.randn(50) * 0.5)

        return pd.DataFrame({
            'open': prices - 0.5,
            'high': prices + 1,
            'low': prices - 1,
            'close': prices,
            'volume': np.random.randint(2_000_000, 5_000_000, 50)
        }, index=dates)

    def test_entry_is_daily_close(self, mock_strategy, sample_df):
        """Verify entry equals the daily close price."""
        from core.strategies.capitulation_rebound import ScoringDimension

        current_price = sample_df['close'].iloc[-1]

        # Mock TechnicalIndicators
        with patch('core.strategies.capitulation_rebound.TechnicalIndicators') as mock_ind:
            mock_ind_instance = MagicMock()
            mock_ind_instance.indicators = {
                'atr': {'atr': current_price * 0.02},
                'ema': {'ema8': current_price * 0.98, 'ema21': current_price * 0.93, 'ema50': current_price * 0.95}
            }
            mock_ind.return_value = mock_ind_instance

            dimensions = [
                ScoringDimension(name='MO', score=3.0, max_score=5.0, details={}),
                ScoringDimension(name='EX', score=2.0, max_score=6.0, details={}),
                ScoringDimension(name='VC', score=3.0, max_score=5.0, details={}),
            ]

            entry, stop, target = mock_strategy.calculate_entry_exit(
                'AAPL', sample_df, dimensions, 8.0, 'B'
            )

            # Entry should be the daily close (rounded to 2 decimals)
            assert abs(entry - round(current_price, 2)) < 0.01, \
                f"Entry {entry} should equal daily close {round(current_price, 2)}"

    def test_target_is_ema50(self, mock_strategy, sample_df):
        """Verify target equals EMA8 (quick mean reversion)."""
        from core.strategies.capitulation_rebound import ScoringDimension

        current_price = sample_df['close'].iloc[-1]
        ema8 = current_price * 0.98  # Mock EMA8 below price

        with patch('core.strategies.capitulation_rebound.TechnicalIndicators') as mock_ind:
            mock_ind_instance = MagicMock()
            mock_ind_instance.indicators = {
                'atr': {'atr': current_price * 0.02},
                'ema': {'ema8': ema8, 'ema21': current_price * 0.93, 'ema50': current_price * 0.90}
            }
            mock_ind.return_value = mock_ind_instance

            dimensions = [
                ScoringDimension(name='MO', score=3.0, max_score=5.0, details={}),
                ScoringDimension(name='EX', score=2.0, max_score=6.0, details={}),
                ScoringDimension(name='VC', score=3.0, max_score=5.0, details={}),
            ]

            entry, stop, target = mock_strategy.calculate_entry_exit(
                'AAPL', sample_df, dimensions, 8.0, 'B'
            )

            # Target should be EMA8 (rounded to 2 decimals)
            assert abs(target - round(ema8, 2)) < 0.01, \
                f"Target {target} should equal EMA8 {round(ema8, 2)}"


class TestCapitulationReboundV8Changes:
    """Test v8.0 refactor changes: time exit removed, RSI velocity, simplified filter."""

    def test_time_exit_removed(self):
        """Verify check_time_exit method has been removed."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy
        assert not hasattr(CapitulationReboundStrategy, 'check_time_exit'), \
            "check_time_exit should be removed"

    def test_filter_passes_through(self):
        """Verify filter() always returns True (all gates in _prefilter_symbol)."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy
        strategy = CapitulationReboundStrategy.__new__(CapitulationReboundStrategy)
        assert strategy.filter('TEST', pd.DataFrame({'close': [1]})) is True

    def test_reversal_not_in_prefilter(self):
        """Verify _prefilter_symbol does not reject based on reversal confirmation."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy
        import inspect
        source = inspect.getsource(CapitulationReboundStrategy._prefilter_symbol)
        assert '_check_reversal_confirmation' not in source, \
            "_prefilter_symbol should not call _check_reversal_confirmation"

    def test_rsi_velocity_calculates(self):
        """Verify _calculate_rsi_velocity returns positive value for fast drops."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy

        # Create a DataFrame with realistic price movement followed by capitulation
        dates = pd.date_range('2024-01-01', periods=40, freq='D')
        # First 25 days: gradual uptrend (RSI in normal range)
        prices = list(range(90, 115)) + [105, 95, 88, 80, 73, 68, 65, 62, 60, 58, 57, 56, 55, 54, 53]
        df = pd.DataFrame({
            'open': [p - 0.5 for p in prices],
            'high': [p + 1 for p in prices],
            'low': [p - 1.5 for p in prices],
            'close': prices,
            'volume': [3_000_000] * 40
        }, index=dates)

        strategy = CapitulationReboundStrategy.__new__(CapitulationReboundStrategy)
        velocity = strategy._calculate_rsi_velocity(df)

        # RSI should have dropped significantly during capitulation
        assert velocity > 5, \
            f"RSI velocity should be positive for fast drop, got {velocity:.1f}"

    def test_mo_uses_rsi_velocity_not_ema_distance(self):
        """Verify _calculate_mo uses RSI velocity instead of EMA distance."""
        from core.strategies.capitulation_rebound import CapitulationReboundStrategy
        import inspect
        source = inspect.getsource(CapitulationReboundStrategy._calculate_mo)
        assert 'rsi_velocity' in source, \
            "_calculate_mo should reference rsi_velocity"
        assert 'atr_multiple' not in source, \
            "_calculate_mo should not reference atr_multiple"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
