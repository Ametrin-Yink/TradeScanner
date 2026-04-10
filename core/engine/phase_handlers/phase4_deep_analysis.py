"""Phase 4: Deep Analysis handler."""
import logging

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.analyzer import OpportunityAnalyzer, AnalyzedOpportunity

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

        # Convert ScoredCandidate with deep_analysis to AnalyzedOpportunity for reporter
        top_10 = []
        for c in analyzed[:10]:
            opp = AnalyzedOpportunity(
                symbol=c.symbol,
                strategy=c.strategy,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                take_profit=c.take_profit,
                confidence=c.confidence,
                match_reasons=getattr(c, 'match_reasons', []),
                ai_reasoning=c.deep_analysis.get('technical_outlook', '') if hasattr(c, 'deep_analysis') and c.deep_analysis else getattr(c, 'reasoning', ''),
                catalyst='',
                risk_factors=c.risk_factors if hasattr(c, 'risk_factors') else [],
                technical_snapshot=getattr(c, 'technical_snapshot', {}),
            )
            top_10.append(opp)

        logger.info(f"Deep analyzed {len(top_10)} opportunities")

        return PhaseResult(success=True, data={'top_10': top_10})
