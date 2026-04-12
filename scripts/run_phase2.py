#!/usr/bin/env python3
"""Standalone Phase 2 runner: Strategy Screening.

Default mode: only strategies with allocated slots (production).
--all mode: all strategies get 4 slots + underfill investigation (debug).

Usage:
    python3 scripts/run_phase2.py          # production
    python3 scripts/run_phase2.py --all    # debug all strategies
"""
import sys
import time
import logging
import argparse
from collections import defaultdict

sys.path.insert(0, '.')
from data.db import Database
from core.screener import StrategyScreener
from core.market_regime import MarketRegimeDetector
from core.market_analyzer import MarketAnalyzer
from core.strategies import StrategyType, STRATEGY_NAME_TO_LETTER, STRATEGY_METADATA

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def _load_regime(db):
    regime_detector = MarketRegimeDetector()
    cached_regime = db.load_regime()

    if cached_regime and cached_regime['regime']:
        regime = cached_regime['regime']
        allocation = cached_regime['allocation']
        logger.info(f"Loaded regime from Phase 1 cache (date: {cached_regime['cache_date']})")
        logger.info(f"Regime: {regime} (AI: {cached_regime.get('ai_regime')}, conf: {cached_regime.get('ai_confidence')})")
        if cached_regime.get('ai_reasoning'):
            logger.info(f"AI reasoning: {cached_regime['ai_reasoning'][:300]}")
        return regime, allocation, regime_detector

    logger.info("No cached regime from Phase 1, running AI analysis...")
    market_analyzer = MarketAnalyzer()
    spy_df = db.get_tier3_cache('SPY')
    vix_df = db.get_tier3_cache('^VIX')
    if vix_df is None:
        vix_df = db.get_tier3_cache('VIXY')

    try:
        analysis = market_analyzer.analyze_for_regime(spy_df, vix_df)
        ai_regime = analysis['sentiment']
        regime = regime_detector.detect_regime_ai(
            spy_df, vix_df,
            ai_regime
        )
        allocation = regime_detector.get_allocation(regime)
        logger.info(f"AI regime: {ai_regime} (confidence: {analysis['confidence']})")
        logger.info(f"AI reasoning: {analysis.get('reasoning', '')[:300]}")
        logger.info(f"Final regime: {regime}")

        db.save_regime(regime=regime, allocation=allocation,
                       ai_regime=ai_regime,
                       ai_confidence=analysis.get('confidence', 50),
                       ai_reasoning=analysis.get('reasoning', ''))
    except Exception as e:
        logger.error(f"AI regime detection failed: {e}, using technical fallback")
        regime = regime_detector.detect_regime(spy_df, vix_df)
        allocation = regime_detector.get_allocation(regime)
        logger.info(f"Fallback regime: {regime}")

    return regime, allocation, regime_detector


def _print_candidates(selected):
    logger.info(f"\n{'='*60}")
    logger.info("Final Candidate List")
    logger.info(f"{'='*60}")
    for i, c in enumerate(selected, 1):
        score = c.technical_snapshot.get('score', 0)
        tier = c.technical_snapshot.get('tier', '?')
        sector = c.technical_snapshot.get('sector', 'Unknown')
        price = c.technical_snapshot.get('current_price', 0)
        logger.info(f"  {i:2d}. {c.symbol:6s} | {c.strategy:25s} | Score:{score:5.1f} Tier:{tier} | ${price:.2f} | {sector}")


# ---------------------------------------------------------------------------
# Investigation helpers (for --all mode)
# ---------------------------------------------------------------------------

