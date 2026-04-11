#!/usr/bin/env python3
"""Test script: Run Phase 0 + Phase 2 with unlimited slots and detailed funnel stats.

This script runs the full screening pipeline without Phase 1 (regime),
giving every strategy unlimited slots to see how many stocks each filter
rejects and how many get scored.

Usage:
    python3 tests/test_phase0_phase2.py
"""
import sys
import os

# Suppress sqlite3 finalizer warnings BEFORE any imports.
# These come through warnings.warn() from sqlite3.Connection.__del__.
import warnings
warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed database")
# Also handle unraisablehook path (Python 3.12+)
_original_unraisablehook = sys.unraisablehook
def _suppress_resource_warnings(exc):
    if exc.exc_type is ResourceWarning and "unclosed database" in str(exc.object):
        return
    _original_unraisablehook(exc)
sys.unraisablehook = _suppress_resource_warnings

import time
import logging
import warnings
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.db import Database
from core.premarket_prep import PreMarketPrep
from core.screener import StrategyScreener
from core.strategies import StrategyType, STRATEGY_NAME_TO_LETTER, STRATEGY_METADATA

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def run_phase0():
    """Run Phase 0 data prep and return symbols list."""
    logger.info("=" * 70)
    logger.info("PHASE 0: Data Preparation")
    logger.info("=" * 70)

    start = time.time()
    db = Database()
    prep = PreMarketPrep(db=db)
    result = prep.run_phase0()
    elapsed = time.time() - start

    if not result['success']:
        logger.error("Phase 0 failed — no qualifying stocks or Tier 1 cache")
        sys.exit(1)

    symbols = sorted(result['symbols'])
    logger.info(f"Phase 0 completed in {elapsed:.1f}s")
    logger.info(f"  Symbols for screening: {len(symbols)}")
    logger.info(f"  Tier 1 cache entries:  {result['tier1_cache_count']}")
    logger.info(f"  ETFs:                  {len(result['etfs'])}")

    return db, symbols, result.get('phase0_data', {})


