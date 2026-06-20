"""Complete 6-phase workflow scheduler for 3 AM automated execution."""
import argparse
import logging
import sys
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
from core.sector_manager import SectorManager
from core.simulation_engine import SimulationEngine

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

        # Load active sectors from database
        try:
            self.active_sectors = [s['name'] for s in SectorManager().get_sectors(self.db)]
            logger.info(f"Loaded {len(self.active_sectors)} active sectors: {self.active_sectors}")
        except Exception as e:
            logger.warning(f"Could not load sectors: {e}")
            self.active_sectors = []

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

        ctx = PipelineContext(
            symbols=symbols or [],
            sectors=self.active_sectors,
            run_date=run_date,
        )
        self._last_ctx = ctx  # For debug inspector

        self.db.save_workflow_status({
            'run_date': run_date,
            'start_time': workflow_start.strftime('%H:%M:%S'),
            'status': 'running'
        })

        try:
            # Phase 0: Data preparation (always in-process)
            phase0_result = self._phase0_data_prep(symbols)
            if not phase0_result['success']:
                logger.error("Phase 0 failed, aborting workflow")
                self._update_workflow_status(run_date, status='failed', error_message='Phase 0 failed')
                return None

            ctx.symbols = phase0_result['symbols']
            self._last_ctx = ctx

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

                # Run simulation engine: auto-select top picks and check open positions
                try:
                    from types import SimpleNamespace
                    engine = SimulationEngine(self.db)
                    all_highlights = []
                    for o in ctx.top_10:
                        rr = 0.0
                        denom = o.entry_price - o.stop_loss
                        if denom > 0:
                            rr = (o.take_profit - o.entry_price) / denom
                        h = SimpleNamespace(
                            symbol=o.symbol,
                            primary_tag=o.strategy,
                            reason=getattr(o, 'ai_reasoning', o.strategy),
                            entry=o.entry_price,
                            stop=o.stop_loss,
                            target=o.take_profit,
                            rr=rr,
                            time_horizon=getattr(o, 'time_frame', 'swing'),
                            position_size=0,
                            risk_dollars=0,
                        )
                        all_highlights.append(h)
                    engine.auto_select(all_highlights, run_date)
                    engine.daily_check()
                except Exception as e:
                    logger.warning(f"Simulation engine step failed: {e}", exc_info=True)

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

        Runs in-process (no subprocess) for both test and production modes.

        Args:
            symbols: Optional pre-defined symbols list

        Returns:
            Phase result dict
        """
        logger.info("\n" + "=" * 60)
        logger.info("PHASE 0: Data Preparation")
        logger.info("=" * 60)

        phase_start = datetime.now()

        # If symbols provided (test mode), use existing cached data
        if symbols is not None:
            logger.info(f"Using provided symbols: {len(symbols)} (cached mode)")
            tier3_data = self.prep._fetch_tier3_data()
            logger.info(f"Tier 3 data fetched: {len(tier3_data)} symbols")

            # Use existing Tier 1 cache — don't recalculate
            tier1_count = len(self.db.get_all_tier1_cache())
            logger.info(f"Tier 1 cache: {tier1_count} entries (from DB)")

            duration = (datetime.now() - phase_start).total_seconds()
            self._phase_times['phase0'] = int(duration)

            return {
                'success': True,
                'symbols': symbols,
                'symbols_count': len(symbols),
                'tier1_count': tier1_count,
                'duration': int(duration)
            }

        # Full production run: call run_phase0() in-process
        logger.info("Running Phase 0 in-process")

        try:
            result = self.prep.run_phase0()

            duration = (datetime.now() - phase_start).total_seconds()
            self._phase_times['phase0'] = int(duration)

            if result.get('success'):
                logger.info(f"Phase 0 completed successfully in {duration:.1f}s")
                logger.info(f"  Symbols for screening: {len(result['symbols'])}")
                logger.info(f"  Tier 1 cache entries: {result.get('tier1_cache_count', 0)}")

                return {
                    'success': True,
                    'symbols': result['symbols'],
                    'symbols_count': len(result['symbols']),
                    'tier1_count': result.get('tier1_cache_count', 0),
                    'duration': int(duration)
                }
            else:
                error_msg = result.get('errors', ['Unknown error'])[0] if result.get('errors') else 'Unknown error'
                logger.error(f"Phase 0 failed: {error_msg}")
                return {
                    'success': False,
                    'symbols': [],
                    'error': error_msg
                }

        except Exception as e:
            logger.exception(f"Phase 0 failed: {e}")
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