def investigate_support_bounce(screener, symbols, phase0_data):
    from core.strategies.support_bounce import SupportBounceStrategy
    strategy = SupportBounceStrategy(db=screener.db)
    strategy.phase0_data = phase0_data
    strategy.market_data = screener.market_data

    prefiltered = []
    rejection_reasons = defaultdict(int)

    for symbol in symbols:
        try:
            df = strategy._get_data(symbol)
            if df is None or len(df) < 50:
                rejection_reasons['no_data'] += 1
                continue

            current_price = df['close'].iloc[-1]
            p0 = phase0_data.get(symbol, {})
            supports = p0.get('supports', [])

            if not supports:
                rejection_reasons['no_supports'] += 1
                continue

            supports_below = [s for s in supports if s < current_price]
            if not supports_below:
                rejection_reasons['no_support_below'] += 1
                continue

            nearest_support = max(supports_below)
            distance_pct = (current_price - nearest_support) / current_price

            if distance_pct > 0.10:
                rejection_reasons['too_far_from_support'] += 1
                continue

            prefiltered.append(symbol)
        except Exception as e:
            rejection_reasons[f'error:{e}'] += 1

    logger.info(f"SupportBounce pre-filter: {len(prefiltered)} passed")
    logger.info(f"SupportBounce rejection reasons: {dict(rejection_reasons)}")

    filter_failures = defaultdict(int)
    for symbol in prefiltered[:50]:
        try:
            df = strategy._get_data(symbol)
            if df is None:
                continue

            if not strategy.filter(symbol, df):
                ind = __import__('core.indicators', fromlist=['TechnicalIndicators']).TechnicalIndicators(df)
                ind.calculate_all()

                if not strategy._check_basic_requirements(df):
                    filter_failures['basic_req(ADR/vol)'] += 1
                    continue

                current_price = df['close'].iloc[-1]
                ema50 = ind.indicators.get('ema', {}).get('ema50', current_price)
                ema50_dist = abs(current_price - ema50) / ema50 if ema50 > 0 else 1.0
                if ema50_dist > 0.15:
                    filter_failures['ema50_too_far'] += 1
                    continue

                sr_levels = strategy._get_sr_levels(df, symbol)
                supports = sr_levels.get('support', [])
                supports_below = [s for s in supports if s < current_price]
                if not supports_below:
                    filter_failures['no_support_below(filter)'] += 1
                    continue

                atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)
                support_touches = strategy._calculate_support_touches(df, max(supports_below), atr)
                touch_dates = support_touches.get('touch_dates', [])
                touches_60d = len([d for d in touch_dates if d <= 60])
                touches_30d = len([d for d in touch_dates if d <= 30])

                if not (touches_60d >= 3 or touches_30d >= 2):
                    filter_failures[f'touch_fail(60d:{touches_60d},30d:{touches_30d})'] += 1
                    continue

                filter_failures['passed_filter_but_dim_fail'] += 1
        except Exception as e:
            filter_failures[f'filter_error:{e}'] += 1

    logger.info(f"SupportBounce filter failure reasons (first 50): {dict(filter_failures)}")


def investigate_earnings_gap(screener, symbols, phase0_data):
    logger.info("Investigating EarningsGap eligibility...")

    gap_stats = defaultdict(int)
    eligible_by_gap = defaultdict(int)

    for symbol in symbols:
        data = phase0_data.get(symbol, {})
        days_since_earnings = data.get('days_since_earnings')
        gap_1d_pct = data.get('gap_1d_pct', 0)
        gap_vol_ratio = data.get('gap_volume_ratio', 1.0)
        rs_pct = data.get('rs_percentile', 0)
        gap_direction = data.get('gap_direction', 'none')

        if days_since_earnings is None:
            gap_stats['no_earnings_data'] += 1
            continue

        gap_stats['has_last_earnings'] += 1
        gap_size = abs(gap_1d_pct)

        if gap_size >= 0.10:
            max_days = 5
        elif gap_size >= 0.07:
            max_days = 3
        else:
            max_days = 2

        if days_since_earnings > max_days or days_since_earnings < 1:
            gap_stats[f'outside_window(post={days_since_earnings},max={max_days})'] += 1
            continue

        gap_stats['in_window'] += 1

        if gap_size < 0.05:
            gap_stats['gap_too_small'] += 1
            continue

        gap_stats['gap_ok'] += 1

        if gap_vol_ratio < 2.0:
            gap_stats['volume_too_low'] += 1
            continue

        gap_stats['volume_ok'] += 1

        if gap_direction == 'up' and rs_pct < 50:
            gap_stats['rs_too_low_long'] += 1
            continue
        elif gap_direction == 'down' and rs_pct > 50:
            gap_stats['rs_too_high_short'] += 1
            continue
        elif gap_direction == 'none':
            gap_stats['no_gap_direction'] += 1
            continue

        gap_stats['fully_eligible'] += 1
        eligible_by_gap[f'{gap_direction}'] += 1

    logger.info(f"EarningsGap eligibility stats: {dict(gap_stats)}")
    logger.info(f"EarningsGap eligible by direction: {dict(eligible_by_gap)}")

    closest = []
    for symbol in symbols:
        data = phase0_data.get(symbol, {})
        days_since_earnings = data.get('days_since_earnings')
        gap_1d_pct = data.get('gap_1d_pct', 0)
        gap_vol_ratio = data.get('gap_volume_ratio', 1.0)
        if days_since_earnings is not None and 1 <= days_since_earnings <= 5:
            closest.append((symbol, abs(gap_1d_pct), days_since_earnings, gap_vol_ratio))

    closest.sort(key=lambda x: -x[0])
    logger.info("Top 10 EarningsGap candidates (by gap size):")
    for sym, gap, days, vol in closest[:10]:
        logger.info(f"  {sym}: gap={gap:.1%}, days_post={days}, vol_ratio={vol:.1f}x")


