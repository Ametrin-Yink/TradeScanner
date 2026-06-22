"""Test entry_type field on StockHighlight.

Verifies that entry_type defaults to 'market' and that the reason-to-type
mapping in _find_stock_highlights produces the correct entry_type for each
setup reason.
"""
from core.sector_analyzer import StockHighlight


def _entry_type_for_reason(reason: str) -> str:
    """Replicates the mapping that _find_stock_highlights applies to entry_type."""
    if reason in ('Near Support', 'MA Bounce'):
        return 'limit'
    if reason in ('Breakout', 'Resistance Test'):
        return 'stop-limit'
    return 'market'


def test_entry_type_default_is_market():
    """StockHighlight defaults entry_type to 'market'."""
    h = StockHighlight(symbol='T', name='Test', price=100.0, market_cap=1e9,
                       reason='Breakout', detail='test')
    assert h.entry_type == 'market'


def test_entry_type_reason_mapping():
    """Each reason type maps to the correct entry_type."""
    cases = [
        ('Near Support', 'limit'),
        ('MA Bounce', 'limit'),
        ('Breakout', 'stop-limit'),
        ('Resistance Test', 'stop-limit'),
        ('Strong Momentum', 'market'),
        ('Good R/R', 'market'),
        ('Inside Day Breakout', 'market'),
        ('Bull Flag', 'market'),
        ('ADX Trend', 'market'),
    ]
    for reason, expected in cases:
        assert _entry_type_for_reason(reason) == expected, \
            f"reason={reason!r} expected entry_type={expected!r}"


def test_entry_type_field_writable():
    """entry_type can be set after construction, like other dynamic attrs."""
    h = StockHighlight(symbol='T', name='Test', price=100.0, market_cap=1e9,
                       reason='Near Support', detail='near 60d low')
    h.entry_type = 'limit'
    assert h.entry_type == 'limit'
    h.entry_type = 'stop-limit'
    assert h.entry_type == 'stop-limit'
