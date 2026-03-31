"""Run complete scan with all stocks and generate report."""
import logging
import sys
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/Projects/TradeChanceScreen')

from core.screener import StrategyScreener
from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator
from data.db import Database
from core.fetcher import DataFetcher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_full_pipeline():
    """Run complete pipeline: Market Analysis → Phase 0/1/2 → AI Selection → Deep Analysis → Report."""

    overall_start = time.time()

    logger.info("=" * 70)
    logger.info("TRADE SCANNER - FULL PIPELINE RUN")
    logger.info("=" * 70)
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Initialize components
    db = Database()
    fetcher = DataFetcher()

    # Load all stocks
    logger.info("\n[STEP 1] Loading stock universe...")
    all_symbols = db.get_active_stocks()
    logger.info(f"Total stocks to analyze: {len(all_symbols)}")

    # Step 1: Market Analysis
    logger.info("\n[STEP 2] Market Environment Analysis...")
    market_start = time.time()
    market_analyzer = MarketAnalyzer()
    market_sentiment = market_analyzer.analyze_sentiment()
    market_elapsed = time.time() - market_start
    logger.info(f"Market sentiment: {market_sentiment.get('market_regime', 'unknown')}")
    logger.info(f"Confidence: {market_sentiment.get('confidence', 0)}%")
    logger.info(f"Time: {market_elapsed:.1f}s")

    # Step 2: Fetch all market data
    logger.info("\n[STEP 3] Fetching market data...")
    fetch_start = time.time()
    market_data = {}

    for i, symbol in enumerate(all_symbols):
        if i % 100 == 0:
            logger.info(f"  Fetching {i+1}/{len(all_symbols)}...")
        try:
            df = fetcher.fetch_stock_data(symbol, period="1y", interval="1d")
            if df is not None and len(df) >= 60:
                market_data[symbol] = df
        except Exception as e:
            logger.debug(f"Error fetching {symbol}: {e}")

    fetch_elapsed = time.time() - fetch_start
    logger.info(f"Fetched data for {len(market_data)} symbols in {fetch_elapsed:.1f}s")

    # Step 3: Strategy Screening (Phase 0/1/2)
    logger.info("\n[STEP 4] Strategy Screening (Phase 0/1/2)...")
    screen_start = time.time()

    screener = StrategyScreener(fetcher=fetcher, db=db)

    # Get strategy weighting from market sentiment
    strategy_weighting = market_sentiment.get('strategy_weighting', {
        'breakout_momentum': 0.25,
        'trend_pullback': 0.25,
        'rebound_range': 0.25,
        'extreme_reversal': 0.25
    })

    candidates = screener.screen_all(
        symbols=all_symbols,
        market_data=market_data,
        batch_size=100,
        strategy_weighting=strategy_weighting
    )

    screen_elapsed = time.time() - screen_start
    logger.info(f"Screening complete: {len(candidates)} candidates in {screen_elapsed:.1f}s")

    # Step 4: AI Selection (30 → 10)
    logger.info("\n[STEP 5] AI Selection (top 10)...")
    select_start = time.time()

    selector = CandidateSelector()
    top_10 = selector.select_top_10(candidates, market_sentiment)

    select_elapsed = time.time() - select_start
    logger.info(f"Selected {len(top_10)} opportunities in {select_elapsed:.1f}s")

    # Step 5: Deep Analysis
    logger.info("\n[STEP 6] Deep Analysis...")
    analyze_start = time.time()

    analyzer = OpportunityAnalyzer(fetcher=fetcher)
    analyzed = []

    for opp in top_10:
        try:
            analyzed_opp = analyzer.analyze_opportunity(opp)
            analyzed.append(analyzed_opp)
        except Exception as e:
            logger.error(f"Error analyzing {opp.symbol}: {e}")
            analyzed.append(opp)

    analyze_elapsed = time.time() - analyze_start
    logger.info(f"Deep analysis complete for {len(analyzed)} opportunities in {analyze_elapsed:.1f}s")

    # Step 6: Generate Report
    logger.info("\n[STEP 7] Generating Report...")
    report_start = time.time()

    reporter = ReportGenerator(fetcher=fetcher, db=db)

    scan_result = {
        'scan_date': datetime.now().strftime('%Y-%m-%d'),
        'scan_time': datetime.now().strftime('%H:%M:%S'),
        'market_sentiment': market_sentiment.get('market_regime', 'neutral'),
        'market_confidence': market_sentiment.get('confidence', 0),
        'market_reasoning': market_sentiment.get('reasoning', ''),
        'top_opportunities': analyzed,
        'all_candidates': candidates,
        'total_stocks': len(all_symbols),
        'success_count': len(market_data),
        'fail_count': len(all_symbols) - len(market_data),
    }

    report_path = reporter.generate_report(scan_result)
    report_elapsed = time.time() - report_start
    logger.info(f"Report generated: {report_path} in {report_elapsed:.1f}s")

    # Final summary
    overall_elapsed = time.time() - overall_start

    logger.info("\n" + "=" * 70)
    logger.info("FULL PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"\nTotal execution time: {overall_elapsed:.1f}s ({overall_elapsed/60:.1f} minutes)")
    logger.info(f"\nBreakdown:")
    logger.info(f"  Market Analysis:   {market_elapsed:.1f}s")
    logger.info(f"  Data Fetch:        {fetch_elapsed:.1f}s")
    logger.info(f"  Strategy Screening:{screen_elapsed:.1f}s")
    logger.info(f"  AI Selection:      {select_elapsed:.1f}s")
    logger.info(f"  Deep Analysis:     {analyze_elapsed:.1f}s")
    logger.info(f"  Report Generation: {report_elapsed:.1f}s")
    logger.info(f"\nResults:")
    logger.info(f"  Stocks analyzed:   {len(all_symbols)}")
    logger.info(f"  Data success:      {len(market_data)}")
    logger.info(f"  Candidates found:  {len(candidates)}")
    logger.info(f"  Top 10 selected:   {len(analyzed)}")
    logger.info(f"\nReport: {report_path}")

    return report_path


if __name__ == "__main__":
    try:
        report_path = run_full_pipeline()
        logger.info("\n✓ Full scan completed successfully!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n✗ Full scan failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
