"""Phase 3: AI Scoring handler."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer

logger = logging.getLogger(__name__)


class Phase3AIScoringHandler(PhaseHandler):
    NAME = "phase3"
    DESCRIPTION = "AI Scoring - Top 30 Selection"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3: AI Analysis")
        logger.info("=" * 60)

        candidates = ctx.candidates
        regime = ctx.regime

        selector = CandidateSelector()
        opportunity_analyzer = OpportunityAnalyzer()

        top_30 = selector.select_top_30(candidates, regime)
        logger.info(f"Selected {len(top_30)} opportunities for deep analysis")
        logger.info(f"Analyzing with 2 parallel workers...")

        analyzed = []
        completed = 0

        def analyze_single(match):
            try:
                analysis = opportunity_analyzer.analyze_opportunity(match, regime)
                return analysis
            except Exception as e:
                logger.error(f"Failed to analyze {match.symbol}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_match = {
                executor.submit(analyze_single, match): match
                for match in top_30
            }

            for future in as_completed(future_to_match):
                match = future_to_match[future]
                try:
                    result = future.result()
                    if result is not None:
                        analyzed.append(result)
                except Exception as e:
                    logger.error(f"Error analyzing {match.symbol}: {e}")

                completed += 1
                logger.info(f"Analyzed {match.symbol} ({completed}/{len(top_30)})...")

        logger.info(f"Analyzed {len(analyzed)} opportunities")

        return PhaseResult(success=True, data={'top_30': analyzed})
