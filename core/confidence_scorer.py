"""Dynamic confidence scoring system for trade opportunities."""
from typing import Dict, List
import numpy as np


class ConfidenceScorer:
    """Calculate dynamic confidence scores based on multiple factors."""

    @staticmethod
    def calculate_confidence(
        strategy: str,
        technical_data: Dict,
        indicators: Dict,
        sr_data: Dict,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        match_reasons: List[str]
    ) -> int:
        """
        Calculate confidence score (0-100) based on multiple factors.

        Args:
            strategy: Strategy name
            technical_data: Price data (highs, lows, volume, etc.)
            indicators: Technical indicators (RSI, EMAs, ATR, etc.)
            sr_data: Support/resistance data
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            match_reasons: List of match reasons

        Returns:
            Confidence score (0-100)
        """
        scores = []

        # 1. Risk/Reward Ratio (max 20 points)
        rrr_score = ConfidenceScorer._score_risk_reward(entry_price, stop_loss, take_profit)
        scores.append(rrr_score)

        # 2. Volume Confirmation (max 15 points)
        volume_score = ConfidenceScorer._score_volume(technical_data, indicators)
        scores.append(volume_score)

        # 3. Technical Alignment (max 25 points)
        alignment_score = ConfidenceScorer._score_technical_alignment(
            strategy, indicators, technical_data
        )
        scores.append(alignment_score)

        # 4. Support/Resistance Quality (max 20 points)
        sr_score = ConfidenceScorer._score_sr_quality(sr_data, technical_data)
        scores.append(sr_score)

        # 5. Trend Consistency (max 20 points)
        trend_score = ConfidenceScorer._score_trend_consistency(indicators, strategy)
        scores.append(trend_score)

        # Calculate weighted average
        weights = [0.20, 0.15, 0.25, 0.20, 0.20]
        weighted_score = sum(s * w for s, w in zip(scores, weights))

        # Round to nearest integer
        final_score = int(round(weighted_score))

        # Ensure bounds
        return max(0, min(100, final_score))

    @staticmethod
    def _score_risk_reward(entry: float, stop: float, target: float) -> float:
        """Score based on risk/reward ratio (max 20 points)."""
        risk = abs(entry - stop)
        reward = abs(target - entry)

        if risk == 0:
            return 5  # Minimal score if no risk defined

        rrr = reward / risk

        # Score based on R/R ratio
        if rrr >= 3.0:
            return 20
        elif rrr >= 2.5:
            return 18
        elif rrr >= 2.0:
            return 16
        elif rrr >= 1.5:
            return 13
        elif rrr >= 1.0:
            return 10
        elif rrr >= 0.5:
            return 7
        else:
            return 5

    @staticmethod
    def _score_volume(technical_data: Dict, indicators: Dict) -> float:
        """Score based on volume confirmation (max 15 points)."""
        if not technical_data or 'volume' not in technical_data:
            return 7.5  # Neutral

        current_volume = technical_data.get('volume', 0)
        avg_volume = technical_data.get('avg_volume_20d', current_volume)

        if avg_volume == 0:
            return 7.5

        volume_ratio = current_volume / avg_volume

        # Score based on volume ratio
        if volume_ratio >= 2.0:
            return 15  # Very high volume
        elif volume_ratio >= 1.5:
            return 13
        elif volume_ratio >= 1.2:
            return 11
        elif volume_ratio >= 1.0:
            return 10
        elif volume_ratio >= 0.8:
            return 8
        else:
            return 6  # Low volume

    @staticmethod
    def _score_technical_alignment(strategy: str, indicators: Dict, technical_data: Dict) -> float:
        """Score based on technical indicator alignment (max 25 points)."""
        score = 12.5  # Start neutral

        rsi = indicators.get('rsi', 50)
        # Ensure rsi is a number, not a dict
        if isinstance(rsi, dict):
            rsi = rsi.get('rsi', 50)
        if not isinstance(rsi, (int, float)):
            rsi = 50

        # RSI-based scoring (strategy-dependent)
        if strategy in ['Momentum', 'EP']:
            # For momentum strategies, moderate RSI is good (50-70)
            if 50 <= rsi <= 65:
                score += 6
            elif 40 <= rsi <= 75:
                score += 3
        elif strategy in ['DTSS', 'Parabolic']:
            # For short strategies, high RSI is good
            if rsi >= 75:
                score += 6
            elif rsi >= 65:
                score += 3
        elif strategy in ['U&R', 'RangeSupport']:
            # For support strategies, low RSI is good (oversold)
            if 30 <= rsi <= 50:
                score += 6
            elif rsi <= 60:
                score += 3

        # Trend strength (ADR)
        adr = indicators.get('adr', {}).get('adr_pct', 0.02)
        if isinstance(adr, dict):
            adr = adr.get('adr_pct', 0.02)
        if not isinstance(adr, (int, float)):
            adr = 0.02

        if adr >= 0.04:  # High volatility
            score += 6.5
        elif adr >= 0.025:
            score += 4
        else:
            score += 2

        return min(25, score)

    @staticmethod
    def _score_sr_quality(sr_data: Dict, technical_data: Dict) -> float:
        """Score based on support/resistance quality (max 20 points)."""
        if not sr_data:
            return 10  # Neutral

        # Score based on number of touches
        touches = sr_data.get('touches', 0)
        if touches >= 10:
            return 20
        elif touches >= 5:
            return 17
        elif touches >= 3:
            return 14
        elif touches >= 2:
            return 11
        else:
            return 8

    @staticmethod
    def _score_trend_consistency(indicators: Dict, strategy: str) -> float:
        """Score based on trend consistency (max 20 points)."""
        score = 10  # Start neutral

        ema8 = indicators.get('ema8', 0)
        ema21 = indicators.get('ema21', 0)
        ema50 = indicators.get('ema50', 0)

        if ema8 == 0 or ema21 == 0:
            return 10

        # Trend alignment
        if strategy in ['Momentum', 'EP', 'Shoryuken', 'Pullbacks', 'U&R', 'RangeSupport']:
            # Long strategies - want uptrend
            if ema8 > ema21 > ema50:
                score += 8  # Strong uptrend
            elif ema8 > ema21:
                score += 5
            elif ema21 > ema50:
                score += 3
            else:
                score += 1
        elif strategy in ['DTSS', 'Parabolic']:
            # Short strategies - want extended/overbought
            if ema8 > ema21 > ema50:
                score += 5  # Extended uptrend, potential reversal
            elif ema8 > ema21:
                score += 3
            else:
                score += 1

        # Price relative to moving averages
        current_price = indicators.get('current_price', ema8)
        if strategy in ['U&R', 'RangeSupport']:
            # Want price near support (EMA50)
            if ema50 * 0.98 <= current_price <= ema50 * 1.05:
                score += 2

        return min(20, score)


def calculate_strategy_confidence(
    strategy: str,
    df_data,
    indicators: Dict,
    entry: float,
    stop: float,
    target: float,
    sr_levels=None
) -> int:
    """
    Convenience function to calculate confidence for a strategy match.

    Args:
        strategy: Strategy name
        df_data: DataFrame or dict with price data
        indicators: Technical indicators dict
        entry: Entry price
        stop: Stop loss
        target: Take profit
        sr_levels: Support/resistance levels

    Returns:
        Confidence score (0-100)
    """
    technical_data = {}

    # Extract data from DataFrame if provided
    if hasattr(df_data, 'iloc'):
        if len(df_data) > 0:
            technical_data['volume'] = df_data['volume'].iloc[-1]
            technical_data['avg_volume_20d'] = df_data['volume'].tail(20).mean()
            technical_data['high_20d'] = df_data['high'].tail(20).max()
            technical_data['low_20d'] = df_data['low'].tail(20).min()
    elif isinstance(df_data, dict):
        technical_data = df_data

    sr_data = sr_levels or {}

    return ConfidenceScorer.calculate_confidence(
        strategy=strategy,
        technical_data=technical_data,
        indicators=indicators,
        sr_data=sr_data,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        match_reasons=[]
    )
