"""Debug script to understand why strategies have 0 matches."""
import argparse
import logging
from collections import defaultdict
from typing import Dict

import pandas as pd

from data.db import Database
from core.fetcher import DataFetcher
from core.market_regime import MarketRegimeDetector

from core.strategies.momentum_breakout import MomentumBreakoutStrategy
from core.strategies.pullback_entry import PullbackEntryStrategy
from core.strategies.support_bounce import SupportBounceStrategy
from core.strategies.distribution_top import DistributionTopStrategy
from core.strategies.accumulation_bottom import AccumulationBottomStrategy
from core.strategies.capitulation_rebound import CapitulationReboundStrategy
from core.strategies.earnings_gap import EarningsGapStrategy
from core.strategies.relative_strength_long import RelativeStrengthLongStrategy

logging.basicConfig(level=logging.WARNING)  # Suppress normal logging


class StrategyDebugRunner:
    """Debug why strategies reject stocks."""

    def __init__(self, backtest_date: str, max_symbols: int = 20):
        self.backtest_date = backtest_date
        self.db = Database()
        self.fetcher = DataFetcher(db=self.db)
        self.max_symbols = max_symbols

    def debug_strategy(self, strategy, symbol: str, df: pd.DataFrame) -> Dict:
        """Debug a single symbol through a strategy."""
        result = {
            'symbol': symbol,
            'data_len': len(df),
            'filter_passed': False,
            'filter_reasons': [],
            'dimensions_calculated': False,
            'score': None,
            'tier': None,
        }

        # Check data requirements
        if len(df) < 50:
            result['filter_reasons'].append(f'Insufficient data: {len(df)} < 50')
            return result

        # Try filter
        try:
            filter_result = strategy.filter(symbol, df)
            result['filter_passed'] = filter_result
            if not filter_result:
                result['filter_reasons'].append('Filter returned False (check strategy logs)')
                return result
        except Exception as e:
            result['filter_reasons'].append(f'Filter exception: {e}')
            return result

        # Try dimensions
        try:
            dimensions = strategy.calculate_dimensions(symbol, df)
            if not dimensions:
                result['filter_reasons'].append('No dimensions calculated')
                return result
            result['dimensions_calculated'] = True
        except Exception as e:
            result['filter_reasons'].append(f'Dimensions exception: {e}')
            return result

        # Calculate score
        try:
            score, tier = strategy.calculate_score(dimensions, df, symbol)
            result['score'] = score
            result['tier'] = tier
        except Exception as e:
            result['filter_reasons'].append(f'Score exception: {e}')

        return result

    def run(self):
        """Run debug analysis."""
        symbols = self.db.get_active_stocks()[:self.max_symbols]
        print(f"\nDebugging {len(symbols)} symbols per strategy\n")

        # Get SPY data for regime detection
        spy_df, _ = self.fetcher._get_cached_data('SPY')
        if spy_df is not None:
            backtest_dt = pd.Timestamp(self.backtest_date)
            spy_df = spy_df[spy_df.index <= backtest_dt]

        vix_df, _ = self.fetcher._get_cached_data('VIXY')
        if vix_df is not None:
            backtest_dt = pd.Timestamp(self.backtest_date)
            vix_df = vix_df[vix_df.index <= backtest_dt]

        detector = MarketRegimeDetector()
        regime = detector.detect_regime(spy_df, vix_df) if spy_df is not None else 'neutral'
        print(f"Regime: {regime}\n")

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

        for letter, (name, strategy_class) in strategies.items():
            print(f"\n{'='*60}")
            print(f"Strategy {letter}: {name}")
            print(f"{'='*60}")

            strategy = strategy_class()
            strategy._spy_df = spy_df
            strategy._current_regime = regime

            # Enable debug logging for this strategy
            strategy_logger = logging.getLogger(f'core.strategies.{name.lower()}')
            strategy_logger.setLevel(logging.DEBUG)

            # Track rejection reasons
            rejection_reasons = defaultdict(int)
            filter_passed = 0
            dimensions_ok = 0
            scored = {'S': 0, 'A': 0, 'B': 0, 'C': 0}

            for symbol in symbols:
                try:
                    df, _ = self.fetcher._get_cached_data(symbol)
                    if df is None or len(df) < 50:
                        rejection_reasons['no_data'] += 1
                        continue

                    backtest_dt = pd.Timestamp(self.backtest_date)
                    df = df[df.index <= backtest_dt]
                    if len(df) < 50:
                        rejection_reasons['insufficient_data'] += 1
                        continue

                    # Load tier1 cache if available
                    phase0_data = {}
                    try:
                        tier1 = self.db.get_tier1_cache(symbol)
                        if tier1:
                            phase0_data[symbol] = {
                                'price': tier1.get('current_price', df['close'].iloc[-1]),
                                'rs_percentile': tier1.get('rs_percentile', 50),
                                'ret_3m': tier1.get('ret_3m', 0),
                                'ema21': tier1.get('ema21', 0),
                                'adr_pct': tier1.get('adr_pct', 0),
                                'volume_sma': tier1.get('volume_sma', 0),
                            }
                            strategy.phase0_data = phase0_data
                    except Exception:
                        pass

                    # Debug this symbol
                    result = self.debug_strategy(strategy, symbol, df)

                    if not result['filter_passed']:
                        for reason in result['filter_reasons']:
                            if 'Filter returned False' in reason:
                                rejection_reasons['filter_false'] += 1
                            else:
                                rejection_reasons[reason] += 1
                    else:
                        filter_passed += 1
                        if result['dimensions_calculated']:
                            dimensions_ok += 1
                            if result['tier']:
                                scored[result['tier']] += 1

                except Exception as e:
                    rejection_reasons[f'exception_{str(e)[:50]}'] += 1

            # Print summary
            print(f"\nTested: {len(symbols)} symbols")
            print(f"\nRejection reasons:")
            for reason, count in sorted(rejection_reasons.items(), key=lambda x: -x[1]):
                print(f"  {reason}: {count}")

            print(f"\nResults:")
            print(f"  Filter passed: {filter_passed}")
            print(f"  Dimensions OK: {dimensions_ok}")
            print(f"  Scored: S={scored['S']}, A={scored['A']}, B={scored['B']}, C={scored['C']}")

            # Show some examples of rejected symbols
            print("\nSample debug (first 3 symbols):")
            for i, symbol in enumerate(symbols[:3]):
                try:
                    df, _ = self.fetcher._get_cached_data(symbol)
                    if df is None:
                        print(f"  {symbol}: No data")
                        continue
                    df = df[df.index <= pd.Timestamp(self.backtest_date)]
                    if len(df) < 50:
                        print(f"  {symbol}: Insufficient data after filter")
                        continue

                    # Get tier1 cache
                    try:
                        tier1 = self.db.get_tier1_cache(symbol)
                        rs_pct = tier1.get('rs_percentile', 'N/A') if tier1 else 'No cache'
                        print(f"  {symbol}: RS%={rs_pct}, len(df)={len(df)}", end='')
                    except:
                        print(f"  {symbol}: No tier1 cache", end='')

                    # Try filter
                    strategy.phase0_data = {}
                    try:
                        passed = strategy.filter(symbol, df)
                        print(f" -> Filter={'PASS' if passed else 'FAIL'}")
                    except Exception as e:
                        print(f" -> Filter ERROR: {e}")
                except Exception as e:
                    print(f"  {symbol}: ERROR {e}")


def main():
    parser = argparse.ArgumentParser(description='Debug strategies')
    parser.add_argument('--date', type=str, required=True, help='Date to debug (YYYY-MM-DD)')
    parser.add_argument('--symbols', type=int, default=20, help='Max symbols to test')
    args = parser.parse_args()

    runner = StrategyDebugRunner(backtest_date=args.date, max_symbols=args.symbols)
    runner.run()


if __name__ == '__main__':
    main()
