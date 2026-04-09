"""Phase 0: Data Preparation handler."""
import logging
import gc
from typing import Optional

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.premarket_prep import PreMarketPrep
from data.db import Database

logger = logging.getLogger(__name__)


class Phase0PrepHandler(PhaseHandler):
    NAME = "phase0"
    DESCRIPTION = "Data Preparation"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 0: Data Preparation")
        logger.info("=" * 60)

        symbols = ctx.symbols if ctx.symbols else None
        db = Database()
        prep = PreMarketPrep(db=db)

        if symbols is not None:
            logger.info(f"Using provided symbols: {len(symbols)} (test mode, in-process)")
            tier3_data = prep._fetch_tier3_data()
            logger.info(f"Tier 3 data fetched: {len(tier3_data)} symbols")
            tier1_count = prep._calculate_tier1_cache(symbols)
            logger.info(f"Tier 1 cache calculated: {tier1_count} symbols")

            return PhaseResult(success=True, data={
                'symbols': symbols,
            })

        # For production mode, delegate to subprocess (handled by scheduler for now)
        # Phase 0 subprocess is complex - keep existing logic in scheduler for now
        return PhaseResult(success=False, error="Production Phase 0 requires subprocess - use scheduler entry point")
