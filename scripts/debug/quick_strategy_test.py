"""Quick strategy test - Run all 8 strategies and report results."""
import logging
from datetime import datetime
from typing import Dict, List

import pandas as pd
from data.db import Database
from core.fetcher import DataFetcher
from core.market_regime import MarketRegimeDetector
from core.indicators import TechnicalIndicators

from core.strategies.momentum_breakout import MomentumBreakoutStrategy
from core.strategies.pullback_entry import PullbackEntryStrategy
from core.strategies.support_bounce import SupportBounceStrategy
from core.strategies.distribution_top import DistributionTopStrategy
from core.strategies.accumulation_bottom import AccumulationBottomStrategy
from core.strategies.capitulation_rebound import CapitulationReboundStrategy
from core.strategies.earnings_gap import EarningsGapStrategy
from core.strategies.relative_strength_long import RelativeStrengthLongStrategy

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def quick_test_strategies(test_date: str = "2026-01-27", max_symbols: int = 200):
    """Quick test of all 8 strategies."""
    print(f"\n{'='*60}")
    print(f"Strategy Test - {test_date}")
    print(f"{'='*60}\n")

    db = Database()
    fetcher = DataFetcher(db=db)

    # Get active stocks
    symbols = db.get_active_stocks()[:max_symbols]
    print(f"Testing on {len(symbols)} symbols\n")

    # Get SPY data for regime detection
    spy_df, _ = fetcher._get_cached_data('SPY')
    if spy_df is not None:
        spy_df = spy_df[spy_df.index <= pd.Timestamp(test_date)]

    vix_df, _ = fetcher._get_cached_data('VIXY')
    if vix_df is not None:
        vix_df = vix_df[vix_df.index <= pd.Timestamp(test_date)]

    # Detect regime
    detector = MarketRegimeDetector()
    regime = detector.detect_regime(spy_df, vix_df)
    allocation = detector.get_allocation(regime)

    print(f"Market Regime: {regime}")
    print(f"Allocation: {allocation}\n")

    # Prepare phase0 data
    phase0_data = {}
    for symbol in symbols:
        try:
            df, _ = fetcher._get_cached_data(symbol)
            if df is None or len(df) < 50:
                continue

            df = df[df.index <= pd.Timestamp(test_date)]
            if len(df) < 50:
                continue

            price = df['close'].iloc[-1]
            ind = TechnicalIndicators(df)
            ind.calculate_all()

            adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
            ema21 = ind.indicators.get('ema', {}).get('ema21', price)
            volume_sma = ind.indicators.get('volume', {}).get('volume_sma', 0)

            # Calculate returns
            ret_3m = price / df['close'].iloc[-min(63, len(df))] - 1
            ret_6m = price / df['close'].iloc[-min(126, len(df))] - 1
            ret_12m = price / df['close'].iloc[-min(252, len(df))] - 1

            phase0_data[symbol] = {
                'price': price,
                'adr_pct': adr_pct,
                'ema21': ema21,
                'volume_sma': volume_sma,
                'returns_3m': ret_3m,
                'returns_6m': ret_6m,
                'returns_12m': ret_12m,
                'market_cap': 10e9,
            }
        except Exception:
            continue

    print(f"Phase 0 data ready: {len(phase0_data)} symbols\n")

    # Define strategies
    strategies = {
        'A': ('MomentumBreakout', MomentumBreakoutStrategy),
        'B': ('PullbackEntry', PullbackEntryStrategy),
        'C': ('SupportBounce', SupportBounceStrategy),
        'D': ('DistributionTop', DistributionTopStrategy),
        'E': ('AccumulationBottom', AccumulationBottomStrategy),
        'F': ('CapitulationRebound', CapitulationReboundStrategy),
        'G': ('EarningsGap', EarningsGapStrategy),
        'H': ('RelativeStrengthLong', RelativeStrengthLongStrategy),
    }

    # Run each strategy
    results = {}
    for letter, (name, strategy_class) in strategies.items():
        slots = allocation.get(letter, 0)
        if slots == 0:
            results[name] = {'slots': 0, 'found': 0, 'S': 0, 'A': 0, 'B': 0}
            continue

        strategy = strategy_class()
        strategy.phase0_data = phase0_data
        strategy._spy_df = spy_df
        strategy._current_regime = regime

        matches = strategy.screen(list(phase0_data.keys()), max_candidates=slots)

        # Count by tier
        s_count = sum(1 for m in matches if m.technical_snapshot.get('tier') == 'S')
        a_count = sum(1 for m in matches if m.technical_snapshot.get('tier') == 'A')
        b_count = sum(1 for m in matches if m.technical_snapshot.get('tier') == 'B')

        results[name] = {
            'slots': slots,
            'found': len(matches),
            'S': s_count,
            'A': a_count,
            'B': b_count,
        }

        print(f"{letter}. {name}: {len(matches)}/{slots} matches (S:{s_count}, A:{a_count}, B:{b_count})")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_found = sum(r['found'] for r in results.values())
    print(f"Total candidates found: {total_found}/30")
    print(f"\nBy Strategy:")
    for name, r in results.items():
        if r['slots'] > 0:
            print(f"  {name}: {r['found']}/{r['slots']} (S:{r['S']}, A:{r['A']}, B:{r['B']})")

    return results


if __name__ == '__main__':
    quick_test_strategies(max_symbols=1000)
