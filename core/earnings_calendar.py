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

        Args:
            symbol: Stock symbol

        Returns:
            Earnings date or None
        """
        try:
            ticker = yf.Ticker(symbol)
            earnings = ticker.earnings_dates
            if earnings is None or earnings.empty:
                return None

            # Get future dates
            today = datetime.now().date()
            future_dates = earnings[earnings.index.date >= today]

            if future_dates.empty:
                return None

            # Return nearest future earnings date
            return future_dates.index[0].to_pydatetime()

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
