"""Phase 2: Strategy Screening handler."""
import logging
import sqlite3
from datetime import datetime

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

        # Identify actual data failures: symbols with neither Tier 1 cache nor
        # market_data DB entries. Everything else that didn't match a strategy
        # is normal — most stocks don't trigger any setup on a given day.
        scan_date = datetime.now().strftime('%Y-%m-%d')
        with db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            tier1_rows = conn.execute(
                "SELECT symbol FROM tier1_cache WHERE cache_date = ?",
                (scan_date,)
            ).fetchall()
            stock_rows = conn.execute(
                "SELECT symbol FROM stocks WHERE is_active = 1"
            ).fetchall()

        cached_symbols = {row['symbol'] for row in tier1_rows}
        stocks_with_data = {row['symbol'] for row in stock_rows}
        fail_symbols = [
            s for s in symbols
            if s not in cached_symbols and s not in stocks_with_data
        ]

        no_match = len(symbols) - len(candidates) - len(fail_symbols)
        logger.info(
            f"Found {len(candidates)} candidates, "
            f"{len(fail_symbols)} data failures, "
            f"{no_match} no-match (normal)"
        )

        return PhaseResult(success=True, data={
            'candidates': candidates,
            'fail_symbols': fail_symbols,
        })
