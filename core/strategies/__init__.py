"""Strategy registry and exports for all trading strategies."""
from typing import Dict, Type, List
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

# Import all 8 strategies (A-H with A1/A2 sub-modes)
from .momentum_breakout import (
    MomentumBreakoutStrategy,      # A1
    PreBreakoutCompressionStrategy  # A2
)
from .pullback_entry import PullbackEntryStrategy                # B
from .support_bounce import SupportBounceStrategy                # C
from .distribution_top import DistributionTopStrategy            # D
from .accumulation_bottom import AccumulationBottomStrategy      # E
from .capitulation_rebound import CapitulationReboundStrategy    # F
from .earnings_gap import EarningsGapStrategy                    # G
from .relative_strength_long import RelativeStrengthLongStrategy # H

# Strategy registry - clean A-H mapping with A1/A2 sub-modes
STRATEGY_REGISTRY: Dict[StrategyType, Type[BaseStrategy]] = {
    StrategyType.A1: MomentumBreakoutStrategy,
    StrategyType.A2: PreBreakoutCompressionStrategy,
    StrategyType.B: PullbackEntryStrategy,
    StrategyType.C: SupportBounceStrategy,
    StrategyType.D: DistributionTopStrategy,
    StrategyType.E: AccumulationBottomStrategy,
    StrategyType.F: CapitulationReboundStrategy,
    StrategyType.G: EarningsGapStrategy,
    StrategyType.H: RelativeStrengthLongStrategy,
}

# Strategy name to letter mapping (for allocation table)
STRATEGY_NAME_TO_LETTER = {
    "MomentumBreakout": "A1",
    "PreBreakoutCompression": "A2",
    "PullbackEntry": "B",
    "SupportBounce": "C",
    "DistributionTop": "D",
    "AccumulationBottom": "E",
    "CapitulationRebound": "F",
    "EarningsGap": "G",
    "RelativeStrengthLong": "H",
}

# Strategy letter to metadata
STRATEGY_METADATA = {
    'A1': {'name': 'MomentumBreakout', 'direction': 'long'},
    'A2': {'name': 'PreBreakoutCompression', 'direction': 'long'},
    'B': {'name': 'PullbackEntry', 'direction': 'long'},
    'C': {'name': 'SupportBounce', 'direction': 'long'},
    'D': {'name': 'DistributionTop', 'direction': 'short'},
    'E': {'name': 'AccumulationBottom', 'direction': 'long'},
    'F': {'name': 'CapitulationRebound', 'direction': 'long'},
    'G': {'name': 'EarningsGap', 'direction': 'both'},
    'H': {'name': 'RelativeStrengthLong', 'direction': 'long'},
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
    'MomentumBreakoutStrategy',      # A1
    'PreBreakoutCompressionStrategy', # A2
    'PullbackEntryStrategy',         # B
    'SupportBounceStrategy',         # C
    'DistributionTopStrategy',       # D
    'AccumulationBottomStrategy',    # E
    'CapitulationReboundStrategy',   # F
    'EarningsGapStrategy',           # G
    'RelativeStrengthLongStrategy',  # H
    'STRATEGY_REGISTRY',
    'STRATEGY_NAME_TO_LETTER',
    'STRATEGY_METADATA',
    'get_strategy',
    'get_all_strategies',
    'create_strategy',
]
