"""Tests for A1/A2 sub-mode split v7.0."""
import pytest
from core.strategies.base_strategy import StrategyType
from core.strategies import STRATEGY_REGISTRY, STRATEGY_NAME_TO_LETTER


class TestA1A2Split:
    """Test A1/A2 sub-mode split."""

    def test_strategy_type_enum_has_a1_a2(self):
        """StrategyType should have A1 and A2."""
        assert hasattr(StrategyType, 'A1')
        assert hasattr(StrategyType, 'A2')

    def test_registry_has_a1_a2(self):
        """Registry should have A1 and A2 entries."""
        assert StrategyType.A1 in STRATEGY_REGISTRY
        assert StrategyType.A2 in STRATEGY_REGISTRY

    def test_a1_is_momentum_breakout(self):
        """A1 should map to MomentumBreakoutStrategy."""
        from core.strategies.momentum_breakout import MomentumBreakoutStrategy
        assert STRATEGY_REGISTRY[StrategyType.A1] == MomentumBreakoutStrategy

    def test_a2_is_prebreakout(self):
        """A2 should map to PreBreakoutCompressionStrategy."""
        from core.strategies.momentum_breakout import PreBreakoutCompressionStrategy
        assert STRATEGY_REGISTRY[StrategyType.A2] == PreBreakoutCompressionStrategy

    def test_strategy_name_to_letter_mapping(self):
        """Strategy names should map to correct letters."""
        assert STRATEGY_NAME_TO_LETTER["MomentumBreakout"] == "A1"
        assert STRATEGY_NAME_TO_LETTER["PreBreakoutCompression"] == "A2"

    def test_strategy_metadata(self):
        """Strategy metadata should include A1 and A2."""
        from core.strategies import STRATEGY_METADATA
        assert 'A1' in STRATEGY_METADATA
        assert 'A2' in STRATEGY_METADATA
        assert STRATEGY_METADATA['A1']['name'] == 'MomentumBreakout'
        assert STRATEGY_METADATA['A2']['name'] == 'PreBreakoutCompression'
        assert STRATEGY_METADATA['A1']['direction'] == 'long'
        assert STRATEGY_METADATA['A2']['direction'] == 'long'
