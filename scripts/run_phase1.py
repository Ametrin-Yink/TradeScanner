#!/usr/bin/env python3
"""Standalone Phase 1 runner: AI Market Regime Detection."""
import sys
import time
import logging

sys.path.insert(0, '.')
from data.db import Database
from core.market_analyzer import MarketAnalyzer
from core.market_regime import MarketRegimeDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def run_phase1():
    db = Database()
    market_analyzer = MarketAnalyzer()
    regime_detector = MarketRegimeDetector()

    logger.info("=" * 60)
    logger.info("PHASE 1: AI Market Regime Detection")
    logger.info("=" * 60)

    spy_df = db.get_tier3_cache('SPY')
    vix_df = db.get_tier3_cache('^VIX')
    if vix_df is None:
        vix_df = db.get_tier3_cache('VIXY')

    if spy_df is None:
        logger.error("No SPY data in Tier 3 cache")
        return False
    if vix_df is None:
        logger.warning("No VIX data, using fallback")

    logger.info(f"SPY data: {len(spy_df)} rows, last date: {spy_df.index[-1]}")
    logger.info(f"VIX data: {len(vix_df)} rows, last date: {vix_df.index[-1]}")

    logger.info("\n[1/2] Running AI market analysis (Tavily + AI)...")
    analysis = market_analyzer.analyze_for_regime(spy_df, vix_df)
    ai_regime = analysis['sentiment']
    ai_confidence = analysis['confidence']
    ai_reasoning = analysis.get('reasoning', '')
    logger.info(f"  AI Regime: {ai_regime}")
    logger.info(f"  Confidence: {ai_confidence}")
    logger.info(f"  Reasoning: {ai_reasoning[:150]}")

    if ai_confidence == 50 and ai_reasoning.startswith('Error:'):
        logger.info("  AI returned error fallback, using technical detection only")
        ai_regime = None

    logger.info("\n[2/2] Technical regime detection + allocation...")
    regime = regime_detector.detect_regime_ai(
        spy_df, vix_df,
        analysis.get('tavily_results', []),
        ai_regime
    )
    allocation = regime_detector.get_allocation(regime)

    logger.info(f"  Final Regime: {regime}")
    logger.info(f"  Strategy allocation: {allocation}")
    logger.info(f"  Total slots: {sum(allocation.values())}")

    tech_regime = regime_detector.detect_regime(spy_df, vix_df)
    logger.info(f"  Technical regime: {tech_regime}")

    db.save_regime(
        regime=regime, allocation=allocation,
        ai_regime=ai_regime,
        ai_confidence=ai_confidence,
        ai_reasoning=ai_reasoning
    )
    logger.info(f"  Regime cached to DB for Phase 2")

    return True


if __name__ == '__main__':
    start = time.time()
    ok = run_phase1()
    elapsed = time.time() - start
    print(f"\nPhase 1 {'PASSED' if ok else 'FAILED'} in {elapsed:.1f}s")
    sys.exit(0 if ok else 1)
