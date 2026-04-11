"""Run Phase 1 (Regime Detection) and Phase 2 (Strategy Screening) using current database."""
import logging
import sys
from pathlib import Path

# Ensure we can import from TradeScanner package
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from data.db import Database
from core.logging_config import setup_logging
from core.services import ServiceRegistry
from core.services.providers import register_defaults
from core.engine.context import PipelineContext
from core.engine.phase_handlers import Phase1RegimeHandler, Phase2ScreeningHandler

setup_logging(level='INFO')
register_defaults()
logger = logging.getLogger(__name__)


def run_phase1_and_2():
    db = Database()

    # Load symbol universe from current database
    symbols = db.get_active_stocks_min_market_cap(min_market_cap=2e9)
    logger.info(f"Loaded {len(symbols)} symbols from database (MC >= $2B)")

    # Verify Tier 1 cache coverage
    import sqlite3
    with sqlite3.connect(db.db_path) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(DISTINCT symbol) FROM tier1_cache')
        t1_count = c.fetchone()[0]
    logger.info(f"Tier 1 cache has {t1_count} symbols")

    if t1_count == 0:
        logger.error("No Tier 1 cache data. Run Phase 0 first.")
        sys.exit(1)

    # Set up context
    from datetime import datetime
    ctx = PipelineContext(
        symbols=symbols,
        run_date=datetime.now().strftime('%Y-%m-%d'),
    )
    ctx.db = db

    # Phase 1: AI Market Regime Detection
    logger.info("=" * 60)
    logger.info("Running Phase 1: AI Market Regime Detection")
    logger.info("=" * 60)

    phase1 = Phase1RegimeHandler()
    result1 = phase1.execute(ctx)

    if not result1.success:
        logger.error(f"Phase 1 failed: {result1.error}")
        sys.exit(1)

    # Copy phase 1 results to context
    for key, value in result1.data.items():
        setattr(ctx, key, value)

    logger.info(f"Phase 1 complete. Regime: {ctx.regime}")
    logger.info(f"Allocation: {ctx.allocation}")

    # Phase 2: Strategy Screening
    logger.info("=" * 60)
    logger.info("Running Phase 2: Strategy Screening")
    logger.info("=" * 60)

    phase2 = Phase2ScreeningHandler()
    result2 = phase2.execute(ctx)

    if not result2.success:
        logger.error(f"Phase 2 failed: {result2.error}")
        sys.exit(1)

    # Copy phase 2 results
    for key, value in result2.data.items():
        setattr(ctx, key, value)

    # Report results
    candidates = ctx.candidates
    logger.info("=" * 60)
    logger.info("PHASE 1+2 COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Regime: {ctx.regime}")
    logger.info(f"Total candidates found: {len(candidates)}")

    # Show summary by strategy
    if candidates:
        from collections import Counter
        strategy_counts = Counter(c.strategy for c in candidates)
        logger.info("Candidates by strategy:")
        for strategy, count in sorted(strategy_counts.items(), key=lambda x: -x[1]):
            logger.info(f"  {strategy}: {count}")

        # Show top candidates
        logger.info("Top candidates:")
        for c in sorted(candidates, key=lambda x: getattr(x, 'score', 0), reverse=True)[:10]:
            score = getattr(c, 'score', 'N/A')
            logger.info(f"  {c.symbol} - {c.strategy}: score={score}")

    # Save summary to context for downstream use
    ctx.status = "completed"


if __name__ == '__main__':
    run_phase1_and_2()
