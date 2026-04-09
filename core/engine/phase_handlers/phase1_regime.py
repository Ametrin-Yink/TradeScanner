"""Phase 1: AI Market Regime Detection handler."""
import logging

from core.engine.base_phase import PhaseHandler, PhaseResult
from core.engine.context import PipelineContext
from core.market_analyzer import MarketAnalyzer
from core.market_regime import MarketRegimeDetector
from data.db import Database

logger = logging.getLogger(__name__)


class Phase1RegimeHandler(PhaseHandler):
    NAME = "phase1"
    DESCRIPTION = "AI Market Regime Detection"

    def execute(self, ctx: PipelineContext) -> PhaseResult:
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 1: AI Market Regime Detection")
        logger.info("=" * 60)

        db = getattr(ctx, 'db', None) or Database()
        market_analyzer = MarketAnalyzer()
        regime_detector = MarketRegimeDetector()

        try:
            spy_df = db.get_tier3_cache('SPY')
            vix_df = db.get_tier3_cache('^VIX')
            if vix_df is None:
                vix_df = db.get_tier3_cache('VIXY')

            analysis = market_analyzer.analyze_for_regime(spy_df, vix_df)
            ai_regime = analysis['sentiment']

            regime = regime_detector.detect_regime_ai(
                spy_df, vix_df,
                analysis.get('tavily_results', []),
                ai_regime
            )
            allocation = regime_detector.get_allocation(regime)

            logger.info(f"AI Regime: {ai_regime} (confidence: {analysis['confidence']})")
            logger.info(f"Final Regime: {regime}")
            logger.info(f"Strategy allocation: {allocation}")

        except Exception as e:
            logger.error(f"AI regime detection failed: {e}, using technical fallback")
            spy_df = db.get_tier3_cache('SPY')
            vix_df = db.get_tier3_cache('^VIX')
            if vix_df is None:
                vix_df = db.get_tier3_cache('VIXY')
            regime = regime_detector.detect_regime(spy_df, vix_df)
            allocation = regime_detector.get_allocation(regime)
            analysis = {'confidence': 0, 'reasoning': f'Fallback: {e}'}

        return PhaseResult(success=True, data={
            'regime': regime,
            'allocation': allocation,
            'regime_analysis': {
                'ai_confidence': analysis.get('confidence', 50),
                'ai_reasoning': analysis.get('reasoning', ''),
            }
        })
