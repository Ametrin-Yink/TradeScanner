"""Stock universe manager with dynamic group maintenance."""
import logging
from datetime import datetime
from typing import List, Set, Dict

from finvizfinance.screener.overview import Overview
from data.db import Database

logger = logging.getLogger(__name__)


class StockGroupManager:
    """Manage stock universe divided into three groups:
    1. large_cap: Market cap > $2B (auto-updated every Monday)
    2. etf: ETF symbols (manually managed)
    3. custom: User-added stocks (manually managed)
    """

    # ETF 列表 - 主要美国市场ETF
    DEFAULT_ETFS = [
        # 大盘指数
        'SPY', 'QQQ', 'IWM', 'DIA', 'VOO', 'VTI',
        # 行业ETF
        'XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLV',
        # 行业细分
        'XBI', 'SMH', 'IGV', 'IYT', 'KRE', 'XRT',
        # 国际
        'EFA', 'EEM', 'IEFA', 'VEA', 'VWO',
        # 债券/商品
        'TLT', 'GLD', 'USO', 'UNG', 'SLV',
        # 波动率
        'VIXY', 'UVXY', 'SVXY'
    ]

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def initialize_groups(self):
        """Initialize database with default ETF group."""
        logger.info("Initializing stock groups...")

        # Run migration first
        self._migrate_existing_stocks()

        # Add default ETFs if not exists
        added_etfs = 0
        for etf in self.DEFAULT_ETFS:
            try:
                # Check if exists
                conn = self.db.get_connection()
                cursor = conn.execute(
                    "SELECT symbol FROM stocks WHERE symbol = ? AND is_active = 1",
                    (etf,)
                )
                if not cursor.fetchone():
                    self.db.add_stock(etf, stock_group='etf')
                    added_etfs += 1
            except Exception as e:
                logger.debug(f"ETF {etf} error: {e}")

        if added_etfs > 0:
            logger.info(f"Added {added_etfs} default ETFs")

        logger.info("Stock groups initialized")

    def _migrate_existing_stocks(self):
        """Migrate existing stocks without group to large_cap."""
        conn = self.db.get_connection()

        # Check if stock_group column exists
        cursor = conn.execute("PRAGMA table_info(stocks)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'stock_group' not in columns:
            # Add stock_group column
            conn.execute("ALTER TABLE stocks ADD COLUMN stock_group TEXT DEFAULT 'large_cap'")
            conn.commit()
            logger.info("Added stock_group column to stocks table")

        # Migrate stocks without group
        cursor = conn.execute(
            "SELECT symbol FROM stocks WHERE stock_group IS NULL OR stock_group = ''"
        )
        stocks_to_migrate = [row[0] for row in cursor.fetchall()]

        for symbol in stocks_to_migrate:
            conn.execute(
                "UPDATE stocks SET stock_group = 'large_cap' WHERE symbol = ?",
                (symbol,)
            )
        conn.commit()

        if stocks_to_migrate:
            logger.info(f"Migrated {len(stocks_to_migrate)} stocks to large_cap group")

    def update_large_cap_group(self) -> Dict[str, int]:
        """
        Update large_cap group by fetching from Finviz.
        Runs automatically every Monday.

        Returns:
            Dict with 'added', 'removed', 'total' counts
        """
        logger.info("Updating large_cap group from Finviz...")

        # Fetch current large cap stocks from Finviz
        try:
            overview = Overview()
            overview.set_filter(filters_dict={'Market Cap.': '+Mid (over $2bln)'})
            df = overview.screener_view()
            current_large_cap = set(df['Ticker'].tolist())
            logger.info(f"Fetched {len(current_large_cap)} stocks from Finviz")
        except Exception as e:
            logger.error(f"Failed to fetch from Finviz: {e}")
            return {'added': 0, 'removed': 0, 'total': 0, 'error': str(e)}

        # Get current large_cap stocks from database
        current_in_db = set(self.db.get_active_stocks(group='large_cap'))

        # Calculate changes
        to_add = current_large_cap - current_in_db
        to_remove = current_in_db - current_large_cap

        # Add new stocks
        added_count = 0
        for symbol in to_add:
            try:
                # Check if stock exists in other groups
                conn = self.db.get_connection()
                cursor = conn.execute(
                    "SELECT stock_group, is_active FROM stocks WHERE symbol = ?",
                    (symbol,)
                )
                result = cursor.fetchone()

                if result:
                    existing_group, is_active = result
                    if existing_group in ('etf', 'custom'):
                        # Keep ETF/custom stocks as-is, don't change group
                        logger.debug(f"Keeping {symbol} in {existing_group} group")
                        continue
                    else:
                        # Reactivate if deactivated
                        if not is_active:
                            self.db.reactivate_stock(symbol)
                            logger.info(f"Reactivated {symbol}")
                else:
                    # New stock - add to large_cap
                    self.db.add_stock(symbol, stock_group='large_cap')
                    added_count += 1
            except Exception as e:
                logger.warning(f"Failed to add {symbol}: {e}")

        # Remove stocks that no longer qualify
        removed_count = 0
        for symbol in to_remove:
            try:
                self.db.deactivate_stock(symbol)
                removed_count += 1
                logger.info(f"Deactivated {symbol} (no longer >$2B)")
            except Exception as e:
                logger.warning(f"Failed to deactivate {symbol}: {e}")

        total = len(self.db.get_active_stocks(group='large_cap'))

        logger.info(f"large_cap update complete: +{added_count}, -{removed_count}, total={total}")

        return {
            'added': added_count,
            'removed': removed_count,
            'total': total
        }

    def add_custom_stock(self, symbol: str, name: str = "") -> bool:
        """
        Add a stock to custom group (manually managed).

        Args:
            symbol: Stock symbol
            name: Optional stock name

        Returns:
            True if added successfully
        """
        try:
            self.db.add_stock(symbol, name=name, stock_group='custom')
            logger.info(f"Added {symbol} to custom group")
            return True
        except Exception as e:
            logger.error(f"Failed to add {symbol}: {e}")
            return False

    def remove_custom_stock(self, symbol: str) -> bool:
        """Remove a stock from custom group (soft delete)."""
        try:
            # Verify it's in custom group
            conn = self.db.get_connection()
            cursor = conn.execute(
                "SELECT stock_group FROM stocks WHERE symbol = ? AND is_active = 1",
                (symbol,)
            )
            result = cursor.fetchone()

            if not result or result[0] != 'custom':
                logger.warning(f"{symbol} is not in custom group or not active")
                return False

            self.db.deactivate_stock(symbol)
            logger.info(f"Removed {symbol} from custom group")
            return True
        except Exception as e:
            logger.error(f"Failed to remove {symbol}: {e}")
            return False

    def add_etf(self, symbol: str, name: str = "") -> bool:
        """Add an ETF to etf group (manually managed)."""
        try:
            self.db.add_stock(symbol, name=name, stock_group='etf')
            logger.info(f"Added {symbol} to ETF group")
            return True
        except Exception as e:
            logger.error(f"Failed to add ETF {symbol}: {e}")
            return False

    def remove_etf(self, symbol: str) -> bool:
        """Remove an ETF from etf group (soft delete)."""
        try:
            conn = self.db.get_connection()
            cursor = conn.execute(
                "SELECT stock_group FROM stocks WHERE symbol = ? AND is_active = 1",
                (symbol,)
            )
            result = cursor.fetchone()

            if not result or result[0] != 'etf':
                logger.warning(f"{symbol} is not in ETF group or not active")
                return False

            self.db.deactivate_stock(symbol)
            logger.info(f"Removed {symbol} from ETF group")
            return True
        except Exception as e:
            logger.error(f"Failed to remove ETF {symbol}: {e}")
            return False

    def get_group_summary(self) -> Dict[str, Dict]:
        """Get summary of all groups."""
        summary = {}
        for group in ['large_cap', 'etf', 'custom']:
            stocks = self.db.get_active_stocks(group=group)
            summary[group] = {
                'count': len(stocks),
                'sample': stocks[:5] if stocks else []
            }
        return summary

    def should_update_large_cap(self) -> bool:
        """Check if it's Monday and large_cap should be updated."""
        today = datetime.now()
        return today.weekday() == 0  # Monday = 0


def run_monday_update():
    """Run large_cap update (called by cron on Mondays)."""
    manager = StockGroupManager()
    result = manager.update_large_cap_group()
    print(f"Monday update: +{result['added']}, -{result['removed']}, total={result['total']}")
    return result


def initialize_stock_groups():
    """Initialize stock groups (run once on setup)."""
    manager = StockGroupManager()
    manager.initialize_groups()


if __name__ == "__main__":
    # Run Monday update
    run_monday_update()
