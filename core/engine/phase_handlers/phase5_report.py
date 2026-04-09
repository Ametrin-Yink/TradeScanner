"""Phase 5: Report Generation handler."""
import logging
from datetime import datetime

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.reporter import ReportGenerator

logger = logging.getLogger(__name__)


class Phase5ReportHandler(PhaseHandler):
    NAME = "phase5"
    DESCRIPTION = "Report Generation"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 5: Report Generation")
        logger.info("=" * 60)

        reporter = ReportGenerator()

        sentiment_result = {
            'reasoning': ctx.regime_analysis.get('ai_reasoning', ''),
            'confidence': ctx.regime_analysis.get('ai_confidence', 50),
            'key_factors': [f"Regime: {ctx.regime}"],
            'timestamp': datetime.now().isoformat()
        }

        report_path = reporter.generate_report(
            opportunities=ctx.top_10,
            all_candidates=ctx.top_30,
            market_sentiment=ctx.regime,
            sentiment_result=sentiment_result,
            total_stocks=len(ctx.symbols),
            success_count=len(ctx.symbols) - len(ctx.fail_symbols),
            fail_count=len(ctx.fail_symbols),
            fail_symbols=ctx.fail_symbols
        )

        logger.info(f"Report generated: {report_path}")

        return PhaseResult(success=True, data={'report_path': report_path})
