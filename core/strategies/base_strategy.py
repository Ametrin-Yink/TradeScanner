"""Base strategy class and registry for all trading strategies."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import logging

import pandas as pd

from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators
from core.market_regime import REGIME_SCALARS, EXTREME_EXEMPT_STRATEGIES
from data.db import Database

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """8 trading strategies - clean A-H naming."""
    A = "A"  # MomentumBreakout
    B = "B"  # PullbackEntry
    C = "C"  # SupportBounce
    D = "D"  # DistributionTop (short)
    E = "E"  # AccumulationBottom (long)
    F = "F"  # CapitulationRebound
    G = "G"  # EarningsGap
    H = "H"  # RelativeStrengthLong


@dataclass
class StrategyMatch:
    """A strategy match result."""
    symbol: str
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: int  # 0-100
    match_reasons: List[str] = field(default_factory=list)
    technical_snapshot: Dict[str, Any] = field(default_factory=dict)
    regime: str = 'neutral'  # NEW: for position sizing reference


@dataclass
class ScoringDimension:
    """A scoring dimension result."""
    name: str
    score: float
    max_score: float
    details: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    # Strategy metadata
    NAME: str = ""  # Short name
    STRATEGY_TYPE: StrategyType = None
    DESCRIPTION: str = ""

    # Scoring dimensions (e.g., ['PQ', 'BS', 'VC', 'TC'])
    DIMENSIONS: List[str] = []
    MAX_SCORE: float = 15.0

    # Tier thresholds
    TIER_S_MIN: float = 12.0
    TIER_A_MIN: float = 9.0
    TIER_B_MIN: float = 7.0

    # Direction: 'long' or 'short' - used for regime-adaptive position sizing
    DIRECTION: str = 'long'

    def __init__(self, fetcher: Optional[DataFetcher] = None, db: Optional[Database] = None):
        """Initialize strategy with data fetcher and database."""
        self.fetcher = fetcher or DataFetcher()
        self.db = db or Database()
        self.market_data: Dict[str, pd.DataFrame] = {}

    @abstractmethod
    def filter(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        Filter symbols based on strategy-specific criteria.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            True if symbol passes all filters
        """
        pass

    @abstractmethod
    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """
        Calculate all scoring dimensions for a symbol.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame

        Returns:
            List of ScoringDimension objects
        """
        pass

    def calculate_score(self, dimensions: List[ScoringDimension]) -> Tuple[float, str]:
        """
        Calculate total score and tier from dimensions.

        Args:
            dimensions: List of dimension scores

        Returns:
            Tuple of (total_score, tier)
        """
        total = round(sum(d.score for d in dimensions), 2)
        total = min(total, self.MAX_SCORE)

        if total >= self.TIER_S_MIN:
            return total, 'S'
        elif total >= self.TIER_A_MIN:
            return total, 'A'
        elif total >= self.TIER_B_MIN:
            return total, 'B'
        else:
            return total, 'C'  # Reject

    def calculate_position_pct(self, tier: str, regime: str = 'neutral') -> float:
        """
        Calculate position size percentage with regime scalar.

        Args:
            tier: 'S', 'A', 'B', or 'C'
            regime: Market regime from MarketRegimeDetector

        Returns:
            Position size as decimal (e.g., 0.20 for 20%)
        """
        base = {'S': 0.20, 'A': 0.10, 'B': 0.05, 'C': 0.0}.get(tier, 0.0)

        if base == 0.0:
            return 0.0

        # Get scalar
        if regime == 'extreme_vix' and self.NAME in EXTREME_EXEMPT_STRATEGIES:
            scalar = 1.0
        else:
            scalar = REGIME_SCALARS.get(regime, {}).get(self.DIRECTION, 1.0)

        final = base * scalar
        logger.debug(f"{self.NAME} position: tier={tier} base={base} regime={regime} scalar={scalar} final={final:.3f}")
        return final

    @abstractmethod
    def calculate_entry_exit(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Tuple[float, float, float]:
        """
        Calculate entry, stop loss, and take profit prices.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            dimensions: Dimension scores
            score: Total score
            tier: Tier (S/A/B/C)

        Returns:
            Tuple of (entry_price, stop_loss, take_profit)
        """
        pass

    def calculate_confidence(self, score: float, tier: str) -> int:
        """Calculate confidence percentage (0-100)."""
        base = {'S': 90, 'A': 75, 'B': 60, 'C': 0}.get(tier, 0)
        bonus = min(10, (score - self.TIER_B_MIN) * 2)
        return min(100, base + bonus)

    @abstractmethod
    def build_match_reasons(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> List[str]:
        """Build human-readable match reasons."""
        pass

    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Screen all symbols using this strategy.

        Args:
            symbols: List of stock symbols

        Returns:
            List of StrategyMatch objects (max 5 per strategy)
        """
        matches = []

        # Get phase0_data if available (contains pre-computed indicators)
        phase0_data = getattr(self, 'phase0_data', {})

        for symbol in symbols:
            try:
                # Get data - prefer phase0_data if available
                if symbol in phase0_data:
                    df = phase0_data[symbol].get('df')
                    cached_ind = phase0_data[symbol].get('ind')
                else:
                    df = self._get_data(symbol)
                    cached_ind = None

                if df is None:
                    logger.debug(f"No data for {symbol}")
                    continue
                if not isinstance(df, pd.DataFrame) or len(df) < 50:
                    logger.debug(f"Insufficient data for {symbol}")
                    continue

                # Filter
                if not self.filter(symbol, df):
                    continue

                # Calculate dimensions - pass cached indicators if available
                if cached_ind is not None:
                    # Temporarily set indicators in df for dimension calculation
                    # Dimensions will use TechnicalIndicators which has class-level cache
                    pass

                dimensions = self.calculate_dimensions(symbol, df)
                if not dimensions:
                    continue

                # Calculate score and tier
                score, tier = self.calculate_score(dimensions)
                if tier == 'C':
                    continue

                # Calculate entry/exit
                entry, stop, target = self.calculate_entry_exit(symbol, df, dimensions, score, tier)

                # Calculate confidence
                confidence = self.calculate_confidence(score, tier)

                # Build match reasons
                reasons = self.build_match_reasons(symbol, df, dimensions, score, tier)

                # Build technical snapshot
                snapshot = self.build_snapshot(symbol, df, dimensions, score, tier)

                matches.append(StrategyMatch(
                    symbol=symbol,
                    strategy=self.NAME,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    match_reasons=reasons,
                    technical_snapshot=snapshot
                ))

            except Exception as e:
                logger.error(f"Error screening {symbol} for {self.NAME}: {e}")
                continue

        # Sort by confidence and return top 5
        return sorted(matches, key=lambda x: x.confidence, reverse=True)[:5]

    def _get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol."""
        if symbol in self.market_data:
            return self.market_data[symbol]
        return self.fetcher.fetch_stock_data(symbol, period="13mo", interval="1d")

    def build_snapshot(
        self,
        symbol: str,
        df: pd.DataFrame,
        dimensions: List[ScoringDimension],
        score: float,
        tier: str
    ) -> Dict[str, Any]:
        """Build technical snapshot for reporting."""
        snapshot = {
            'current_price': df['close'].iloc[-1],
            'score': score,
            'tier': tier,
            'position_pct': self.calculate_position_pct(tier),
        }

        # Add dimension scores
        for dim in dimensions:
            snapshot[f'{dim.name.lower()}_score'] = dim.score
            snapshot.update(dim.details)

        return snapshot

    def _check_basic_requirements(self, df: pd.DataFrame) -> bool:
        """Check basic requirements: ADR and volume."""
        try:
            ind = TechnicalIndicators(df)
            ind.calculate_all()

            adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
            volume_sma = ind.indicators.get('volume', {}).get('volume_sma', 0)

            if adr_pct is None or adr_pct < 0.03:  # MIN_ADR_PCT
                return False
            if volume_sma is None or volume_sma < 1_000_000:  # MIN_VOLUME
                return False

            return True
        except:
            return False
