"""Debug script with detailed filter rejection reasons."""
import argparse
import logging
from collections import defaultdict
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


def debug_momentum_filter(symbol: str, df: pd.DataFrame, phase0_data: Dict) -> List[str]:
    """Debug MomentumBreakout filter step by step."""
    reasons = []

    # Check RS percentile
    rs_pct = phase0_data.get(symbol, {}).get('rs_percentile', 0)
    if rs_pct < 50:
        reasons.append(f"RS% {rs_pct:.1f} < 50 (TC gate)")
        return reasons

    # Check data length
    if len(df) < 60:
        reasons.append(f"Data length {len(df)} < 60")
        return reasons

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Check EMA200
    ema200 = ind.indicators.get('ema', {}).get('ema200')
    if ema200 is None:
        reasons.append("EMA200 is None")
        return reasons
    if current_price <= ema200:
        reasons.append(f"Price {current_price:.2f} <= EMA200 {ema200:.2f}")
        return reasons

    # Check 3m return
    ret_3m = phase0_data.get(symbol, {}).get('ret_3m')
    if ret_3m is None:
        if len(df) >= 63:
            price_3m = df['close'].iloc[-63]
            ret_3m = (current_price - price_3m) / price_3m if price_3m > 0 else 0
        else:
            ret_3m = 0
    if ret_3m < -0.20:
        reasons.append(f"3m return {ret_3m:.2%} < -20%")
        return reasons

    # Check volume
    avg_volume_20d = df['volume'].tail(20).mean()
    if avg_volume_20d < 100_000:
        reasons.append(f"Avg volume {avg_volume_20d:.0f} < 100K")
        return reasons

    # Check VCP platform
    platform = ind.detect_vcp_platform()
    if platform is None or not platform.get('is_valid'):
        reasons.append("No valid VCP platform")
        return reasons

    # Check breakout
    platform_high = platform['platform_high']
    breakout_pct = (current_price - platform_high) / platform_high
    if breakout_pct < 0.02:
        reasons.append(f"Breakout {breakout_pct:.3f} < 2%")
        return reasons

    # Check CLV
    clv = ind.calculate_clv()
    if clv < 0.75:
        reasons.append(f"CLV {clv:.3f} < 0.75")
        return reasons

    # Check volume ratio
    current_volume = df['volume'].iloc[-1]
    volume_sma20 = df['volume'].tail(20).mean()
    volume_ratio = current_volume / volume_sma20 if volume_sma20 > 0 else 0
    if volume_ratio < 2.0:
        reasons.append(f"Volume ratio {volume_ratio:.2f}x < 2.0x")
        return reasons

    reasons.append("ALL PASSED")
    return reasons


def debug_pullback_filter(symbol: str, df: pd.DataFrame, phase0_data: Dict) -> List[str]:
    """Debug PullbackEntry filter step by step."""
    reasons = []

    data = phase0_data.get(symbol, {})

    # Check RS percentile
    rs_pct = data.get('rs_percentile', 0)
    if rs_pct < 70:
        reasons.append(f"RS% {rs_pct:.1f} < 70 (TC gate)")
        return reasons

    # Check data length
    if len(df) < 200:
        reasons.append(f"Data length {len(df)} < 200")
        return reasons

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Check price > EMA200
    ema200 = ind.indicators.get('ema', {}).get('ema200')
    if ema200 is None:
        reasons.append("EMA200 is None")
        return reasons
    if current_price <= ema200:
        reasons.append(f"Price {current_price:.2f} <= EMA200 {ema200:.2f}")
        return reasons

    # Check price > EMA21
    ema21 = ind.indicators.get('ema', {}).get('ema21')
    if ema21 is None:
        reasons.append("EMA21 is None")
        return reasons

    # Check pullback - price should be below EMA21 but above EMA200
    if current_price > ema21:
        reasons.append(f"Price {current_price:.2f} > EMA21 {ema21:.2f} (not in pullback)")
        return reasons

    # Check 3m return
    ret_3m = data.get('ret_3m', 0)
    if ret_3m < -0.30:
        reasons.append(f"3m return {ret_3m:.2%} < -30%")
        return reasons

    # Check volume
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume < 100_000:
        reasons.append(f"Avg volume {avg_volume:.0f} < 100K")
        return reasons

    reasons.append("ALL PASSED")
    return reasons


def debug_support_bounce_filter(symbol: str, df: pd.DataFrame, phase0_data: Dict) -> List[str]:
    """Debug SupportBounce filter step by step."""
    reasons = []

    data = phase0_data.get(symbol, {})

    # Check RS percentile
    rs_pct = data.get('rs_percentile', 0)
    if rs_pct < 50:
        reasons.append(f"RS% {rs_pct:.1f} < 50")
        return reasons

    # Check data length
    if len(df) < 100:
        reasons.append(f"Data length {len(df)} < 100")
        return reasons

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Check EMA200
    ema200 = ind.indicators.get('ema', {}).get('ema200')
    if ema200 is not None and current_price < ema200:
        reasons.append(f"Price {current_price:.2f} < EMA200 {ema200:.2f}")
        return reasons

    # Check for false breakdown (price went below EMA50 then reclaimed)
    ema50 = ind.indicators.get('ema', {}).get('ema50')
    if ema50 is None:
        reasons.append("EMA50 is None")
        return reasons

    # Check volume
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume < 100_000:
        reasons.append(f"Avg volume {avg_volume:.0f} < 100K")
        return reasons

    reasons.append("ALL PASSED")
    return reasons


