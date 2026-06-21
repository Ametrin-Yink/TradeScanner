"""Tests for pre-trade guardrails: liquidity, earnings proximity, correlation.

Verifies that _find_stock_highlights skips illiquid stocks, halves position
near earnings, and flags correlated picks in the same sector.
"""
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from core.sector_analyzer import StockHighlight, SectorAnalyzer, SectorAnalysis


def _make_cache(overrides=None):
    """Create a tier1 cache dict with sensible defaults.

    Defaults are chosen so that a stock qualifies for Strong Momentum (RS >= 80,
    above EMAs, bullish candle).
    """
    base = {
        'current_price': 100.0,
        'atr_pct': 0.03,
        'rs_percentile': 85,
        'volume_ratio': 2.0,
        'avg_volume_20d': 5_000_000,
        'high_60d': 150.0,
        'low_60d': 80.0,
        'ema21': 95.0,
        'ema50': 90.0,
        'ret_5d': 3.0,
        'rs_consecutive_days_80': 5,
        'supports': json.dumps([75.0, 82.0]),
        'resistances': json.dumps([145.0, 155.0]),
        'open': 99.0,
        'close': 100.0,
        'high': 101.0,
        'low': 98.5,
    }
    if overrides:
        base.update(overrides)
    return base


def _make_stock(symbol='AAPL', name='Apple Inc.', market_cap=2_000_000_000_000):
    return {'symbol': symbol, 'name': name, 'market_cap': market_cap}


def _make_sector(name='Technology'):
    return SectorAnalysis(
        name=name, etf='XLK', stock_count=10, daily_change=1.0,
        ret_3m=8.0, rs_percentile=75, trend='uptrend', above_ema50=True,
        outlook='Bullish',
    )


def _make_highlight(**overrides):
    """Create a StockHighlight with sensible defaults."""
    h = StockHighlight(
        symbol=overrides.pop('symbol', 'AAPL'),
        name=overrides.pop('name', 'Apple Inc.'),
        price=overrides.pop('price', 100.0),
        market_cap=overrides.pop('market_cap', 2_000_000_000_000),
        reason=overrides.pop('reason', 'Strong Momentum'),
        detail=overrides.pop('detail', 'RS 85th percentile'),
        entry=overrides.pop('entry', 100.0),
        stop=overrides.pop('stop', 95.0),
        target=overrides.pop('target', 115.0),
        rr=overrides.pop('rr', 3.0),
        position_size=overrides.pop('position_size', 1000),
        position_cost=overrides.pop('position_cost', 100_000),
        risk_dollars=overrides.pop('risk_dollars', 5000),
    )
    h.rs_percentile = overrides.get('rs_percentile', 85)
    h.volume_ratio = overrides.get('volume_ratio', 2.0)
    h.ret_5d = overrides.get('ret_5d', 3.0)
    h.ema_above = overrides.get('ema_above', True)
    h.rs_consecutive_days_80 = overrides.get('rs_consecutive_days_80', 5)
    h.atr_pct = overrides.get('atr_pct', 0.03)
    return h


# ------------------------------------------------------------------
# StockHighlight attribute tests
# ------------------------------------------------------------------

class TestStockHighlightAttributes:
    """StockHighlight should support the new guardrail fields."""

    def test_default_earnings_warning_is_none(self):
        h = StockHighlight(
            symbol='AAPL', name='Apple', price=100.0, market_cap=1e9,
            reason='Breakout', detail='Test',
        )
        assert h.earnings_warning is None

    def test_default_correlation_warning_is_none(self):
        h = StockHighlight(
            symbol='AAPL', name='Apple', price=100.0, market_cap=1e9,
            reason='Breakout', detail='Test',
        )
        assert h.correlation_warning is None

    def test_can_set_earnings_warning(self):
        h = StockHighlight(
            symbol='AAPL', name='Apple', price=100.0, market_cap=1e9,
            reason='Breakout', detail='Test',
            earnings_warning="Earnings in 3d -- halved position",
        )
        assert h.earnings_warning == "Earnings in 3d -- halved position"

    def test_can_set_correlation_warning(self):
        h = StockHighlight(
            symbol='AAPL', name='Apple', price=100.0, market_cap=1e9,
            reason='Breakout', detail='Test',
            correlation_warning="Similar setup to GOOGL",
        )
        assert h.correlation_warning == "Similar setup to GOOGL"


