"""Bar-level OHLC data quality validation."""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Known delisted/inactive symbols
_DELISTED = set()


def validate_ohlc(df: pd.DataFrame) -> list:
    """Validate OHLC DataFrame and return list of warning strings.
    Empty list means all checks passed."""
    warnings = []
    if len(df) == 0:
        return ['empty_dataframe']

    # Column name normalization: lowercase columns if capitalized
    cols = {c.lower(): c for c in df.columns}
    o = df[cols.get('open', 'Open')]
    h = df[cols.get('high', 'High')]
    l = df[cols.get('low', 'Low')]
    c = df[cols.get('close', 'Close')]
    v = df[cols.get('volume', 'Volume')]

    # High >= Low
    if (h < l).any():
        warnings.append('high < low detected')

    # Close within [Low, High]
    if (c < l).any() or (c > h).any():
        warnings.append('close outside [low, high] range')

    # Open within [Low, High]
    if (o < l).any() or (o > h).any():
        warnings.append('open outside [low, high] range')

    # NaN checks
    for col_name, col_data in [('open', o), ('high', h), ('low', l), ('close', c)]:
        if col_data.isna().any():
            warnings.append(f'{col_name} contains NaN values')
            break

    # Volume >= 0
    if (v <= 0).any():
        warnings.append('zero or negative volume')

    # Large overnight gap (>15%)
    if len(c) >= 2:
        close_prev = c.iloc[:-1].values
        open_curr = o.iloc[1:].values
        with np.errstate(divide='ignore', invalid='ignore'):
            gaps = np.abs((open_curr - close_prev) / np.where(close_prev != 0, close_prev, np.nan))
        if np.nanmax(gaps) > 0.15:
            warnings.append('large overnight gap (>15%)')

    # Stale prices (<=2 unique closes in last 30 bars)
    if len(c) >= 20:
        recent = c.tail(30)
        unique_closes = len(set(round(x, 4) for x in recent))
        if unique_closes <= 2:
            warnings.append('stale/flat prices (<=2 unique closes in 30 bars)')

    return warnings


def validate_ticker_active(symbol: str) -> bool:
    """Check if a ticker is known to be active (not delisted).
    Returns True if ticker appears active, False if known delisted."""
    if symbol.upper() in _DELISTED:
        return False
    return True
