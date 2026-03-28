"""Test script for strategies A, B, C with 252-day data and sector info."""
import sys
sys.path.insert(0, '/home/admin/Projects/TradeChanceScreen')

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from data.db import Database
from core.fetcher import DataFetcher
from core.screener import StrategyScreener, StrategyType
from core.indicators import TechnicalIndicators

# Test symbols - diverse sectors for better coverage
TEST_SYMBOLS = [
    # Technology (cluster for sector resonance test)
    'AAPL', 'MSFT', 'NVDA', 'AVGO', 'ADBE', 'CRM',
    # Consumer/Retail
    'AMZN', 'TSLA', 'HD', 'NKE', 'MCD', 'SBUX',
    # Healthcare
    'JNJ', 'PFE', 'UNH', 'ABBV', 'MRK', 'LLY',
    # Financial
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C',
    # Energy (cluster for sector resonance test)
    'XOM', 'CVX', 'COP', 'EOG', 'SLB', 'OXY',
    # Industrial
    'CAT', 'BA', 'HON', 'UPS', 'LMT', 'GE',
    # Communication
    'GOOGL', 'META', 'NFLX', 'DIS', 'CMCSA', 'VZ',
    # Utilities
    'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC'
]

def download_12m_data(symbol: str) -> pd.DataFrame:
    """Download 12 months of data for testing."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="13mo", interval="1d", auto_adjust=True)
        if df.empty:
            return None
        df.columns = [c.lower().replace(' ', '_') for c in df.columns]
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        return df
    except Exception as e:
        logger.error(f"Failed to download {symbol}: {e}")
        return None

def save_to_cache(symbol: str, df: pd.DataFrame, db: Database):
    """Save dataframe to database cache."""
    try:
        conn = db.get_connection()
        # Delete existing data for this symbol
        conn.execute("DELETE FROM market_data WHERE symbol = ?", (symbol,))

        # Insert new data
        for idx, row in df.iterrows():
            date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
            conn.execute('''
                INSERT OR REPLACE INTO market_data
                (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, date_str, float(row['open']), float(row['high']),
                  float(row['low']), float(row['close']), int(row['volume'])))
        conn.commit()
        logger.info(f"Saved {len(df)} rows for {symbol}")
    except Exception as e:
        logger.error(f"Failed to save {symbol}: {e}")

def test_strategy_a(screener: StrategyScreener, symbols: list):
    """Test VCP-EP strategy."""
    logger.info("\n" + "="*60)
    logger.info("Testing Strategy A: VCP-EP")
    logger.info("="*60)

    matches = screener.screen_ep(symbols)

    if not matches:
        logger.info("No VCP-EP candidates found")
        return

    logger.info(f"Found {len(matches)} candidates:")
    for i, m in enumerate(matches[:5], 1):
        ts = m.technical_snapshot
        logger.info(f"\n#{i} {m.symbol}:")
        logger.info(f"  Score: {ts.get('score', 0)}/15 (Tier {ts.get('tier', '?')})")
        logger.info(f"  Dimensions: PQ:{ts.get('pq_score', 0)} BS:{ts.get('bs_score', 0)} "
                   f"VC:{ts.get('vc_score', 0)} TC:{ts.get('tc_score', 0)}")
        logger.info(f"  Entry: ${m.entry_price}, Stop: ${m.stop_loss}, Target: ${m.take_profit}")
        logger.info(f"  Reasons: {m.match_reasons[:2]}")

def test_strategy_b(screener: StrategyScreener, symbols: list):
    """Test Momentum strategy."""
    logger.info("\n" + "="*60)
    logger.info("Testing Strategy B: Momentum Breakout")
    logger.info("="*60)

    matches = screener.screen_momentum(symbols)

    if not matches:
        logger.info("No Momentum candidates found")
        return

    logger.info(f"Found {len(matches)} candidates:")
    for i, m in enumerate(matches[:5], 1):
        ts = m.technical_snapshot
        logger.info(f"\n#{i} {m.symbol}:")
        logger.info(f"  Score: {ts.get('total_score', 0)}/15 (Tier {ts.get('tier', '?')})")
        logger.info(f"  Dimensions: RS:{ts.get('rs_score', 0)} SQ:{ts.get('sq_score', 0)} "
                   f"VC:{ts.get('vc_score', 0)} TC:{ts.get('tc_score', 0)}")
        logger.info(f"  RS Percentile: {ts.get('rs_percentile', 0):.1f}")
        logger.info(f"  Entry: ${m.entry_price}, Stop: ${m.stop_loss}, Target: ${m.take_profit}")

def test_strategy_c(screener: StrategyScreener, symbols: list):
    """Test Shoryuken strategy with sector bonus."""
    logger.info("\n" + "="*60)
    logger.info("Testing Strategy C: Shoryuken v3.0")
    logger.info("="*60)

    matches = screener.screen_shoryuken(symbols)

    if not matches:
        logger.info("No Shoryuken candidates found")
        return

    logger.info(f"Found {len(matches)} candidates:")
    for i, m in enumerate(matches[:5], 1):
        ts = m.technical_snapshot
        logger.info(f"\n#{i} {m.symbol}:")
        logger.info(f"  Score: {ts.get('score', 0)}/15 (Tier {ts.get('tier', '?')})")
        logger.info(f"  Dimensions: TI:{ts.get('ti_score', 0)} RS:{ts.get('rs_score', 0)} "
                   f"VC:{ts.get('vc_score', 0)} Bonus:{ts.get('bonus_score', 0)}")
        logger.info(f"  Sector: {ts.get('sector', 'Unknown')}")
        logger.info(f"  EMA21 Slope: {ts.get('ema21_slope_norm', 0):.3f}")
        logger.info(f"  Entry: ${m.entry_price}, Stop: ${m.stop_loss}, Target: ${m.take_profit}")

def verify_data_coverage(symbols: list, db: Database):
    """Check data coverage for test symbols."""
    logger.info("\n" + "="*60)
    logger.info("Data Coverage Verification")
    logger.info("="*60)

    conn = db.get_connection()
    for symbol in symbols:
        cursor = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM market_data WHERE symbol = ?",
            (symbol,)
        )
        count, min_date, max_date = cursor.fetchone()
        logger.info(f"{symbol}: {count} days ({min_date} to {max_date})")

def main():
    use_existing = True  # Set to False to re-download all data

    db = Database()
    fetcher = DataFetcher(db=db)
    screener = StrategyScreener(fetcher=fetcher, db=db)

    # Step 1: Download 12-month data for test symbols (if not using existing)
    if not use_existing:
        logger.info("Step 1: Downloading 12-month historical data...")
        for symbol in TEST_SYMBOLS:
            logger.info(f"Downloading {symbol}...")
            df = download_12m_data(symbol)
            if df is not None:
                save_to_cache(symbol, df, db)
    else:
        logger.info("Step 1: Using existing data (use_existing=True)")

    # Step 2: Verify data coverage
    verify_data_coverage(TEST_SYMBOLS, db)

    # Step 3: Check sector data
    logger.info("\n" + "="*60)
    logger.info("Sector Data Verification")
    logger.info("="*60)
    sector_data = fetcher.fetch_batch_stock_info(TEST_SYMBOLS)
    for symbol, info in sector_data.items():
        logger.info(f"{symbol}: {info.get('sector', 'Unknown')}")

    # Step 4: Test strategies
    test_strategy_a(screener, TEST_SYMBOLS)
    test_strategy_b(screener, TEST_SYMBOLS)
    test_strategy_c(screener, TEST_SYMBOLS)

    logger.info("\n" + "="*60)
    logger.info("Test Complete")
    logger.info("="*60)

if __name__ == '__main__':
    main()