def investigate_rs_long(screener, symbols, phase0_data, regime):
    logger.info(f"Investigating RelativeStrengthLong (regime={regime})...")

    stats = defaultdict(int)
    for symbol in symbols:
        data = phase0_data.get(symbol, {})
        rs_pct = data.get('rs_percentile', 0)

        stats['total'] += 1

        if regime not in ['bear_moderate', 'bear_strong', 'extreme_vix', 'neutral']:
            stats[f'regime_blocked({regime})'] += 1
            break

        if rs_pct < 80:
            stats['rs_below_80'] += 1
            continue

        stats['rs_ok'] += 1

    logger.info(f"RS Long stats: {dict(stats)}")

    rs_80_plus = []
    for symbol in symbols:
        data = phase0_data.get(symbol, {})
        rs_pct = data.get('rs_percentile', 0)
        if rs_pct >= 80:
            rs_80_plus.append((symbol, rs_pct))

    rs_80_plus.sort(key=lambda x: -x[1])
    logger.info(f"Stocks with RS >= 80th percentile: {len(rs_80_plus)}")
    for sym, rs in rs_80_plus[:10]:
        logger.info(f"  {sym}: RS={rs:.0f}th")


# ---------------------------------------------------------------------------
# Main runners
# ---------------------------------------------------------------------------