def run_phase2_unlimited(db, symbols, phase0_data):
    """Run Phase 2 screening with unlimited slots per strategy and detailed funnel."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 2: Strategy Screening (UNLIMITED SLOTS — full view)")
    logger.info("=" * 70)

    screener = StrategyScreener(db=db)
    screener.market_data = {}
    screener._phase0_data = screener._run_phase0_precalculation(symbols, screener.market_data)

    # Merge any pre-existing phase0_data from Phase 0 runner
    for sym, data in phase0_data.items():
        if sym not in screener._phase0_data:
            screener._phase0_data[sym] = data

    # Update screener's strategy instances with shared data references
    strategies = {}
    for stype, strategy in screener._strategies.items():
        strategy.market_data = screener.market_data
        strategy.phase0_data = screener._phase0_data
        strategy.spy_return_5d = screener._spy_return_5d
        strategy._spy_df = screener._spy_data
        strategy._current_regime = 'neutral'  # Default, Phase 1 skipped
        strategies[stype] = strategy

    # Detailed funnel tracking
    funnel = {}  # strategy_name -> { screened, passed_filter, scored, tier_rejected, entry_warned, final }

    all_candidates = []
    strategy_results = {}

    for stype, strategy in strategies.items():
        letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME, '?')
        max_candidates = 9999  # Unlimited

        t0 = time.time()

        # Manually run the screening loop to capture per-strategy funnel details
        matches = []
        screened = 0
        passed_filter = 0
        scored = 0
        tier_rejected = 0
        entry_warned = 0

        for symbol in symbols:
            try:
                symbol_data = screener._phase0_data.get(symbol, {})

                df = strategy._get_data(symbol)
                if df is None:
                    continue
                import pandas as pd
                if not isinstance(df, pd.DataFrame) or len(df) < 50:
                    continue

                screened += 1

                if not strategy.filter(symbol, df):
                    continue

                passed_filter += 1

                dimensions = strategy.calculate_dimensions(symbol, df)
                if not dimensions:
                    continue

                score, tier = strategy.calculate_score(dimensions, df, symbol)
                scored += 1

                if tier == 'C':
                    tier_rejected += 1
                    continue

                entry, stop, target, entry_warning = strategy.calculate_entry_exit(
                    symbol, df, dimensions, score, tier
                )
                if entry is None:
                    current_price = df['close'].iloc[-1]
                    entry = round(current_price, 2)
                    stop = round(entry * 0.95, 2)
                    target = round(entry * 1.05, 2)
                    entry_warning = "Entry conditions not met, using current price"
                entry_warned += 1 if entry_warning else 0

                confidence = strategy.calculate_confidence(score, tier)
                reasons = strategy.build_match_reasons(symbol, df, dimensions, score, tier)
                snapshot = strategy.build_snapshot(symbol, df, dimensions, score, tier)

                from core.strategies.base_strategy import StrategyMatch
                matches.append(StrategyMatch(
                    symbol=symbol,
                    strategy=strategy.NAME,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    match_reasons=reasons,
                    technical_snapshot=snapshot,
                    entry_warning=entry_warning
                ))

            except Exception as e:
                logger.error(f"Error screening {symbol} for {strategy.NAME}: {e}")
                continue

        elapsed = time.time() - t0

        # Sort by confidence, no limit
        results = sorted(matches, key=lambda x: x.confidence, reverse=True)

        funnel[strategy.NAME] = {
            'letter': letter,
            'screened': screened,
            'passed_filter': passed_filter,
            'scored': scored,
            'tier_rejected': tier_rejected,
            'entry_warned': entry_warned,
            'final': len(results),
            'time': elapsed,
        }

        strategy_results[strategy.NAME] = results
        all_candidates.extend(results)

        logger.info(
            f"  {strategy.NAME} ({letter}): screened={screened} -> "
            f"filter_pass={passed_filter} -> scored={scored} -> "
            f"tierC_rej={tier_rejected} -> entry_warn={entry_warned} -> "
            f"final={len(results)} ({elapsed:.1f}s)"
        )

    # Print detailed funnel table
    print_detailed_funnel(funnel, symbols)

    # Print top candidates per strategy
    print_top_candidates(strategy_results)

    return funnel, strategy_results, all_candidates


def print_detailed_funnel(funnel, all_symbols):
    """Print a detailed funnel table showing rejection counts at each stage."""
    logger.info("")
    logger.info("=" * 90)
    logger.info("DETAILED SCREENING FUNNEL")
    logger.info("=" * 90)

    header = f"{'Strategy':<25} {'Input':>6} {'Screened':>8} {'FilterPass':>11} {'FilteredOut':>12} {'Scored':>7} {'TierC':>6} {'Warn':>5} {'Final':>6} {'Time(s)':>7}"
    logger.info(header)
    logger.info("-" * 90)

    total_input = len(all_symbols)
    totals = {
        'screened': 0, 'passed_filter': 0, 'scored': 0,
        'tier_rejected': 0, 'entry_warned': 0, 'final': 0, 'time': 0.0
    }

    for name in sorted(funnel.keys(), key=lambda x: funnel[x]['letter']):
        f = funnel[name]
        filtered_out = f['screened'] - f['passed_filter']
        logger.info(
            f"  {name:<23} {total_input:>6} {f['screened']:>8} {f['passed_filter']:>11} "
            f"{filtered_out:>12} {f['scored']:>7} {f['tier_rejected']:>6} "
            f"{f['entry_warned']:>5} {f['final']:>6} {f['time']:>7.1f}"
        )
        totals['screened'] += f['screened']
        totals['passed_filter'] += f['passed_filter']
        totals['scored'] += f['scored']
        totals['tier_rejected'] += f['tier_rejected']
        totals['entry_warned'] += f['entry_warned']
        totals['final'] += f['final']
        totals['time'] += f['time']

    logger.info("-" * 90)
    total_filtered = totals['screened'] - totals['passed_filter']
    logger.info(
        f"  {'TOTAL':<23} {total_input:>6} {totals['screened']:>8} {totals['passed_filter']:>11} "
        f"{total_filtered:>12} {totals['scored']:>7} {totals['tier_rejected']:>6} "
        f"{totals['entry_warned']:>5} {totals['final']:>6} {totals['time']:>7.1f}"
    )

    # Per-strategy rejection breakdown
    logger.info("")
    logger.info("=" * 70)
    logger.info("REJECTION BREAKDOWN (per strategy)")
    logger.info("=" * 70)

    for name in sorted(funnel.keys(), key=lambda x: funnel[x]['letter']):
        f = funnel[name]
        input_count = len(all_symbols)
        no_data = input_count - f['screened']
        filter_rej = f['screened'] - f['passed_filter']
        tier_rej = f['tier_rejected']
        passed_all = f['final']

        logger.info(f"\n  {name} ({f['letter']}):")
        logger.info(f"    No data / insufficient:  {no_data:>5}  ({no_data/input_count*100:.1f}% of input)")
        logger.info(f"    Filter rejected:         {filter_rej:>5}  ({filter_rej/f['screened']*100 if f['screened'] > 0 else 0:.1f}% of screened)")
        logger.info(f"    Score < Tier B (C tier): {tier_rej:>5}  ({tier_rej/f['scored']*100 if f['scored'] > 0 else 0:.1f}% of scored)")
        logger.info(f"    Passed all stages:       {passed_all:>5}  ({passed_all/f['screened']*100 if f['screened'] > 0 else 0:.1f}% of screened)")


def print_top_candidates(strategy_results, top_n=10):
    """Print top N candidates per strategy."""
    logger.info("")
    logger.info("=" * 90)
    logger.info("TOP CANDIDATES PER STRATEGY (by confidence, unlimited)")
    logger.info("=" * 90)

    for name in sorted(strategy_results.keys(), key=lambda x: STRATEGY_NAME_TO_LETTER.get(x, '?')):
        results = strategy_results[name]
        letter = STRATEGY_NAME_TO_LETTER.get(name, '?')

        if not results:
            logger.info(f"\n  {name} ({letter}): No candidates found")
            continue

        logger.info(f"\n  {name} ({letter}): {len(results)} candidates (showing top {min(top_n, len(results))})")
        logger.info(f"  {'#':>3} {'Symbol':<7} {'Score':>6} {'Tier':<5} {'Conf':>5} {'Entry':>8} {'Stop':>8} {'Target':>8} {'Price':>8}")
        logger.info(f"  {'-'*75}")

        for i, c in enumerate(results[:top_n], 1):
            snap = c.technical_snapshot
            price = snap.get('current_price', 0)
            score = snap.get('score', 0)
            tier = snap.get('tier', '?')
            logger.info(
                f"  {i:>3} {c.symbol:<7} {score:>6.1f} {tier:<5} {c.confidence:>5} "
                f"${c.entry_price:>7.2f} ${c.stop_loss:>7.2f} ${c.take_profit:>7.2f} ${price:>7.2f}"
            )


def main():
    total_start = time.time()

    # Phase 0
    db, symbols, phase0_data = run_phase0()

    # Phase 2
    funnel, strategy_results, all_candidates = run_phase2_unlimited(db, symbols, phase0_data)

    total_elapsed = time.time() - total_start

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"TOTAL: Phase 0 + Phase 2 completed in {total_elapsed:.1f}s")
    logger.info(f"  Total candidates across all strategies: {len(all_candidates)}")
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
