"""Support and Resistance level calculator using 5 methods."""
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class Level:
    """A single S/R level with metadata."""
    price: float
    method: str
    strength: float = 1.0
    touches: int = 0


class SupportResistanceCalculator:
    """Calculate support/resistance levels using 5 methods."""

    def __init__(self, df: pd.DataFrame):
        """
        Initialize with OHLCV data.

        Args:
            df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
        """
        self.df = df.copy()
        self.levels: List[Level] = []

    def calculate_all(self) -> Dict[str, List[float]]:
        """
        Calculate all S/R levels using 5 methods.

        Returns:
            Dict with 'support' and 'resistance' lists of prices
        """
        # Handle empty dataframe
        if len(self.df) == 0:
            return {'support': [], 'resistance': [], 'all_levels': []}

        self.levels = []

        # Run all 5 methods
        self._calc_pivot_points()
        self._calc_recent_highs_lows()
        self._calc_volume_profile()
        self._calc_psychological_levels()
        self._calc_trading_range()

        # Cluster and merge levels
        return self._cluster_levels()

    def _calc_pivot_points(self):
        """Calculate classic pivot points from recent data."""
        if len(self.df) < 2:
            return

        # Use last 20 days
        recent = self.df.tail(20)

        for i in range(1, len(recent)):
            prev = recent.iloc[i-1]
            high, low, close = prev['high'], prev['low'], prev['close']

            # Classic pivot
            pivot = (high + low + close) / 3

            # Support levels
            s1 = 2 * pivot - high
            s2 = pivot - (high - low)

            # Resistance levels
            r1 = 2 * pivot - low
            r2 = pivot + (high - low)

            self.levels.append(Level(pivot, 'pivot', strength=2.0))
            self.levels.append(Level(s1, 'pivot', strength=1.0))
            self.levels.append(Level(s2, 'pivot', strength=0.8))
            self.levels.append(Level(r1, 'pivot', strength=1.0))
            self.levels.append(Level(r2, 'pivot', strength=0.8))

    def _calc_recent_highs_lows(self, window: int = 20):
        """Find recent significant highs and lows."""
        if len(self.df) < window:
            return

        recent = self.df.tail(window)

        # Local maxima (resistance)
        highs = recent['high'].values
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                self.levels.append(Level(
                    float(highs[i]),
                    'recent_high',
                    strength=1.5,
                    touches=1
                ))

        # Local minima (support)
        lows = recent['low'].values
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                self.levels.append(Level(
                    float(lows[i]),
                    'recent_low',
                    strength=1.5,
                    touches=1
                ))

    def _calc_volume_profile(self, bins: int = 20):
        """Calculate volume-weighted price levels."""
        if len(self.df) < 20:
            return

        recent = self.df.tail(60)  # Use 60 days

        # Calculate VWAP for each day
        typical_price = (recent['high'] + recent['low'] + recent['close']) / 3
        vwap = (typical_price * recent['volume']).sum() / recent['volume'].sum()

        self.levels.append(Level(float(vwap), 'vwap', strength=2.0))

        # Volume profile - price levels with highest volume
        price_range = recent['high'].max() - recent['low'].min()
        bin_size = price_range / bins

        volume_by_price = defaultdict(float)
        for _, row in recent.iterrows():
            bin_idx = int((row['close'] - recent['low'].min()) / bin_size)
            price_bin = recent['low'].min() + bin_idx * bin_size
            volume_by_price[price_bin] += row['volume']

        # Top 3 volume nodes
        top_volumes = sorted(volume_by_price.items(), key=lambda x: x[1], reverse=True)[:3]
        for price, vol in top_volumes:
            self.levels.append(Level(
                float(price),
                'volume_profile',
                strength=1.2
            ))

    def _calc_psychological_levels(self):
        """Generate psychological price levels (round numbers)."""
        current_price = self.df['close'].iloc[-1]

        # Determine appropriate rounding based on price level
        if current_price >= 1000:
            step = 100
        elif current_price >= 100:
            step = 10
        elif current_price >= 10:
            step = 5
        else:
            step = 1

        # Generate levels around current price
        base = round(current_price / step) * step

        for offset in [-2, -1, 0, 1, 2]:
            level = base + offset * step
            if level > 0:
                self.levels.append(Level(
                    float(level),
                    'psychological',
                    strength=1.0
                ))

    def _calc_trading_range(self, window: int = 60, min_touches: int = 3):
        """
        Identify levels from price consolidation areas.
        Finds price ranges where price has oscillated multiple times.
        """
        if len(self.df) < window:
            return

        recent = self.df.tail(window)

        # Find horizontal support/resistance from multiple tests
        highs = recent['high'].values
        lows = recent['low'].values

        # Count touches for each price level
        tolerance = recent['close'].std() * 0.3  # 30% of std dev

        # Check for levels tested multiple times
        price_levels = np.linspace(recent['low'].min(), recent['high'].max(), 50)

        for level in price_levels:
            touches = 0
            for i in range(len(highs)):
                if abs(highs[i] - level) <= tolerance:
                    touches += 1
                elif abs(lows[i] - level) <= tolerance:
                    touches += 1

            if touches >= min_touches:
                self.levels.append(Level(
                    float(level),
                    'trading_range',
                    strength=min(2.0, touches * 0.4),
                    touches=touches
                ))

    def _cluster_levels(self, tolerance_pct: float = 0.01) -> Dict[str, List[float]]:
        """
        Cluster similar levels and separate into support/resistance.

        Args:
            tolerance_pct: Levels within this % of each other are merged

        Returns:
            Dict with 'support', 'resistance', and 'all_levels'
        """
        if not self.levels:
            return {'support': [], 'resistance': [], 'all_levels': []}

        current_price = self.df['close'].iloc[-1]
        tolerance = current_price * tolerance_pct

        # Sort by price
        sorted_levels = sorted(self.levels, key=lambda x: x.price)

        # Cluster nearby levels
        clusters = []
        current_cluster = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            if abs(level.price - current_cluster[0].price) <= tolerance:
                current_cluster.append(level)
            else:
                clusters.append(current_cluster)
                current_cluster = [level]
        clusters.append(current_cluster)

        # Merge clusters into final levels
        merged = []
        for cluster in clusters:
            avg_price = np.mean([l.price for l in cluster])
            total_strength = sum(l.strength for l in cluster)
            total_touches = sum(l.touches for l in cluster)
            methods = ','.join(set(l.method for l in cluster))

            merged.append(Level(
                price=round(avg_price, 2),
                method=methods,
                strength=round(total_strength, 2),
                touches=total_touches
            ))

        # Sort by strength descending
        merged.sort(key=lambda x: x.strength, reverse=True)

        # Separate into support/resistance
        support = [l for l in merged if l.price < current_price]
        resistance = [l for l in merged if l.price > current_price]

        return {
            'support': [l.price for l in sorted(support, key=lambda x: x.price, reverse=True)][:5],
            'resistance': [l.price for l in sorted(resistance, key=lambda x: x.price)][:5],
            'all_levels': [
                {'price': l.price, 'strength': l.strength, 'methods': l.method, 'touches': l.touches}
                for l in merged[:10]
            ]
        }

    def count_touches(self, level_price: float, lookback: int = 60, tolerance_pct: float = 0.02) -> int:
        """
        Count number of times price touched a specific level within lookback period.

        Args:
            level_price: The price level to check
            lookback: Number of days to look back
            tolerance_pct: Tolerance percentage for touch detection (default 2%)

        Returns:
            Number of touches detected
        """
        if len(self.df) < lookback:
            df = self.df
        else:
            df = self.df.tail(lookback)

        tolerance = level_price * tolerance_pct
        touches = 0

        for _, row in df.iterrows():
            # Check if low or high crossed the level
            if row['low'] <= level_price + tolerance and row['high'] >= level_price - tolerance:
                touches += 1

        return touches

    def get_nearest_levels(self, n: int = 3) -> Tuple[List[float], List[float]]:
        """
        Get n nearest support and resistance levels to current price.

        Returns:
            Tuple of (support_levels, resistance_levels)
        """
        result = self.calculate_all()
        return result['support'][:n], result['resistance'][:n]
