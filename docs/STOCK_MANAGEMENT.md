# Stock Management

Managing the stock universe for the Trade Scanner.

## Stock Universe Overview

The Trade Scanner uses a **static CSV file** (`nasdaq_stocklist_screener.csv`) as the source of truth for the stock universe. The database is initialized from this file and can be re-synced when needed.

### Categories

- **stocks**: Individual stocks from NASDAQ/NYSE (~2,800)
- **market_index_etf**: Market index ETFs (SPY, QQQ, IWM, VIXY, UVXY, etc.)

### Market Cap Filter

Only stocks with market cap >= $2B are included in the scan:

- Fetched from yfinance during Phase 0
- Stored in `stocks.market_cap` column
- Updated on each universe sync

---

## Adding Stocks

### Method 1: CSV File (Recommended)

Edit `nasdaq_stocklist_screener.csv`:

```csv
symbol,name,sector,category
NEW_TICKER,Company Name,Technology,stocks
```

Then re-initialize the database:

```bash
python -c "from core.stock_universe import StockUniverseManager; StockUniverseManager().initialize_database()"
```

### Method 2: Python API

```python
from core.stock_universe import StockUniverseManager
from data.db import Database

# Add single stock
db = Database()
db.add_stock(
    symbol="NEW_TICKER",
    name="Company Name",
    sector="Technology"
)

# Sync from CSV (recommended approach)
manager = StockUniverseManager()
result = manager.initialize_database()
print(f"Stocks: {result['stocks']}, ETFs: {result['etfs']}")
```

### Method 3: API (if server running)

```bash
curl -X POST http://47.90.229.136:19801/stocks/add \
  -H "Content-Type: application/json" \
  -d '{"symbol": "NEW_TICKER", "name": "Company Name", "sector": "Technology"}'
```

---

## Removing Stocks

### Soft Delete (Recommended)

```python
from data.db import Database

db = Database()
with db.get_connection() as conn:
    conn.execute(
        "UPDATE stocks SET is_active = 0 WHERE symbol = ?",
        ("TICKER",)
    )
    conn.commit()
```

### Hard Delete

```python
from data.db import Database

db = Database()
with db.get_connection() as conn:
    conn.execute(
        "DELETE FROM stocks WHERE symbol = ?",
        ("TICKER",)
    )
    conn.commit()
```

---

## Checking Stock Status

```python
from data.db import Database

db = Database()

# Check single stock
with db.get_connection() as conn:
    cursor = conn.execute(
        "SELECT symbol, name, sector, market_cap, is_active FROM stocks WHERE symbol = ?",
        ("AAPL",)
    )
    row = cursor.fetchone()
    if row:
        print(f"{row[0]}: {row[1]}, cap=${row[3]/1e9:.1f}B, active={row[4]}")

# List active stocks
count = db.get_stocks_count()
print(f"Active stocks: {count}")
```

---

## Stock Universe Sync

### Full Universe Initialization

```python
from core.stock_universe import StockUniverseManager

manager = StockUniverseManager()
result = manager.initialize_database()

print(f"Stocks added: {result['stocks']}")
print(f"ETFs added: {result['etfs']}")
print(f"Total: {result['total']}")
```

### Get Universe for Scanning

```python
from core.stock_universe import StockUniverseManager

manager = StockUniverseManager()

# Get all stocks (is_active=1)
all_stocks = manager.get_stocks()
print(f"Total stocks: {len(all_stocks)}")

# Get market ETFs for Tier 3
etfs = manager.get_market_etfs()
print(f"Market ETFs: {etfs}")
```

---

## Database Schema

```sql
CREATE TABLE stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    category TEXT DEFAULT 'stocks',  -- 'stocks' or 'market_index_etf'
    market_cap REAL,                   -- Market cap in dollars
    added_date TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE tier1_cache (
    symbol TEXT PRIMARY KEY,
    price REAL,
    ema8 REAL, ema21 REAL, ema50 REAL, ema200 REAL,
    atr REAL, adr REAL, atr_pct REAL, adr_pct REAL,
    return_3m REAL, return_6m REAL, return_12m REAL, return_5d REAL,
    rs_score REAL, rs_percentile REAL,
    distance_from_52w_high REAL, distance_from_52w_low REAL,
    volume REAL, avg_volume_20d REAL,
    calculated_at TEXT
);

CREATE TABLE tier3_cache (
    symbol TEXT PRIMARY KEY,
    data BLOB,  -- pickled DataFrame
    updated_at TEXT
);
```

---

## CSV File Format

The `nasdaq_stocklist_screener.csv` format:

```csv
symbol,name,sector,category
AAPL,Apple Inc,Technology,stocks
MSFT,Microsoft Corp,Technology,stocks
SPY,SPDR S&P 500,Index,market_index_etf
VIXY,ProShares VIX Short-Term Futures ETF,Volatility,market_index_etf
```

**Note**: Market cap is NOT in the CSV - it's fetched from yfinance during Phase 0.

---

## Important Notes

1. **CSV is source of truth**: Edit the CSV file for permanent changes
2. **Soft delete preferred**: Use `is_active=0` rather than DELETE
3. **Market cap from yfinance**: Not stored in CSV, fetched live
4. **Category matters**: 'stocks' for individual stocks, 'market_index_etf' for ETFs
5. **Universe sync**: Run `initialize_database()` to sync CSV changes to DB
6. **Filtered by cap**: Only stocks with market_cap >= $2B are scanned
