"""Backtest script - Run workflow for a specific historical date."""
import argparse
import logging
import sys
import gc
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import pandas as pd
import numpy as np

from config.settings import settings
from data.db import Database
from core.premarket_prep import PreMarketPrep
from core.market_analyzer import MarketAnalyzer
from core.screener import StrategyScreener, StrategyMatch
from core.selector import CandidateSelector
from core.ai_confidence_scorer import ScoredCandidate
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator
from core.market_regime import MarketRegimeDetector
from core.notifier import MultiNotifier
from core.fetcher import DataFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure reports directory exists
os.makedirs('reports', exist_ok=True)


class BacktestRunner:
    """Run backtest for a specific historical date."""

    def __init__(self, backtest_date: str):
        """Initialize with specific backtest date.

        Args:
            backtest_date: Date string in YYYY-MM-DD format
        """
        self.backtest_date = backtest_date
        self.db = Database()
        self.fetcher = DataFetcher(db=self.db)
        self.prep = PreMarketPrep(db=self.db)
        self.regime_detector = MarketRegimeDetector()
        self.screener = StrategyScreener()
        self.selector = CandidateSelector()
        self.ai_scorer = OpportunityAnalyzer()
        self.reporter = ReportGenerator()
        self.notifier = MultiNotifier()

    def run(self) -> Optional[str]:
        """Run complete backtest workflow for the specified date.

        Returns:
            Path to generated report or None if failed
        """
        logger.info("=" * 60)
        logger.info(f"BACKTEST: {self.backtest_date}")
        logger.info("=" * 60)

        try:
            # Get symbols from database
            symbols = self.db.get_active_stocks()
            logger.info(f"Active stocks: {len(symbols)}")

            # Filter symbols that have data for the backtest date
            valid_symbols = []
            for symbol in symbols:
                try:
                    df, _ = self.fetcher._get_cached_data(symbol)
                    if df is not None and len(df) > 0:
                        # Check if backtest date exists in data
                        backtest_dt = pd.Timestamp(self.backtest_date)
                        if backtest_dt in df.index:
                            valid_symbols.append(symbol)
                except Exception:
                    continue

            logger.info(f"Symbols with data for {self.backtest_date}: {len(valid_symbols)}")

            if len(valid_symbols) == 0:
                logger.error(f"No data available for {self.backtest_date}")
                return None

            # Run Phase 1: Market Regime Detection
            logger.info("\n" + "=" * 60)
            logger.info("PHASE 1: Market Regime Detection")
            logger.info("=" * 60)

            # Fetch SPY data for the backtest date
            spy_df, _ = self.fetcher._get_cached_data('SPY')
            if spy_df is not None:
                backtest_dt = pd.Timestamp(self.backtest_date)
                spy_df = spy_df[spy_df.index <= backtest_dt]

            vix_df, _ = self.fetcher._get_cached_data('VIXY')
            if vix_df is not None:
                backtest_dt = pd.Timestamp(self.backtest_date)
                vix_df = vix_df[vix_df.index <= backtest_dt]

            if spy_df is None or len(spy_df) < 50:
                logger.error("Insufficient SPY data for regime detection")
                return None

            regime = self.regime_detector.detect_regime(spy_df, vix_df)
            logger.info(f"Detected regime: {regime}")

            # Get allocation for regime
            allocation = self.regime_detector.get_allocation(regime)
            logger.info(f"Strategy allocation: {allocation}")

            # Run Phase 2: Strategy Screening
            logger.info("\n" + "=" * 60)
            logger.info("PHASE 2: Strategy Screening")
            logger.info("=" * 60)

            # Set phase0_data for screener with backtest date context
            from core.stock_universe import StockUniverseManager
            manager = StockUniverseManager(db=self.db)

            # Pre-calculate Tier 1 metrics for valid symbols
            phase0_data = {}
            for symbol in valid_symbols[:500]:  # Limit for backtest speed
                try:
                    df, _ = self.fetcher._get_cached_data(symbol)
                    if df is None or len(df) < 50:
                        continue

                    # Filter data up to backtest date
                    backtest_dt = pd.Timestamp(self.backtest_date)
                    df = df[df.index <= backtest_dt]
                    if len(df) < 50:
                        continue

                    # Calculate basic metrics
                    from core.indicators import TechnicalIndicators
                    ind = TechnicalIndicators(df)
                    ind.calculate_all()

                    # Calculate returns
                    price = df['close'].iloc[-1]
                    price_3m = df['close'].iloc[-min(63, len(df))]
                    price_6m = df['close'].iloc[-min(126, len(df))]
                    price_12m = df['close'].iloc[-min(252, len(df))]

                    returns_3m = (price / price_3m - 1) if price_3m > 0 else 0
                    returns_6m = (price / price_6m - 1) if price_6m > 0 else 0
                    returns_12m = (price / price_12m - 1) if price_12m > 0 else 0

                    # Calculate RS vs SPY
                    if spy_df is not None and len(spy_df) >= 63:
                        spy_price = spy_df['close'].iloc[-1]
                        # Find price 63 days ago in spy_df (relative to backtest date)
                        spy_3m_idx = max(0, len(spy_df) - 63)
                        spy_3m = spy_df['close'].iloc[spy_3m_idx]
                        spy_return = (spy_price / spy_3m - 1) if spy_3m > 0 else 0
                        rs_3m = returns_3m - spy_return
                    else:
                        rs_3m = 0

                    # Get indicators
                    adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
                    ema21 = ind.indicators.get('ema', {}).get('ema21', price)
                    ema50 = ind.indicators.get('ema', {}).get('ema50', price)
                    ema200 = ind.indicators.get('ema', {}).get('ema200', price)
                    atr14 = ind.indicators.get('atr', {}).get('atr14', price * 0.02)
                    volume_sma = ind.indicators.get('volume', {}).get('volume_sma', 0)

                    phase0_data[symbol] = {
                        'price': price,
                        'returns_3m': returns_3m,
                        'returns_6m': returns_6m,
                        'returns_12m': returns_12m,
                        'rs_3m': rs_3m,
                        'adr_pct': adr_pct,
                        'ema21': ema21,
                        'ema50': ema50,
                        'ema200': ema200,
                        'atr14': atr14,
                        'volume_sma': volume_sma,
                        'market_cap': 10e9,  # Placeholder for backtest
                    }
                except Exception as e:
                    continue

            logger.info(f"Phase 0 data prepared: {len(phase0_data)} symbols")

            # Run screening
            all_matches = []
            fail_symbols = []

            from core.strategies.momentum_breakout import MomentumBreakoutStrategy
            from core.strategies.pullback_entry import PullbackEntryStrategy
            from core.strategies.support_bounce import SupportBounceStrategy
            from core.strategies.distribution_top import DistributionTopStrategy
            from core.strategies.accumulation_bottom import AccumulationBottomStrategy
            from core.strategies.capitulation_rebound import CapitulationReboundStrategy
            from core.strategies.earnings_gap import EarningsGapStrategy
            from core.strategies.relative_strength_long import RelativeStrengthLongStrategy

            strategies = {
                'A': MomentumBreakoutStrategy,
                'B': PullbackEntryStrategy,
                'C': SupportBounceStrategy,
                'D': DistributionTopStrategy,
                'E': AccumulationBottomStrategy,
                'F': CapitulationReboundStrategy,
                'G': EarningsGapStrategy,
                'H': RelativeStrengthLongStrategy,
            }

            for strategy_letter, max_slots in allocation.items():
                if max_slots == 0 or strategy_letter == 'TOTAL':
                    continue

                strategy_class = strategies.get(strategy_letter)
                if not strategy_class:
                    continue

                strategy = strategy_class()
                strategy.phase0_data = phase0_data

                # Set SPY data for strategies that need it
                strategy._spy_df = spy_df
                strategy._current_regime = regime

                logger.info(f"\nScreening Strategy {strategy_letter}: {max_slots} slots")

                matches = strategy.screen(list(phase0_data.keys()), max_candidates=max_slots)
                logger.info(f"  Found {len(matches)} matches")
                all_matches.extend(matches)

            logger.info(f"\nTotal matches: {len(all_matches)}")

            if not all_matches:
                logger.warning("No candidates found")
                return None

            # Convert to ScoredCandidate format
            candidates = []
            for match in all_matches:
                candidate = ScoredCandidate(
                    symbol=match.symbol,
                    strategy=match.strategy,
                    entry_price=match.entry_price,
                    stop_loss=match.stop_loss,
                    take_profit=match.take_profit,
                    confidence=match.confidence,
                    reasoning="",
                    key_factors=[],
                    risk_factors=[],
                    match_reasons=match.match_reasons,
                    technical_snapshot=match.technical_snapshot
                )
                candidates.append(candidate)

            # Sort by confidence and take top 30
            candidates.sort(key=lambda x: x.confidence, reverse=True)
            top_30 = candidates[:30]

            logger.info(f"\nTop 30 candidates selected")

            # Phase 3: AI Analysis (simplified for backtest)
            logger.info("\n" + "=" * 60)
            logger.info("PHASE 3: AI Confidence Scoring (Backtest Mode - Skipped)")
            logger.info("=" * 60)

            # Phase 4: Deep Analysis (simplified for backtest)
            logger.info("\n" + "=" * 60)
            logger.info("PHASE 4: Deep Analysis (Backtest Mode - Skipped)")
            logger.info("=" * 60)

            final_candidates = top_30[:10]

            # Phase 5: Report Generation
            logger.info("\n" + "=" * 60)
            logger.info("PHASE 5: Report Generation")
            logger.info("=" * 60)

            # Prepare scan results
            scan_results = []
            for candidate in top_30:
                scan_results.append({
                    'symbol': candidate.symbol,
                    'strategy': candidate.strategy,
                    'entry_price': float(candidate.entry_price),
                    'stop_loss': float(candidate.stop_loss),
                    'take_profit': float(candidate.take_profit),
                    'confidence': int(candidate.confidence),
                    'technical_snapshot': {
                        k: float(v) if isinstance(v, (int, float, np.integer, np.floating)) else v
                        for k, v in candidate.technical_snapshot.items()
                    },
                    'tier': str(candidate.technical_snapshot.get('tier', 'C')),
                    'score': float(candidate.technical_snapshot.get('score', 0)),
                })

            # Generate simple report
            report_filename = f"backtest_{self.backtest_date}.html"
            report_path = f"reports/{report_filename}"

            # Create simple HTML report
            html = self._generate_simple_report(scan_results, regime, final_candidates)

            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html)

            # Save scan results to DB
            self.db.save_scan_result({
                'scan_date': self.backtest_date,
                'scan_time': '09:30:00',
                'market_sentiment': regime,
                'top_opportunities': scan_results[:10],
                'all_candidates': scan_results,
                'total_stocks': len(valid_symbols),
                'success_count': len(valid_symbols),
                'fail_count': 0,
                'fail_symbols': [],
                'report_path': report_path
            })

            logger.info(f"Report generated: {report_path}")

            return report_path

        except Exception as e:
            logger.error(f"Backtest failed: {e}", exc_info=True)
            return None

    def _generate_simple_report(self, scan_results, regime, final_candidates):
        """Generate simple HTML report."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Backtest Report - {self.backtest_date}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .tier-s {{ color: #d32f2f; font-weight: bold; }}
        .tier-a {{ color: #f57c00; font-weight: bold; }}
        .tier-b {{ color: #388e3c; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Backtest Report - {self.backtest_date}</h1>
    <p><strong>Regime:</strong> {regime}</p>
    <p><strong>Total Candidates:</strong> {len(scan_results)}</p>
    <p><strong>Top 10 with Deep Analysis:</strong> {len(final_candidates)}</p>

    <table>
        <tr>
            <th>Rank</th>
            <th>Symbol</th>
            <th>Strategy</th>
            <th>Tier</th>
            <th>Score</th>
            <th>Confidence</th>
            <th>Entry</th>
            <th>Stop Loss</th>
            <th>Target</th>
        </tr>
"""
        for i, r in enumerate(scan_results, 1):
            tier_class = f"tier-{r['tier'].lower()}"
            html += f"""
        <tr>
            <td>{i}</td>
            <td>{r['symbol']}</td>
            <td>{r['strategy']}</td>
            <td class="{tier_class}">{r['tier']}</td>
            <td>{r['score']:.2f}</td>
            <td>{r['confidence']}</td>
            <td>${r['entry_price']:.2f}</td>
            <td>${r['stop_loss']:.2f}</td>
            <td>${r['take_profit']:.2f}</td>
        </tr>
"""

        html += """
    </table>
</body>
</html>
"""
        return html

def main():
    parser = argparse.ArgumentParser(description='Trade Scanner - Backtest')
    parser.add_argument('--date', type=str, required=True, help='Date to backtest (YYYY-MM-DD)')
    args = parser.parse_args()

    runner = BacktestRunner(backtest_date=args.date)
    report_path = runner.run()

    if report_path:
        print(f"\n{'='*60}")
        print(f"Backtest complete: {report_path}")
        print(f"{'='*60}")
    else:
        print(f"\nBacktest failed for {args.date}")
        sys.exit(1)


if __name__ == '__main__':
    main()
