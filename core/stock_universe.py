"""Stock universe management using static CSV file.

Manages a stock database with two categories:
- stocks: Regular stocks from CSV (e.g., AAPL, MSFT)
- market_index_etf: Market indices and ETFs (e.g., SPY, ^VIX, XLK)
"""
import csv
import logging
from pathlib import Path
from typing import List, Dict, Optional

from data.db import Database

logger = logging.getLogger(__name__)

# Path to static stock list CSV
CSV_PATH = Path(__file__).parent.parent / "nasdaq_stocklist_screener.csv"

# Market index ETFs and benchmarks (Tier 3 symbols)
MARKET_INDEX_ETFS = {
    'benchmarks': ['SPY', 'QQQ', 'IWM'],
    'volatility': ['^VIX', 'VIXY', 'UVXY'],
    'sectors': ['XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLV',
                'XBI', 'SMH', 'IGV', 'IYT', 'KRE', 'XRT']
}


def get_all_market_etfs() -> List[str]:
    """Get all market index ETF symbols."""
    etfs = []
    for category in MARKET_INDEX_ETFS.values():
        etfs.extend(category)
    return list(set(etfs))


class StockUniverseManager:
    """Manage stock database with categorized symbols.

    Categories:
    - stocks: Regular stocks loaded from CSV
    - market_index_etf: Market indices and ETFs for benchmarking
    """

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def load_stocks_from_csv(self) -> List[Dict[str, str]]:
        """Load stock data from static CSV file.

        Returns:
            List of dicts with 'symbol', 'name', 'sector'
            Note: Market cap is fetched from yfinance, not CSV
        """
        logger.info(f"Loading stocks from {CSV_PATH.name}...")

        stocks = []
        try:
            with open(CSV_PATH, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol = row.get('Symbol', '').strip()
                    name = row.get('Name', '').strip()
                    sector = row.get('Sector', '').strip()

                    if symbol:
                        # Clean symbol (replace dots and slashes with dashes for yfinance compatibility)
                        # yfinance uses: BRK-A, BRK-B (not BRK/A, BRK/B or BRK.A, BRK.B)
                        symbol = symbol.replace('.', '-').replace('/', '-')

                        stocks.append({
                            'symbol': symbol,
                            'name': name,
                            'sector': sector
                            # market_cap is NOT loaded from CSV - fetched from yfinance
                        })

            logger.info(f"Loaded {len(stocks)} stocks from CSV")
            return stocks

        except Exception as e:
            logger.error(f"Failed to load from CSV: {e}")
            return []

    def initialize_database(self, force_reload: bool = False) -> Dict[str, any]:
        """Initialize stock database from static sources.

        Loads:
        1. Market index ETFs (category='market_index_etf')
        2. Stocks from CSV (category='stocks')

        Args:
            force_reload: Force re-import even if DB has stocks

        Returns:
            Dict with init results
        """
        # Check if already initialized
        existing_stocks = self.db.get_active_stocks()
        if existing_stocks and len(existing_stocks) > 100 and not force_reload:
            logger.info(f"Using existing {len(existing_stocks)} stocks from database")
            return {
                'stocks_added': 0,
                'etfs_added': 0,
                'total_symbols': len(existing_stocks),
                'symbols': existing_stocks,
                'source': 'database_cache'
            }

        # Step 1: Add market index ETFs
        etfs = get_all_market_etfs()
        etfs_added = 0
        logger.info(f"Adding {len(etfs)} market index ETFs...")

        for symbol in etfs:
            try:
                self.db.add_stock_with_category(
                    symbol=symbol,
                    name=symbol,
                    sector='Benchmark',
                    category='market_index_etf',
                    market_cap=None
                )
                etfs_added += 1
            except Exception as e:
                logger.warning(f"Failed to add ETF {symbol}: {e}")

        # Step 2: Add stocks from CSV
        csv_stocks = self.load_stocks_from_csv()
        stocks_added = 0
        logger.info(f"Adding {len(csv_stocks)} stocks from CSV...")

        for i, stock in enumerate(csv_stocks):
            try:
                self.db.add_stock_with_category(
                    symbol=stock['symbol'],
                    name=stock['name'],
                    sector=stock['sector'],
                    category='stocks',
                    market_cap=None  # Market cap fetched from yfinance, not CSV
                )
                stocks_added += 1

                if (i + 1) % 500 == 0:
                    logger.info(f"  Added {i + 1}/{len(csv_stocks)} stocks...")
            except Exception as e:
                logger.warning(f"Failed to add stock {stock['symbol']}: {e}")

        final_symbols = self.db.get_active_stocks()

        result = {
            'stocks_added': stocks_added,
            'etfs_added': etfs_added,
            'total_symbols': len(final_symbols),
            'symbols': final_symbols,
            'source': 'csv_import'
        }

        logger.info(f"Database initialization complete: "
                   f"+{stocks_added} stocks, +{etfs_added} ETFs, "
                   f"{len(final_symbols)} total")

        return result

    def get_all_symbols(self) -> List[str]:
        """Get all active symbols (stocks + ETFs).

        Returns:
            List of all active symbols
        """
        return self.db.get_active_stocks()

    def get_stocks(self, min_market_cap: Optional[float] = None) -> List[str]:
        """Get stock symbols (optionally filtered by market cap).

        Args:
            min_market_cap: Minimum market cap in USD (e.g., 2e9 for $2B)

        Returns:
            List of stock symbols
        """
        if min_market_cap:
            return self.db.get_active_stocks_min_market_cap(min_market_cap)
        return self.db.get_stocks_by_category('stocks')

    def get_market_etfs(self) -> List[str]:
        """Get market index ETF symbols.

        Returns:
            List of ETF symbols
        """
        return self.db.get_stocks_by_category('market_index_etf')

    def get_stocks_count(self) -> int:
        """Get count of regular stocks."""
        return len(self.db.get_stocks_by_category('stocks'))

    def get_etfs_count(self) -> int:
        """Get count of market index ETFs."""
        return len(self.db.get_stocks_by_category('market_index_etf'))

    def refresh_from_csv(self) -> Dict[str, any]:
        """Force refresh stocks from CSV file.

        Use this when the CSV file has been updated.
        Market ETFs are not affected.

        Returns:
            Dict with refresh results
        """
        logger.info("Refreshing stocks from CSV...")

        csv_stocks = self.load_stocks_from_csv()
        existing = set(self.db.get_stocks_by_category('stocks'))

        added = 0
        for stock in csv_stocks:
            if stock['symbol'] not in existing:
                try:
                    self.db.add_stock_with_category(
                        symbol=stock['symbol'],
                        name=stock['name'],
                        sector=stock['sector'],
                        category='stocks',
                        market_cap=stock['market_cap']
                    )
                    added += 1
                except Exception as e:
                    logger.warning(f"Failed to add {stock['symbol']}: {e}")

        all_stocks = self.db.get_stocks_by_category('stocks')
        logger.info(f"CSV refresh complete: +{added} new, {len(all_stocks)} total stocks")

        return {
            'stocks_added': added,
            'total_stocks': len(all_stocks)
        }


# Convenience functions
def initialize_stock_database(force_reload: bool = False) -> Dict[str, any]:
    """Initialize stock database and return all symbols.

    Args:
        force_reload: Force re-import from sources

    Returns:
        Dict with initialization results
    """
    manager = StockUniverseManager()
    return manager.initialize_database(force_reload=force_reload)


def get_scanning_universe(min_market_cap: float = 2e9) -> Dict[str, List[str]]:
    """Get complete scanning universe.

    Returns:
        Dict with:
            - stocks: List of stock symbols meeting criteria
            - market_etfs: List of market index ETF symbols
    """
    manager = StockUniverseManager()
    return {
        'stocks': manager.get_stocks(min_market_cap=min_market_cap),
        'market_etfs': manager.get_market_etfs()
    }
