"""Phase 3: AI Scoring handler."""
import logging

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.selector import CandidateSelector

logger = logging.getLogger(__name__)


class Phase3AIScoringHandler(PhaseHandler):
    NAME = "phase3"
    DESCRIPTION = "AI Scoring - Top 30 Selection"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3: AI Scoring - Top 30 Selection")
        logger.info("=" * 60)

        candidates = ctx.candidates
        regime = ctx.regime

        selector = CandidateSelector()
        top_30 = selector.select_top_30(candidates, regime)

        logger.info(f"Selected {len(top_30)} opportunities for top 30")

        return PhaseResult(success=True, data={'top_30': top_30})
