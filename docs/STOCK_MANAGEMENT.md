# 股票管理流程

## 添加新股票

### 方法1: Python脚本（推荐）

```python
from data.db import Database
from datetime import datetime

db = Database()
conn = db.get_connection()

# 添加单只股票
symbol = "NEW_TICKER"
name = "Company Name"
sector = "Technology"

conn.execute('''
    INSERT INTO stocks (symbol, name, sector, added_date, is_active)
    VALUES (?, ?, ?, ?, 1)
''', (symbol, name, sector, datetime.now().strftime('%Y-%m-%d')))
conn.commit()
```

### 方法2: 命令行

```bash
cd /home/admin/Projects/TradeChanceScreen
source venv/bin/activate
python -c "
from data.db import Database
from datetime import datetime
db = Database()
conn = db.get_connection()
conn.execute('INSERT INTO stocks (symbol, name, sector, added_date, is_active) VALUES (?, ?, ?, ?, 1)', ('EOSE', 'Eos Energy Enterprises, Inc.', 'Industrials', datetime.now().strftime('%Y-%m-%d')))
conn.commit()
print('Added EOSE')
"
```

### 方法3: API（如果服务器运行中）

```bash
curl -X POST http://47.90.229.136:19801/stocks/add \
  -H "Content-Type: application/json" \
  -d '{"symbol": "EOSE", "name": "Eos Energy Enterprises", "sector": "Industrials"}'
```

## 移除股票

### 软删除（推荐）

```bash
source venv/bin/activate
python -c "
from data.db import Database
db = Database()
conn = db.get_connection()
conn.execute('UPDATE stocks SET is_active = 0 WHERE symbol = ?', ('TICKER',))
conn.commit()
print('Removed TICKER')
"
```

### 硬删除

```bash
source venv/bin/activate
python -c "
from data.db import Database
db = Database()
conn = db.get_connection()
conn.execute('DELETE FROM stocks WHERE symbol = ?', ('TICKER',))
conn.commit()
print('Deleted TICKER')
"
```

## 检查股票状态

```bash
source venv/bin/activate
python -c "
from data.db import Database
db = Database()
conn = db.get_connection()

# Check if exists
cursor = conn.execute('SELECT symbol, name, is_active FROM stocks WHERE symbol = ?', ('EOSE',))
row = cursor.fetchone()
if row:
    print(f'{row[0]}: {row[1]} (Active: {bool(row[2])})')
else:
    print('Not found')

# List all active
cursor = conn.execute('SELECT COUNT(*) FROM stocks WHERE is_active = 1')
print(f'Total active: {cursor.fetchone()[0]}')
"
```

## 批量操作

### 添加多只股票

```python
stocks_to_add = [
    ('EOSE', 'Eos Energy Enterprises, Inc.', 'Industrials'),
    ('OPEN', 'Opendoor Technologies Inc.', 'Real Estate'),
    # Add more...
]

for symbol, name, sector in stocks_to_add:
    # Check if exists first
    cursor = conn.execute('SELECT 1 FROM stocks WHERE symbol = ?', (symbol,))
    if not cursor.fetchone():
        conn.execute('INSERT INTO stocks (symbol, name, sector, added_date, is_active) VALUES (?, ?, ?, ?, 1)',
                    (symbol, name, sector, datetime.now().strftime('%Y-%m-%d')))

conn.commit()
```

## 注意事项

1. **验证ticker**: 添加前用yfinance验证ticker存在
2. **避免重复**: 检查数据库是否已存在
3. **软删除优先**: 使用is_active=0而不是DELETE，保留历史记录
4. **缓存数据**: 新股票首次扫描会下载完整历史数据（较慢）
5. **Delisted处理**: 已退市股票放入`config/delisted.py`，不再扫描

## 数据库Schema

```sql
CREATE TABLE stocks (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    added_date TEXT,
    is_active INTEGER DEFAULT 1
);
```

- `is_active = 1`: 活跃，参与扫描
- `is_active = 0`: 非活跃，保留记录但不扫描
