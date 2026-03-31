"""Strategy registry and exports for all trading strategies."""
from typing import Dict, Type, List
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

# Import all strategies
from .momentum_breakout import MomentumBreakoutStrategy
from .pullback_entry import PullbackEntryStrategy
from .support_bounce import SupportBounceStrategy
from .range_short import RangeShortStrategy
from .double_top_bottom import DoubleTopBottomStrategy
from .capitulation_rebound import CapitulationReboundStrategy

# Registry mapping
STRATEGY_REGISTRY: Dict[StrategyType, Type[BaseStrategy]] = {
    StrategyType.EP: MomentumBreakoutStrategy,
    StrategyType.SHORYUKEN: PullbackEntryStrategy,
    StrategyType.UPTHRUST_REBOUND: SupportBounceStrategy,
    StrategyType.RANGE_SUPPORT: RangeShortStrategy,
    StrategyType.DTSS: DoubleTopBottomStrategy,
    StrategyType.PARABOLIC: CapitulationReboundStrategy,
}


def get_strategy(strategy_type: StrategyType) -> Type[BaseStrategy]:
    """Get strategy class by type."""
    return STRATEGY_REGISTRY.get(strategy_type)


def get_all_strategies() -> List[Type[BaseStrategy]]:
    """Get all strategy classes."""
    return list(STRATEGY_REGISTRY.values())


def create_strategy(strategy_type: StrategyType, fetcher=None, db=None) -> BaseStrategy:
    """Create strategy instance by type."""
    strategy_class = STRATEGY_REGISTRY.get(strategy_type)
    if strategy_class:
        return strategy_class(fetcher=fetcher, db=db)
    raise ValueError(f"Unknown strategy type: {strategy_type}")


# Exports
__all__ = [
    'BaseStrategy',
    'StrategyMatch',
    'ScoringDimension',
    'StrategyType',
    'MomentumBreakoutStrategy',
    'PullbackEntryStrategy',
    'SupportBounceStrategy',
    'RangeShortStrategy',
    'DoubleTopBottomStrategy',
    'CapitulationReboundStrategy',
    'STRATEGY_REGISTRY',
    'get_strategy',
    'get_all_strategies',
    'create_strategy',
]
