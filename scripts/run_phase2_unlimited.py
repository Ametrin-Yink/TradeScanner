"""Run Phase 2 with all strategies, no slot limits."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from data.db import Database
from core.logging_config import setup_logging
from core.screener import StrategyScreener, STRATEGY_NAME_TO_LETTER
from core.stock_universe import get_all_market_etfs
from core.strategies import (
    create_strategy,
    get_all_strategies,
    StrategyType,
    StrategyMatch,
)
from core.market_regime import MarketRegimeDetector

setup_logging(level='INFO')
logger = logging.getLogger(__name__)


def main():
    db = Database()
    symbols = db.get_active_stocks_min_market_cap(min_market_cap=2e9)
    logger.info(f"Screening symbols: {len(symbols)}")

    # Load regime from DB (saved by Phase 1)
    regime_data = db.load_regime()
    if regime_data:
        regime = regime_data.get('regime', 'bull_moderate')
    else:
        regime = 'bull_moderate'
    logger.info(f"Regime: {regime}")

    screener = StrategyScreener(db=db)

    # Load Tier 3 data
    tier3_symbols = get_all_market_etfs()
    tier3_data = {}
    for sym in tier3_symbols:
        df = db.get_tier3_cache(sym)
        if df is not None and not df.empty:
            tier3_data[sym] = df
    logger.info(f"Loaded {len(tier3_data)} Tier 3 symbols")

    # Run ALL strategies - no slot filtering
    detector = MarketRegimeDetector()
    allocation = detector.get_allocation(regime)
    logger.info(f"Normal allocation (for reference): {allocation}")

    all_candidates = []
    for stype in [StrategyType.A1, StrategyType.A2, StrategyType.B,
                   StrategyType.C, StrategyType.D, StrategyType.E,
                   StrategyType.F, StrategyType.G, StrategyType.H]:
        strategy = create_strategy(stype, db=db)
        letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
        slots = allocation.get(letter, 0) if letter else 0
        logger.info(f"Running {strategy.NAME} ({letter}): normal slot limit = {slots}")

        # Set up strategy with necessary data
        strategy.market_data = tier3_data
        strategy.spy_return_5d = screener._spy_return_5d
        strategy._spy_df = screener._spy_data
        strategy._current_regime = regime
        strategy.phase0_data = screener._phase0_data

        # Use a high number to effectively remove limit
        candidates = strategy.screen(symbols, max_candidates=9999)
        all_candidates.extend(candidates)
        logger.info(f"  {strategy.NAME}: {len(candidates)} candidates")

    logger.info("=" * 60)
    logger.info(f"TOTAL candidates (no slot limits): {len(all_candidates)}")

    # Show breakdown by strategy
    from collections import Counter
    counts = Counter(c.strategy for c in all_candidates)
    for strategy_name, count in sorted(counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {strategy_name}: {count}")

    # Show top 20 by score
    logger.info("Top 20 by score:")
    sorted_candidates = sorted(
        all_candidates,
        key=lambda x: x.technical_snapshot.get('score', 0),
        reverse=True
    )
    for c in sorted_candidates[:20]:
        score = c.technical_snapshot.get('score', 'N/A')
        logger.info(f"  {c.symbol} - {c.strategy}: score={score}")


if __name__ == '__main__':
    main()