def debug_distribution_filter(symbol: str, df: pd.DataFrame, phase0_data: Dict) -> List[str]:
    """Debug DistributionTop filter step by step."""
    reasons = []

    data = phase0_data.get(symbol, {})

    # Check RS percentile
    rs_pct = data.get('rs_percentile', 0)
    if rs_pct < 50:
        reasons.append(f"RS% {rs_pct:.1f} < 50")
        return reasons

    # Check data length
    if len(df) < 100:
        reasons.append(f"Data length {len(df)} < 100")
        return reasons

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Check ADR
    adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
    if adr_pct < 0.03:
        reasons.append(f"ADR% {adr_pct:.2%} < 3%")
        return reasons

    # Check volume
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume < 100_000:
        reasons.append(f"Avg volume {avg_volume:.0f} < 100K")
        return reasons

    reasons.append("ALL PASSED")
    return reasons


def debug_capitulation_filter(symbol: str, df: pd.DataFrame, phase0_data: Dict) -> List[str]:
    """Debug CapitulationRebound filter step by step."""
    reasons = []

    data = phase0_data.get(symbol, {})

    # Check data length
    if len(df) < 60:
        reasons.append(f"Data length {len(df)} < 60")
        return reasons

    ind = TechnicalIndicators(df)
    ind.calculate_all()

    current_price = df['close'].iloc[-1]

    # Check ADR
    adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
    if adr_pct < 0.02:
        reasons.append(f"ADR% {adr_pct:.2%} < 2%")
        return reasons

    # Check volume
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume < 100_000:
        reasons.append(f"Avg volume {avg_volume:.0f} < 100K")
        return reasons

    # Check for capitulation - large decline
    ret_3m = data.get('ret_3m', 0)
    if ret_3m is not None and ret_3m > -0.15:
        reasons.append(f"3m return {ret_3m:.2%} > -15% (not capitulation)")
        return reasons

    reasons.append("ALL PASSED")
    return reasons


class DetailedDebugRunner:
    """Run detailed debug on specific symbols."""

    def __init__(self, backtest_date: str, symbols: List[str]):
        self.backtest_date = backtest_date
        self.db = Database()
        self.fetcher = DataFetcher(db=self.db)
        self.symbols = symbols

    def run(self):
        """Run detailed debug."""
        print(f"\nDetailed Debug for {len(self.symbols)} symbols\n")

        # Get SPY/VIX data
        spy_df, _ = self.fetcher._get_cached_data('SPY')
        backtest_dt = pd.Timestamp(self.backtest_date)
        if spy_df is not None:
            spy_df = spy_df[spy_df.index <= backtest_dt]

        vix_df, _ = self.fetcher._get_cached_data('VIXY')
        if vix_df is not None:
            vix_df = vix_df[vix_df.index <= backtest_dt]

        detector = MarketRegimeDetector()
        regime = detector.detect_regime(spy_df, vix_df) if spy_df is not None else 'neutral'
        print(f"Regime: {regime}\n")

        # Get phase0_data (tier1 cache)
        phase0_data = {}
        for symbol in self.symbols:
            try:
                tier1 = self.db.get_tier1_cache(symbol)
                if tier1:
                    phase0_data[symbol] = {
                        'rs_percentile': tier1.get('rs_percentile', 50),
                        'ret_3m': tier1.get('ret_3m', 0),
                    }
            except Exception:
                pass

        # Test each symbol with each strategy
        debug_functions = {
            'A': ('MomentumBreakout', debug_momentum_filter),
            'B': ('PullbackEntry', debug_pullback_filter),
            'C': ('SupportBounce', debug_support_bounce_filter),
            'D': ('DistributionTop', debug_distribution_filter),
            'F': ('CapitulationRebound', debug_capitulation_filter),
        }

        for symbol in self.symbols[:10]:  # First 10 symbols
            try:
                df, _ = self.fetcher._get_cached_data(symbol)
                if df is None:
                    print(f"\n{symbol}: No data")
                    continue

                df = df[df.index <= backtest_dt]
                if len(df) < 50:
                    print(f"\n{symbol}: Insufficient data ({len(df)})")
                    continue

                print(f"\n{'='*60}")
                print(f"Symbol: {symbol}")
                rs_pct = phase0_data.get(symbol, {}).get('rs_percentile', 'N/A')
                ret_3m = phase0_data.get(symbol, {}).get('ret_3m', 'N/A')
                print(f"  RS%: {rs_pct}, 3m return: {ret_3m}, Length: {len(df)}")
                print(f"{'='*60}")

                for letter, (name, debug_fn) in debug_functions.items():
                    reasons = debug_fn(symbol, df, phase0_data)
                    status = "PASS" if reasons == ["ALL PASSED"] else "FAIL"
                    print(f"  {letter}. {name}: {status}")
                    if reasons != ["ALL PASSED"]:
                        for r in reasons:
                            print(f"      -> {r}")
            except Exception as e:
                print(f"\n{symbol}: ERROR - {e}")


def main():
    parser = argparse.ArgumentParser(description='Detailed strategy debug')
    parser.add_argument('--date', type=str, required=True, help='Date (YYYY-MM-DD)')
    args = parser.parse_args()

    db = Database()
    symbols = db.get_active_stocks()[:50]  # Test first 50

    runner = DetailedDebugRunner(backtest_date=args.date, symbols=symbols)
    runner.run()


if __name__ == '__main__':
    main()
