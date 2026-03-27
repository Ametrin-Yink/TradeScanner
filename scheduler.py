"""Scheduler - main entry point for daily scans."""
import argparse
import logging
import sys
from datetime import datetime
from typing import Optional, List

from config.settings import settings
from data.db import Database
from core.fetcher import DataFetcher
from core.screener import StrategyScreener
from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TradeScanner:
    """Main trade scanner orchestrator."""

    def __init__(self):
        """Initialize scanner components."""
        self.db = Database()
        self.fetcher = DataFetcher(db=self.db)
        self.screener = StrategyScreener(fetcher=self.fetcher, db=self.db)
        self.market_analyzer = MarketAnalyzer()
        self.selector = CandidateSelector()
        self.opportunity_analyzer = OpportunityAnalyzer(fetcher=self.fetcher)
        self.reporter = ReportGenerator(fetcher=self.fetcher)

    def is_trading_day(self) -> bool:
        """Check if today is a US trading day."""
        from datetime import datetime
        import pytz

        ny_tz = pytz.timezone('America/New_York')
        now = datetime.now(ny_tz)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday or Sunday
            logger.info(f"Today is {now.strftime('%A')} - not a trading day")
            return False

        # TODO: Check for holidays
        # For now, assume Monday-Friday are trading days

        return True

    def run_scan(
        self,
        symbols: Optional[List[str]] = None,
        skip_market_hours_check: bool = False
    ) -> Optional[str]:
        """
        Run full scan pipeline.

        Args:
            symbols: Optional list of symbols (uses active stocks if None)
            skip_market_hours_check: Skip trading day check

        Returns:
            Path to generated report or None if failed
        """
        try:
            # Check trading day
            if not skip_market_hours_check and not self.is_trading_day():
                logger.info("Not a trading day, skipping scan")
                return None

            # Get symbols to scan
            if not symbols:
                symbols = self.db.get_active_stocks()

            if not symbols:
                logger.error("No symbols to scan")
                return None

            logger.info(f"Starting scan of {len(symbols)} symbols")
            scan_start = datetime.now()

            # Step 1: Market sentiment analysis
            logger.info("Step 1/5: Analyzing market sentiment...")
            sentiment_result = self.market_analyzer.analyze_sentiment()
            market_sentiment = sentiment_result.get('sentiment', 'neutral')
            logger.info(f"Market sentiment: {market_sentiment}")

            # Step 2: Screen all symbols
            logger.info("Step 2/5: Screening symbols with 8 strategies...")
            # Pre-fetch data for efficiency
            logger.info("Fetching market data...")
            market_data = self.fetcher.download_batch(symbols, period="6mo", interval="1d")

            if not market_data:
                logger.error("Failed to fetch any market data")
                return None

            logger.info(f"Fetched data for {len(market_data)} symbols")

            # Screen using cached data
            candidates = self.screener.screen_all(
                symbols=list(market_data.keys()),
                market_data=market_data
            )

            logger.info(f"Found {len(candidates)} total candidates")

            if not candidates:
                logger.warning("No candidates found")
                return None

            # Step 3: Select top 10
            logger.info("Step 3/5: Selecting top 10 opportunities...")
            top_10 = self.selector.select_top_10(candidates, market_sentiment)
            logger.info(f"Selected {len(top_10)} top opportunities")

            # Step 4: Deep analysis
            logger.info("Step 4/5: Running deep AI analysis...")
            analyzed = self.opportunity_analyzer.analyze_all(top_10, market_sentiment)
            logger.info(f"Analyzed {len(analyzed)} opportunities")

            # Step 5: Generate report
            logger.info("Step 5/5: Generating report...")
            fail_symbols = [s for s in symbols if s not in market_data]
            report_path = self.reporter.generate_report(
                opportunities=analyzed,
                market_sentiment=market_sentiment,
                total_stocks=len(symbols),
                success_count=len(market_data),
                fail_count=len(fail_symbols),
                fail_symbols=fail_symbols
            )

            # Save scan result
            scan_result = {
                'scan_date': scan_start.strftime('%Y-%m-%d'),
                'scan_time': scan_start.strftime('%H:%M:%S'),
                'market_sentiment': market_sentiment,
                'top_opportunities': [{
                    'symbol': o.symbol,
                    'strategy': o.strategy,
                    'entry_price': o.entry_price,
                    'stop_loss': o.stop_loss,
                    'take_profit': o.take_profit,
                    'confidence': o.confidence
                } for o in analyzed],
                'all_candidates': [{
                    'symbol': o.symbol,
                    'strategy': o.strategy,
                    'entry_price': o.entry_price,
                    'stop_loss': o.stop_loss,
                    'take_profit': o.take_profit,
                    'confidence': o.confidence
                } for o in candidates],
                'total_stocks': len(symbols),
                'success_count': len(market_data),
                'fail_count': len(fail_symbols),
                'fail_symbols': fail_symbols,
                'report_path': report_path
            }
            self.db.save_scan_result(scan_result)

            scan_duration = (datetime.now() - scan_start).total_seconds()
            logger.info(f"Scan complete in {scan_duration:.1f}s")
            logger.info(f"Report: {report_path}")

            return report_path

        except Exception as e:
            logger.error(f"Scan failed: {e}", exc_info=True)
            return None

    def run_test_scan(self, test_symbols: List[str]) -> Optional[str]:
        """Run test scan with limited symbols."""
        logger.info(f"Running test scan with {len(test_symbols)} symbols")
        return self.run_scan(symbols=test_symbols, skip_market_hours_check=True)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trade Scanner')
    parser.add_argument('--test', action='store_true', help='Run test scan')
    parser.add_argument('--symbols', type=str, help='Comma-separated symbols for test')
    parser.add_argument('--force', action='store_true', help='Skip trading day check')
    parser.add_argument('--server', action='store_true', help='Start API server')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    scanner = TradeScanner()

    if args.test:
        symbols = args.symbols.split(',') if args.symbols else ['AAPL', 'MSFT', 'NVDA']
        report_path = scanner.run_test_scan(symbols)
    else:
        report_path = scanner.run_scan(skip_market_hours_check=args.force)

    if report_path:
        print(f"\n✅ Scan complete!")
        print(f"📄 Report: {report_path}")
    else:
        print("\n❌ Scan failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
