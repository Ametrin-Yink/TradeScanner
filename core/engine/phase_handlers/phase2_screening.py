"""Phase 2: Strategy Screening handler."""
import logging

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.screener import StrategyScreener
from core.stock_universe import get_all_market_etfs
from data.db import Database

logger = logging.getLogger(__name__)


class Phase2ScreeningHandler(PhaseHandler):
    NAME = "phase2"
    DESCRIPTION = "Strategy Screening"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Strategy Screening")
        logger.info("=" * 60)

        symbols = ctx.symbols
        regime = ctx.regime

        logger.info(f"Screening {len(symbols)} symbols with regime: {regime}")

        db = getattr(ctx, 'db', None) or Database()
        screener = StrategyScreener(db=db)

        tier3_symbols = get_all_market_etfs()
        tier3_data = {}
        for sym in tier3_symbols:
            df = db.get_tier3_cache(sym)
            if df is not None and not df.empty:
                tier3_data[sym] = df
        logger.info(f"Loaded {len(tier3_data)} Tier 3 symbols from cache")

        candidates = screener.screen_all(
            symbols=symbols,
            regime=regime,
            market_data=tier3_data
        )

        # Track symbols that didn't produce any candidate
        candidate_symbols = {c.symbol for c in candidates}
        fail_symbols = [s for s in symbols if s not in candidate_symbols]

        logger.info(f"Found {len(candidates)} candidates, {len(fail_symbols)} symbols without matches")

        return PhaseResult(success=True, data={
            'candidates': candidates,
            'fail_symbols': fail_symbols,
        })