def run_phase2(all_mode=False):
    db = Database()
    regime, allocation, regime_detector = _load_regime(db)

    if all_mode:
        allocation = {
            'A1': 4, 'A2': 4, 'B': 4, 'C': 4, 'D': 4, 'E': 4, 'F': 4, 'G': 4, 'H': 4
        }
        logger.info("=" * 60)
        logger.info("PHASE 2: Strategy Screening (ALL STRATEGIES TEST)")
        logger.info("=" * 60)
    else:
        logger.info("=" * 60)
        logger.info("PHASE 2: Strategy Screening")
        logger.info("=" * 60)

    logger.info(f"Regime: {regime}")
    logger.info(f"Allocation: {allocation}")
    logger.info(f"Total slots: {sum(allocation.values())}")

    all_tier1 = db.get_all_tier1_cache()
    symbols = sorted(all_tier1.keys())
    logger.info(f"\nTotal symbols with Tier 1 cache: {len(symbols)}")

    screener_start = time.time()
    screener = StrategyScreener(db=db)
    screener_init_time = time.time() - screener_start
    logger.info(f"Screener initialized in {screener_init_time:.1f}s")

    screener.market_data = {}
    screener._phase0_data = screener._run_phase0_precalculation(symbols, screener.market_data)

    active_strategies = {}
    for stype, strategy in screener._strategies.items():
        letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
        slots = allocation.get(letter, 0) if letter else 0
        if slots > 0:
            active_strategies[stype] = strategy

    for strategy in active_strategies.values():
        strategy.market_data = screener.market_data
        strategy.phase0_data = screener._phase0_data
        strategy.spy_return_5d = screener._spy_return_5d
        strategy._spy_df = screener._spy_data
        strategy._current_regime = regime

    strategy_results = {}
    all_candidates = []

    logger.info(f"\n{'='*60}")
    logger.info("Per-Strategy Screening Results")
    logger.info(f"{'='*60}")

    for stype, strategy in active_strategies.items():
        letter = STRATEGY_NAME_TO_LETTER.get(strategy.NAME)
        max_slots = allocation.get(letter, 0)

        if all_mode and max_slots == 0:
            logger.info(f"  {strategy.NAME} ({letter}): SKIPPED (0 slots)")
            continue

        t0 = time.time()
        screen_count = max_slots + 4  # screen extra for round-robin fill
        candidates = strategy.screen(symbols, max_candidates=screen_count)
        elapsed = time.time() - t0

        strategy_results[strategy.NAME] = {
            'letter': letter,
            'slots': max_slots,
            'time': elapsed,
            'candidates': candidates,
            'count': len(candidates),
        }

        score_range = ""
        if candidates:
            scores = [c.technical_snapshot.get('score', 0) for c in candidates]
            score_range = f" scores: {min(scores):.1f}-{max(scores):.1f}"

        logger.info(f"  {strategy.NAME} ({letter}): {len(candidates)}/{max_slots} slots filled, {elapsed:.1f}s{score_range}")

        all_candidates.extend(candidates)

    logger.info(f"\n{'='*60}")
    logger.info("Allocation (duplicate handling + sector cap)")
    logger.info(f"{'='*60}")

    alloc_start = time.time()
    selected = screener._allocate_by_table(all_candidates, allocation, regime)
    alloc_time = time.time() - alloc_start

    total_screening_time = sum(r['time'] for r in strategy_results.values())
    total_time = total_screening_time + alloc_time

    logger.info(f"\nAllocation completed in {alloc_time:.1f}s")
    logger.info(f"Final candidates: {len(selected)}")

    _print_candidates(selected)

    logger.info(f"\n{'='*60}")
    logger.info("Summary")
    logger.info(f"{'='*60}")
    logger.info(f"  Regime: {regime}")
    logger.info(f"  Input symbols (Tier 1): {len(symbols)}")
    logger.info(f"  Total candidates before allocation: {len(all_candidates)}")
    logger.info(f"  Final candidates after allocation: {len(selected)}")
    logger.info(f"  Screening time: {total_screening_time:.1f}s")
    logger.info(f"  Allocation time: {alloc_time:.1f}s")
    logger.info(f"  Total Phase 2 time: {total_time:.1f}s")
    logger.info(f"  Screener init time: {screener_init_time:.1f}s")

    logger.info(f"\n{'Strategy':<25} {'Slots':>5} {'Filled':>7} {'Time(s)':>8}")
    logger.info("-" * 50)
    for name, result in sorted(strategy_results.items(), key=lambda x: x[1]['letter']):
        logger.info(f"  {name:<23} {result['slots']:>5} {result['count']:>7} {result['time']:>8.1f}")

    if all_mode:
        logger.info(f"\n{'='*60}")
        logger.info("INVESTIGATION: Why C, G, H are underfilled")
        logger.info(f"{'='*60}")

        logger.info("\n--- Strategy C: SupportBounce ---")
        investigate_support_bounce(screener, symbols, screener._phase0_data)

        logger.info("\n--- Strategy G: EarningsGap ---")
        investigate_earnings_gap(screener, symbols, screener._phase0_data)

        logger.info("\n--- Strategy H: RelativeStrengthLong ---")
        investigate_rs_long(screener, symbols, screener._phase0_data, regime)

    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phase 2 Strategy Screening')
    parser.add_argument('--all', action='store_true', help='Run all strategies with 4 slots each + underfill investigation')
    args = parser.parse_args()

    start = time.time()
    ok = run_phase2(all_mode=args.all)
    elapsed = time.time() - start
    print(f"\nPhase 2 {'PASSED' if ok else 'FAILED'} in {elapsed:.1f}s")
    sys.exit(0 if ok else 1)
