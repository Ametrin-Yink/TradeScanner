# Data-Fetch-Rework Plan

## Current Architecture Issues

1. **Stock Universe**: Static from `db.get_active_stocks()` - no dynamic discovery
2. **Data Fetch Timing**: Streaming during screening phase - slow and coupled
3. **No Pre-Market Prep**: Everything happens at scan time
4. **No finvizfinance Integration**: Missing dynamic >$2B market cap filtering
5. **Redundant Calculations**: Strategies re-calculate same indicators
6. **Market Sentiment Timing**: Currently runs inline with screening (slows down scan)

## Pre-Calculation Tier Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TIER 1 (Universal - Pre-Calc)                     │
│                    Calculate for ALL symbols at 6 AM                     │
├─────────────────────────────────────────────────────────────────────────┤
│ Price/Volume: current_price, avg_volume_20d, volume_ratio, volume_sma   │
│ EMAs: ema8, ema21, ema50, ema200                                        │
│ Volatility: atr, atr_pct, adr, adr_pct                                  │
│ Returns: ret_3m, ret_6m, ret_12m, ret_5d                                │
│ RS Metrics: rs_raw, rs_percentile                                       │
│ 52-Week: distance_from_52w_high, high_60d, low_60d                      │
│ Basic: gaps_5d, rsi_14                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        TIER 2 (Strategy-Specific - Lazy)                 │
│                    Calculate during screening only                       │
├─────────────────────────────────────────────────────────────────────────┤
│ VCP Platform (EP): platform data, contraction ratios, concentration     │
│ S/R Levels (U&R, Range, DTSS): support/resistance, touches, intervals   │
│ EMA Slopes (Shoryuken): normalized slopes, retracement structure        │
│ Divergence (DTSS, Capitulation): RSI divergence, exhaustion gaps        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        TIER 3 (Market Data - Pre-Calc)                   │
│                    Fetch once at 6 AM, share across strategies          │
├─────────────────────────────────────────────────────────────────────────┤
│ SPY: price, ema200, ema50, returns (market regime detection)            │
│ VIX: current level, slope (capitulation filtering)                      │
│ Sector ETFs: XLK, XLF, XLE, XLI, XLP, XLY, XLB, XLU, XLV (sector α)    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Target Architecture (6 AM ET Complete Workflow)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     COMPLETE 6 AM ET WORKFLOW                            │
│         (Market Sentiment → Report Generation → Push Notification)       │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 0: Data Preparation  │
                    │  (6:00 AM ET Start)         │
                    ├─────────────────────────────┤
                    │  0.1: Fetch Universe        │
                    │       - finvizfinance       │
                    │       - Market cap >$2B     │
                    │                             │
                    │  0.2: Sync with Database    │
                    │       - Add new symbols     │
                    │       - Mark inactive       │
                    │                             │
                    │  0.3: Fetch Market Data     │
                    │       - yfinance bulk       │
                    │       - SPY, VIX, ETFs      │
                    │       - All universe stocks │
                    │                             │
                    │  0.4: Tier 1 Pre-Calc       │
                    │       - Universal metrics   │
                    │       - Store in SQLite     │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 1: Market Sentiment  │
                    │  (Parallel with screening)  │
                    ├─────────────────────────────┤
                    │  - Tavily news search       │
                    │  - AI sentiment analysis    │
                    │  - Market regime detection  │
                    │  - Returns sentiment_result │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 2: Strategy Screening│
                    │  (Uses Tier 1 + Tier 3)     │
                    ├─────────────────────────────┤
                    │  2.1: Load Tier 1 cache     │
                    │  2.2: Load Tier 3 data      │
                    │  2.3: Pre-filter (fast)     │
                    │  2.4: Tier 2 calc (lazy)    │
                    │  2.5: Score & rank          │
                    │  2.6: Dynamic allocation    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 3: AI Analysis       │
                    │  (Top 10 candidates)        │
                    ├─────────────────────────────┤
                    │  - Deep analysis per stock  │
                    │  - Risk assessment          │
                    │  - Confidence scoring       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 4: Report Generation │
                    ├─────────────────────────────┤
                    │  - HTML report              │
                    │  - Charts & visualizations  │
                    │  - Summary statistics       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Phase 5: Push Notification │
                    ├─────────────────────────────┤
                    │  - WeChat notification      │
                    │  - Discord webhook          │
                    │  - Email (optional)         │
                    └─────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │     WORKFLOW COMPLETE        │
                    │     (~70-80 min total)       │
                    └──────────────────────────────┘
