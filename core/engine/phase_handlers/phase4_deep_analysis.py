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
            da = c.deep_analysis if hasattr(c, 'deep_analysis') and c.deep_analysis else {}

            # Map catalysts from deep_analysis
            catalysts = da.get('key_catalysts', [])
            if isinstance(catalysts, list):
                catalyst = '; '.join(str(x) for x in catalysts) if catalysts else ''
            else:
                catalyst = str(catalysts) if catalysts else ''

            # Map reasoning: prefer detailed_reasoning, fallback to technical_outlook, then reasoning
            ai_reasoning = (
                da.get('detailed_reasoning', '')
                or da.get('technical_outlook', '')
                or getattr(c, 'reasoning', '')
            )

            # Map risk factors: combine ScoredCandidate risk_factors with deep_analysis risk_level
            risk_factors = list(getattr(c, 'risk_factors', []) or [])
            risk_level = da.get('risk_level', '')
            if risk_level and not risk_factors:
                risk_factors = [f"{risk_level} overall risk environment"]

            opp = AnalyzedOpportunity(
                symbol=c.symbol,
                strategy=c.strategy,
                entry_price=c.entry_price,
                stop_loss=c.stop_loss,
                take_profit=c.take_profit,
                confidence=c.confidence,
                match_reasons=getattr(c, 'match_reasons', []),
                ai_reasoning=ai_reasoning,
                catalyst=catalyst,
                risk_factors=risk_factors[:3],
                technical_snapshot=getattr(c, 'technical_snapshot', {}),
            )
            top_10.append(opp)

        logger.info(f"Deep analyzed {len(top_10)} opportunities")

        return PhaseResult(success=True, data={'top_10': top_10})
