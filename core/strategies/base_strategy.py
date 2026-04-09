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


# Strategy max scores for normalization to 0-15 scale
STRATEGY_MAX_SCORES = {
    'MomentumBreakout': 18.5,
    'PreBreakoutCompression': 18.5,
    'PullbackEntry': 17.0,
    'SupportBounce': 15.0,
    'DistributionTop': 15.0,
    'AccumulationBottom': 15.0,
    'CapitulationRebound': 15.0,
    'EarningsGap': 15.0,
    'RelativeStrengthLong': 13.0,
}


def normalize_score(raw_score: float, strategy_name: str) -> float:
    """
    Normalize raw score to 0-15 scale.

    Args:
        raw_score: Raw score from strategy
        strategy_name: Strategy NAME (e.g., 'MomentumBreakout')

    Returns:
        Normalized score on 0-15 scale
    """
    strategy_max = STRATEGY_MAX_SCORES.get(strategy_name, 15.0)
    normalized = (raw_score / strategy_max) * 15.0
    return round(normalized, 2)


class StrategyType(Enum):
    """8 trading strategies with A1/A2 sub-modes."""
    A1 = "A1"  # MomentumBreakout (confirmed breakout)
    A2 = "A2"  # PreBreakoutCompression (pre-breakout)
    B = "B"    # PullbackEntry
    C = "C"    # SupportBounce
    D = "D"    # DistributionTop (short)
    E = "E"    # AccumulationBottom (long)
    F = "F"    # CapitulationRebound
    G = "G"    # EarningsGap
    H = "H"    # RelativeStrengthLong


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

    def __init__(self, fetcher: Optional[DataFetcher] = None, db: Optional[Database] = None,
                 config: Optional[Dict] = None):
        """Initialize strategy with data fetcher, database, and optional config override."""
        self.fetcher = fetcher or DataFetcher()
        self.db = db or Database()
        self.market_data: Dict[str, pd.DataFrame] = {}
        if config:
            class_params = getattr(self, 'PARAMS', {})
            self.PARAMS = {**class_params, **config}

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

    def calculate_score(self, dimensions: List[ScoringDimension], df: pd.DataFrame = None, symbol: str = None) -> Tuple[float, str]:
        """
        Calculate total score and tier from dimensions with normalization.

        Args:
            dimensions: List of dimension scores
            df: Optional DataFrame for strategies that need it (e.g., for bonus calculation)
            symbol: Optional symbol for strategies that need it

        Returns:
            Tuple of (total_score, tier)
        """
        raw_total = round(sum(d.score for d in dimensions), 2)

        # Normalize to 0-15 scale
        total = normalize_score(raw_total, self.NAME)
        total = min(total, 15.0)  # Cap at 15

        # Tier thresholds on normalized 0-15 scale
        if total >= self.TIER_S_MIN:  # 12
            return total, 'S'
        elif total >= self.TIER_A_MIN:  # 9
            return total, 'A'
        elif total >= self.TIER_B_MIN:  # 7
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

    def screen(self, symbols: List[str], max_candidates: int = 5) -> List[StrategyMatch]:
        """
        Screen all symbols using this strategy.

        Args:
            symbols: List of stock symbols
            max_candidates: Maximum candidates to return (from allocation table)

        Returns:
            List of StrategyMatch objects (max max_candidates)
        """
        matches = []

        # Get phase0_data if available (contains pre-computed indicators)
        phase0_data = getattr(self, 'phase0_data', {})

        for symbol in symbols:
            try:
                # Get data - phase0_data now only contains scalars, fetch df on demand
                phase0_data = getattr(self, 'phase0_data', {})
                symbol_data = phase0_data.get(symbol, {})

                # Always fetch data on-demand (phase0_data no longer stores DataFrames to save memory)
                df = self._get_data(symbol)
                if df is None:
                    logger.debug(f"No data for {symbol}")
                    continue
                if not isinstance(df, pd.DataFrame) or len(df) < 50:
                    logger.debug(f"Insufficient data for {symbol}")
                    continue

                # Filter
                if not self.filter(symbol, df):
                    continue

                # Calculate dimensions
                dimensions = self.calculate_dimensions(symbol, df)
                if not dimensions:
                    continue

                # Calculate score and tier
                score, tier = self.calculate_score(dimensions, df, symbol)
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

        # Sort by confidence and return top max_candidates
        return sorted(matches, key=lambda x: x.confidence, reverse=True)[:max_candidates]

    def _get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol.

        Priority:
        1. In-memory cache (self.market_data) - fastest
        2. Database cache (market_data table) - fast, no network
        3. yfinance fetch - slow, rate-limited (fallback only)
        """
        # 1. Check in-memory cache first
        if symbol in self.market_data:
            return self.market_data[symbol]

        # 2. Check database cache (Phase 0 should have populated this)
        df = self.db.get_market_data_df(symbol)
        if df is not None and len(df) >= 200:
            self.market_data[symbol] = df  # Cache for subsequent calls
            return df

        # 3. Fallback to yfinance (should not happen if Phase 0 completed)
        logger.warning(f"No cached data for {symbol}, fetching from yfinance...")
        df = self.fetcher.fetch_stock_data(symbol, period="13mo", interval="1d")
        if df is not None:
            self.market_data[symbol] = df
        return df

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
        except Exception:
            return False
