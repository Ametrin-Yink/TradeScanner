"""Delisted stocks - symbols that are no longer trading."""

# Stocks that have been delisted or merged
# Format: SYMBOL: reason
DELISTED_STOCKS = {
    'WBA': 'Walgreens Boots Alliance - delisted March 2025',
    'UA': 'Under Armour - merged',
    'SBNY': 'Signature Bank - delisted after collapse',
    'FRC': 'First Republic Bank - delisted after collapse',
    'SIVB': 'SVB Financial - delisted after collapse',
}

# Quick lookup set
DELISTED_SYMBOLS = set(DELISTED_STOCKS.keys())


def is_delisted(symbol: str) -> bool:
    """Check if a symbol is delisted."""
    return symbol.upper() in DELISTED_SYMBOLS


def filter_delisted(symbols: list) -> list:
    """Filter out delisted symbols from a list."""
    return [s for s in symbols if not is_delisted(s)]


def get_delisted_info(symbol: str) -> str:
    """Get delisting reason for a symbol."""
    return DELISTED_STOCKS.get(symbol.upper(), "Unknown")
