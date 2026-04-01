"""Complete 5-phase workflow scheduler for 6 AM automated execution."""
import argparse
import logging
import sys
import gc
from datetime import datetime
from typing import Optional, List, Dict

from config.settings import settings
from data.db import Database
from core.premarket_prep import PreMarketPrep
from core.market_analyzer import MarketAnalyzer
from core.screener import StrategyScreener, StrategyMatch
from core.selector import CandidateSelector
from core.ai_confidence_scorer import ScoredCandidate
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator
from core.notifier import MultiNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompleteScanner:
    """Complete 5-phase workflow scanner for daily 6 AM execution.

    Phase 0: Data Preparation (15-20 min)
        - Fetch universe from Finviz
        - Sync with database
        - Fetch Tier 3 market data
        - Calculate Tier 1 universal metrics

    Phase 1: Market Sentiment (2-3 min)
        - Analyze market sentiment using Tavily + DashScope

    Phase 2: Strategy Screening (10-15 min)
        - Screen all symbols using pre-calculated Tier 1/3 data
        - Lazy Tier 2 calculations for candidates only

    Phase 3: AI Analysis (15-20 min)
        - Deep analysis of top 10 candidates

    Phase 4: Report Generation (2-3 min)
        - Generate HTML report

    Phase 5: Push Notifications (1 min)
        - Send notifications to WeChat and Discord
    """

    def __init__(self):
        """Initialize scanner components."""
        self.db = Database()
        self.prep = PreMarketPrep(db=self.db)
        self.market_analyzer = MarketAnalyzer()
        self.screener = StrategyScreener(db=self.db)
        self.selector = CandidateSelector()
        self.opportunity_analyzer = OpportunityAnalyzer()
        self.reporter = ReportGenerator()
        self.notifier = MultiNotifier(
            discord_webhook=getattr(settings, 'DISCORD_WEBHOOK', None),
            wechat_webhook=getattr(settings, 'WECHAT_WEBHOOK', None)
        )

        # Phase timing tracking
        self._phase_times: Dict[str, int] = {}

    def is_trading_day(self) -> bool:
        """Check if today is a US trading day."""
        import pytz
        ny_tz = pytz.timezone('America/New_York')
        now = datetime.now(ny_tz)

        if now.weekday() >= 5:
            logger.info(f"Today is {now.strftime('%A')} - not a trading day")
            return False

        return True

    def run_complete_workflow(
        self,
        symbols: Optional[List[str]] = None,
        skip_market_hours_check: bool = False
    ) -> Optional[str]:
        """
        Run complete 5-phase workflow.

        Args:
            symbols: Optional list of symbols (uses universe sync if None)
            skip_market_hours_check: Skip trading day check

        Returns:
            Path to generated report or None if failed
        """
        workflow_start = datetime.now()
        run_date = workflow_start.strftime('%Y-%m-%d')

        # Initialize workflow status
        self.db.save_workflow_status({
            'run_date': run_date,
            'start_time': workflow_start.strftime('%H:%M:%S'),
            'status': 'running'
        })

        try:
            if not skip_market_hours_check and not self.is_trading_day():
                logger.info("Not a trading day, skipping workflow")
                self._update_workflow_status(run_date, status='skipped')
                return None

            logger.info("=" * 60)
            logger.info("STARTING COMPLETE 5-PHASE WORKFLOW")
            logger.info("=" * 60)

            # Phase 0: Data Preparation
            phase0_result = self._phase0_data_prep(symbols)
            if not phase0_result['success']:
                logger.error("Phase 0 failed, aborting workflow")
                self._update_workflow_status(
                    run_date,
                    status='failed',
                    error_message='Phase 0 failed'
                )
                return None

            symbols = phase0_result['symbols']

            # Phase 1: Market Sentiment
            sentiment = self._phase1_market_sentiment()

            # Phase 2: Strategy Screening
            phase2_result = self._phase2_screening(symbols)
            candidates = phase2_result['candidates']
            fail_symbols = phase2_result['fail_symbols']

            if not candidates:
                logger.warning("No candidates found, generating empty report")
                report_path = self._phase4_report(
                    [], candidates, sentiment, symbols, fail_symbols
                )
                self._phase5_notify(report_path, sentiment, [])
                self._update_workflow_status(
                    run_date,
                    status='completed',
                    report_path=report_path
                )
                return report_path

            # Phase 3: AI Analysis
            analyzed = self._phase3_ai_analysis(candidates, sentiment)

            # Phase 4: Report Generation
            report_path = self._phase4_report(
                analyzed, candidates, sentiment, symbols, fail_symbols
            )

            # Phase 5: Push Notifications
            self._phase5_notify(report_path, sentiment, analyzed)

            # Finalize workflow status
            total_duration = (datetime.now() - workflow_start).total_seconds()
            self._update_workflow_status(
                run_date,
                status='completed',
                report_path=report_path,
                candidates_count=len(analyzed)
            )

            logger.info("=" * 60)
            logger.info(f"WORKFLOW COMPLETE in {total_duration:.0f}s")
            logger.info("=" * 60)

            return report_path

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            self._update_workflow_status(
                run_date,
                status='failed',
                error_message=str(e)
            )
            return None

    def _phase0_data_prep(self, symbols: Optional[List[str]]) -> Dict:
        """Phase 0: Data Preparation.

        Args:
            symbols: Optional pre-defined symbols list

        Returns:
            Phase result dict
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 0: Data Preparation")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # If symbols provided (test mode), skip universe sync
        if symbols is not None:
            logger.info(f"Using provided symbols: {len(symbols)}")
            # Still fetch Tier 3 data
            tier3_data = self.prep._fetch_tier3_data()
            logger.info(f"Tier 3 data fetched: {len(tier3_data)} symbols")
            # Calculate Tier 1 for provided symbols
            tier1_count = self.prep._calculate_tier1_cache(symbols)
            logger.info(f"Tier 1 cache calculated: {tier1_count} symbols")

            duration = (datetime.now() - phase_start).total_seconds()
            self._phase_times['phase0'] = int(duration)

            return {
                'success': True,
                'symbols': symbols,
                'duration': int(duration)
            }

        # Full Phase 0 with universe sync
        result = self.prep.run_phase0()
        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase0'] = int(duration)

        logger.info(f"Phase 0 complete in {duration:.1f}s")

        return result

    def _phase1_market_sentiment(self) -> str:
        """Phase 1: Market Sentiment Analysis.

        Returns:
            Market sentiment string
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 1: Market Sentiment Analysis")
        logger.info("=" * 60)

        phase_start = datetime.now()

        try:
            sentiment_result = self.market_analyzer.analyze_sentiment()
            sentiment = sentiment_result.get('sentiment', 'neutral')
            logger.info(f"Market sentiment: {sentiment.upper()}")
        except Exception as e:
            logger.error(f"Market sentiment analysis failed: {e}")
            sentiment = 'neutral'

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase1'] = int(duration)
        logger.info(f"Phase 1 complete in {duration:.1f}s")

        return sentiment

    def _phase2_screening(self, symbols: List[str]) -> Dict:
        """Phase 2: Strategy Screening.

        Args:
            symbols: List of symbols to screen

        Returns:
            Dict with candidates and fail_symbols
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Strategy Screening")
        logger.info("=" * 60)

        phase_start = datetime.now()

        logger.info(f"Screening {len(symbols)} symbols with 6 strategies")

        # Screen all symbols using pre-calculated Tier 1 data
        # The screener will use cached Tier 1/Tier 3 data
        candidates = self.screener.screen_all(symbols=symbols)

        # For now, we don't track individual failures in the new flow
        # Could be enhanced later
        fail_symbols = []

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase2'] = int(duration)

        logger.info(f"Found {len(candidates)} candidates")
        logger.info(f"Phase 2 complete in {duration:.1f}s")

        return {
            'candidates': candidates,
            'fail_symbols': fail_symbols
        }

    def _phase3_ai_analysis(
        self,
        candidates: List,
        sentiment: str
    ) -> List:
        """Phase 3: AI Analysis of top candidates.

        Args:
            candidates: List of strategy matches
            sentiment: Market sentiment

        Returns:
            List of analyzed opportunities
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3: AI Analysis")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # Select top 10
        top_10 = self.selector.select_top_10(candidates, sentiment)
        logger.info(f"Selected {len(top_10)} opportunities for deep analysis")

        # Analyze each one
        analyzed = []
        for i, match in enumerate(top_10):
            try:
                logger.info(f"Analyzing {match.symbol} ({i+1}/{len(top_10)})...")
                analysis = self.opportunity_analyzer.analyze_opportunity(match, sentiment)
                analyzed.append(analysis)
                gc.collect()
            except Exception as e:
                logger.error(f"Failed to analyze {match.symbol}: {e}")

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase3'] = int(duration)

        logger.info(f"Analyzed {len(analyzed)} opportunities")
        logger.info(f"Phase 3 complete in {duration:.1f}s")

        return analyzed

    def _phase4_report(
        self,
        analyzed: List,
        candidates: List,
        sentiment: str,
        symbols: List[str],
        fail_symbols: List[str]
    ) -> str:
        """Phase 4: Report Generation.

        Args:
            analyzed: List of analyzed opportunities
            candidates: All candidates found
            sentiment: Market sentiment
            symbols: All symbols screened
            fail_symbols: Failed symbols

        Returns:
            Path to generated report
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4: Report Generation")
        logger.info("=" * 60)

        phase_start = datetime.now()

        report_path = self.reporter.generate_report(
            opportunities=analyzed,
            all_candidates=candidates,
            market_sentiment=sentiment,
            total_stocks=len(symbols),
            success_count=len(symbols) - len(fail_symbols),
            fail_count=len(fail_symbols),
            fail_symbols=fail_symbols
        )

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase4'] = int(duration)

        logger.info(f"Report generated: {report_path}")
        logger.info(f"Phase 4 complete in {duration:.1f}s")

        return report_path

    def _phase5_notify(
        self,
        report_path: str,
        sentiment: str,
        analyzed: List
    ):
        """Phase 5: Push Notifications.

        Args:
            report_path: Path to report
            sentiment: Market sentiment
            analyzed: List of analyzed opportunities
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 5: Push Notifications")
        logger.info("=" * 60)

        phase_start = datetime.now()

        scan_date = datetime.now().strftime('%Y-%m-%d')

        # Send notifications
        results = self.notifier.send_scan_summary(
            scan_date=scan_date,
            market_sentiment=sentiment,
            top_opportunities=analyzed,
            report_url=report_path
        )

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase5'] = int(duration)

        logger.info(f"Discord: {'sent' if results.get('discord') else 'failed'}")
        logger.info(f"WeChat: {'sent' if results.get('wechat') else 'failed'}")
        logger.info(f"Phase 5 complete in {duration:.1f}s")

    def _update_workflow_status(
        self,
        run_date: str,
        status: str,
        report_path: Optional[str] = None,
        error_message: Optional[str] = None,
        candidates_count: int = 0
    ):
        """Update workflow status in database.

        Args:
            run_date: Date string
            status: Workflow status
            report_path: Optional report path
            error_message: Optional error message
            candidates_count: Number of candidates
        """
        total_duration = sum(self._phase_times.values())

        self.db.save_workflow_status({
            'run_date': run_date,
            'status': status,
            'phase0_duration': self._phase_times.get('phase0'),
            'phase1_duration': self._phase_times.get('phase1'),
            'phase2_duration': self._phase_times.get('phase2'),
            'phase3_duration': self._phase_times.get('phase3'),
            'phase4_duration': self._phase_times.get('phase4'),
            'phase5_duration': self._phase_times.get('phase5'),
            'total_duration': total_duration,
            'symbols_count': getattr(self, '_symbols_count', 0),
            'candidates_count': candidates_count,
            'report_path': report_path,
            'error_message': error_message
        })

    def run_test_scan(self, test_symbols: List[str]) -> Optional[str]:
        """Run test scan with limited symbols."""
        logger.info(f"Running test scan with {len(test_symbols)} symbols")
        return self.run_complete_workflow(
            symbols=test_symbols,
            skip_market_hours_check=True
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trade Scanner - Complete Workflow')
    parser.add_argument('--test', action='store_true', help='Run test scan')
    parser.add_argument('--symbols', type=str, help='Comma-separated symbols for test')
    parser.add_argument('--force', action='store_true', help='Skip trading day check')
    parser.add_argument('--server', action='store_true', help='Start API server')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    scanner = CompleteScanner()

    if args.test:
        symbols = args.symbols.split(',') if args.symbols else ['AAPL', 'MSFT', 'NVDA']
        report_path = scanner.run_test_scan(symbols)
    else:
        report_path = scanner.run_complete_workflow(skip_market_hours_check=args.force)

    if report_path:
        print(f"\n✅ Workflow complete!")
        print(f"📄 Report: {report_path}")
    else:
        print("\n❌ Workflow failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
