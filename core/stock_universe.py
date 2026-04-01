"""Stock universe management for daily workflow."""
import logging
from datetime import datetime
from typing import List, Set, Dict, Optional

from finvizfinance.screener.overview import Overview
from data.db import Database

logger = logging.getLogger(__name__)


class StockUniverseManager:
    """Manage daily stock universe sync from Finviz.

    Fetches all US stocks with market cap > $2B from Finviz,
    syncs with local database, and tracks changes.
    """

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def fetch_large_cap_universe(self) -> List[str]:
        """Fetch all stocks with market cap > $2B from Finviz.

        Returns:
            List of stock symbols
        """
        logger.info("Fetching stocks with market cap > $2B from Finviz...")

        try:
            overview = Overview()
            # Use '+Mid (over $2bln)' to get all stocks > $2B
            overview.set_filter(filters_dict={'Market Cap.': '+Mid (over $2bln)'})
            df = overview.screener_view()

            tickers = df['Ticker'].tolist()
            logger.info(f"Fetched {len(tickers)} stocks from Finviz")
            return tickers

        except Exception as e:
            logger.error(f"Failed to fetch from Finviz: {e}")
            return []

    def sync_universe(self) -> Dict[str, any]:
        """Sync stock universe with Finviz.

        Compares current database with Finviz universe and:
        - Adds new stocks not in database
        - Reactivates previously deactivated stocks
        - Deactivates stocks no longer in universe (optional)

        Returns:
            Dict with sync results:
                - symbols_added: int
                - symbols_removed: int
                - total_symbols: int
                - symbols: List[str] (current active symbols)
        """
        sync_start = datetime.now()

        # Fetch current universe from Finviz
        finviz_symbols = set(self.fetch_large_cap_universe())
        if not finviz_symbols:
            logger.error("Failed to fetch universe from Finviz")
            return {
                'symbols_added': 0,
                'symbols_removed': 0,
                'total_symbols': 0,
                'symbols': [],
                'error': 'Failed to fetch from Finviz'
            }

        # Get current active symbols from database
        db_symbols = set(self.db.get_active_stocks())

        # Calculate changes
        to_add = finviz_symbols - db_symbols
        # Note: We don't remove symbols, just don't include them in scan
        # This preserves historical data

        logger.info(f"Universe sync: {len(finviz_symbols)} from Finviz, "
                   f"{len(db_symbols)} in DB, {len(to_add)} to add")

        # Add new symbols
        added_count = 0
        for symbol in sorted(to_add):
            try:
                self.db.add_stock(symbol)
                added_count += 1
                if added_count % 100 == 0:
                    logger.info(f"Added {added_count}/{len(to_add)} new stocks...")
            except Exception as e:
                logger.warning(f"Failed to add {symbol}: {e}")

        # Get final active symbol list
        final_symbols = self.db.get_active_stocks()

        sync_result = {
            'symbols_added': added_count,
            'symbols_removed': 0,  # We don't delete, just don't scan
            'total_symbols': len(final_symbols),
            'symbols': final_symbols,
            'finviz_count': len(finviz_symbols)
        }

        # Record sync history
        self.db.save_universe_sync({
            'sync_date': sync_start.date().isoformat(),
            'symbols_added': added_count,
            'symbols_removed': 0,
            'total_symbols': len(final_symbols)
        })

        logger.info(f"Universe sync complete: +{added_count} new, "
                   f"{len(final_symbols)} total active")

        return sync_result

    def get_universe_symbols(self) -> List[str]:
        """Get current active universe symbols.

        Returns:
            List of active stock symbols
        """
        return self.db.get_active_stocks()

    def get_universe_size(self) -> int:
        """Get count of active universe symbols.

        Returns:
            Number of active symbols
        """
        return len(self.db.get_active_stocks())


def sync_stock_universe() -> List[str]:
    """Convenience function to sync universe and return symbols.

    Returns:
        List of active stock symbols after sync
    """
    manager = StockUniverseManager()
    result = manager.sync_universe()
    return result['symbols']
