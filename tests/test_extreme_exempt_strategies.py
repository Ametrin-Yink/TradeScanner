"""Test EXTREME_EXEMPT_STRATEGIES configuration.

This test ensures only strategies F (CapitulationRebound) and H (RelativeStrengthLong)
are exempt from extreme_vix position sizing reduction.

See: docs/Strategy_Description_v7.md - extreme_vix regime position sizing rules.
"""

import unittest


class TestExtremeExemptStrategies(unittest.TestCase):
    """Test EXTREME_EXEMPT_STRATEGIES list correctness."""

    def test_exempt_strategies_count(self):
        """Only 2 strategies should be exempt from extreme_vix scalar reduction."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertEqual(
            len(EXTREME_EXEMPT_STRATEGIES),
            2,
            f"Expected 2 exempt strategies, got {len(EXTREME_EXEMPT_STRATEGIES)}: {EXTREME_EXEMPT_STRATEGIES}"
        )

    def test_exempt_strategies_content(self):
        """Exempt strategies must be exactly CapitulationRebound and RelativeStrengthLong."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        expected = ['CapitulationRebound', 'RelativeStrengthLong']
        self.assertEqual(
            EXTREME_EXEMPT_STRATEGIES,
            expected,
            f"Expected {expected}, got {EXTREME_EXEMPT_STRATEGIES}"
        )

    def test_capitulation_rebound_exempt(self):
        """Strategy F (CapitulationRebound) must be in exempt list."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertIn(
            'CapitulationRebound',
            EXTREME_EXEMPT_STRATEGIES,
            "CapitulationRebound must be exempt from extreme_vix scalar reduction"
        )

    def test_relative_strength_long_exempt(self):
        """Strategy H (RelativeStrengthLong) must be in exempt list."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertIn(
            'RelativeStrengthLong',
            EXTREME_EXEMPT_STRATEGIES,
            "RelativeStrengthLong must be exempt from extreme_vix scalar reduction"
        )

    def test_earnings_gap_not_exempt(self):
        """Strategy G (EarningsGap) must NOT be in exempt list."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertNotIn(
            'EarningsGap',
            EXTREME_EXEMPT_STRATEGIES,
            "EarningsGap should NOT be exempt from extreme_vix scalar reduction"
        )

    def test_support_bounce_not_exempt(self):
        """Strategy C (SupportBounce) must NOT be in exempt list."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertNotIn(
            'SupportBounce',
            EXTREME_EXEMPT_STRATEGIES,
            "SupportBounce should NOT be exempt from extreme_vix scalar reduction"
        )

    def test_prebreakout_compression_not_exempt(self):
        """Strategy A2 (PreBreakoutCompression) must NOT be in exempt list."""
        from core.market_regime import EXTREME_EXEMPT_STRATEGIES

        self.assertNotIn(
            'PreBreakoutCompression',
            EXTREME_EXEMPT_STRATEGIES,
            "PreBreakoutCompression should NOT be exempt from extreme_vix scalar reduction"
        )


if __name__ == '__main__':
    unittest.main()
