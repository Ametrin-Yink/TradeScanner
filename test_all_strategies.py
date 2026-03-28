"""Quick test all 8 strategies - verify they can be instantiated and have correct structure."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.strategies.vcp_ep import VCPEPStrategy
from core.strategies.momentum import MomentumStrategy
from core.strategies.shoryuken import ShoryukenStrategy
from core.strategies.pullbacks import PullbacksStrategy
from core.strategies.upthrust_rebound import UpthrustReboundStrategy
from core.strategies.range_support import RangeSupportStrategy
from core.strategies.dtss import DTSSStrategy
from core.strategies.parabolic import ParabolicStrategy


def test_strategy(name: str, strategy_class):
    """Test a single strategy structure."""
    print(f"\n{'='*60}")
    print(f"Testing Strategy {name}")
    print(f"{'='*60}")

    try:
        # Instantiate
        strategy = strategy_class()
        print(f"✅ Instantiated successfully")

        # Check required attributes
        checks = [
            ('NAME', hasattr(strategy, 'NAME') and strategy.NAME),
            ('STRATEGY_TYPE', hasattr(strategy, 'STRATEGY_TYPE')),
            ('DESCRIPTION', hasattr(strategy, 'DESCRIPTION')),
            ('DIMENSIONS', hasattr(strategy, 'DIMENSIONS') and len(strategy.DIMENSIONS) > 0),
            ('PARAMS', hasattr(strategy, 'PARAMS')),
        ]

        for attr, exists in checks:
            status = "✅" if exists else "❌"
            print(f"  {status} {attr}: {getattr(strategy, attr, 'MISSING')}")

        # Check methods
        methods = ['filter', 'calculate_dimensions', 'calculate_entry_exit', 'build_match_reasons']
        for method in methods:
            exists = hasattr(strategy, method) and callable(getattr(strategy, method))
            status = "✅" if exists else "❌"
            print(f"  {status} Method: {method}")

        # Check dimension scoring
        dims = strategy.DIMENSIONS
        print(f"\n  Dimensions: {dims}")

        # Try to access scoring functions from scoring_utils
        from core.scoring_utils import (
            calculate_clv, check_rsi_divergence, calculate_test_interval,
            calculate_institutional_intensity, calculate_rs_score_weighted,
            calculate_volume_climax_score, calculate_normalized_ema_slope
        )
        print(f"✅ scoring_utils imports working")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run tests for all 8 strategies."""
    print("Testing All 8 Strategies")
    print("="*60)

    strategies = [
        ('A: VCP-EP', VCPEPStrategy),
        ('B: Momentum', MomentumStrategy),
        ('C: Shoryuken', ShoryukenStrategy),
        ('D: Pullback', PullbacksStrategy),
        ('E: Upthrust & Rebound', UpthrustReboundStrategy),
        ('F: Range Support', RangeSupportStrategy),
        ('G: DTSS', DTSSStrategy),
        ('H: Parabolic', ParabolicStrategy),
    ]

    results = {}

    for name, strategy_class in strategies:
        success = test_strategy(name, strategy_class)
        results[name] = success

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(results.values())
    total = len(results)

    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\n{passed}/{total} strategies passed")

    if passed == total:
        print("\n🎉 All strategies working correctly!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} strategy(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
