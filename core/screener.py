"""Strategy screener - thin orchestrator using plugin architecture."""
import logging
from typing import Dict, List, Optional

import pandas as pd

from core.fetcher import DataFetcher
from core.strategies import (
    create_strategy,
    get_all_strategies,
    StrategyType,
    StrategyMatch,
)
from data.db import Database

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ['StrategyScreener', 'StrategyType', 'StrategyMatch']


class StrategyScreener:
    """Screen stocks using 8 trading strategies via plugin architecture."""

    # Backward compatibility: minimum requirements constants
    MIN_ADR_PCT = 0.03  # 3% minimum ADR
    MIN_VOLUME = 1_000_000  # 1M minimum volume
    MAX_CANDIDATES_PER_STRATEGY = 5

    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        db: Optional[Database] = None
    ):
        """Initialize screener with data fetcher and database."""
        self.fetcher = fetcher or DataFetcher()
        self.db = db or Database()
        self.earnings_calendar: Dict[str, pd.Timestamp] = {}
        self.market_data: Dict[str, pd.DataFrame] = {}
        self._market_regime: Optional[str] = None

        # Initialize all strategy plugins
        self._strategies = {}
        for strategy_type in StrategyType:
            self._strategies[strategy_type] = create_strategy(
                strategy_type, fetcher=self.fetcher, db=self.db
            )

        logger.info(f"Initialized {len(self._strategies)} strategy plugins")

    def _get_market_regime(self) -> str:
        """
        Get current market regime based on SPY vs EMA200.

        Returns:
            'bullish' if SPY > EMA200 and rising
            'bearish' if SPY < EMA200
            'neutral' otherwise or if no data
        """
        if self._market_regime is not None:
            return self._market_regime

        try:
            spy_df = self._get_data('SPY')
            if spy_df is None or len(spy_df) < 200:
                self._market_regime = 'neutral'
                return 'neutral'

            close = spy_df['close']
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema50_prev = close.ewm(span=50, adjust=False).mean().iloc[-10]

            if current_price > ema200:
                if ema50 > ema50_prev:
                    self._market_regime = 'bullish'
                else:
                    self._market_regime = 'neutral'
            else:
                self._market_regime = 'bearish'

            logger.info(f"Market regime: {self._market_regime} (SPY: ${current_price:.2f}, EMA200: ${ema200:.2f})")
            return self._market_regime

        except Exception as e:
            logger.warning(f"Could not determine market regime: {e}")
            self._market_regime = 'neutral'
            return 'neutral'

    def _apply_market_filter(self, score: float, tier: str) -> tuple:
        """
        Apply market regime filter to score and tier.

        When market is bearish (SPY < EMA200):
        - Tier S -> A
        - Tier A -> B
        - Tier B -> reject

        Args:
            score: Original score
            tier: Original tier ('S', 'A', 'B')

        Returns:
            tuple of (adjusted_score, adjusted_tier)
        """
        regime = self._get_market_regime()

        if regime == 'bearish':
            if tier == 'S':
                return min(score, 11.99), 'A'
            elif tier == 'A':
                return min(score, 8.99), 'B'
            else:
                return 0, 'REJECT'

        return score, tier

    def load_earnings_calendar(self, symbols: Optional[List[str]] = None):
        """Load earnings calendar for EP strategy."""
        self.earnings_calendar = self.fetcher.fetch_earnings_calendar(symbols)
        logger.info(f"Loaded {len(self.earnings_calendar)} earnings dates")

    def _get_data(self, symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol."""
        if symbol in self.market_data:
            return self.market_data[symbol]
        return self.fetcher.fetch_stock_data(symbol, period=period, interval="1d")

    def _check_basic_requirements(self, df: pd.DataFrame, ind) -> bool:
        """
        Check basic requirements: ADR and volume (backward compatibility).

        Args:
            df: OHLCV DataFrame
            ind: TechnicalIndicators instance

        Returns:
            True if symbol passes all filters
        """
        try:
            adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
            volume_data = ind.indicators.get('volume', {})
            volume_sma = volume_data.get('volume_sma', 0)

            if adr_pct is None or adr_pct < self.MIN_ADR_PCT:
                return False

            if volume_sma is None or volume_sma < self.MIN_VOLUME:
                return False

            return True
        except:
            return False

    def screen_all(
        self,
        symbols: List[str],
        market_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> List[StrategyMatch]:
        """
        Screen all symbols using all 8 strategy plugins.

        Args:
            symbols: List of stock symbols to screen
            market_data: Optional pre-loaded market data cache

        Returns:
            List of StrategyMatch (max 40 total: 5 per strategy)
        """
        self.market_data = market_data or {}

        # Load earnings if not already loaded
        if not self.earnings_calendar:
            self.load_earnings_calendar(symbols)

        # Share market data and earnings calendar with all strategies
        for strategy in self._strategies.values():
            strategy.market_data = self.market_data
            if hasattr(strategy, 'earnings_calendar'):
                strategy.earnings_calendar = self.earnings_calendar

        all_candidates = []

        # Run each strategy plugin
        for strategy_type, strategy in self._strategies.items():
            try:
                candidates = strategy.screen(symbols)
                if candidates:
                    # Apply market regime filter
                    for match in candidates:
                        if hasattr(match, 'technical_snapshot'):
                            original_tier = match.technical_snapshot.get('tier', 'B')
                            original_score = match.technical_snapshot.get('score', 0)
                            adjusted_score, adjusted_tier = self._apply_market_filter(
                                original_score, original_tier
                            )
                            if adjusted_tier == 'REJECT':
                                continue
                            match.technical_snapshot['score'] = adjusted_score
                            match.technical_snapshot['tier'] = adjusted_tier
                            match.technical_snapshot['position_pct'] = {
                                'S': 0.20, 'A': 0.10, 'B': 0.05
                            }.get(adjusted_tier, 0.0)

                    all_candidates.extend(candidates[:self.MAX_CANDIDATES_PER_STRATEGY])
                    logger.info(f"{strategy_type.value}: found {len(candidates)} candidates")
            except Exception as e:
                logger.error(f"Error in {strategy_type.value} screening: {e}")

        return all_candidates

    # Backward compatibility: expose individual screen methods
    def screen_ep(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for VCP-EP strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.EP)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_momentum(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Momentum strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.MOMENTUM)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_shoryuken(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Shoryuken strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.SHORYUKEN)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_pullbacks(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Pullbacks strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.PULLBACKS)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_upthrust_rebound(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Upthrust & Rebound strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.UPTHRUST_REBOUND)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_range_support(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Range Support strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.RANGE_SUPPORT)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_dtss(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for DTSS strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.DTSS)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []

    def screen_parabolic(self, symbols: List[str]) -> List[StrategyMatch]:
        """Screen for Parabolic strategy (backward compatibility)."""
        strategy = self._strategies.get(StrategyType.PARABOLIC)
        if strategy:
            strategy.market_data = self.market_data
            return strategy.screen(symbols)[:self.MAX_CANDIDATES_PER_STRATEGY]
        return []
