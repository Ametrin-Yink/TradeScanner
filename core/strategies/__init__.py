"""Strategy registry - dynamic plugin discovery."""
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, Type, List, Optional

from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType


# Auto-discovered registry - built at import time
STRATEGY_REGISTRY: Dict[StrategyType, Type[BaseStrategy]] = {}
STRATEGY_NAME_TO_LETTER: Dict[str, str] = {}
STRATEGY_METADATA: Dict[str, Dict[str, str]] = {}


def _discover_strategies() -> None:
    """Auto-discover strategy classes from the strategies/ directory."""
    strategies_path = Path(__file__).parent
    for importer, modname, ispkg in pkgutil.iter_modules([str(strategies_path)]):
        if modname in ('__init__', 'base_strategy'):
            continue
        module = importlib.import_module(f"core.strategies.{modname}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and hasattr(attr, 'NAME')
                    and attr.NAME):
                strategy_type = getattr(attr, 'STRATEGY_TYPE', None)
                if strategy_type is not None:
                    STRATEGY_REGISTRY[strategy_type] = attr
                    letter = strategy_type.value
                    STRATEGY_NAME_TO_LETTER[attr.NAME] = letter
                    STRATEGY_METADATA[letter] = {
                        'name': attr.NAME,
                        'direction': getattr(attr, 'DIRECTION', 'long'),
                    }


_discover_strategies()


def get_strategy(strategy_type: StrategyType) -> Optional[Type[BaseStrategy]]:
    """Get strategy class by type."""
    return STRATEGY_REGISTRY.get(strategy_type)


def get_all_strategies() -> List[Type[BaseStrategy]]:
    """Get all discovered strategy classes."""
    return list(STRATEGY_REGISTRY.values())


def create_strategy(strategy_type: StrategyType, fetcher=None, db=None, config: Optional[Dict] = None) -> BaseStrategy:
    """Create strategy instance by type."""
    strategy_class = STRATEGY_REGISTRY.get(strategy_type)
    if strategy_class:
        return strategy_class(fetcher=fetcher, db=db, config=config)
    raise ValueError(f"Unknown strategy type: {strategy_type}")


__all__ = [
    'BaseStrategy',
    'StrategyMatch',
    'ScoringDimension',
    'StrategyType',
    'STRATEGY_REGISTRY',
    'STRATEGY_NAME_TO_LETTER',
    'STRATEGY_METADATA',
    'get_strategy',
    'get_all_strategies',
    'create_strategy',
]
