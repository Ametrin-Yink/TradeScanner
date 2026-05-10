#!/usr/bin/env python3
"""Test Phase 3 AI scoring in isolation - mimics exactly what the pipeline does."""
import logging
import sys
import json
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

# Import the actual components
from core.screener import StrategyMatch
from core.ai_confidence_scorer import AIConfidenceScorer


def make_candidate(symbol, strategy, rsi, volume_ratio, adr_pct, tier, score, rs_pct):
    """Create a realistic StrategyMatch candidate."""
    return StrategyMatch(
        symbol=symbol,
        strategy=strategy,
        entry_price=100.0,
        stop_loss=97.0,
        take_profit=109.0,
        confidence=0,  # placeholder, AI scoring will overwrite
        match_reasons=["RS > 50", "EMA aligned", f"Strategy conditions met"],
        technical_snapshot={
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "adr_percent": adr_pct,
            "ema_alignment": True,
            "ema21_distance_pct": 2.5,
            "rs_percentile": rs_pct,
            "tier": tier,
            "score": score,
            "sector": "Technology",
            "current_price": 100.0,
            "atr": 2.5,
        }
    )


def test_phase3_scoring():
    """Run Phase 3 AI scoring on 8 realistic candidates (2 batches of 4)."""

    candidates = [
        make_candidate("AAPL", "Momentum", 65, 1.8, 2.8, "A", 75, 85),
        make_candidate("MSFT", "Shoryuken", 45, 1.2, 2.2, "A", 70, 75),
        make_candidate("GOOGL", "Pullbacks", 40, 0.9, 2.5, "B", 60, 70),
        make_candidate("TSLA", "RangeSupport", 35, 1.5, 3.5, "B", 55, 65),
        make_candidate("NVDA", "Momentum", 70, 2.0, 3.2, "S", 85, 95),
        make_candidate("AMD", "Momentum", 55, 1.3, 2.8, "A", 72, 80),
        make_candidate("AMZN", "Pullbacks", 42, 0.8, 2.0, "B", 58, 68),
        make_candidate("META", "Shoryuken", 48, 1.1, 2.4, "A", 68, 78),
    ]

    print("=" * 60)
    print("Phase 3 AI Scoring Test - 8 candidates, 2 batches")
    print("=" * 60)
    print(f"Candidates: {[c.symbol for c in candidates]}")
    print(f"Market sentiment: neutral")
    print()

    scorer = AIConfidenceScorer()

    overall_start = time.time()
    try:
        results = scorer.score_candidates(candidates, market_sentiment='neutral')
        elapsed = time.time() - overall_start

        print(f"\nTotal time: {elapsed:.1f}s")
        print(f"Scored {len(results)} candidates:")
        for r in results:
            print(f"  {r.symbol}: confidence={r.confidence}, strategy={r.strategy}")
            print(f"    reasoning: {r.reasoning[:100]}...")
        print("\nSUCCESS: Phase 3 AI scoring works correctly")

    except Exception as e:
        elapsed = time.time() - overall_start
        print(f"\nFAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == '__main__':
    ok = test_phase3_scoring()
    sys.exit(0 if ok else 1)