```

## Cron Schedule (Single Entry Point)

```bash
# /etc/cron.d/trade-scanner

# Complete workflow at 6:00 AM ET (Mon-Fri)
# This runs the ENTIRE pipeline:
# - Data prep (Phase 0)
# - Market sentiment (Phase 1)
# - Strategy screening (Phase 2)
# - AI analysis (Phase 3)
# - Report generation (Phase 4)
# - Push notifications (Phase 5)
0 6 * * 1-5 root cd /path/to/project && python3 scheduler.py --full-scan >> /var/log/trade_scanner.log 2>&1

# Optional: Mid-day update at 12:00 PM ET
# Only re-runs screening with existing data (no universe refresh)
0 12 * * 1-5 root cd /path/to/project && python3 scheduler.py --quick-update >> /var/log/trade_scanner_midday.log 2>&1
```

## Modified `scheduler.py` - Complete Workflow

```python
#!/usr/bin/env python3
"""
Complete Trade Scanner Workflow
Runs entire pipeline from data prep to notification push.
"""
import argparse
import logging
import sys
import gc
from datetime import datetime
from typing import Optional, List

from config.settings import settings
from data.db import Database
from core.fetcher import DataFetcher
from core.premarket_prep import PreMarketPrep
from core.screener import StrategyScreener
from core.market_analyzer import MarketAnalyzer
from core.selector import CandidateSelector
from core.analyzer import OpportunityAnalyzer
from core.reporter import ReportGenerator
from core.notifier import Notifier  # For WeChat/Discord push

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompleteScanner:
    """Complete scanner workflow from data prep to notification."""

    MAX_HISTORY_DAYS = 280

    def __init__(self):
        ""Initialize all components."""
        self.db = Database()
        self.fetcher = DataFetcher(
            db=self.db,
            max_workers=2,
            max_history_days=self.MAX_HISTORY_DAYS
        )
        self.prep = PreMarketPrep(db=self.db, fetcher=self.fetcher)
        self.screener = StrategyScreener(fetcher=self.fetcher, db=self.db)
        self.market_analyzer = MarketAnalyzer()
        self.selector = CandidateSelector()
        self.opportunity_analyzer = OpportunityAnalyzer(fetcher=self.fetcher)
        self.reporter = ReportGenerator(fetcher=self.fetcher)
        self.notifier = Notifier()  # WeChat + Discord

    def run_full_workflow(
        self,
        skip_market_hours_check: bool = False,
        skip_data_prep: bool = False
    ) -> Optional[str]:
        """
        Run the complete workflow from data prep to notification.

        Phases:
        0. Data Preparation (fetch universe, Tier 1 pre-calc, Tier 3 fetch)
        1. Market Sentiment Analysis
        2. Strategy Screening (with lazy Tier 2 calc)
        3. AI Analysis (top 10)
        4. Report Generation
        5. Push Notifications (WeChat + Discord)

        Returns:
            Path to generated report or None if failed
        """
        workflow_start = datetime.now()

        try:
            # Check trading day
            if not skip_market_hours_check and not self._is_trading_day():
                logger.info("Not a trading day, skipping workflow")
                return None

            # ============================================================
            # PHASE 0: Data Preparation (6:00 AM start)
            # ============================================================
            if not skip_data_prep:
                logger.info("=" * 60)
                logger.info("PHASE 0: Data Preparation")
                logger.info("=" * 60)

                prep_result = self.prep.run_prep_pipeline()
                if not prep_result.success:
                    logger.error(f"Data prep failed: {prep_result.error}")
                    return None

                logger.info(f"✅ Phase 0 complete: {prep_result.symbols_count} symbols ready")
                logger.info(f"   Tier 1 cached: {prep_result.tier1_cached}")
                logger.info(f"   Tier 3 cached: {prep_result.tier3_cached}")
            else:
                logger.info("Skipping data prep (using cached data)")
                prep_result = self._load_prep_result()

            # ============================================================
            # PHASE 1: Market Sentiment Analysis
            # ============================================================
            logger.info("=" * 60)
            logger.info("PHASE 1: Market Sentiment Analysis")
            logger.info("=" * 60)

            sentiment_result = self.market_analyzer.analyze_sentiment()
            market_sentiment = sentiment_result.get('sentiment', 'neutral')
            logger.info(f"Market sentiment: {market_sentiment} "
                       f"(confidence: {sentiment_result.get('confidence', 0)}%)")

            # ============================================================
            # PHASE 2: Strategy Screening
            # ============================================================
            logger.info("=" * 60)
            logger.info("PHASE 2: Strategy Screening")
            logger.info("=" * 60)

            # Load pre-calculated data
            tier1_data = self.prep.load_tier1_cache()
            tier3_data = self.prep.load_tier3_cache()
            symbols = list(tier1_data.keys())

            logger.info(f"Screening {len(symbols)} symbols with pre-calc data...")

            candidates = self.screener.screen_all(
                symbols=symbols,
                tier1_data=tier1_data,      # Pass Tier 1 (fast)
                tier3_data=tier3_data,      # Pass Tier 3 (market context)
                market_sentiment=market_sentiment
            )

            logger.info(f"Found {len(candidates)} candidates from all strategies")

            if not candidates:
                logger.warning("No candidates found, generating empty report")
                report_path = self._generate_empty_report(
                    sentiment_result=sentiment_result,
                    total_stocks=len(symbols)
                )
                self._push_notification(report_path, empty=True)
                return report_path

            # ============================================================
            # PHASE 3: AI Analysis (Top 10 Selection)
            # ============================================================
            logger.info("=" * 60)
            logger.info("PHASE 3: AI Analysis & Top 10 Selection")
            logger.info("=" * 60)

            # Select and score top 10
            top_10_scored = self.selector.select_top_10(candidates, market_sentiment)
            logger.info(f"Selected {len(top_10_scored)} opportunities for deep analysis")

            # Run deep AI analysis one by one
            analyzed = []
            for i, match in enumerate(top_10_scored):
                try:
                    logger.info(f"Analyzing {match.symbol} ({i+1}/{len(top_10_scored)})...")
                    analysis = self.opportunity_analyzer.analyze_opportunity(
                        match, market_sentiment,
                        cached_data=tier1_data.get(match.symbol)
                    )
                    analyzed.append(analysis)
                    gc.collect()
                except Exception as e:
                    logger.error(f"Failed to analyze {match.symbol}: {e}")
                    analyzed.append(self._create_basic_analysis(match))

            logger.info(f"Completed analysis for {len(analyzed)} opportunities")

            # ============================================================
            # PHASE 4: Report Generation
            # ============================================================
            logger.info("=" * 60)
            logger.info("PHASE 4: Report Generation")
            logger.info("=" * 60)

            report_path = self.reporter.generate_report(
                opportunities=analyzed,
                all_candidates=candidates,
                market_sentiment=market_sentiment,
                total_stocks=len(symbols),
                success_count=prep_result.success_count,
                fail_count=prep_result.fail_count,
                sentiment_result=sentiment_result,
                tier1_data=tier1_data
            )

            logger.info(f"✅ Report generated: {report_path}")

            # Save scan result to database
            self._save_scan_result(
                workflow_start, market_sentiment, analyzed,
                candidates, report_path, prep_result
            )

            # ============================================================
            # PHASE 5: Push Notifications
            # ============================================================
            logger.info("=" * 60)
            logger.info("PHASE 5: Push Notifications")
            logger.info("=" * 60)

            self._push_notification(report_path, opportunities=analyzed)

            # ============================================================
            # WORKFLOW COMPLETE
            # ============================================================
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.info("=" * 60)
            logger.info("WORKFLOW COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Total duration: {duration/60:.1f} minutes")
            logger.info(f"Report: {report_path}")

            return report_path

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            return None

    def _push_notification(self, report_path: str, opportunities: List = None, empty: bool = False):
        """Push notification to WeChat and Discord."""
        try:
            if empty:
                message = f"📊 Trade Scanner - No opportunities today\n"
                message += f"Report: {report_path}"
            else:
                message = f"📊 Trade Scanner - {len(opportunities)} opportunities found\n"
                message += f"Top picks: {', '.join([o.symbol for o in opportunities[:3]])}\n"
                message += f"Report: {report_path}"

            # WeChat notification
            self.notifier.send_wechat(message)

            # Discord webhook
            self.notifier.send_discord(message)

            logger.info("✅ Notifications sent")

        except Exception as e:
            logger.error(f"Failed to send notifications: {e}")

    def _is_trading_day(self) -> bool:
        """Check if today is a US trading day."""
        import pytz
        ny_tz = pytz.timezone('America/New_York')
        now = datetime.now(ny_tz)

        if now.weekday() >= 5:
            logger.info(f"Today is {now.strftime('%A')} - not a trading day")
            return False
        return True

    def _generate_empty_report(self, sentiment_result: dict, total_stocks: int) -> str:
        """Generate report when no candidates found."""
        return self.reporter.generate_report(
            opportunities=[],
            all_candidates=[],
            market_sentiment=sentiment_result.get('sentiment', 'neutral'),
            total_stocks=total_stocks,
            success_count=total_stocks,
            fail_count=0,
            sentiment_result=sentiment_result
        )

    def _create_basic_analysis(self, match):
        """Create basic analysis when AI analysis fails."""
        from core.analyzer import AnalyzedOpportunity
        return AnalyzedOpportunity(
            symbol=match.symbol,
            strategy=match.strategy,
            entry_price=match.entry_price,
            stop_loss=match.stop_loss,
            take_profit=match.take_profit,
            confidence=match.confidence,
            match_reasons=match.match_reasons
        )

    def _save_scan_result(self, start_time, sentiment, analyzed, candidates, report_path, prep_result):
        """Save scan result to database."""
        scan_result = {
            'scan_date': start_time.strftime('%Y-%m-%d'),
            'scan_time': start_time.strftime('%H:%M:%S'),
            'market_sentiment': sentiment,
            'top_opportunities': [{
                'symbol': o.symbol,
                'strategy': o.strategy,
                'entry_price': o.entry_price,
                'stop_loss': o.stop_loss,
                'take_profit': o.take_profit,
                'confidence': o.confidence
            } for o in analyzed],
            'all_candidates': [{
                'symbol': c.symbol,
                'strategy': c.strategy,
                'confidence': c.confidence
            } for c in candidates],
            'total_stocks': prep_result.symbols_count,
            'success_count': prep_result.success_count,
            'fail_count': prep_result.fail_count,
            'report_path': report_path
        }
        self.db.save_scan_result(scan_result)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trade Scanner - Complete Workflow')
    parser.add_argument('--full-scan', action='store_true',
                       help='Run complete workflow (data prep → notification)')
    parser.add_argument('--quick-update', action='store_true',
                       help='Quick update using cached data (no universe refresh)')
    parser.add_argument('--test', action='store_true',
                       help='Run test scan with limited symbols')
    parser.add_argument('--symbols', type=str,
                       help='Comma-separated symbols for test')
    parser.add_argument('--force', action='store_true',
                       help='Skip trading day check')
    parser.add_argument('--skip-data-prep', action='store_true',
                       help='Skip Phase 0 data prep (use cached)')
    parser.add_argument('--server', action='store_true',
                       help='Start API server only')

    args = parser.parse_args()

    if args.server:
        from api.server import run_server
        run_server()
        return

    scanner = CompleteScanner()

    if args.test:
        symbols = args.symbols.split(',') if args.symbols else ['AAPL', 'MSFT', 'NVDA']
        logger.info(f"Running test scan with {len(symbols)} symbols")
        report_path = scanner.run_full_workflow(
            skip_market_hours_check=True,
            skip_data_prep=args.skip_data_prep
        )
    elif args.full_scan or not args.quick_update:
        # Default: full workflow
        report_path = scanner.run_full_workflow(
            skip_market_hours_check=args.force,
            skip_data_prep=args.skip_data_prep
        )
    else:
        # Quick update: skip universe refresh
        report_path = scanner.run_full_workflow(
            skip_market_hours_check=args.force,
            skip_data_prep=True  # Use cached data
        )

    if report_path:
        print(f"\n✅ Workflow complete!")
        print(f"📄 Report: {report_path}")
    else:
        print("\n❌ Workflow failed or skipped")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

## New Components Required

### 1. `core/stock_universe.py`

```python
class StockUniverseManager:
    """Manage stock universe from finvizfinance."""

    def fetch_finviz_universe(self, min_market_cap_b: float = 2.0) -> List[str]:
        """Fetch stocks with >$2B market cap from finviz."""
        pass

    def sync_with_database(self, finviz_symbols: List[str]) -> Dict[str, List[str]]:
        """Sync finviz symbols with local DB."""
        pass
```

### 2. `core/premarket_prep.py`

```python
class PreMarketPrep:
    """Phase 0: Data preparation pipeline."""

    MARKET_SYMBOLS = ['SPY', 'VIX', 'QQQ']
    SECTOR_ETFS = ['XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLV', 'XBI', 'SMH']

    def __init__(self, db: Database, fetcher: DataFetcher):
        self.db = db
        self.fetcher = fetcher
        self.universe_manager = StockUniverseManager(db)

    def run_prep_pipeline(self) -> PrepResult:
        """
        Phase 0: Complete data preparation.

        Steps:
        0.1: Fetch universe from finviz
        0.2: Sync with database
        0.3: Fetch Tier 3 market data (SPY, VIX, ETFs)
        0.4: Fetch market data for all symbols
        0.5: Run Tier 1 pre-calculation
        0.6: Store all caches
        """
        pass

    def run_tier1_precalculation(self, market_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict]:
        """
        Run Tier 1 pre-calculation.

        Calculates for each symbol:
        - Price: current_price
        - Volume: avg_volume_20d, volume_ratio, volume_sma
        - EMAs: ema8, ema21, ema50, ema200
        - Volatility: atr, atr_pct, adr, adr_pct
        - Returns: ret_3m, ret_6m, ret_12m, ret_5d
        - RS: rs_raw, rs_percentile
        - 52-Week: distance_from_52w_high, high_60d, low_60d
        - Basic: gaps_5d, rsi_14
        """
        pass

    def load_tier1_cache(self) -> Dict[str, Dict]:
        """Load Tier 1 cache from database."""
        pass

    def load_tier3_cache(self) -> Dict[str, pd.DataFrame]:
        """Load Tier 3 cache from database."""
        pass
```

### 3. `core/notifier.py` (New)

```python
class Notifier:
    """Send notifications to WeChat and Discord."""

    def __init__(self):
        self.wechat_key = settings.get_secret('wechat.key')
        self.discord_webhook = settings.get_secret('discord.webhook')

    def send_wechat(self, message: str):
        """Send WeChat notification."""
        pass

    def send_discord(self, message: str):
        """Send Discord webhook notification."""
        pass
```

## DB Schema Updates

```sql
-- Universe sync history
CREATE TABLE IF NOT EXISTS universe_sync (
    id INTEGER PRIMARY KEY,
    sync_date TEXT,
    symbols_added INTEGER,
    symbols_removed INTEGER,
    total_symbols INTEGER
);

-- Tier 1 cache (universal metrics)
CREATE TABLE IF NOT EXISTS tier1_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    current_price REAL,
    avg_volume_20d REAL,
    volume_ratio REAL,
    volume_sma REAL,
    ema8 REAL, ema21 REAL, ema50 REAL, ema200 REAL,
    atr REAL, atr_pct REAL, adr REAL, adr_pct REAL,
    ret_3m REAL, ret_6m REAL, ret_12m REAL, ret_5d REAL,
    rs_raw REAL, rs_percentile REAL,
    distance_from_52w_high REAL, high_60d REAL, low_60d REAL,
    gaps_5d INTEGER, rsi_14 REAL,
    data_days INTEGER
);

-- Tier 3 cache (market data)
CREATE TABLE IF NOT EXISTS tier3_cache (
    symbol TEXT PRIMARY KEY,
    cache_date TEXT,
    market_data BLOB
);

-- Workflow status
CREATE TABLE IF NOT EXISTS workflow_status (
    run_date TEXT PRIMARY KEY,
    start_time TEXT,
    end_time TEXT,
    status TEXT,  -- 'running', 'completed', 'failed'
    phase0_duration INTEGER,
    phase1_duration INTEGER,
    phase2_duration INTEGER,
    phase3_duration INTEGER,
    phase4_duration INTEGER,
    phase5_duration INTEGER,
    total_duration INTEGER,
    symbols_count INTEGER,
    candidates_count INTEGER,
    report_path TEXT,
    error_message TEXT
);
```

## Files to Modify

| File | Changes |
|------|---------|
| `scheduler.py` | Complete rewrite for 5-phase workflow |
| `data/db.py` | Add tier1_cache, tier3_cache, workflow_status tables |
| `core/screener.py` | Accept tier1_data and tier3_data |
| `core/strategies/base_strategy.py` | Add screen_with_precalc() |
| `core/strategies/*.py` | Modify filter() for lazy Tier 2 calc |

## New Files

| File | Purpose |
|------|---------|
| `core/stock_universe.py` | finvizfinance integration |
| `core/premarket_prep.py` | Phase 0 data preparation |
| `core/notifier.py` | WeChat + Discord notifications |

## Performance Expectations

- **Phase 0 (Data Prep)**: ~15-20 minutes
- **Phase 1 (Sentiment)**: ~2-3 minutes (parallel)
- **Phase 2 (Screening)**: ~10-15 minutes (with lazy Tier 2)
- **Phase 3 (AI Analysis)**: ~15-20 minutes (top 10)
- **Phase 4 (Report)**: ~2-3 minutes
- **Phase 5 (Notifications)**: ~1 minute
- **Total**: ~45-60 minutes
