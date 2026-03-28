"""Strategy registry and exports for all trading strategies."""
from typing import Dict, Type, List
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

# Import all strategies
from .vcp_ep import VCPEPStrategy
from .momentum import MomentumStrategy
from .shoryuken import ShoryukenStrategy
from .pullbacks import PullbacksStrategy
from .upthrust_rebound import UpthrustReboundStrategy
from .range_support import RangeSupportStrategy
from .dtss import DTSSStrategy
from .parabolic import ParabolicStrategy

# Registry mapping
STRATEGY_REGISTRY: Dict[StrategyType, Type[BaseStrategy]] = {
    StrategyType.EP: VCPEPStrategy,
    StrategyType.MOMENTUM: MomentumStrategy,
    StrategyType.SHORYUKEN: ShoryukenStrategy,
    StrategyType.PULLBACKS: PullbacksStrategy,
    StrategyType.UPTHRUST_REBOUND: UpthrustReboundStrategy,
    StrategyType.RANGE_SUPPORT: RangeSupportStrategy,
    StrategyType.DTSS: DTSSStrategy,
    StrategyType.PARABOLIC: ParabolicStrategy,
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
    'VCPEPStrategy',
    'MomentumStrategy',
    'ShoryukenStrategy',
    'PullbacksStrategy',
    'UpthrustReboundStrategy',
    'RangeSupportStrategy',
    'DTSSStrategy',
    'ParabolicStrategy',
    'STRATEGY_REGISTRY',
    'get_strategy',
    'get_all_strategies',
    'create_strategy',
]
