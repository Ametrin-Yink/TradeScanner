"""Strategy screener - 8 trading strategies implementation."""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np

from core.fetcher import DataFetcher
from core.indicators import TechnicalIndicators, calculate_indicators_for_symbol
from core.support_resistance import SupportResistanceCalculator
from core.confidence_scorer import calculate_strategy_confidence
from data.db import Database
from config.settings import settings

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """8 trading strategies."""
    EP = "EP"  # Earnings Play
    MOMENTUM = "Momentum"  # Momentum Breakout
    SHORYUKEN = "Shoryuken"  # Pullback to EMA
    PULLBACKS = "Pullbacks"  # Buying Pullbacks
    UPTHRUST_REBOUND = "U&R"  # Upthrust & Rebound
    RANGE_SUPPORT = "RangeSupport"  # Range bottom support
    DTSS = "DTSS"  # Distribution Top Sell Signal
    PARABOLIC = "Parabolic"  # Parabolic short


@dataclass
class StrategyMatch:
    """A strategy match result."""
    symbol: str
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: int  # 0-100
    match_reasons: List[str] = field(default_factory=list)
    technical_snapshot: Dict[str, Any] = field(default_factory=dict)


class StrategyScreener:
    """Screen stocks using 8 trading strategies."""

    # Minimum requirements
    MIN_ADR_PCT = 0.03  # 3% minimum ADR
    MIN_VOLUME = 1_000_000  # 1M minimum volume
    MAX_CANDIDATES_PER_STRATEGY = 5

    def __init__(
        self,
        fetcher: Optional[DataFetcher] = None,
        db: Optional[Database] = None
    ):
        """Initialize screener with data fetcher and database."""
        self.fetcher = fetcher or DataFetcher()
        self.db = db or Database()
        self.earnings_calendar: Dict[str, datetime] = {}
        self.market_data: Dict[str, pd.DataFrame] = {}
    def load_earnings_calendar(self, symbols: Optional[List[str]] = None):
        """Load earnings calendar for EP strategy."""
        self.earnings_calendar = self.fetcher.fetch_earnings_calendar(symbols)
        logger.info(f"Loaded {len(self.earnings_calendar)} earnings dates")

    def screen_all(
        self,
        symbols: List[str],
        market_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> List[StrategyMatch]:
        """
        Screen all symbols using all 8 strategies.

        Returns:
            List of StrategyMatch (40 total: 5 per strategy)
        """
        self.market_data = market_data or {}

        # Load earnings if not already loaded
        if not self.earnings_calendar:
            self.load_earnings_calendar(symbols)

        all_candidates = []

        # Run each strategy
        strategies = [
            (self.screen_ep, StrategyType.EP),
            (self.screen_momentum, StrategyType.MOMENTUM),
            (self.screen_shoryuken, StrategyType.SHORYUKEN),
            (self.screen_pullbacks, StrategyType.PULLBACKS),
            (self.screen_upthrust_rebound, StrategyType.UPTHRUST_REBOUND),
            (self.screen_range_support, StrategyType.RANGE_SUPPORT),
            (self.screen_dtss, StrategyType.DTSS),
            (self.screen_parabolic, StrategyType.PARABOLIC),
        ]

        for screen_func, strategy_type in strategies:
            try:
                candidates = screen_func(symbols)
                if candidates:
                    all_candidates.extend(candidates[:self.MAX_CANDIDATES_PER_STRATEGY])
                    logger.info(f"{strategy_type.value}: found {len(candidates)} candidates")
            except Exception as e:
                logger.error(f"Error in {strategy_type.value} screening: {e}")

        return all_candidates

    def _get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Get cached or fetch data for symbol."""
        if symbol in self.market_data:
            return self.market_data[symbol]
        return self.fetcher.fetch_stock_data(symbol, period="6mo", interval="1d")

    def _check_basic_requirements(self, df: pd.DataFrame, ind: TechnicalIndicators) -> bool:
        """Check basic requirements: ADR and volume."""
        try:
            adr_pct = ind.indicators.get('adr', {}).get('adr_pct', 0)
            volume_data = ind.indicators.get('volume', {})
            volume_sma = volume_data.get('volume_sma', 0)

            if adr_pct is None or adr_pct < self.MIN_ADR_PCT:
                return False

            if volume_sma is None or volume_sma < self.MIN_VOLUME:
                return False

            return True
        except:
            return False

    def screen_ep(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy A: EP (Earnings Play)
        Check earnings calendar for tonight/tomorrow.
        """
        matches = []
        today = datetime.now().date()

        for symbol in symbols:
            if symbol not in self.earnings_calendar:
                continue

            earnings_date = self.earnings_calendar[symbol]
            if isinstance(earnings_date, datetime):
                earnings_date = earnings_date.date()

            # Check if earnings is today or tomorrow
            days_until = (earnings_date - today).days
            if days_until not in [0, 1]:
                continue

            df = self._get_data(symbol)
            if df is None or len(df) < 20:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            current_price = df['close'].iloc[-1]

            # EP entry: current price
            # Stop: 2x ATR below
            # Target: 3x ATR above
            atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

            entry_price = round(current_price, 2)
            stop_loss = round(current_price - atr * 2, 2)
            take_profit = round(current_price + atr * 3, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.EP.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.EP.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[f"Earnings in {days_until} day(s)", f"ADR: {ind.indicators['adr']['adr_pct']:.1f}%"],
                technical_snapshot={
                    'current_price': current_price,
                    'earnings_date': earnings_date.isoformat(),
                    'atr': atr
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_momentum(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy B: Momentum Breakout
        Price within 2% of resistance + volume building.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 50:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            # Check if in uptrend
            if not ind.is_uptrend():
                continue

            current_price = df['close'].iloc[-1]

            # Calculate S/R levels
            calc = SupportResistanceCalculator(df)
            sr_levels = calc.calculate_all()

            # Check if price within 2% of nearest resistance
            resistances = sr_levels.get('resistance', [])
            if not resistances:
                continue

            nearest_resistance = min(resistances)
            distance_pct = abs(nearest_resistance - current_price) / current_price

            if distance_pct > 0.02:  # More than 2% away
                continue

            # Check volume building
            volume_data = ind.indicators.get('volume', {})
            volume_spike = volume_data.get('volume_spike', False)
            volume_ratio = volume_data.get('volume_ratio', 1.0)

            if not volume_spike and volume_ratio < 1.2:
                continue

            atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

            entry_price = round(nearest_resistance, 2)
            stop_loss = round(current_price - atr * 1.5, 2)
            take_profit = round(nearest_resistance + atr * 2, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.MOMENTUM.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit,
                sr_levels={'resistance': resistances}
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.MOMENTUM.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"Near resistance ({distance_pct*100:.1f}%)",
                    f"Volume ratio: {volume_ratio:.1f}x"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'nearest_resistance': nearest_resistance,
                    'volume_ratio': volume_ratio,
                    'in_uptrend': True
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_shoryuken(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy C: Shoryuken
        Price declining toward EMA8/21, within 1 ATR of support.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 50:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            ema = ind.indicators.get('ema', {})
            ema8 = ema.get('ema8')
            ema21 = ema.get('ema21')
            atr = ind.indicators.get('atr', {}).get('atr')

            if ema8 is None or ema21 is None or atr is None:
                continue

            current_price = df['close'].iloc[-1]

            # Check if price is declining toward EMA
            if current_price > ema8 or current_price > ema21:
                continue

            # Check if within 1 ATR of EMA8
            distance_to_ema8 = abs(current_price - ema8)
            if distance_to_ema8 > atr:
                continue

            # Check if overall trend is up (EMA8 > EMA21)
            if ema8 <= ema21:
                continue

            entry_price = round(current_price, 2)
            stop_loss = round(ema21 - atr, 2)
            take_profit = round(ema8 + atr * 2, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.SHORYUKEN.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.SHORYUKEN.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"Price {distance_to_ema8:.2f} from EMA8",
                    "Declining toward EMA support"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'ema8': ema8,
                    'ema21': ema21,
                    'atr': atr
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_pullbacks(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy D: Buying Pullbacks
        1-5 days pullback from 20-day high, still above EMA50.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 50:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            ema = ind.indicators.get('ema', {})
            ema50 = ema.get('ema50')

            if ema50 is None:
                continue

            current_price = df['close'].iloc[-1]

            # Must be above EMA50
            if current_price <= ema50:
                continue

            # Check 20-day high
            price_metrics = ind.indicators.get('price_metrics', {})
            high_20d = price_metrics.get('high_20d')
            distance_from_high = price_metrics.get('distance_from_high')

            if high_20d is None or distance_from_high is None:
                continue

            # Must be in pullback (1-5% below high)
            pullback_pct = abs(distance_from_high)
            if pullback_pct < 1 or pullback_pct > 5:
                continue

            # Check pullback duration (price making lower highs)
            recent_highs = df['high'].tail(5).values
            is_pullback = all(recent_highs[i] >= recent_highs[i+1] for i in range(len(recent_highs)-1))

            if not is_pullback:
                continue

            atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

            entry_price = round(current_price, 2)
            stop_loss = round(ema50 - atr, 2)
            take_profit = round(high_20d, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.PULLBACKS.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.PULLBACKS.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"Pullback {pullback_pct:.1f}% from high",
                    "Above EMA50",
                    "Descending highs (5 days)"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'high_20d': high_20d,
                    'pullback_pct': pullback_pct,
                    'ema50': ema50
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_upthrust_rebound(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy E: Upthrust & Rebound (U&R)
        Price within 1% of support + volume contraction.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 50:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            current_price = df['close'].iloc[-1]

            # Calculate S/R
            calc = SupportResistanceCalculator(df)
            sr_levels = calc.calculate_all()

            supports = sr_levels.get('support', [])
            if not supports:
                continue

            # Find nearest support
            nearest_support = max(supports)  # Highest support below price
            distance_pct = abs(current_price - nearest_support) / current_price

            if distance_pct > 0.01:  # More than 1% from support
                continue

            # Check volume contraction
            volume_data = ind.indicators.get('volume', {})
            volume_ratio = volume_data.get('volume_ratio', 1.0)

            if volume_ratio > 0.8:  # Not enough contraction
                continue

            atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

            entry_price = round(current_price, 2)
            stop_loss = round(nearest_support - atr, 2)
            take_profit = round(current_price + atr * 2.5, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.UPTHRUST_REBOUND.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit,
                sr_levels={'support': supports}
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.UPTHRUST_REBOUND.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"Near support ({distance_pct*100:.1f}%)",
                    f"Volume contraction ({volume_ratio:.1f}x)"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'nearest_support': nearest_support,
                    'volume_ratio': volume_ratio
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_range_support(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy F: Range Support (Left Side Buying)
        Uptrend + consolidation range bottom + multiple tests.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 60:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            # Must be in uptrend
            if not ind.is_uptrend():
                continue

            current_price = df['close'].iloc[-1]

            # Calculate S/R with focus on trading ranges
            calc = SupportResistanceCalculator(df)
            sr_levels = calc.calculate_all()

            # Find levels with multiple touches
            range_levels = [
                l for l in sr_levels.get('all_levels', [])
                if l.get('touches', 0) >= 3
            ]

            if not range_levels:
                continue

            # Find support level near current price
            for level_info in range_levels:
                level_price = level_info['price']
                if current_price > level_price:  # Below current price = support
                    distance_pct = (current_price - level_price) / current_price
                    if distance_pct <= 0.03:  # Within 3%
                        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

                        entry_price = round(current_price, 2)
                        stop_loss = round(level_price - atr, 2)
                        take_profit = round(current_price + atr * 3, 2)

                        # Calculate dynamic confidence
                        confidence = calculate_strategy_confidence(
                            strategy=StrategyType.RANGE_SUPPORT.value,
                            df_data=df,
                            indicators=ind.indicators,
                            entry=entry_price,
                            stop=stop_loss,
                            target=take_profit,
                            sr_levels=level_info
                        )

                        matches.append(StrategyMatch(
                            symbol=symbol,
                            strategy=StrategyType.RANGE_SUPPORT.value,
                            entry_price=entry_price,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            confidence=confidence,
                            match_reasons=[
                                "Uptrend confirmed",
                                f"Support tested {level_info['touches']} times",
                                "Range bottom entry"
                            ],
                            technical_snapshot={
                                'current_price': current_price,
                                'support_level': level_price,
                                'touches': level_info['touches'],
                                'methods': level_info['methods']
                            }
                        ))
                        break

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_dtss(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy G: DTSS (Distribution Top Sell Signal)
        Short strategy: Within 3% of 60-day high + showing weakness.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 60:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            current_price = df['close'].iloc[-1]
            price_metrics = ind.indicators.get('price_metrics', {})
            high_60d = price_metrics.get('high_60d')

            if high_60d is None:
                continue

            # Check if near 60-day high (within 3%)
            distance_from_high = abs(high_60d - current_price) / current_price
            if distance_from_high > 0.03:
                continue

            # Check for weakness signs
            ema = ind.indicators.get('ema', {})
            ema8 = ema.get('ema8')
            ema21 = ema.get('ema21')

            if ema8 is None or ema21 is None:
                continue

            # Weakness: EMA8 crossing below EMA21 or price below both
            weakness = ema8 < ema21 or current_price < ema8

            if not weakness:
                continue

            # Volume spike on decline
            volume_data = ind.indicators.get('volume', {})
            volume_spike = volume_data.get('volume_spike', False)

            atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

            entry_price = round(current_price, 2)
            stop_loss = round(high_60d + atr, 2)
            take_profit = round(current_price - atr * 3, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.DTSS.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.DTSS.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"Near 60-day high ({distance_from_high*100:.1f}%)",
                    "Weakness detected",
                    f"Volume spike: {volume_spike}"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'high_60d': high_60d,
                    'ema8': ema8,
                    'ema21': ema21,
                    'in_weakness': True
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)

    def screen_parabolic(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        Strategy H: Parabolic Short
        RSI>80 + price > 50EMA + 5*ATR + 2+ gaps in 5 days.
        """
        matches = []

        for symbol in symbols:
            df = self._get_data(symbol)
            if df is None or len(df) < 50:
                continue

            ind = TechnicalIndicators(df)
            ind.calculate_all()

            if not self._check_basic_requirements(df, ind):
                continue

            rsi_data = ind.indicators.get('rsi', {})
            rsi = rsi_data.get('rsi')

            if rsi is None or rsi <= 80:
                continue

            current_price = df['close'].iloc[-1]
            ema = ind.indicators.get('ema', {})
            ema50 = ema.get('ema50')
            atr = ind.indicators.get('atr', {}).get('atr')

            if ema50 is None or atr is None:
                continue

            # Price should be significantly above 50EMA
            if current_price <= ema50 + 5 * atr:
                continue

            # Check for gaps
            price_metrics = ind.indicators.get('price_metrics', {})
            gaps = price_metrics.get('gaps_5d', 0)

            if gaps < 2:
                continue

            entry_price = round(current_price, 2)
            stop_loss = round(current_price + atr * 2, 2)
            take_profit = round(ema50, 2)

            # Calculate dynamic confidence
            confidence = calculate_strategy_confidence(
                strategy=StrategyType.PARABOLIC.value,
                df_data=df,
                indicators=ind.indicators,
                entry=entry_price,
                stop=stop_loss,
                target=take_profit
            )

            matches.append(StrategyMatch(
                symbol=symbol,
                strategy=StrategyType.PARABOLIC.value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                match_reasons=[
                    f"RSI: {rsi:.1f}",
                    f"Gaps in 5 days: {gaps}",
                    "Far above 50EMA"
                ],
                technical_snapshot={
                    'current_price': current_price,
                    'rsi': rsi,
                    'ema50': ema50,
                    'atr': atr,
                    'gaps_5d': gaps
                }
            ))

        return sorted(matches, key=lambda x: x.confidence, reverse=True)
