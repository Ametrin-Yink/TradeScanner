"""Complete 6-phase workflow scheduler for 3 AM automated execution."""
import argparse
import logging
import sys
import gc
import subprocess
import json
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
from core.market_regime import MarketRegimeDetector
from core.notifier import MultiNotifier
from core.logging_config import setup_logging
from core.services import ServiceRegistry
from core.services.providers import register_defaults
from core.engine import PipelineOrchestrator, PipelineContext, PhaseResult

setup_logging()
register_defaults()
logger = logging.getLogger(__name__)


def check_memory():
    """Check available memory and warn if critically low."""
    try:
        with open('/proc/meminfo') as f:
            meminfo = f.read()

        mem_total = 0
        mem_available = 0

        for line in meminfo.split('\n'):
            if line.startswith('MemTotal:'):
                mem_total = int(line.split()[1]) / 1024 / 1024  # GB
            elif line.startswith('MemAvailable:'):
                mem_available = int(line.split()[1]) / 1024 / 1024  # GB

        logger.info(f"Memory: {mem_total:.1f}GB total, {mem_available:.1f}GB available")

        if mem_available < 0.3:
            logger.warning("CRITICAL: Less than 300MB memory available! Process may crash.")
            return False
        elif mem_available < 0.5:
            logger.warning("LOW MEMORY: Less than 500MB available. Consider reducing batch sizes.")
            return True
        return True
    except Exception as e:
        logger.debug(f"Could not check memory: {e}")
        return True


