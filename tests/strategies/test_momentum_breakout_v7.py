"""Tests for Strategy A1 VC structure (v8.0 - BS/VC split)."""
import pytest
from core.strategies.momentum_breakout import MomentumBreakoutStrategy


class TestMomentumBreakoutV7:
    """Test Strategy A1 VC structure after BS/VC split."""

    def test_vc_no_penalty_for_high_volume(self):
        """VC should not penalize vol_contract > 1.0 (should give minimal points)."""
        strategy = MomentumBreakoutStrategy()

        platform = {
            'volume_contraction_ratio': 1.15,  # > 1.0
        }

        score = strategy._calculate_vc(platform, volume_ratio=2.5, clv=0.80)

        # vol_contract > 1.0 = 0.2 base
        # volume_ratio 2.5 = 1.25
        # clv 0.80 = 0.833
        # Total ~ 2.28
        assert score > 1.5, f"Should have meaningful VC score with high volume surge, got {score}"

    def test_vc_gives_minimal_points_for_high_volume(self):
        """VC should give minimal base points for vol_contract > 1.0 with no volume surge."""
        strategy = MomentumBreakoutStrategy()

        platform = {
            'volume_contraction_ratio': 1.50,  # > 1.0
        }

        score = strategy._calculate_vc(platform, volume_ratio=1.0, clv=0.65)

        # vol_contract > 1.0 = 0.2
        # volume_ratio 1.0 = 0.0
        # clv 0.65 = 0.425
        # Total = 0.625
        assert abs(score - 0.62) < 0.02, f"Expected ~0.62 base points for vol_contract > 1.0, got {score}"

    def test_vc_still_rewards_low_volume_contraction(self):
        """VC should still reward proper volume dry-up (vol_contract < 0.5)."""
        strategy = MomentumBreakoutStrategy()

        platform = {
            'volume_contraction_ratio': 0.45,  # Excellent dry-up
        }

        score = strategy._calculate_vc(platform, volume_ratio=1.0, clv=0.65)

        # vol_contract < 0.5 = 1.5
        # volume_ratio 1.0 = 0.0
        # clv 0.65 = 0.425
        # Total = 1.925
        assert abs(score - 1.93) < 0.02, f"Expected ~1.93 for vol_contract < 0.5, got {score}"
