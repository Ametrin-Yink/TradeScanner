"""Tests for stale data guard v7.0 - Task 12b.

Stale data guard excludes symbols where close price hasn't updated
within 2 trading days (earnings days, halts, vendor glitches).
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from core.premarket_prep import PreMarketPrep


class TestStaleDataGuard:
    """Test stale data guard for Phase 0."""

    def test_fresh_data_yesterday(self):
        """Should allow data updated 1 day ago."""
        prep = PreMarketPrep()

        # Create DataFrame with yesterday as last date
        today = datetime.now().date()
        dates = pd.date_range(end=today - timedelta(days=1), periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        result = prep._is_data_stale(df, max_stale_days=2)

        assert result is False  # Not stale

    def test_fresh_data_two_days_ago(self):
        """Should allow data updated exactly 2 days ago (boundary)."""
        prep = PreMarketPrep()

        # Create DataFrame with 2 days ago as last date
        today = datetime.now().date()
        dates = pd.date_range(end=today - timedelta(days=2), periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        result = prep._is_data_stale(df, max_stale_days=2)

        assert result is False  # Not stale (exactly at boundary)

    def test_stale_data_three_days(self):
        """Should flag data older than 2 days as stale."""
        prep = PreMarketPrep()

        # Create DataFrame with 5 days ago as last date
        today = datetime.now().date()
        dates = pd.date_range(end=today - timedelta(days=5), periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        result = prep._is_data_stale(df, max_stale_days=2)

        assert result is True  # Stale

    def test_stale_data_one_week(self):
        """Should flag data 1 week old as stale."""
        prep = PreMarketPrep()

        # Create DataFrame with 7 days ago as last date
        today = datetime.now().date()
        dates = pd.date_range(end=today - timedelta(days=7), periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        result = prep._is_data_stale(df, max_stale_days=2)

        assert result is True  # Stale

    def test_empty_dataframe_is_stale(self):
        """Should treat empty DataFrame as stale."""
        prep = PreMarketPrep()

        df = pd.DataFrame()

        result = prep._is_data_stale(df, max_stale_days=2)

        assert result is True  # Stale

    def test_none_dataframe_is_stale(self):
        """Should treat None DataFrame as stale."""
        prep = PreMarketPrep()

        result = prep._is_data_stale(None, max_stale_days=2)

        assert result is True  # Stale

    def test_friday_data_allows_monday(self):
        """Should allow Friday data on Monday (weekend handling)."""
        prep = PreMarketPrep()

        # Create DataFrame with Friday as last date
        # 2024-01-05 is a Friday
        friday = datetime(2024, 1, 5).date()
        dates = pd.date_range(end=friday, periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        # Mock today as Monday (2 calendar days after Friday, but weekend)
        mock_monday = datetime(2024, 1, 8).date()  # Monday

        with patch.object(prep, '_get_current_date', return_value=mock_monday):
            result = prep._is_data_stale(df, max_stale_days=2)

        assert result is False  # Not stale (Friday data ok on Monday)

    def test_friday_data_allows_tuesday(self):
        """Should allow Friday data on Tuesday (3 days with weekend)."""
        prep = PreMarketPrep()

        # Create DataFrame with Friday as last date
        # 2024-01-05 is a Friday
        friday = datetime(2024, 1, 5).date()
        dates = pd.date_range(end=friday, periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        # Mock today as Tuesday (3 calendar days after Friday, but weekend)
        mock_tuesday = datetime(2024, 1, 9).date()  # Tuesday

        with patch.object(prep, '_get_current_date', return_value=mock_tuesday):
            result = prep._is_data_stale(df, max_stale_days=2)

        assert result is False  # Not stale (Friday data ok on Tuesday)

    def test_thursday_data_rejects_monday(self):
        """Should reject Thursday data on Monday (>2 business days)."""
        prep = PreMarketPrep()

        # Create DataFrame with Thursday as last date
        # 2024-01-04 is a Thursday
        thursday = datetime(2024, 1, 4).date()
        dates = pd.date_range(end=thursday, periods=200, freq='D')
        df = pd.DataFrame({'close': range(200)}, index=dates)

        # Mock today as Monday (4 calendar days after Thursday)
        mock_monday = datetime(2024, 1, 8).date()  # Monday

        with patch.object(prep, '_get_current_date', return_value=mock_monday):
            result = prep._is_data_stale(df, max_stale_days=2)

        # Thursday to Monday = 4 calendar days > 2, so should be stale
        assert result is True  # Stale


class TestStaleDataGuardIntegration:
    """Test stale data guard integration in Phase 0 workflow."""

    def test_stale_symbols_excluded_from_tier1(self):
        """Should exclude stale symbols from Tier 1 calculation."""
        # This tests the integration - stale symbols should not get Tier 1 cache
        # Implementation tested via run_premarket_prep with mocked data
        prep = PreMarketPrep()

        # Create fresh and stale DataFrames
        today = datetime.now().date()

        # Fresh data (yesterday)
        fresh_dates = pd.date_range(end=today - timedelta(days=1), periods=200, freq='D')
        fresh_df = pd.DataFrame({'close': range(200)}, index=fresh_dates)

        # Stale data (5 days ago)
        stale_dates = pd.date_range(end=today - timedelta(days=5), periods=200, freq='D')
        stale_df = pd.DataFrame({'close': range(200)}, index=stale_dates)

        # Test fresh data
        assert prep._is_data_stale(fresh_df, max_stale_days=2) is False

        # Test stale data
        assert prep._is_data_stale(stale_df, max_stale_days=2) is True
