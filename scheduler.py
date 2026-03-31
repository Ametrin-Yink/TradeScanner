"""Memory-optimized scheduler with streaming processing for 2C2G VPS."""
import argparse
import logging
import sys
import gc
from datetime import datetime
from typing import Optional, List, Iterator

from config.settings import settings
from data.db import Database
from core.fetcher import DataFetcher
from core.screener import StrategyScreener, StrategyMatch
from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.ai_confidence_scorer import ScoredCandidate
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MemoryOptimizedScanner:
    """Memory-optimized trade scanner for low-resource VPS."""

    # Keep 150 trading days of history
    MAX_HISTORY_DAYS = 150

    def __init__(self):
        """Initialize scanner components."""
        self.db = Database()
        self.fetcher = DataFetcher(
            db=self.db,
            max_workers=1,  # Reduced to 1 worker for memory
            max_history_days=self.MAX_HISTORY_DAYS  # Keep 150 trading days
        )
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

        if now.weekday() >= 5:
            logger.info(f"Today is {now.strftime('%A')} - not a trading day")
            return False

        return True

    def fetch_symbols_streaming(
        self,
        symbols: List[str],
        batch_size: int = 50
    ) -> Iterator[List[tuple]]:
        """
        Fetch data in batches with incremental updates.

        Yields:
            List of (symbol, DataFrame) tuples for each batch
        """
        total = len(symbols)
        fetched = 0
        cached_count = 0

        for i in range(0, total, batch_size):
            batch = symbols[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total - 1) // batch_size + 1
            logger.info(f"Fetching batch {batch_num}/{total_batches} ({len(batch)} symbols)")

            # Fetch this batch with incremental updates
            batch_data = []
            for symbol in batch:
                # This will use cache and fetch only new data
                df = self.fetcher.fetch_stock_data(
                    symbol,
                    period="7mo",  # Fetch enough to get 150 trading days
                    interval="1d",
                    use_cache=True  # Enable incremental update
                )
                if df is not None and not df.empty:
                    batch_data.append((symbol, df))
                    if len(df) >= self.MAX_HISTORY_DAYS - 5:  # Approximately cached
                        cached_count += 1
                fetched += 1

            logger.info(f"Batch {batch_num}: fetched {len(batch_data)}/{len(batch)} symbols")

            yield batch_data

            # Force garbage collection after each batch
            del batch_data
            gc.collect()

        logger.info(f"Total fetched: {fetched} symbols, ~{cached_count} from cache")

    def screen_symbols_streaming(
        self,
        symbols: List[str]
    ) -> List[StrategyMatch]:
        """
        Screen symbols using streaming to limit memory.

        Args:
            symbols: List of symbols to screen

        Returns:
            List of all candidates found
        """
        all_candidates = []
        batch_size = 50

        for batch_data in self.fetch_symbols_streaming(symbols, batch_size):
            if not batch_data:
                continue

            # Create temporary market_data dict for this batch
            batch_market_data = {sym: df for sym, df in batch_data}

            # Screen this batch
            batch_symbols = list(batch_market_data.keys())
            candidates = self.screener.screen_all(
                symbols=batch_symbols,
                market_data=batch_market_data
            )

            all_candidates.extend(candidates)
            logger.info(f"Batch screening: found {len(candidates)} candidates (total: {len(all_candidates)})")

            # Clear batch data and force GC
            batch_market_data.clear()
            batch_data.clear()
            gc.collect()

        return all_candidates

    def run_scan(
        self,
        symbols: Optional[List[str]] = None,
        skip_market_hours_check: bool = False
    ) -> Optional[str]:
        """
        Run memory-optimized scan pipeline.

        Args:
            symbols: Optional list of symbols
            skip_market_hours_check: Skip trading day check

        Returns:
            Path to generated report or None if failed
        """
        try:
            if not skip_market_hours_check and not self.is_trading_day():
                logger.info("Not a trading day, skipping scan")
                return None

            symbols = symbols or self.db.get_active_stocks()
            if not symbols:
                logger.error("No symbols to scan")
                return None

            logger.info(f"Starting memory-optimized scan of {len(symbols)} symbols")
            logger.info(f"Batch size: 50, Max workers: 1, History: {self.MAX_HISTORY_DAYS} trading days")
            scan_start = datetime.now()

            # Step 1: Market sentiment
            logger.info("Step 1/5: Analyzing market sentiment...")
            sentiment_result = self.market_analyzer.analyze_sentiment()
            market_sentiment = sentiment_result.get('sentiment', 'neutral')
            logger.info(f"Market sentiment: {market_sentiment}")

            # Step 2: Screen symbols (streaming with incremental data)
            logger.info(f"Step 2/5: Screening symbols with 8 strategies (incremental update)...")
            logger.info(f"Target: {len(symbols)} symbols, keeping {self.MAX_HISTORY_DAYS} trading days of history")
            candidates = self.screen_symbols_streaming(symbols)
            logger.info(f"Found {len(candidates)} total candidates")

            if not candidates:
                logger.warning("No candidates found")
                return None

            # Step 3: Select and score top 10
            logger.info("Step 3/5: AI scoring and selecting top 10...")
            top_10_scored = self.selector.select_top_10(candidates, market_sentiment)
            logger.info(f"Selected {len(top_10_scored)} opportunities")

            if top_10_scored:
                confidences = [c.confidence for c in top_10_scored]
                logger.info(f"Confidence: {min(confidences)}-{max(confidences)}%, avg: {sum(confidences)/len(confidences):.1f}%")

            # Step 4: Deep analysis (one by one to save memory)
            logger.info("Step 4/5: Running deep AI analysis...")
            analyzed = []
            for i, match in enumerate(top_10_scored):
                try:
                    logger.info(f"Analyzing {match.symbol} ({i+1}/{len(top_10_scored)})...")
                    analysis = self.opportunity_analyzer.analyze_opportunity(match, market_sentiment)
                    analyzed.append(analysis)
                    gc.collect()  # Clean up after each analysis
                except Exception as e:
                    logger.error(f"Failed to analyze {match.symbol}: {e}")
                    # Create basic analysis
                    from core.analyzer import AnalyzedOpportunity
                    analyzed.append(AnalyzedOpportunity(
                        symbol=match.symbol,
                        strategy=match.strategy,
                        entry_price=match.entry_price,
                        stop_loss=match.stop_loss,
                        take_profit=match.take_profit,
                        confidence=match.confidence,
                        match_reasons=match.match_reasons
                    ))

            logger.info(f"Analyzed {len(analyzed)} opportunities")

            # Step 5: Generate report
            logger.info("Step 5/5: Generating report...")
            report_path = self.reporter.generate_report(
                opportunities=analyzed,
                all_candidates=candidates,
                market_sentiment=market_sentiment,
                total_stocks=len(symbols),
                success_count=len(symbols),  # Simplified
                fail_count=0,
                fail_symbols=[],
                sentiment_result=sentiment_result
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
                    'confidence': o.confidence
                } for o in candidates],
                'total_stocks': len(symbols),
                'success_count': len(symbols),
                'fail_count': 0,
                'fail_symbols': [],
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
    parser = argparse.ArgumentParser(description='Trade Scanner (Memory Optimized)')
    parser.add_argument('--test', action='store_true', help='Run test scan')
    parser.add_argument('--symbols', type=str, help='Comma-separated symbols for test')
    parser.add_argument('--force', action='store_true', help='Skip trading day check')
    parser.add_argument('--server', action='store_true', help='Start API server')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    scanner = MemoryOptimizedScanner()

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