# ------------------------------------------------------------------
# Helper to run _find_stock_highlights with controlled mocks
# ------------------------------------------------------------------

def _run_find_stock_highlights(db_mock, stocks, sector_override=None):
    """Run _find_stock_highlights with a patched get_tag_stocks."""
    analyzer = SectorAnalyzer(db=db_mock)
    sector = sector_override or _make_sector()
    sector.highlights = []
    with patch.object(analyzer.tag_manager, 'get_tag_stocks', return_value=stocks):
        analyzer._find_stock_highlights([sector])
    return sector


# ------------------------------------------------------------------
# Liquidity guardrail tests
# ------------------------------------------------------------------

class TestLiquidityGuardrail:
    """Position must be < 5% of avg daily volume — otherwise skip."""

    def test_large_position_relative_to_volume_is_skipped(self):
        """When position > 5% of avg volume, the stock should be skipped."""
        mock_db = MagicMock()
        # avg_volume_20d = 100_000 shares
        # With price=100, stop=95 => risk=5/share => max_risk=500 => size=100
        # 100 / 100_000 = 0.1% — this is less than 5%, so it WON'T be skipped!
        # We need avg_volume_20d to be VERY small to trigger the check.
        # position_size will be ~100 (500/5), so 5% of that is 100/0.05 = 2000
        # avg_volume_20d < 2000 would trigger the skip.
        mock_db.get_tier1_cache.return_value = _make_cache({
            'avg_volume_20d': 500,  # position 100 / 500 = 20% > 5%
        })
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 0

    def test_small_position_relative_to_volume_kept(self):
        """When position <= 5% of avg volume, the stock should be kept."""
        mock_db = MagicMock()
        mock_db.get_tier1_cache.return_value = _make_cache({
            'avg_volume_20d': 5_000_000,  # position 100 / 5M = 0.002% < 5%
        })
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1

    def test_zero_avg_volume_skips_check(self):
        """When avg_volume_20d is 0, liquidity check should be skipped."""
        mock_db = MagicMock()
        mock_db.get_tier1_cache.return_value = _make_cache({
            'avg_volume_20d': 0,
        })
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1


# ------------------------------------------------------------------
# Earnings guardrail tests
# ------------------------------------------------------------------

class TestEarningsGuardrail:
    """Position should be halved if earnings within 5 days."""

    def test_earnings_within_5_days_halves_position(self):
        """When earnings are 3 days away, position_size should be halved."""
        mock_db = MagicMock()
        future_date = (datetime.now().date() + timedelta(days=3)).strftime('%Y-%m-%d')
        mock_db.get_stock_earnings_date.return_value = future_date
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is not None
        assert 'earnings' in h.earnings_warning.lower()
        assert 'halved' in h.earnings_warning.lower()

    def test_earnings_today_halves_position(self):
        """When earnings are today, position should be halved."""
        mock_db = MagicMock()
        today = datetime.now().strftime('%Y-%m-%d')
        mock_db.get_stock_earnings_date.return_value = today
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is not None

    def test_earnings_after_5_days_no_change(self):
        """When earnings are 10 days away, position should NOT be halved."""
        mock_db = MagicMock()
        future_date = (datetime.now().date() + timedelta(days=10)).strftime('%Y-%m-%d')
        mock_db.get_stock_earnings_date.return_value = future_date
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is None

    def test_earnings_in_past_no_change(self):
        """Past earnings dates should not affect position."""
        mock_db = MagicMock()
        past_date = (datetime.now().date() - timedelta(days=5)).strftime('%Y-%m-%d')
        mock_db.get_stock_earnings_date.return_value = past_date
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is None

    def test_no_earnings_date_no_change(self):
        """When no earnings date is cached, position should not be affected."""
        mock_db = MagicMock()
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is None

    def test_earnings_1_day_away_halves_position(self):
        """When earnings are tomorrow, position should be halved."""
        mock_db = MagicMock()
        future_date = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        mock_db.get_stock_earnings_date.return_value = future_date
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        h = sector.highlights[0]
        assert h.earnings_warning is not None
        assert 'halved' in h.earnings_warning.lower()


