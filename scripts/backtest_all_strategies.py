"""Backtest all 8 strategies - Run on all cached stocks and report tier distribution."""
import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from collections import defaultdict

import pandas as pd
import numpy as np

from config.settings import settings
from data.db import Database
from core.market_regime import MarketRegimeDetector
from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators

from core.strategies.momentum_breakout import MomentumBreakoutStrategy
from core.strategies.pullback_entry import PullbackEntryStrategy
from core.strategies.support_bounce import SupportBounceStrategy
from core.strategies.distribution_top import DistributionTopStrategy
from core.strategies.accumulation_bottom import AccumulationBottomStrategy
from core.strategies.capitulation_rebound import CapitulationReboundStrategy
from core.strategies.earnings_gap import EarningsGapStrategy
from core.strategies.relative_strength_long import RelativeStrengthLongStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

os.makedirs('reports', exist_ok=True)


class AllStocksBacktestRunner:
    """Run backtest on ALL cached stocks without slot allocation."""

    def __init__(self, backtest_date: str):
        self.backtest_date = backtest_date
        self.db = Database()
        self.fetcher = DataFetcher(db=self.db)

    def run(self) -> Optional[Dict]:
        logger.info("=" * 60)
        logger.info(f"BACKTEST ALL STOCKS: {self.backtest_date}")
        logger.info("=" * 60)

        # Get symbols from database
        symbols = self.db.get_active_stocks()
        logger.info(f"Active stocks in database: {len(symbols)}")

        # Get SPY data for regime detection
        spy_df, _ = self.fetcher._get_cached_data('SPY')
        if spy_df is not None:
            backtest_dt = pd.Timestamp(self.backtest_date)
            spy_df = spy_df[spy_df.index <= backtest_dt]

        vix_df, _ = self.fetcher._get_cached_data('VIXY')
        if vix_df is not None:
            backtest_dt = pd.Timestamp(self.backtest_date)
            vix_df = vix_df[vix_df.index <= backtest_dt]

        # Detect regime
        detector = MarketRegimeDetector()
        regime = detector.detect_regime(spy_df, vix_df) if spy_df is not None else 'neutral'
        logger.info(f"Detected regime: {regime}")

        # Load phase0_data for ALL symbols and calculate RS percentiles
        logger.info("\nLoading phase0_data and calculating RS percentiles...")
        phase0_data = {}
        rs_scores = []

        for symbol in symbols:
            try:
                df, _ = self.fetcher._get_cached_data(symbol)
                if df is None or len(df) < 50:
                    continue

                backtest_dt = pd.Timestamp(self.backtest_date)
                df = df[df.index <= backtest_dt]
                if len(df) < 50:
                    continue

                # Load from tier1 cache
                tier1 = self.db.get_tier1_cache(symbol)
                if not tier1:
                    continue

                # Get rs_raw for percentile calculation
                rs_raw = tier1.get('rs_raw', 0) or 0
                rs_scores.append({'symbol': symbol, 'rs': rs_raw})

                # Store phase0_data - NOTE: ret_3m is stored as percentage in cache, convert to decimal
                phase0_data[symbol] = {
                    'price': tier1.get('current_price', df['close'].iloc[-1]),
                    'rs_percentile': 50.0,  # Will calculate below
                    'ret_3m': (tier1.get('ret_3m', 0) or 0) / 100.0,  # Convert % to decimal
                    'ret_6m': (tier1.get('ret_6m', 0) or 0) / 100.0,
                    'ret_12m': (tier1.get('ret_12m', 0) or 0) / 100.0,
                    'ema21': tier1.get('ema21', 0),
                    'ema50': tier1.get('ema50', 0),
                    'ema200': tier1.get('ema200', 0),
                    'adr_pct': tier1.get('adr_pct', 0),
                    'volume_sma': tier1.get('volume_sma', 0),
                    'atr': tier1.get('atr', 0),
                }
            except Exception as e:
                logger.debug(f"Error loading {symbol}: {e}")
                continue

        # Calculate RS percentiles (like screener.py does)
        if rs_scores:
            sorted_scores = sorted(rs_scores, key=lambda x: x['rs'])
            n = len(sorted_scores)
            for i, item in enumerate(sorted_scores):
                percentile = ((i + 1) / n) * 100
                if item['symbol'] in phase0_data:
                    phase0_data[item['symbol']]['rs_percentile'] = min(99.9, percentile)

        logger.info(f"Phase 0 data ready: {len(phase0_data)} symbols with RS percentiles calculated")

        # Calculate market_atr_median for strategies that need it (PullbackEntry)
        logger.info("Calculating market ATR median...")
        all_atrs = []
        for symbol, data in phase0_data.items():
            atr = data.get('atr', 0)
            if atr and atr > 0:
                all_atrs.append(atr)
        market_atr_median = sorted(all_atrs)[len(all_atrs) // 2] if all_atrs else 1.0
        logger.info(f"Market ATR median: {market_atr_median:.2f}")

        # Define all 8 strategies
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

        logger.info("\n" + "=" * 60)
        logger.info("RUNNING ALL 8 STRATEGIES ON ALL STOCKS")
        logger.info("=" * 60)

        all_scored_by_strategy = {}
        grand_total_scored = 0

        for letter, (name, strategy_class) in strategies.items():
            logger.info(f"\n--- Strategy {letter}: {name} ---")

            strategy = strategy_class()
            strategy._spy_df = spy_df
            strategy._current_regime = regime
            strategy.phase0_data = phase0_data  # Share pre-calculated phase0_data

            # Set market_atr_median for strategies that need it
            if hasattr(strategy, 'market_atr_median'):
                strategy.market_atr_median = market_atr_median

            # Count all stocks that were scored (including C tier)
            total_scored = 0
            tier_counts = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
            passed_filter = 0

            for symbol in symbols:
                if symbol not in phase0_data:
                    continue

                try:
                    # Get cached data only (no yfinance calls)
                    df, _ = self.fetcher._get_cached_data(symbol)
                    if df is None or len(df) < 50:
                        continue

                    backtest_dt = pd.Timestamp(self.backtest_date)
                    df = df[df.index <= backtest_dt]
                    if len(df) < 50:
                        continue

                    # Run filter (strategy already has phase0_data)
                    if not strategy.filter(symbol, df):
                        continue

                    passed_filter += 1

                    # Calculate dimensions
                    dimensions = strategy.calculate_dimensions(symbol, df)
                    if not dimensions:
                        continue

                    # Calculate score and tier
                    score, tier = strategy.calculate_score(dimensions, df, symbol)
                    total_scored += 1
                    tier_counts[tier] += 1
                    grand_total_scored += 1

                except Exception:
                    continue

            all_scored_by_strategy[name] = {
                'letter': letter,
                'passed_filter': passed_filter,
                'total_scored': total_scored,
                'S': tier_counts['S'],
                'A': tier_counts['A'],
                'B': tier_counts['B'],
                'C': tier_counts['C'],
            }

            logger.info(f"  {name} ({letter}): {passed_filter} passed filter, {total_scored} scored")
            logger.info(f"  Tiers: S:{tier_counts['S']}, A:{tier_counts['A']}, B:{tier_counts['B']}, C:{tier_counts['C']}")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 60)

        logger.info(f"Date: {self.backtest_date}")
        logger.info(f"Regime: {regime}")
        logger.info(f"Total stocks in database: {len(symbols)}")

        # Aggregate tier totals
        total_S = sum(all_scored_by_strategy[s]['S'] for s in all_scored_by_strategy)
        total_A = sum(all_scored_by_strategy[s]['A'] for s in all_scored_by_strategy)
        total_B = sum(all_scored_by_strategy[s]['B'] for s in all_scored_by_strategy)
        total_C = sum(all_scored_by_strategy[s]['C'] for s in all_scored_by_strategy)
        total_passed_filter = sum(all_scored_by_strategy[s]['passed_filter'] for s in all_scored_by_strategy)

        logger.info(f"\nTotal scored across all strategies: {grand_total_scored}")
        logger.info(f"Total passed filter: {total_passed_filter}")

        logger.info(f"\nAggregate Tier Distribution (all strategies):")
        logger.info(f"  Tier S (12+): {total_S}")
        logger.info(f"  Tier A (9-12): {total_A}")
        logger.info(f"  Tier B (7-9): {total_B}")
        logger.info(f"  Tier C (<7): {total_C}")
        logger.info(f"  Total scored: {total_S + total_A + total_B + total_C}")

        logger.info(f"\nPer-Strategy Breakdown:")
        for name, stats in all_scored_by_strategy.items():
            logger.info(f"  {stats['letter']}. {name}:")
            logger.info(f"    Passed filter: {stats['passed_filter']}, Scored: {stats['total_scored']}")
            logger.info(f"    Tiers: S:{stats['S']}, A:{stats['A']}, B:{stats['B']}, C:{stats['C']}")

        return {
            'date': self.backtest_date,
            'regime': regime,
            'universe_size': len(symbols),
            'total_scored': grand_total_scored,
            'tiers': {
                'S': total_S,
                'A': total_A,
                'B': total_B,
                'C': total_C,
            },
            'by_strategy': all_scored_by_strategy,
        }


def main():
    parser = argparse.ArgumentParser(description='Trade Scanner - Backtest All Strategies on All Stocks')
    parser.add_argument('--date', type=str, required=True, help='Date to backtest (YYYY-MM-DD)')
    args = parser.parse_args()

    runner = AllStocksBacktestRunner(backtest_date=args.date)
    results = runner.run()

    if results:
        print(f"\n{'='*60}")
        print(f"Backtest complete for {results['date']}")
        print(f"Regime: {results['regime']}")
        print(f"Universe: {results['universe_size']} stocks")
        print(f"Total scored: {results['total_scored']}")
        print(f"Tiers: S={results['tiers']['S']}, A={results['tiers']['A']}, B={results['tiers']['B']}, C={results['tiers']['C']}")
        print(f"{'='*60}")
    else:
        print(f"\nBacktest failed for {args.date}")
        sys.exit(1)


if __name__ == '__main__':
    main()
