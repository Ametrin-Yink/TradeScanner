"""ETF Pre-calculation Module.

Calculates all market/sector ETF data needed by strategies:
- SPY, QQQ (market regime)
- VIX (fear gauge)
- Sector ETFs (XLK, XLF, XLE, etc.)

All calculations are done in Phase 0 and cached in etf_cache table.
Strategies access this pre-calculated data instead of calculating themselves.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import pandas as pd

from core.indicators import TechnicalIndicators
from core.fetcher import DataFetcher
from data.db import Database
from core.constants import SECTOR_ETFS

logger = logging.getLogger(__name__)


# Re-export for backward compatibility
__all__ = ['SECTOR_ETFS', 'ETFPreCalculator']

# Market ETFs for regime detection
MARKET_ETFS = ['SPY', 'QQQ', 'IWM', 'DIA']

# Fear gauge
VIX_SYMBOL = '^VIX'


class ETFPreCalculator:
    """Pre-calculate all ETF data for strategy use."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.fetcher = DataFetcher(db=self.db)

    def calculate_all_etfs(self) -> Dict[str, Dict[str, Any]]:
        """Calculate and cache all ETF data.

        Returns:
            Dict mapping ETF symbol to pre-calculated data
        """
        logger.info("Starting ETF pre-calculation...")

        etf_cache = {}

        # 1. Calculate VIX data
        vix_data = self._calculate_vix()
        if vix_data:
            etf_cache[VIX_SYMBOL] = vix_data
            self.db.save_etf_cache(VIX_SYMBOL, vix_data)

        # 2. Calculate market ETF data (SPY, QQQ, etc.)
        for symbol in MARKET_ETFS:
            df = self._fetch_etf_data(symbol)
            if df is not None and len(df) >= 50:
                etf_data = self._calculate_market_etf_data(symbol, df, vix_data)
                etf_cache[symbol] = etf_data
                self.db.save_etf_cache(symbol, etf_data)

        # 3. Calculate sector ETF data
        for sector, symbol in SECTOR_ETFS.items():
            df = self._fetch_etf_data(symbol)
            if df is not None and len(df) >= 50:
                etf_data = self._calculate_sector_etf_data(sector, symbol, df)
                etf_cache[symbol] = etf_data
                self.db.save_etf_cache(symbol, etf_data)

        logger.info(f"ETF pre-calculation complete: {len(etf_cache)} ETFs cached")
        return etf_cache

    def _fetch_etf_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch ETF data from yfinance."""
        try:
            df = self.fetcher.fetch_stock_data(symbol, period="13mo", interval="1d")
            if df is not None and not df.empty:
                # Cache in tier3_cache for backward compatibility
                self.db.save_tier3_cache(symbol, df)
                return df
            logger.warning(f"No data for ETF: {symbol}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch ETF data for {symbol}: {e}")
            return None

    def _calculate_vix(self) -> Optional[Dict[str, Any]]:
        """Calculate VIX data."""
        try:
            df = self._fetch_etf_data(VIX_SYMBOL)
            if df is None or len(df) < 10:
                logger.warning("VIX data unavailable")
                return None

            current_vix = df['close'].iloc[-1]
            vix_5d_ago = df['close'].iloc[-6] if len(df) > 5 else current_vix
            vix_slope = (current_vix - vix_5d_ago) / 5

            # VIX status per v5.0 spec
            if current_vix < 15:
                vix_status = 'reject'  # No fear = no capitulation
            elif current_vix > 35:
                vix_status = 'extreme'  # Cap at Tier B
            else:
                vix_status = 'normal'  # 15-35 window

            return {
                'current_price': current_vix,
                'vix_current': current_vix,
                'vix_5d_slope': vix_slope,
                'vix_status': vix_status,
            }
        except Exception as e:
            logger.error(f"Failed to calculate VIX data: {e}")
            return None

    def _calculate_market_etf_data(
        self,
        symbol: str,
        df: pd.DataFrame,
        vix_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Calculate market ETF data (SPY, QQQ, etc.)."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # EMAs
        ema50 = ind.indicators.get('ema', {}).get('ema50', 0)
        ema200 = ind.indicators.get('ema', {}).get('ema200', 0)

        # ATR
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # RSI
        rsi = ind.indicators.get('rsi', {}).get('rsi14', 50)

        # Returns
        close = df['close']
        ret_5d = (close.iloc[-1] / close.iloc[-min(5, len(close))] - 1) * 100 if len(close) >= 5 else 0
        ret_3m = (close.iloc[-1] / close.iloc[-min(63, len(close))] - 1) * 100 if len(close) >= 63 else 0
        ret_6m = (close.iloc[-1] / close.iloc[-min(126, len(close))] - 1) * 100 if len(close) >= 126 else 0
        ret_12m = (close.iloc[-1] / close.iloc[-min(252, len(close))] - 1) * 100 if len(close) >= 252 else 0

        # Volume ratio
        volume_sma = df['volume'].tail(20).mean()
        volume_ratio = df['volume'].iloc[-1] / volume_sma if volume_sma > 0 else 1.0

        # Price vs EMA50
        price_vs_ema50_pct = (current_price - ema50) / ema50 * 100 if ema50 > 0 else 0
        above_ema50 = current_price > ema50

        # Market trend determination
        market_trend = 'bull' if above_ema50 and price_vs_ema50_pct > 2 else ('bear' if price_vs_ema50_pct < -2 else 'neutral')

        # SPY regime (used for regime detection)
        spy_regime = self._determine_spy_regime(symbol, current_price, ema50, ema200, vix_data)

        return {
            'current_price': current_price,
            'ema50': ema50,
            'ema200': ema200,
            'atr': atr,
            'rsi_14': rsi,
            'ret_5d': ret_5d,
            'ret_3m': ret_3m,
            'ret_6m': ret_6m,
            'ret_12m': ret_12m,
            'rs_percentile': 50.0,  # Market ETF, use neutral
            'above_ema50': above_ema50,
            'volume_ratio': volume_ratio,
            'spy_regime': spy_regime,
            'spy_price_vs_ema50_pct': price_vs_ema50_pct if symbol == 'SPY' else None,
            'qqq_price_vs_ema50_pct': price_vs_ema50_pct if symbol == 'QQQ' else None,
            'market_trend': market_trend,
        }

    def _calculate_sector_etf_data(
        self,
        sector: str,
        symbol: str,
        df: pd.DataFrame
    ) -> Dict[str, Any]:
        """Calculate sector ETF data."""
        ind = TechnicalIndicators(df)
        ind.calculate_all()

        current_price = df['close'].iloc[-1]

        # EMAs
        ema50 = ind.indicators.get('ema', {}).get('ema50', 0)
        ema200 = ind.indicators.get('ema', {}).get('ema200', 0)

        # ATR
        atr = ind.indicators.get('atr', {}).get('atr', current_price * 0.02)

        # RSI
        rsi = ind.indicators.get('rsi', {}).get('rsi14', 50)

        # Returns
        close = df['close']
        ret_5d = (close.iloc[-1] / close.iloc[-min(5, len(close))] - 1) * 100 if len(close) >= 5 else 0
        ret_3m = (close.iloc[-1] / close.iloc[-min(63, len(close))] - 1) * 100 if len(close) >= 63 else 0
        ret_6m = (close.iloc[-1] / close.iloc[-min(126, len(close))] - 1) * 100 if len(close) >= 126 else 0
        ret_12m = (close.iloc[-1] / close.iloc[-min(252, len(close))] - 1) * 100 if len(close) >= 252 else 0

        # Volume ratio
        volume_sma = df['volume'].tail(20).mean()
        volume_ratio = df['volume'].iloc[-1] / volume_sma if volume_sma > 0 else 1.0

        # Price vs EMA50
        price_vs_ema50_pct = (current_price - ema50) / ema50 * 100 if ema50 > 0 else 0
        above_ema50 = current_price > ema50

        # Calculate RS score (vs SPY)
        rs_percentile = self._calculate_etf_rs_percentile(df, ret_3m)

        return {
            'current_price': current_price,
            'ema50': ema50,
            'ema200': ema200,
            'atr': atr,
            'rsi_14': rsi,
            'ret_5d': ret_5d,
            'ret_3m': ret_3m,
            'ret_6m': ret_6m,
            'ret_12m': ret_12m,
            'rs_percentile': rs_percentile,
            'above_ema50': above_ema50,
            'volume_ratio': volume_ratio,
            'sector_name': sector,
            'price_vs_ema50_pct': price_vs_ema50_pct,  # For sector alignment calculation
        }

    def _calculate_etf_rs_percentile(self, df: pd.DataFrame, ret_3m: float) -> float:
        """Calculate RS percentile for ETF (simplified)."""
        # Full RS percentile requires universe-wide data
        # Here we use a simplified approximation based on 3m return
        if ret_3m >= 15:
            return 90.0
        elif ret_3m >= 10:
            return 80.0
        elif ret_3m >= 5:
            return 70.0
        elif ret_3m >= 0:
            return 50.0
        elif ret_3m >= -5:
            return 30.0
        else:
            return 10.0

    def _determine_spy_regime(
        self,
        symbol: str,
        price: float,
        ema50: float,
        ema200: float,
        vix_data: Optional[Dict] = None
    ) -> str:
        """Determine market regime based on SPY/QQQ/VIX.

        Regimes:
        - bull_strong: SPY > EMA50 > EMA200, VIX < 20
        - bull_moderate: SPY > EMA50, VIX 20-25
        - neutral: SPY around EMA50 (±2%), VIX 25-30
        - bear_moderate: SPY < EMA50, VIX 30-35
        - bear_strong: SPY < EMA50 < EMA200, VIX > 35
        - extreme_vix: VIX > 30 (overrides other signals)
        """
        if symbol not in ['SPY', 'QQQ']:
            return 'neutral'

        vix_current = vix_data.get('vix_current', 20) if vix_data else 20

        # VIX > 30 = extreme_vix
        if vix_current > 30:
            return 'extreme_vix'

        price_vs_ema50 = (price - ema50) / ema50 if ema50 > 0 else 0
        price_vs_ema200 = (price - ema200) / ema200 if ema200 > 0 else 0

        # Bull regimes
        if price > ema50 and ema50 > ema200:
            if vix_current < 20:
                return 'bull_strong'
            elif vix_current < 25:
                return 'bull_moderate'
            else:
                return 'neutral'
        elif price > ema50:
            if vix_current < 25:
                return 'bull_moderate'
            else:
                return 'neutral'

        # Bear regimes
        if price < ema50 and ema50 < ema200:
            if vix_current > 35:
                return 'bear_strong'
            elif vix_current > 30:
                return 'bear_moderate'
            else:
                return 'neutral'
        elif price < ema50:
            if vix_current > 30:
                return 'bear_moderate'
            else:
                return 'neutral'

        # Default
        return 'neutral'

    def get_etf_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get pre-calculated ETF data from cache.

        Args:
            symbol: ETF symbol

        Returns:
            Dict with ETF metrics or None
        """
        return self.db.get_etf_cache(symbol)

    def get_all_etf_data(self) -> Dict[str, Dict[str, Any]]:
        """Get all pre-calculated ETF data.

        Returns:
            Dict mapping symbol to ETF metrics
        """
        return self.db.get_all_etf_cache()

    def get_sector_etf_symbol(self, sector: str) -> Optional[str]:
        """Get sector ETF symbol for a given sector.

        Args:
            sector: Sector name

        Returns:
            ETF symbol or None
        """
        return SECTOR_ETFS.get(sector)

    def get_vix_status(self) -> str:
        """Get current VIX status.

        Returns:
            'reject', 'extreme', or 'normal'
        """
        vix_data = self.get_etf_data(VIX_SYMBOL)
        return vix_data.get('vix_status', 'normal') if vix_data else 'normal'

    def get_market_regime(self) -> str:
        """Get current market regime.

        Returns:
            Regime string
        """
        spy_data = self.get_etf_data('SPY')
        return spy_data.get('spy_regime', 'neutral') if spy_data else 'neutral'


def run_etf_precalc(db: Optional[Database] = None) -> Dict[str, Dict[str, Any]]:
    """Run ETF pre-calculation.

    Args:
        db: Optional database instance

    Returns:
        Dict mapping ETF symbol to pre-calculated data
    """
    prep = ETFPreCalculator(db=db)
    return prep.calculate_all_etfs()
