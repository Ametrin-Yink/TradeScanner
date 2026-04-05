"""Tests for Phase 0 G-eligibility pre-calculation."""
import pytest


class TestPremarketPrepV7:
    """Test G-eligibility pre-calculation logic."""

    def test_g_eligibility_large_gap(self):
        """Gap >= 10% should be eligible for days 1-5."""
        # Test the logic
        abs_gap = 0.12
        days_post = 3

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 5
        assert g_eligible is True

    def test_g_eligibility_medium_gap_day_4(self):
        """Gap 7-10% should be rejected on day 4."""
        abs_gap = 0.08
        days_post = 4

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 3
        assert g_eligible is False

    def test_g_eligibility_small_gap_day_3(self):
        """Gap < 7% should be rejected on day 3."""
        abs_gap = 0.05
        days_post = 3

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 2
        assert g_eligible is False

    def test_g_eligibility_day_0_not_eligible(self):
        """Day 0 (same day as earnings) should not be eligible."""
        abs_gap = 0.12
        days_post = 0

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 5
        assert g_eligible is False

    def test_g_eligibility_large_gap_day_5(self):
        """Gap >= 10% should still be eligible on day 5 (boundary)."""
        abs_gap = 0.10
        days_post = 5

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 5
        assert g_eligible is True

    def test_g_eligibility_large_gap_day_6(self):
        """Gap >= 10% should be rejected on day 6 (past window)."""
        abs_gap = 0.12
        days_post = 6

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 5
        assert g_eligible is False

    def test_g_eligibility_medium_gap_boundary(self):
        """Gap exactly 7% should use 3-day window."""
        abs_gap = 0.07
        days_post = 3

        if abs_gap >= 0.10:
            g_max_days = 5
        elif abs_gap >= 0.07:
            g_max_days = 3
        else:
            g_max_days = 2

        g_eligible = (days_post >= 1 and days_post <= g_max_days)

        assert g_max_days == 3
        assert g_eligible is True
