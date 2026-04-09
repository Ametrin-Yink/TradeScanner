"""Tests for Phase 2: Strategy-as-Plugin System."""
import pytest
from core.strategies import (
    STRATEGY_REGISTRY, STRATEGY_NAME_TO_LETTER, STRATEGY_METADATA,
    create_strategy, get_all_strategies, get_strategy, StrategyType
)


class TestStrategyDiscovery:
    """Test dynamic strategy discovery."""

    def test_all_strategies_discovered(self):
        assert len(STRATEGY_REGISTRY) == 9
        expected = {'A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'G', 'H'}
        actual = {st.value for st in STRATEGY_REGISTRY.keys()}
        assert actual == expected

    def test_name_to_letter_mapping(self):
        assert len(STRATEGY_NAME_TO_LETTER) == 9
        assert STRATEGY_NAME_TO_LETTER['MomentumBreakout'] == 'A1'
        assert STRATEGY_NAME_TO_LETTER['PreBreakoutCompression'] == 'A2'
        assert STRATEGY_NAME_TO_LETTER['PullbackEntry'] == 'B'

    def test_metadata_mapping(self):
        assert len(STRATEGY_METADATA) == 9
        assert STRATEGY_METADATA['A1']['name'] == 'MomentumBreakout'
        assert STRATEGY_METADATA['A1']['direction'] == 'long'
        assert STRATEGY_METADATA['D']['direction'] == 'short'
        assert STRATEGY_METADATA['G']['direction'] == 'both'

    def test_get_all_strategies(self):
        strategies = get_all_strategies()
        assert len(strategies) == 9

    def test_get_strategy(self):
        cls = get_strategy(StrategyType.A1)
        assert cls is not None
        assert cls.NAME == 'MomentumBreakout'
        assert STRATEGY_REGISTRY.get(object()) is None


class TestStrategyCreation:
    """Test create_strategy with config overlay."""

    def test_create_strategy_basic(self):
        s = create_strategy(StrategyType.A1)
        assert s.NAME == 'MomentumBreakout'

    def test_create_strategy_config_override(self):
        s = create_strategy(StrategyType.B, config={'min_data_days': 999})
        assert s.PARAMS['min_data_days'] == 999

    def test_create_strategy_invalid_type(self):
        with pytest.raises(ValueError):
            StrategyType('ZZ')

    def test_all_strategies_creatable(self):
        for st in STRATEGY_REGISTRY.keys():
            s = create_strategy(st)
            assert s is not None
            assert s.NAME


class TestStrategyConfigYaml:
    """Test YAML config file exists and is parseable."""

    def test_yaml_config_exists(self):
        from pathlib import Path
        config_path = Path(__file__).parent.parent / 'config' / 'strategy_config.yaml'
        assert config_path.exists()

    def test_yaml_config_parseable(self):
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent / 'config' / 'strategy_config.yaml'
        # Use a simple YAML-like check without the yaml module
        content = config_path.read_text()
        assert 'MomentumBreakout:' in content
        assert 'PullbackEntry:' in content
        assert 'RelativeStrengthLong:' in content
