"""Tests for Strategy A v7.0 VC fix."""
import pytest
from core.strategies.momentum_breakout import MomentumBreakoutStrategy


class TestMomentumBreakoutV7:
    """Test Strategy A1 VC fix."""

    def test_vc_no_penalty_for_high_volume(self):
        """VC should not penalize vol_contract > 1.0 (should give minimal points)."""
        strategy = MomentumBreakoutStrategy()

        # Mock platform with vol_contract > 1.0
        platform = {
            'volume_contraction_ratio': 1.15,  # > 1.0
        }

        # Call _calculate_vc with high vol_contract
        score = strategy._calculate_vc(platform, volume_ratio=2.5, clv=0.80)

        # Should get at least some base points (0.1) + breakout volume points
        # vol_contract > 1.0 = 0.1 base
        # volume_ratio 2.5 = 1.25 (between 2.0-3.0: 1.0 + (2.5-2.0)/1.0 * 0.5 = 1.25)
        # clv 0.80 = 0.5 (between 0.65-0.85: (0.80-0.65)/0.20 * 0.5 = 0.375)
        # Total should be around 1.725
        assert score > 0.5, f"Should not severely penalize high vol_contract, got {score}"

    def test_vc_gives_minimal_points_for_high_volume(self):
        """VC should give exactly 0.1 base points for vol_contract > 1.0."""
        strategy = MomentumBreakoutStrategy()

        platform = {
            'volume_contraction_ratio': 1.50,  # > 1.0
        }

        # Use volume_ratio=1.0 and clv=0.65 to isolate base volume scoring
        # volume_ratio 1.0 = 0 points (at boundary)
        # clv 0.65 = 0 points (at boundary)
        score = strategy._calculate_vc(platform, volume_ratio=1.0, clv=0.65)

        # Should get exactly 0.1 base points for vol_contract > 1.0
        assert score == 0.1, f"Expected 0.1 base points for vol_contract > 1.0, got {score}"

    def test_vc_still_rewards_low_volume_contraction(self):
        """VC should still reward proper volume dry-up (vol_contract < 0.5)."""
        strategy = MomentumBreakoutStrategy()

        platform = {
            'volume_contraction_ratio': 0.45,  # Excellent dry-up
        }

        # Use volume_ratio=1.0 and clv=0.65 to isolate base volume scoring
        score = strategy._calculate_vc(platform, volume_ratio=1.0, clv=0.65)

        # Should get 2.0 base points for excellent dry-up
        assert score == 2.0, f"Expected 2.0 base points for vol_contract < 0.5, got {score}"