class CompleteScanner:
    """Complete 6-phase workflow scanner for daily 3 AM execution.

    Phase 0: Data Preparation (15-20 min)
        - Fetch universe from stock list
        - Sync with database
        - Fetch Tier 3 market data
        - Calculate Tier 1 universal metrics

    Phase 1: AI Market Regime Detection (2-3 min)
        - AI-powered regime classification using Tavily + technicals
        - Returns regime, allocation, ai_confidence, ai_reasoning

    Phase 2: Strategy Screening (10-15 min)
        - Screen all symbols using pre-calculated Tier 1/3 data
        - Pass regime context for strategy filtering
        - Lazy Tier 2 calculations for candidates only
        - Returns up to 30 candidates

    Phase 3: AI Scoring - Top 30 Selection (5-10 min)
        - Select top 30 candidates using regime-aware scoring
        - Parallel AI analysis with 2 workers

    Phase 4: Deep Analysis - Top 10 (10-15 min)
        - Deep analysis of top 10 candidates
        - Risk/reward assessment, setup quality scoring

    Phase 5: Report Generation (2-3 min)
        - Generate HTML report with top 30 table and top 10 deep analysis

    Phase 6: Push Notifications (1 min)
        - Send notifications to WeChat and Discord with AI regime info
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
            discord_webhook=settings.get_secret('discord.webhook_url'),
            wechat_webhook=settings.get_secret('wechat.webhook_url')
        )

        # Phase timing tracking
        self._phase_times: Dict[str, int] = {}
        self._sentiment_result: Optional[Dict] = None
        self.regime_detector = MarketRegimeDetector()

        # Update strategy descriptions for v5.0
        self.STRATEGY_DESCRIPTIONS = {
            "MomentumBreakout": "VCP platform + volume breakout - momentum plays",
            "PullbackEntry": "Institutional pullback to EMA support",
            "SupportBounce": "False breakdown reclaim - regime adaptive",
            "DistributionTop": "Short distribution tops (was RangeShort + DoubleTop)",
            "AccumulationBottom": "Long accumulation bottoms",
            "CapitulationRebound": "Capitulation bottom detection - VIX 15-35",
            "EarningsGap": "Post-earnings gap continuation - long/short",
            "RelativeStrengthLong": "RS divergence longs in bear markets"
        }

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
        Run complete 6-phase workflow using the pipeline engine.

        Args:
            symbols: Optional list of symbols (uses universe sync if None)
            skip_market_hours_check: Skip trading day check

        Returns:
            Path to generated report or None if failed
        """
        workflow_start = datetime.now()
        run_date = workflow_start.strftime('%Y-%m-%d')

        if not skip_market_hours_check and not self.is_trading_day():
            logger.info("Not a trading day, skipping workflow")
            self._update_workflow_status(run_date, status='skipped')
            return None

        logger.info("=" * 60)
        logger.info("STARTING COMPLETE 6-PHASE WORKFLOW")
        logger.info("=" * 60)

        check_memory()

        ctx = PipelineContext(
            symbols=symbols or [],
            run_date=run_date,
        )
        self._last_ctx = ctx  # For debug inspector

        self.db.save_workflow_status({
            'run_date': run_date,
            'start_time': workflow_start.strftime('%H:%M:%S'),
            'status': 'running'
        })

        try:
            # For test mode (symbols provided), run phases directly
            if symbols is not None:
                result = self._run_pipeline(ctx)
            else:
                # Production mode: Phase 0 subprocess, then pipeline for phases 1-6
                phase0_result = self._phase0_data_prep(symbols)
                if not phase0_result['success']:
                    logger.error("Phase 0 failed, aborting workflow")
                    self._update_workflow_status(run_date, status='failed', error_message='Phase 0 failed')
                    return None

                ctx.symbols = phase0_result['symbols']
                self._last_ctx = ctx
                gc.collect()
                logger.info("Memory cleaned after Phase 0")

                result = self._run_pipeline(ctx)

            # Copy pipeline phase times to scanner tracking
            for k, v in ctx.phase_times.items():
                self._phase_times[k] = v

            if ctx.status == "completed":
                total_duration = sum(ctx.phase_times.values())
                self._update_workflow_status(
                    run_date,
                    status='completed',
                    report_path=ctx.report_path,
                    candidates_count=len(ctx.top_10),
                )
                logger.info("=" * 60)
                logger.info(f"WORKFLOW COMPLETE in {total_duration:.0f}s")
                logger.info("=" * 60)
                return ctx.report_path
            else:
                self._update_workflow_status(
                    run_date,
                    status='failed',
                    error_message=ctx.error_message,
                )
                return None

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            self._update_workflow_status(run_date, status='failed', error_message=str(e))
            return None

    def _run_pipeline(self, ctx: PipelineContext) -> PipelineContext:
        """Run phases 1-6 through the pipeline engine."""
        from core.engine.phase_handlers import (
            Phase1RegimeHandler, Phase2ScreeningHandler,
            Phase3AIScoringHandler, Phase4DeepAnalysisHandler,
            Phase5ReportHandler, Phase6NotifyHandler,
        )

        pipeline = PipelineOrchestrator()
        # Replace default handlers with our custom set (skip phase0, already done)
        pipeline.handlers = [
            ("phase1", Phase1RegimeHandler()),
            ("phase2", Phase2ScreeningHandler()),
            ("phase3", Phase3AIScoringHandler()),
            ("phase4", Phase4DeepAnalysisHandler()),
            ("phase5", Phase5ReportHandler()),
            ("phase6", Phase6NotifyHandler()),
        ]

        return pipeline.run(ctx)

    def _phase0_data_prep(self, symbols: Optional[List[str]]) -> Dict:
        """Phase 0: Data Preparation.

        For full workflow (symbols=None): runs as separate process for memory isolation.
        For test mode (symbols provided): runs in-process for simplicity.

        Args:
            symbols: Optional pre-defined symbols list

        Returns:
            Phase result dict
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 0: Data Preparation")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # If symbols provided (test mode), run in-process
        if symbols is not None:
            logger.info(f"Using provided symbols: {len(symbols)} (test mode, in-process)")
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

        # FIX 7: Full Phase 0 runs as separate process for memory isolation
        # This is critical for 2GB RAM servers - process boundary ensures
        # all Phase 0 memory is reclaimed before Phase 1-6 begin
        logger.info("Running Phase 0 as separate process (memory isolation)")

        try:
            # Run Phase 0 runner as subprocess with real-time output streaming
            proc = subprocess.Popen(
                [sys.executable, 'scripts/run_phase0.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output to main log in real-time using iter with timeout
            output_lines = []
            logger.info("[Phase0] Subprocess started, streaming output...")

            import threading
            timeout_event = threading.Event()

            def read_output():
                for line in iter(proc.stdout.readline, ''):
                    if timeout_event.is_set():
                        break
                    logger.info(f"[Phase0] {line.strip()}")
                    output_lines.append(line)

            # Start reading in a thread
            reader_thread = threading.Thread(target=read_output)
            reader_thread.daemon = True
            reader_thread.start()

            # Wait for process with timeout (60 minutes)
            proc.wait(timeout=3600)

            # Wait for reader thread to finish
            reader_thread.join(timeout=5)

            # Signal timeout if still running
            timeout_event.set()

            # Build output string for result parsing
            output = ''.join(output_lines)
            result = type('CompletedProcess', (), {'returncode': proc.returncode, 'stdout': output, 'stderr': ''})()

            # Parse JSON result from stdout
            output = result.stdout
            json_start = output.find('=== PHASE0_RESULT_START ===')
            json_end = output.find('=== PHASE0_RESULT_END ===')

            if json_start != -1 and json_end != -1:
                json_str = output[json_start + 28:json_end].strip()
                phase0_result = json.loads(json_str)
            else:
                # Fallback: try to parse any JSON in output
                logger.warning("Could not find result markers, parsing output directly")
                for line in output.split('\n'):
                    if line.strip().startswith('{'):
                        phase0_result = json.loads(line)
                        break

            duration = (datetime.now() - phase_start).total_seconds()
            self._phase_times['phase0'] = int(duration)

            if result.returncode == 0 and phase0_result.get('success'):
                logger.info(f"Phase 0 subprocess completed successfully in {duration:.1f}s")
                logger.info(f"  Symbols for screening: {phase0_result['symbols_count']}")
                logger.info(f"  Tier 1 cache entries: {phase0_result['tier1_count']}")

                # Load symbols list from result for Phase 2
                # Note: We need the actual symbol list, not just count
                # The subprocess should have saved this info or we query from DB
                symbols_list = phase0_result.get('symbols', [])

                # If symbols not in result, query from DB using existing method
                if not symbols_list:
                    logger.info("Loading symbols from database (market cap >= $2B)...")
                    symbols_list = self.db.get_active_stocks_min_market_cap(min_market_cap=2e9)
                    logger.info(f"Loaded {len(symbols_list)} symbols from DB")

                return {
                    'success': True,
                    'symbols': symbols_list,
                    'symbols_count': phase0_result['symbols_count'],
                    'tier1_count': phase0_result['tier1_count'],
                    'duration': int(duration)
                }
            else:
                error_msg = phase0_result.get('error', 'Unknown error') or f"Subprocess exit code: {result.returncode}"
                logger.error(f"Phase 0 subprocess failed: {error_msg}")
                if result.stderr:
                    logger.error(f"Phase 0 stderr: {result.stderr[-500:]}")  # Last 500 chars
                return {
                    'success': False,
                    'symbols': [],
                    'error': error_msg
                }

        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error("Phase 0 subprocess timed out after 60 minutes")
            return {
                'success': False,
                'symbols': [],
                'error': 'Phase 0 timeout after 60 minutes'
            }
        except Exception as e:
            logger.exception(f"Phase 0 subprocess failed: {e}")
            return {
                'success': False,
                'symbols': [],
                'error': str(e)
            }

    def _phase1_market_analysis(self) -> Dict:
        """
        Phase 1: AI-Powered Market Regime Detection.
        Combines technical analysis + Tavily news + AI classification.

        Returns:
            Dict with 'regime', 'allocation', 'ai_confidence', 'ai_reasoning'
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 1: AI Market Regime Detection")
        logger.info("=" * 60)

        phase_start = datetime.now()

        try:
            # Get technical data
            spy_df = self.db.get_tier3_cache('SPY')
            vix_df = self.db.get_tier3_cache('^VIX')
            if vix_df is None:
                vix_df = self.db.get_tier3_cache('VIXY')

            # Get AI + Tavily analysis
            analysis = self.market_analyzer.analyze_for_regime(spy_df, vix_df)
            ai_regime = analysis['sentiment']

            # Use AI regime with technical validation
            regime = self.regime_detector.detect_regime_ai(
                spy_df, vix_df,
                ai_regime
            )

            allocation = self.regime_detector.get_allocation(regime)

            logger.info(f"AI Regime: {ai_regime} (confidence: {analysis['confidence']})")
            logger.info(f"Final Regime: {regime}")
            logger.info(f"AI Reasoning: {analysis['reasoning'][:100]}...")
            logger.info(f"Strategy allocation: {allocation}")

        except Exception as e:
            logger.error(f"AI regime detection failed: {e}, using technical fallback")
            spy_df = self.db.get_tier3_cache('SPY')
            vix_df = self.db.get_tier3_cache('^VIX')
            if vix_df is None:
                vix_df = self.db.get_tier3_cache('VIXY')
            regime = self.regime_detector.detect_regime(spy_df, vix_df)
            allocation = self.regime_detector.get_allocation(regime)
            analysis = {'confidence': 0, 'reasoning': f'Fallback: {e}'}

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase1'] = int(duration)

        return {
            'regime': regime,
            'allocation': allocation,
            'ai_confidence': analysis.get('confidence', 50),
            'ai_reasoning': analysis.get('reasoning', '')
        }

    def _phase2_screening(self, symbols: List[str], regime: str) -> Dict:
        """Phase 2: Strategy Screening.

        Args:
            symbols: List of symbols to screen
            regime: Market regime from regime detector

        Returns:
            Dict with candidates and fail_symbols
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 2: Strategy Screening")
        logger.info("=" * 60)

        phase_start = datetime.now()

        logger.info(f"Screening {len(symbols)} symbols with regime: {regime}")

        # Load Tier 3 market data from cache for strategies
        from core.stock_universe import get_all_market_etfs
        tier3_symbols = get_all_market_etfs()
        tier3_data = {}
        for sym in tier3_symbols:
            df = self.db.get_tier3_cache(sym)
            if df is not None and not df.empty:
                tier3_data[sym] = df
        logger.info(f"Loaded {len(tier3_data)} Tier 3 symbols from cache")

        # Screen all symbols using pre-calculated Tier 1 data
        # Pass regime to screener for strategy filtering
        # Pass Tier 3 data so strategies can use cached market data
        candidates = self.screener.screen_all(
            symbols=symbols,
            regime=regime,
            market_data=tier3_data
        )

        # For now, we don't track individual failures in the new flow
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
        regime: str
    ) -> List:
        """Phase 3: AI Analysis of top candidates (parallelized).

        Args:
            candidates: List of strategy matches
            regime: Market regime

        Returns:
            List of analyzed opportunities
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.info("\n" + "=" * 60)
        logger.info("PHASE 3: AI Analysis")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # Select top 30 (regime-aware selection)
        top_30 = self.selector.select_top_30(candidates, regime)
        logger.info(f"Selected {len(top_30)} opportunities for deep analysis")
        logger.info(f"Analyzing with 2 parallel workers...")

        # Analyze in parallel with 2 workers (for 2-core server)
        analyzed = []
        completed = 0

        def analyze_single(match):
            """Analyze a single opportunity."""
            try:
                analysis = self.opportunity_analyzer.analyze_opportunity(match, regime)
                return analysis
            except Exception as e:
                logger.error(f"Failed to analyze {match.symbol}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all tasks
            future_to_match = {
                executor.submit(analyze_single, match): match
                for match in top_30
            }

            # Collect results as they complete
            for future in as_completed(future_to_match):
                match = future_to_match[future]
                try:
                    result = future.result()
                    if result is not None:
                        analyzed.append(result)
                except Exception as e:
                    logger.error(f"Error analyzing {match.symbol}: {e}")

                completed += 1
                logger.info(f"Analyzed {match.symbol} ({completed}/{len(top_30)})...")

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase3'] = int(duration)

        logger.info(f"Analyzed {len(analyzed)} opportunities")
        logger.info(f"Phase 3 complete in {duration:.1f}s")

        return analyzed

    def _phase4_deep_analysis(self, top_30: list, regime: str) -> list:
        """Phase 4: Deep analysis for top 10."""
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 4: Deep Analysis (Top 10)")
        logger.info("=" * 60)

        phase_start = datetime.now()

        analyzed = self.opportunity_analyzer.analyze_top_10_deep(top_30, regime)

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase4'] = int(duration)

        logger.info(f"Deep analyzed {len(analyzed)} opportunities")
        logger.info(f"Phase 4 complete in {duration:.1f}s")

        return analyzed

    def _phase5_report(
        self,
        all_candidates: List,
        deep_analyzed: List,
        regime: str,
        symbols: List[str],
        fail_symbols: List[str],
        phase1_result: Dict = None
    ) -> str:
        """Phase 5: Report Generation.

        Args:
            all_candidates: All 30 candidates for full table
            deep_analyzed: Top 10 with deep analysis
            regime: Market regime
            symbols: All symbols screened
            fail_symbols: Failed symbols
            phase1_result: Phase 1 analysis result with AI details

        Returns:
            Path to generated report
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 5: Report Generation")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # Build sentiment result dict
        sentiment_result = {}
        if phase1_result:
            sentiment_result = {
                'reasoning': phase1_result.get('ai_reasoning', ''),
                'confidence': phase1_result.get('ai_confidence', 50),
                'key_factors': [f"Regime: {regime}"],
                'timestamp': datetime.now().isoformat()
            }

        report_path = self.reporter.generate_report(
            opportunities=deep_analyzed,
            all_candidates=all_candidates,
            market_sentiment=regime,
            sentiment_result=sentiment_result,
            total_stocks=len(symbols),
            success_count=len(symbols) - len(fail_symbols),
            fail_count=len(fail_symbols),
            fail_symbols=fail_symbols
        )

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase5'] = int(duration)

        logger.info(f"Report generated: {report_path}")
        logger.info(f"Phase 5 complete in {duration:.1f}s")

        return report_path

    def _phase6_notify(
        self,
        report_path: str,
        regime: str,
        candidates: List,
        ai_confidence: int,
        ai_reasoning: str
    ):
        """Phase 6: Push Notifications.

        Args:
            report_path: Path to report
            regime: Market regime
            candidates: List of final analyzed opportunities (top 10)
            ai_confidence: AI regime detection confidence (0-100)
            ai_reasoning: AI reasoning summary for regime classification
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 6: Push Notifications")
        logger.info("=" * 60)

        phase_start = datetime.now()

        scan_date = datetime.now().strftime('%Y-%m-%d')

        # Convert local file path to web URL
        report_filename = report_path.split('/')[-1]
        report_url = f"{settings.get('report', {}).get('base_url', 'http://47.90.229.136:19801')}/reports/{report_filename}"

        # Log AI info
        logger.info(f"AI Regime Confidence: {ai_confidence}%")
        logger.info(f"AI Reasoning: {ai_reasoning[:100]}...")
        logger.info(f"Final candidates: {len(candidates)}")

        # Send notifications
        results = self.notifier.send_scan_summary(
            scan_date=scan_date,
            market_sentiment=regime,  # Use market_sentiment parameter name
            top_opportunities=candidates,
            report_url=report_url
        )

        duration = (datetime.now() - phase_start).total_seconds()
        self._phase_times['phase6'] = int(duration)

        logger.info(f"Discord: {'sent' if results.get('discord') else 'failed'}")
        logger.info(f"WeChat: {'sent' if results.get('wechat') else 'failed'}")
        logger.info(f"Phase 6 complete in {duration:.1f}s")

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
            'phase6_duration': self._phase_times.get('phase6'),
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
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with verbose logging')
    parser.add_argument('--phase', type=str, help='Run specific phase only (phase0-phase6)')

    args = parser.parse_args()

    if args.debug:
        setup_logging(level='DEBUG', verbose=True)
    else:
        setup_logging()

    register_defaults()

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
        print(f"\nWorkflow complete!")
        print(f"Report: {report_path}")

        if args.debug:
            from core.debug import PipelineInspector
            inspector = PipelineInspector(scanner._last_ctx)
            print("\n" + inspector.summary())
    else:
        print("\nWorkflow failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
