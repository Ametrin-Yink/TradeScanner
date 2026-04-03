"""Earnings calendar module for blow-off detection pause."""
import logging
from typing import List, Optional
from datetime import datetime, timedelta
import yfinance as yf

logger = logging.getLogger(__name__)


class EarningsCalendar:
    """Fetch and manage stock earnings dates."""

    def __init__(self):
        self._cache = {}
        self._cache_date = None

    def get_earnings_date(self, symbol: str) -> Optional[datetime]:
        """
        Get next earnings date for a stock.

        Optimized to use ticker.calendar (4 quarters) instead of
        ticker.earnings_dates (full history) to reduce memory usage.

        Args:
            symbol: Stock symbol

        Returns:
            Earnings date or None
        """
        try:
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar

            # calendar is a dict with keys like 'Earnings Date', 'Dividend Date', etc.
            if calendar and 'Earnings Date' in calendar:
                earnings_dates = calendar['Earnings Date']
                if earnings_dates and isinstance(earnings_dates, list):
                    # Get the first (nearest) future earnings date
                    today = datetime.now().date()
                    for date_val in earnings_dates:
                        if date_val:
                            try:
                                # Handle both date objects and ISO strings
                                if isinstance(date_val, str):
                                    date = datetime.fromisoformat(date_val).date()
                                elif hasattr(date_val, 'date'):
                                    date = date_val.date()
                                else:
                                    date = date_val  # Already a date object
                                if date >= today:
                                    return datetime.combine(date, datetime.min.time())
                            except:
                                continue

            return None

        except Exception as e:
            logger.warning(f"Failed to get earnings date for {symbol}: {e}")
            return None

    def is_earnings_day(self, symbol: str, date: Optional[datetime] = None) -> bool:
        """
        Check if date is earnings day (±1 day tolerance).

        Args:
            symbol: Stock symbol
            date: Date to check, defaults to today

        Returns:
            True if earnings day
        """
        if date is None:
            date = datetime.now()

        earnings_date = self.get_earnings_date(symbol)
        if earnings_date is None:
            return False

        # ±1 day tolerance (pre/post market)
        delta = abs((earnings_date.date() - date.date()).days)
        return delta <= 1

    def clear_cache(self):
        """Clear cache."""
        self._cache.clear()
        self._cache_date = None
