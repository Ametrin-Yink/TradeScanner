#!/usr/bin/env python3
"""Reselect candidates using new per-strategy allocation and generate report."""
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from data.db import Database
from core.screener import StrategyScreener, StrategyMatch
from core.selector import CandidateSelector
from core.ai_confidence_scorer import ScoredCandidate
from core.reporter import ReportGenerator
from core.notifier import MultiNotifier
from config.settings import settings

def reselect_and_generate():
    """Reselect candidates with new allocation and generate report."""
    db = Database()

    # Get the last scan results from database
    logger.info("Loading candidates from last scan...")
    candidates = db.get_latest_scan_results()

    if not candidates:
        logger.error("No candidates found in database")
        return None

    logger.info(f"Loaded {len(candidates)} candidates from database")

    # Convert to StrategyMatch objects
    strategy_matches = []
    for c in candidates:
        match = StrategyMatch(
            symbol=c['symbol'],
            strategy=c['strategy'],
            entry_price=c['entry_price'],
            stop_loss=c['stop_loss'],
            take_profit=c['take_profit'],
            confidence=c['confidence'],
            match_reasons=c.get('match_reasons', []),
            technical_snapshot=c.get('technical_snapshot', {})
        )
        strategy_matches.append(match)

    # Group by strategy to see what we have
    from collections import defaultdict
    by_strategy = defaultdict(list)
    for m in strategy_matches:
        by_strategy[m.strategy].append(m)

    logger.info("\nCandidates by strategy:")
    for strategy, matches in sorted(by_strategy.items()):
        logger.info(f"  {strategy}: {len(matches)}")

    # Apply new per-strategy allocation
    # Use the allocation from market analyzer
    strategy_allocation = {
        'MomentumBreakout': 4,
        'PullbackEntry': 6,
        'SupportBounce': 6,
        'RangeShort': 4,
        'DoubleTopBottom': 6,
        'CapitulationRebound': 4
    }

    logger.info(f"\nStrategy allocation: {strategy_allocation}")

    # Use screener's new allocation method
    screener = StrategyScreener(db=db)
    selected = screener._allocate_candidates_by_strategy(strategy_matches, strategy_allocation)

    logger.info(f"\nSelected {len(selected)} candidates with new allocation:")
    by_strategy_selected = defaultdict(list)
    for m in selected:
        by_strategy_selected[m.strategy].append(m)

    for strategy, matches in sorted(by_strategy_selected.items()):
        logger.info(f"  {strategy}: {len(matches)}")
        for m in matches[:3]:  # Show top 3 per strategy
            logger.info(f"    - {m.symbol}: score={m.technical_snapshot.get('score', 0):.2f}, tier={m.technical_snapshot.get('tier', 'N/A')}")

    # Score with AI
    logger.info("\nScoring selected candidates with AI...")
    selector = CandidateSelector()
    scored = selector.select_top_30(selected, market_sentiment='bullish')

    logger.info(f"Final scored candidates: {len(scored)}")

    # Generate report
    logger.info("\nGenerating report...")
    reporter = ReportGenerator()

    # Get market sentiment from last scan
    market_sentiment = {
        'sentiment': 'bullish',
        'confidence': 75,
        'reasoning': 'SPY showing strength with 5-day return of 3.23%',
        'key_factors': ['Strong momentum', 'Above key EMAs', 'Volume confirmation']
    }

    report_path = reporter.generate_report(
        candidates=scored,
        market_sentiment=market_sentiment,
        phase_times={'phase0': 1334, 'phase1': 19, 'phase2': 5711, 'phase3': 0, 'phase4': 7, 'phase5': 1}
    )

    logger.info(f"Report generated: {report_path}")

    # Send notifications
    logger.info("Sending notifications...")
    notifier = MultiNotifier(
        discord_webhook=settings.get_secret('discord.webhook_url'),
        wechat_webhook=settings.get_secret('wechat.webhook_url')
    )

    notifier.send_notifications(
        opportunities=scored,
        market_sentiment=market_sentiment,
        report_path=report_path
    )

    logger.info("✅ Reselection and report generation complete!")
    return report_path

if __name__ == '__main__':
    report = reselect_and_generate()
    if report:
        print(f"\n✅ New report: {report}")
    else:
        print("\n❌ Failed")
        sys.exit(1)
