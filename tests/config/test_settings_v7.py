"""Tests for settings v7.0 changes."""
import pytest
from config.settings import settings


class TestSettingsV7:
    """Test settings changes for v7.0."""

    def test_retention_days_updated(self):
        """Report retention should be 60 days (was 15)."""
        retention = settings.get('report', {}).get('retention_days')
        assert retention == 60, f"retention_days should be 60, got {retention}"
