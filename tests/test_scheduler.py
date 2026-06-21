"""Tests for scheduler trading day check."""
import pytest
from datetime import date, datetime
from unittest.mock import patch, MagicMock


class TestIsTradingDay:
    """Tests for scheduler.is_trading_day()."""

    def test_weekday_with_calendar(self):
        """A weekday with valid NYSE schedule should be a trading day."""
        from scheduler import is_trading_day

        with patch('scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 22)  # Monday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.now.strftime.return_value = '2026-06-22'
            mock_date = date(2026, 6, 22)
            mock_dt.now.date.return_value = mock_date

            with patch('pandas_market_calendars.get_calendar') as mock_get_cal:
                mock_cal = MagicMock()
                mock_get_cal.return_value = mock_cal
                mock_schedule = MagicMock()
                mock_schedule.empty = False
                mock_cal.schedule.return_value = mock_schedule

                assert is_trading_day() is True

    def test_saturday_returns_false(self):
        """Saturday should not be a trading day (empty NYSE schedule)."""
        from scheduler import is_trading_day

        with patch('scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 20)  # Saturday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.now.date.return_value = date(2026, 6, 20)

            with patch('pandas_market_calendars.get_calendar') as mock_get_cal:
                mock_cal = MagicMock()
                mock_get_cal.return_value = mock_cal
                mock_schedule = MagicMock()
                mock_schedule.empty = True
                mock_cal.schedule.return_value = mock_schedule

                assert is_trading_day() is False

    def test_holiday_returns_false(self):
        """A holiday (empty NYSE schedule) should not be a trading day."""
        from scheduler import is_trading_day

        with patch('scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 12, 25)  # Christmas
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.now.date.return_value = date(2026, 12, 25)

            with patch('pandas_market_calendars.get_calendar') as mock_get_cal:
                mock_cal = MagicMock()
                mock_get_cal.return_value = mock_cal
                mock_schedule = MagicMock()
                mock_schedule.empty = True
                mock_cal.schedule.return_value = mock_schedule

                assert is_trading_day() is False

    def _patch_import_missing(self, name):
        """Patch __import__ to raise ImportError for a specific module."""
        original_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __builtins__.__import__

        def _mock_import(mod_name, *args, **kwargs):
            if mod_name == name:
                raise ImportError(f"No module named '{name}'")
            return original_import(mod_name, *args, **kwargs)
        return _mock_import

    def test_fallback_weekday_when_library_missing(self):
        """Fallback weekday check should return True on a Monday."""
        from scheduler import is_trading_day

        with patch('scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 22)  # Monday
            mock_dt.now.weekday.return_value = 0  # Monday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.now.strftime.return_value = '2026-06-22'
            mock_dt.now.date.return_value = date(2026, 6, 22)

            with patch('builtins.__import__', self._patch_import_missing('pandas_market_calendars')):
                assert is_trading_day() is True

    def test_fallback_saturday_when_library_missing(self):
        """Fallback weekday check should return False on Saturday."""
        from scheduler import is_trading_day

        with patch('builtins.__import__', self._patch_import_missing('pandas_market_calendars')):
            with patch('scheduler.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 6, 20)  # Saturday
                mock_dt.now.weekday.return_value = 5  # Saturday
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                mock_dt.now.date.return_value = date(2026, 6, 20)

                assert is_trading_day() is False
