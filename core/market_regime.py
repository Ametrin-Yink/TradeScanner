import logging
from typing import Dict
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Phase 1 Allocation Table (30 total slots) - clean A-H naming
REGIME_ALLOCATION_TABLE: Dict[str, Dict[str, int]] = {
    'bull_strong': {
        'A': 8,  # MomentumBreakout
        'B': 6,  # PullbackEntry
        'C': 4,  # SupportBounce
        'D': 0,  # DistributionTop
        'E': 0,  # AccumulationBottom
        'F': 0,  # CapitulationRebound
        'G': 8,  # EarningsGap
        'H': 4,  # RelativeStrengthLong
    },
    'bull_moderate': {
        'A': 8,
        'B': 6,
        'C': 4,
        'D': 0,
        'E': 0,
        'F': 0,
        'G': 8,
        'H': 4,
    },
    'neutral': {
        'A': 6,
        'B': 5,
        'C': 5,
        'D': 4,
        'E': 4,
        'F': 0,
        'G': 3,
        'H': 3,
    },
    'bear_moderate': {
        'A': 4,
        'B': 4,
        'C': 4,
        'D': 5,
        'E': 5,
        'F': 2,
        'G': 0,
        'H': 6,
    },
    'bear_strong': {
        'A': 0,
        'B': 0,
        'C': 4,
        'D': 6,
        'E': 6,
        'F': 8,
        'G': 0,
        'H': 6,
    },
    'extreme_vix': {
        'A': 0,
        'B': 0,
        'C': 0,
        'D': 3,
        'E': 3,
        'F': 12,
        'G': 0,
        'H': 12,
    }
}

# Regime-adaptive position sizing scalars
REGIME_SCALARS = {
    'bull_strong': {'long': 1.0, 'short': 0.3},
    'bull_moderate': {'long': 1.0, 'short': 0.3},
    'neutral': {'long': 0.8, 'short': 0.8},
    'bear_moderate': {'long': 0.5, 'short': 1.0},
    'bear_strong': {'long': 0.5, 'short': 1.0},
    'extreme_vix': {'long': 0.3, 'short': 0.5}
}

# Strategies exempt from extreme regime scalar reduction
EXTREME_EXEMPT_STRATEGIES = ['CapitulationRebound', 'RelativeStrengthLong', 'EarningsGap', 'SupportBounce']


class MarketRegimeDetector:
    """Detect market regime from SPY/VIX technicals."""

    def detect_regime(self, spy_df: pd.DataFrame, vix_df: pd.DataFrame) -> str:
        """
        Detect market regime based on SPY EMAs and VIX level.

        Priority:
        1. VIX > 30 → extreme_vix (regardless of SPY)
        2. SPY trend analysis for bull/bear/neutral

        Args:
            spy_df: SPY OHLCV DataFrame (needs at least 200 days)
            vix_df: VIX DataFrame with 'close' column

        Returns:
            Regime string from REGIME_ALLOCATION_TABLE keys
        """
        # Check VIX first
        vix_current = vix_df['close'].iloc[-1] if vix_df is not None and not vix_df.empty else 20.0

        if vix_current > 30:
            logger.info(f"Regime: extreme_vix (VIX={vix_current:.1f})")
            return 'extreme_vix'

        # Calculate SPY EMAs
        if spy_df is None or len(spy_df) < 200:
            logger.warning("Insufficient SPY data, defaulting to neutral")
            return 'neutral'

        close = spy_df['close']
        ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        current_price = close.iloc[-1]

        # Check EMA50 slope (10 days ago vs now)
        ema50_10d_ago = close.ewm(span=50, adjust=False).mean().iloc[-10]
        ema50_rising = ema50 > ema50_10d_ago

        # Determine regime
        if current_price > ema50 and ema50 > ema200:
            # Bull regime
            if vix_current <= 20:
                regime = 'bull_strong'
            else:
                regime = 'bull_moderate'
        elif current_price < ema50 and ema50 < ema200:
            # Bear regime
            if ema50_rising:
                regime = 'bear_moderate'
            else:
                regime = 'bear_strong'
        else:
            # Neutral - price between EMAs or mixed alignment
            regime = 'neutral'

        logger.info(f"Regime: {regime} (SPY=${current_price:.2f}, EMA50=${ema50:.2f}, EMA200=${ema200:.2f}, VIX={vix_current:.1f})")
        return regime

    def detect_regime_ai(self, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                         tavily_results: list, ai_sentiment: str) -> str:
        """
        Select regime from 6 options based on technical + news analysis.

        Priority:
        1. If VIX > 30 AND tavily shows fear/extreme volatility -> extreme_vix
        2. Use ai_sentiment if confidence >= 70
        3. Fallback to technical detection

        Returns one of: bull_strong, bull_moderate, neutral,
        bear_moderate, bear_strong, extreme_vix
        """
        vix_current = vix_df['close'].iloc[-1] if vix_df is not None else 20.0

        # Hard rule: VIX > 30 takes precedence
        if vix_current > 30:
            return 'extreme_vix'

        # Trust AI sentiment if provided
        valid_regimes = ['bull_strong', 'bull_moderate', 'neutral',
                         'bear_moderate', 'bear_strong', 'extreme_vix']
        if ai_sentiment in valid_regimes:
            return ai_sentiment

        # Fallback to technical
        return self.detect_regime(spy_df, vix_df)

    def get_allocation(self, regime: str) -> Dict[str, int]:
        """
        Get strategy slot allocation for a regime.

        Args:
            regime: Regime string from detect_regime()

        Returns:
            Dict mapping strategy letters (A-H) to slot counts
        """
        allocation = REGIME_ALLOCATION_TABLE.get(regime)
        if allocation is None:
            logger.warning(f"Unknown regime '{regime}', using neutral")
            allocation = REGIME_ALLOCATION_TABLE['neutral']
        return allocation.copy()

    def get_position_scalar(self, regime: str, direction: str, strategy_name: str) -> float:
        """
        Get position sizing scalar for regime/direction/strategy.

        Args:
            regime: Regime string
            direction: 'long' or 'short'
            strategy_name: Strategy class NAME

        Returns:
            Scalar multiplier (0.3 to 1.0)
        """
        # Check exemption
        if regime == 'extreme_vix' and strategy_name in EXTREME_EXEMPT_STRATEGIES:
            logger.debug(f"Strategy {strategy_name} exempt from extreme scalar")
            return 1.0

        scalar = REGIME_SCALARS.get(regime, {}).get(direction, 1.0)
        return scalar
