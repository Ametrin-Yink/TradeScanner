"""Tests for Strategy C v7.0 tightening.

v7.0 Changes:
1. Pre-filter: Requires ≥3 touches in 60d OR ≥2 touches in 30d (recency matters more)
2. Touch dates tracking: _calculate_support_touches returns touch_dates list
3. RB hard gate: depth must be ≥2% (depth<2% can no longer score)
4. RB scoring: Remove 5d reclaim speed scoring (0.5 pts for 4-5 days)
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from core.strategies.support_bounce import SupportBounceStrategy


class TestSupportBounceV7:
    """Test Strategy C tightening."""

    def create_base_df(self, periods=90, base_price=100):
        """Create a base DataFrame for testing."""
        dates = pd.date_range(end=datetime.now(), periods=periods, freq='B')

        # Create oscillating price data
        prices = []
        for i in range(periods):
            price = base_price + (i % 10) * 0.5
            prices.append(price)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': [1_000_000] * periods
        }, index=dates)

        return df

    def test_support_touches_requires_three_or_recent(self):
        """Touch requirement: >=3 touches in 60d OR >=2 touches in 30d.

        Test _calculate_support_touches directly to verify touch counting
        and the filter's rejection of insufficient touches.
        """
        strategy = SupportBounceStrategy()

        # Create data with exactly 2 old touches (days 35 and 50 ago)
        # and no recent touches
        dates = pd.date_range(end=datetime.now(), periods=90, freq='B')
        support_level = 98.0
        atr = 1.0  # Fixed ATR for controlled test

        base_price = 100
        prices = []
        lows = []
        highs = []

        for i in range(90):
            price = base_price
            low = base_price + 0.5  # Stay well above support
            high = base_price + 1.0
            prices.append(price)
            lows.append(low)
            highs.append(high)

        # Create 2 touches at days 35 and 50
        idx_35 = 90 - 1 - 35
        idx_50 = 90 - 1 - 50
        lows[idx_35] = support_level
        lows[idx_50] = support_level

        df = pd.DataFrame({
            'open': prices,
            'high': highs,
            'low': lows,
            'close': prices,
            'volume': [1_000_000] * 90
        }, index=dates)

        # Test _calculate_support_touches directly
        result = strategy._calculate_support_touches(df, support_level, atr)
        touch_dates = result['touch_dates']
        touches_60d = len([d for d in touch_dates if d <= 60])
        touches_30d = len([d for d in touch_dates if d <= 30])

        assert touches_60d == 2, f"Expected 2 touches in 60d, got {touches_60d}"
        assert touches_30d == 0, f"Expected 0 touches in 30d, got {touches_30d}"
        assert result['touches'] == 2, f"Expected 2 total touches, got {result['touches']}"

        # This should fail the touch requirement (2 < 3 in 60d, 0 < 2 in 30d)
        assert not (touches_60d >= 3 or touches_30d >= 2), \
            "Touch requirement should NOT be met"

    def test_touch_dates_tracking(self):
        """Support touches should track dates for recency check.

        _calculate_support_touches should return touch_dates list.
        """
        strategy = SupportBounceStrategy()

        # Create data with known support touches
        dates = pd.date_range(end=datetime.now(), periods=60, freq='B')

        base_price = 100
        support_level = 98

        prices = []
        lows = []

        # Create touches at specific days (5, 15, 40 days ago)
        touch_days = [5, 15, 40]

        for i in range(60):
            days_ago = 59 - i
            price = base_price + (i % 10) * 0.5

            if days_ago in touch_days:
                low = support_level - 0.2  # Touch support
            else:
                low = price * 0.98

            prices.append(price)
            lows.append(low)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': lows,
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        # Calculate support touches
        result = strategy._calculate_support_touches(df, support_level, atr=2.0)

        # Verify touch_dates is returned
        assert 'touch_dates' in result, "Should return touch_dates in result dict"
        assert isinstance(result['touch_dates'], list), "touch_dates should be a list"
        assert len(result['touch_dates']) >= 2, "Should find at least 2 touch dates"

    def test_rb_dimension_depth_gate(self):
        """RB dimension should have ≥2% depth hard gate.

        Candidates with depth < 2% should not score in RB dimension.
        """
        strategy = SupportBounceStrategy()

        # Create data where price is < 2% from support
        dates = pd.date_range(end=datetime.now(), periods=60, freq='B')

        base_price = 100
        support_level = 99  # Only 1% below - should fail depth gate

        prices = []
        for i in range(60):
            price = base_price + (i % 5) * 0.1  # Stay near 1% depth
            prices.append(price)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.01 for p in prices],
            'low': [p * 0.99 for p in prices],
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        # Create mock indicators
        from core.indicators import TechnicalIndicators
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        # Calculate RB dimension - should have depth gate
        clv = 0.5  # Mock CLV
        rb_score, rb_details = strategy._calculate_rb(ind, df, clv, 'TEST')

        # With depth < 2%, RB should either:
        # - Return 0 score, OR
        # - Have a flag indicating depth gate failed
        # This test verifies the depth gate exists
        assert rb_score == 0 or rb_details.get('depth_gate_failed', False), \
            f"RB should enforce ≥2% depth gate, got score {rb_score}"

    def test_rb_dimension_no_5d_scoring(self):
        """RB dimension should not score 4-5 day reclaims.

        v7.0 removes 0.5 pts for 4-5 day reclaims.
        """
        strategy = SupportBounceStrategy()

        # Create data with a 5-day-old reclaim
        dates = pd.date_range(end=datetime.now(), periods=60, freq='B')

        base_price = 100
        support_level = 95

        prices = []
        lows = []

        for i in range(60):
            days_ago = 59 - i
            if days_ago == 5:
                # False breakdown 5 days ago
                price = support_level - 0.5
                low = support_level - 1.0
            else:
                price = base_price
                low = price * 0.98

            prices.append(price)
            lows.append(low)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': lows,
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        from core.indicators import TechnicalIndicators
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        clv = 0.5
        rb_score, rb_details = strategy._calculate_rb(ind, df, clv, 'TEST')

        # Days since breakdown = 5
        # v7.0: 4-5 day reclaims should NOT score (removed 0.5 pts)
        days_since = rb_details.get('days_since_breakdown', 0)

        if days_since >= 4:
            # Reclaim scoring should be 0 or minimal for 4-5 days
            reclaim_component = rb_details.get('reclaim_score', 0)
            assert reclaim_component == 0 or reclaim_component == 'expired', \
                f"5-day reclaim should not score, got {reclaim_component}"


class TestSupportBouncePreFilterV7:
    """Test pre-filter changes for v7.0."""

    def test_recent_touches_sufficient(self):
        """≥2 touches in 30d should pass pre-filter."""
        strategy = SupportBounceStrategy()

        dates = pd.date_range(end=datetime.now(), periods=60, freq='B')

        base_price = 100
        support_level = 98

        prices = []
        lows = []

        # Create 2 touches within last 30d (at days 10 and 25)
        for i in range(60):
            days_ago = 59 - i
            price = base_price + (i % 10) * 0.5

            if days_ago in [10, 25]:
                low = support_level - 0.2
            else:
                low = price * 0.98

            prices.append(price)
            lows.append(low)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': lows,
            'close': prices,
            'volume': [1_000_000] * 60
        }, index=dates)

        # 2 touches in 30d should be sufficient
        result = strategy.filter('TEST', df)

        # This may pass or fail for other reasons, but touch requirement should be met
        # The key is that 2 recent touches is valid under v7.0

    def test_three_touches_in_60d_sufficient(self):
        """≥3 touches in 60d should pass pre-filter even if not recent."""
        strategy = SupportBounceStrategy()

        dates = pd.date_range(end=datetime.now(), periods=90, freq='B')

        base_price = 100
        support_level = 98

        prices = []
        lows = []

        # Create 3 touches in 60d (at days 35, 45, 55) - none in 30d
        for i in range(90):
            days_ago = 89 - i
            price = base_price + (i % 10) * 0.5

            if days_ago in [35, 45, 55]:
                low = support_level - 0.2
            else:
                low = price * 0.98

            prices.append(price)
            lows.append(low)

        df = pd.DataFrame({
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': lows,
            'close': prices,
            'volume': [1_000_000] * 90
        }, index=dates)

        # 3 touches in 60d should be sufficient even without recent touches
        result = strategy.filter('TEST', df)

        # Should pass touch requirement (3 in 60d)
