"""Phase 4: Deep Analysis handler."""
import logging

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.analyzer import OpportunityAnalyzer

logger = logging.getLogger(__name__)


class Phase4DeepAnalysisHandler(PhaseHandler):
    NAME = "phase4"
    DESCRIPTION = "Deep Analysis - Top 10"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4: Deep Analysis (Top 10)")
        logger.info("=" * 60)

        top_30 = ctx.top_30
        regime = ctx.regime

        opportunity_analyzer = OpportunityAnalyzer()
        analyzed = opportunity_analyzer.analyze_top_10_deep(top_30, regime)

        logger.info(f"Deep analyzed {len(analyzed)} opportunities")

        return PhaseResult(success=True, data={'top_10': analyzed})
