"""Quick test script for 100 stocks strategy validation."""
import sys
import logging
from pathlib import Path

sys.path.insert(0, '/home/admin/Projects/TradeChanceScreen')

from data.db import Database
from core.fetcher import DataFetcher
from core.screener import StrategyScreener, StrategyType
from config.stocks import load_stock_universe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_100_stocks():
    """Test all strategies with 100 stocks from active universe."""
    db = Database()
    fetcher = DataFetcher()

    # Get first 100 active stocks
    all_stocks = load_stock_universe(db)
    test_stocks = all_stocks[:100]
    logger.info(f"Testing with {len(test_stocks)} stocks: {test_stocks[:10]}...")

    # Test each strategy
    screener = StrategyScreener(fetcher=fetcher, db=db)

    results = {}
    errors = []

    for strategy_type in StrategyType:
        try:
            logger.info(f"\n=== Testing {strategy_type.value} ===")
            matches = screener.screen([strategy_type], test_stocks)
            results[strategy_type.value] = len(matches)
            logger.info(f"✓ {strategy_type.value}: {len(matches)} matches")
        except Exception as e:
            logger.error(f"✗ {strategy_type.value}: {e}")
            errors.append((strategy_type.value, str(e)))

    # Summary
    logger.info("\n=== Test Summary ===")
    logger.info(f"Total stocks tested: {len(test_stocks)}")
    logger.info(f"Strategies passed: {len(results)}/{len(list(StrategyType))}")

    if errors:
        logger.error(f"\nErrors encountered:")
        for strategy, error in errors:
            logger.error(f"  - {strategy}: {error}")
        return 1
    else:
        logger.info("\n✓ All strategies passed 100-stock test")
        return 0


if __name__ == "__main__":
    exit(test_100_stocks())
