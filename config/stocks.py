"""Stock universe loader - SP500, NASDAQ100, DOW."""
import json
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config.settings import settings
from config.delisted import filter_delisted
from data.db import Database

logger = logging.getLogger(__name__)


def load_sp500_symbols() -> list:
    """Fetch S&P 500 symbols from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        from pandas import read_html
        tables = read_html(response.text)
        sp500_df = tables[0]
        symbols = sp500_df['Symbol'].tolist()

        logger.info(f"Loaded {len(symbols)} S&P 500 symbols")
        return symbols
    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 symbols: {e}")
        return []


def load_nasdaq100_symbols() -> list:
    """Fetch NASDAQ 100 symbols from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/NASDAQ-100"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        from pandas import read_html
        tables = read_html(response.text)

        # Find the table with NASDAQ-100 components
        for table in tables:
            if 'Ticker' in table.columns or 'Symbol' in table.columns:
                col_name = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                symbols = table[col_name].tolist()
                logger.info(f"Loaded {len(symbols)} NASDAQ 100 symbols")
                return symbols

        return []
    except Exception as e:
        logger.error(f"Failed to fetch NASDAQ 100 symbols: {e}")
        return []


def load_dow_symbols() -> list:
    """Fetch Dow Jones Industrial Average symbols."""
    try:
        url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        from pandas import read_html
        tables = read_html(response.text)

        for table in tables:
            if 'Symbol' in table.columns:
                symbols = table['Symbol'].tolist()
                logger.info(f"Loaded {len(symbols)} Dow Jones symbols")
                return symbols

        return []
    except Exception as e:
        logger.error(f"Failed to fetch Dow Jones symbols: {e}")
        return []


def load_stock_universe(db: Database = None, force_refresh: bool = False) -> list:
    """
    Load complete stock universe (SP500 + NASDAQ100 + DOW).

    Args:
        db: Database instance
        force_refresh: Force reload from web

    Returns:
        List of unique symbols
    """
    db = db or Database()

    # Check if we already have stocks
    if not force_refresh:
        existing = db.get_active_stocks()
        if existing and len(existing) > 100:
            logger.info(f"Using existing {len(existing)} stocks from database")
            return existing

    # Load from web
    logger.info("Loading stock universe from web...")

    sp500 = load_sp500_symbols()
    nasdaq100 = load_nasdaq100_symbols()
    dow = load_dow_symbols()

    # Combine and deduplicate
    all_symbols = list(set(sp500 + nasdaq100 + dow))

    # Add market ETFs for regime detection (SPY for S&P500 trend)
    market_etfs = ['SPY']
    all_symbols = list(set(all_symbols + market_etfs))

    # Add sector ETFs for industry strength comparison
    sector_etfs = [
        'XLK',  # Technology
        'XLF',  # Financials
        'XLE',  # Energy
        'XLI',  # Industrials
        'XLP',  # Consumer Staples
        'XLY',  # Consumer Discretionary
        'XLB',  # Materials
        'XLU',  # Utilities
        'XLV',  # Health Care
        'XBI',  # Biotech
        'SMH',  # Semiconductor
        'IGV',  # Software
        'IYT',  # Transportation
    ]
    all_symbols = list(set(all_symbols + sector_etfs))
    logger.info(f"Added {len(sector_etfs)} sector ETFs for industry strength comparison")

    # Filter out delisted stocks
    all_symbols = filter_delisted(all_symbols)
    logger.info(f"Filtered out delisted stocks, {len(all_symbols)} remaining")

    # Clean symbols (remove any suffixes like BRK.B)
    cleaned = []
    for sym in all_symbols:
        if isinstance(sym, str):
            # Replace common suffixes
            sym = sym.replace('.', '-')
            cleaned.append(sym.strip())

    all_symbols = list(set(cleaned))
    all_symbols.sort()

    logger.info(f"Total unique symbols: {len(all_symbols)}")

    # Save to database
    for symbol in all_symbols:
        db.add_stock(symbol, "", "")

    return all_symbols


def save_universe_to_json(symbols: list, filepath: str = None):
    """Save universe to JSON file."""
    if not filepath:
        filepath = settings.CONFIG_DIR / "stocks.json"

    data = {
        'symbols': symbols,
        'count': len(symbols),
        'sources': ['SP500', 'NASDAQ100', 'DOW'],
        'last_updated': str(Path.cwd())
    }

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(symbols)} symbols to {filepath}")


def load_universe_from_json(filepath: str = None) -> list:
    """Load universe from JSON file."""
    if not filepath:
        filepath = settings.CONFIG_DIR / "stocks.json"

    if not Path(filepath).exists():
        logger.warning(f"Universe file not found: {filepath}")
        return []

    with open(filepath) as f:
        data = json.load(f)

    return data.get('symbols', [])


if __name__ == '__main__':
    # Load universe when run directly
    symbols = load_stock_universe()
    print(f"Loaded {len(symbols)} symbols")
    print(f"First 10: {symbols[:10]}")