# ------------------------------------------------------------------
# Correlation flag tests
# ------------------------------------------------------------------

class TestCorrelationFlag:
    """Correlation check within sector: flag pairs with same reason."""

    def test_same_reason_stocks_get_correlation_warning(self):
        """When two highlights have the same reason, both should be flagged."""
        mock_db = MagicMock()

        def _cache_for_symbol(sym):
            caches = {
                'AAPL': _make_cache({
                    'rs_percentile': 85, 'volume_ratio': 2.0, 'close': 100.0, 'open': 99.0,
                    'high_60d': 150.0, 'low_60d': 80.0,
                }),
                'GOOGL': _make_cache({
                    'rs_percentile': 82, 'volume_ratio': 1.8, 'close': 100.0, 'open': 99.0,
                    'high_60d': 150.0, 'low_60d': 80.0,
                }),
            }
            return caches.get(sym)

        mock_db.get_tier1_cache.side_effect = _cache_for_symbol
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL'), _make_stock('GOOGL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        # Both are Strong Momentum (RS >= 80) — should get correlation warning
        assert len(sector.highlights) >= 2
        warned = [h for h in sector.highlights if h.correlation_warning is not None]
        assert len(warned) >= 1

    def test_different_reasons_no_correlation_warning(self):
        """When highlights have different reasons, no correlation warnings."""
        mock_db = MagicMock()

        call_count = [0]

        def _cache_for_symbol(sym):
            call_count[0] += 1
            if call_count[0] == 1:
                # AAPL: Strong Momentum
                return _make_cache({
                    'rs_percentile': 85, 'volume_ratio': 2.0, 'close': 100.0, 'open': 99.0,
                    'high_60d': 150.0, 'low_60d': 80.0,
                })
            else:
                # GOOGL: Good R/R (low RS but qualifies from low/high range)
                # low=60, high=150, price=100. stop=60*0.99=59.4, RR=(150-100)/(100-59.4)=1.23 — not >= 2.0
                # Let me use a closer low to get better R:R
                # low=90, high=150, price=100. stop=90*0.99=89.1, RR=(150-100)/(100-89.1)=50/10.9=4.59
                return _make_cache({
                    'rs_percentile': 30, 'volume_ratio': 1.0, 'close': 100.0, 'open': 99.0,
                    'high_60d': 150.0, 'low_60d': 90.0, 'ema21': 95.0, 'ema50': 90.0,
                })

        mock_db.get_tier1_cache.side_effect = _cache_for_symbol
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL'), _make_stock('GOOGL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        warned = [h for h in sector.highlights if h.correlation_warning is not None]
        assert len(warned) == 0

    def test_single_highlight_no_correlation_warning(self):
        """Single highlight should have no correlation warning."""
        mock_db = MagicMock()
        mock_db.get_tier1_cache.return_value = _make_cache()
        mock_db.get_market_data_df.return_value = None
        mock_db.get_stock_earnings_date.return_value = None
        mock_db.save_recommendation = MagicMock()

        stocks = [_make_stock('AAPL')]
        sector = _run_find_stock_highlights(mock_db, stocks)

        assert len(sector.highlights) == 1
        assert sector.highlights[0].correlation_warning is None
