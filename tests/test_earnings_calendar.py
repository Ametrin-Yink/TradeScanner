"""Tests for earnings calendar module."""
import pytest
from datetime import datetime, timedelta
from core.earnings_calendar import EarningsCalendar


class TestEarningsCalendar:
    def test_init(self):
        cal = EarningsCalendar()
        assert cal._cache == {}
        assert cal._cache_date is None

    def test_is_earnings_day_with_no_earnings(self):
        cal = EarningsCalendar()
        # Use test symbol unlikely to have earnings data
        result = cal.is_earnings_day("TEST")
        assert result is False

    def test_is_earnings_day_cache(self):
        cal = EarningsCalendar()
        cal._cache["AAPL"] = datetime.now()
        # Test cache structure
        assert "AAPL" in cal._cache
