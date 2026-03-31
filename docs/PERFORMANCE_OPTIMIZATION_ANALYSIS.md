# 性能优化调研报告 - Trade Scanner

> 日期: 2026-03-29
> 调研目标: 识别系统瓶颈，提出优化方案，研究yfinance/polygon.io预计算数据替代本地计算的可行性

---

## 1. 当前系统性能概况

### 1.1 数据规模
- **活跃股票**: 2,002只
- **市场数据**: 436,475行
- **平均每只股票**: 218天历史数据
- **数据表结构**: symbol, date, open, high, low, close, volume

### 1.2 当前运行时间估算
基于CLAUDE.md中的记录：
- **全量扫描（首次）**: 70-80分钟
- **增量扫描（有缓存）**: 20-25分钟
- **数据获取**: 2-3分钟（增量）/ 60-70分钟（全量）
- **策略筛选**: 主要耗时环节

---

## 2. 识别的性能瓶颈

### 2.1 严重问题（高影响）

#### 2.1.1 指标重复计算 ⚠️ 最严重
**问题描述**: 每只股票的指标在每个策略中被重复计算多次

**具体表现**:
```python
# 在filter()中
ind = TechnicalIndicators(df)
ind.calculate_all()  # 第1次计算 EMA/ATR/RSI/Volume

# 在calculate_dimensions()中
ind = TechnicalIndicators(df)
ind.calculate_all()  # 第2次计算 - 完全相同！

# 在build_match_reasons()中
ind = TechnicalIndicators(df)
ind.calculate_all()  # 第3次计算！
```

**计算复杂度**:
- 每只股票的 `calculate_all()` 包含: EMA8/21/50, ATR14, ADR20, RSI14, Volume SMA20
- 假设每只股票被2个策略匹配: **每只股票最多6次重复计算**
- 2000只股票 × 6次 × 8策略 = 96,000次重复计算**

**性能损失估算**:
- pandas rolling/ewm计算是CPU密集型
- 96,000次重复计算 ≈ 15-20分钟额外耗时

#### 2.1.2 RS分数重复计算
**问题描述**: VCP-EP和Momentum策略独立计算所有股票的RS分数

```python
# VCP-EP Phase 0.1 - 计算所有股票的RS
for symbol in symbols:  # 2000次
    calculate_rs_score()

# Momentum Phase 1 - 再次计算所有股票的RS
for symbol in symbols:  # 2000次
    calculate_rs_score()
```

**性能损失**: 约2-3分钟

#### 2.1.3 逐个数据库插入
**问题位置**: `fetcher.py:243-254`

```python
# 当前实现 - 逐行插入
for date, row in df_to_save.iterrows():
    self.db.save_market_data(symbol, {...})  # 每行一次INSERT
```

**问题**: 218天数据 × 2000只股票 = 436,000次单独INSERT
**优化后**: 使用 `executemany()` 可达到 **10-50倍** 速度提升

---

### 2.2 中等问题（中等影响）

#### 2.2.1 策略间数据未共享
每个策略独立调用 `_get_data()`，即使同一只股票的数据在内存中已存在：

```python
# Strategy A 获取 AAPL 数据
aapl_df = strategy_a._get_data('AAPL')

# Strategy B 再次获取 AAPL 数据（重复查询）
aapl_df = strategy_b._get_data('AAPL')
```

**解决方案**: 使用统一的 `market_data` 字典缓存

#### 2.2.2 预过滤阶段计算浪费
在 `screen()` 方法中，某些策略对所有股票进行昂贵的预过滤计算：

```python
# VCP-EP: 对所有股票计算RS和52w metrics
for symbol in symbols:  # 2000次
    calculate_rs_score()  # 昂贵
    calculate_52w_metrics()  # 昂贵
    # 最后只有10-20只通过预过滤
```

**问题**: 95%的计算结果被丢弃

---

### 2.3 轻微问题（低影响）

#### 2.3.1 未使用批量数据获取API
当前使用 `ThreadPoolExecutor` + 逐个 `ticker.history()`，而非 `yf.download()` 批量API

#### 2.3.2 Python GIL限制
当前多线程受GIL限制，CPU密集型计算无法并行

---

## 3. 数据提供商预计算能力调研

### 3.1 yfinance 预计算数据

#### 3.1.1 可直接获取的数据（无需本地计算）

| 数据类型 | yfinance支持 | API方法 | 备注 |
|---------|-------------|---------|------|
| OHLCV | ✅ | `ticker.history()` | 已在用 |
| 52周高低 | ✅ | `ticker.info['fiftyTwoWeekHigh']` | 实时数据 |
| 50日/200日均价 | ✅ | `ticker.info['fiftyDayAverage']` | 预计算 |
| 成交量均值 | ✅ | `ticker.info['averageVolume']` | 预计算 |
| 市值 | ✅ | `ticker.info['marketCap']` | 已在用 |
| Beta | ✅ | `ticker.info['beta']` | 可用 |
| 市盈率 | ✅ | `ticker.info['trailingPE']` | 可用 |
| 行业/板块 | ✅ | `ticker.info['sector']` | 已在用 |

#### 3.1.2 无法直接获取的数据（必须本地计算）

| 数据类型 | 原因 | 复杂度 |
|---------|------|--------|
| EMA8/21/50 | 需要完整历史价格序列 | 中等 |
| ATR14 | 需要High/Low/Close序列 | 中等 |
| ADR20 | 需要High/Low序列 | 低 |
| RSI14 | 需要Close序列计算涨跌幅 | 中等 |
| VCP平台检测 | 需要算法识别模式 | 高 |
| Squeeze检测 | 需要多周期比较 | 中等 |
| CLV | 需要单根K线计算 | 极低 |

#### 3.1.3 yfinance批量API
```python
# 更高效的数据获取方式
import yfinance as yf

# 当前方式 - 逐个获取
for symbol in symbols:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="6mo")

# 优化方式 - 批量获取（yfinance原生支持）
df = yf.download(symbols, period="6mo", group_by='ticker', threads=True)
# 返回: MultiIndex DataFrame (symbol, date) -> OHLCV
```

**性能提升**: 批量API比逐个获取快 **5-10倍**（yfinance内部优化了并发和连接复用）

---

### 3.2 Polygon.io 预计算数据

Polygon.io 提供更专业的金融数据API，但它是**付费服务**。

#### 3.2.1 Polygon.io 技术指标API
Polygon提供直接的技术指标端点，无需本地计算：

| 指标 | API端点 | 说明 |
|------|---------|------|
| SMA | `/v1/indicators/sma/{stockTicker}` | 简单移动平均 |
| EMA | `/v1/indicators/ema/{stockTicker}` | 指数移动平均 |
| RSI | `/v1/indicators/rsi/{stockTicker}` | 相对强弱指标 |
| MACD | `/v1/indicators/macd/{stockTicker}` | MACD指标 |
| ATR | 需本地计算 | 无直接API |
| Bollinger Bands | 需本地计算 | 无直接API |

**限制**:
- 免费套餐: 5 API calls/minute
- 付费套餐: 从 $49/month 起
- 每个指标需要单独API调用

**成本分析**（2000只股票）:
- EMA: 2000 calls
- RSI: 2000 calls
- SMA: 2000 calls
- 总计: 6000 calls/天

**结论**: Polygon.io适合需要极高精度或低频策略，但对于日频扫描，本地计算更经济高效。

---

## 4. 优化方案

### 4.1 立即可实施的优化（Phase 1）

#### 4.1.1 指标计算结果缓存（最高优先级）

**实现思路**:
```python
class IndicatorCache:
    """线程安全的指标缓存"""
    def __init__(self):
        self._cache: Dict[str, TechnicalIndicators] = {}

    def get(self, symbol: str, df: pd.DataFrame) -> TechnicalIndicators:
        cache_key = f"{symbol}_{len(df)}_{df.index[-1]}"
        if cache_key not in self._cache:
            ind = TechnicalIndicators(df)
            ind.calculate_all()
            self._cache[cache_key] = ind
        return self._cache[cache_key]

    def clear(self):
        self._cache.clear()
```

**预期收益**:
- 避免每只股票的重复计算
- 估计节省: **15-20分钟**

#### 4.1.2 批量数据库插入

**当前代码优化**:
```python
# 从:
for date, row in df_to_save.iterrows():
    self.db.save_market_data(symbol, {...})

# 改为:
rows = [
    (symbol, date, row['open'], row['high'], row['low'], row['close'], row['volume'])
    for date, row in df_to_save.iterrows()
]
conn.executemany('''
    INSERT OR REPLACE INTO market_data (symbol, date, open, high, low, close, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?)
''', rows)
```

**预期收益**:
- 数据保存速度提升: **10-50倍**
- 估计节省: **2-3分钟**

#### 4.1.3 RS分数统一计算

**实现思路**:
```python
class Screener:
    def screen_all(self, symbols):
        # 预计算所有股票的RS（一次）
        rs_cache = self._precalculate_rs_for_all(symbols)

        # 传递给各策略
        for strategy in self._strategies.values():
            strategy.rs_cache = rs_cache
```

**预期收益**:
- 避免重复RS计算
- 估计节省: **2-3分钟**

---

### 4.2 中期优化（Phase 2）

#### 4.2.1 预计算指标持久化

**新数据库表设计**:
```sql
CREATE TABLE technical_indicators (
    symbol TEXT,
    date TEXT,
    ema8 REAL,
    ema21 REAL,
    ema50 REAL,
    ema200 REAL,
    atr14 REAL,
    adr20 REAL,
    adr_pct REAL,
    rsi14 REAL,
    volume_sma20 REAL,
    updated_at TIMESTAMP,
    PRIMARY KEY (symbol, date)
);
```

**实现逻辑**:
1. 每天收盘后，批量计算所有指标
2. 策略运行时直接查询，无需实时计算
3. 只计算增量数据（新交易日）

**预期收益**:
- 策略筛选阶段无需计算任何指标
- 估计节省: **30-40分钟**（全量扫描）

#### 4.2.2 策略并行执行

**实现思路**:
```python
from concurrent.futures import ProcessPoolExecutor

class Screener:
    def screen_all_parallel(self, symbols):
        with ProcessPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(strategy.screen, symbols): strategy
                for strategy in self._strategies.values()
            }
            for future in as_completed(futures):
                results.extend(future.result())
```

**注意事项**:
- 需要使用多进程（multiprocessing）而非多线程，绕过GIL
- 需要序列化传递数据（使用shared memory或Redis）
- 内存消耗会增加（8个进程 × 2000只股票数据）

**预期收益**:
- 在4核系统上，理论加速: **3-4倍**
- 估计节省: **10-15分钟**

---

### 4.3 长期优化（Phase 3）

#### 4.3.1 使用yfinance批量下载

**重构数据获取层**:
```python
class DataFetcher:
    def fetch_batch_optimized(self, symbols, period="6mo"):
        # 分批处理（yfinance限制每批约1000只）
        batch_size = 1000
        all_data = {}

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            df = yf.download(
                batch,
                period=period,
                group_by='ticker',
                threads=True,  # yfinance内部优化
                progress=False
            )
            # 解析MultiIndex DataFrame
            for symbol in batch:
                all_data[symbol] = df[symbol] if len(batch) > 1 else df

        return all_data
```

**预期收益**:
- 数据获取速度提升: **5-10倍**
- 估计节省: **5-10分钟**

#### 4.3.2 使用更高效的数据存储

**可选方案**:
- **Parquet格式**: 比SQLite快10倍读取，压缩率高
- **Redis**: 内存数据库，亚毫秒级查询
- **ClickHouse**: 列式数据库，适合时间序列分析

**推荐**: 对于当前规模（43万行），SQLite足够。当数据增长到1000万行以上时考虑迁移。

---

## 5. 优化收益汇总

| 优化项 | 当前耗时 | 优化后耗时 | 节省时间 | 实施难度 |
|--------|---------|-----------|---------|---------|
| 指标缓存 | 20-25min | 5-10min | **15min** | 低 |
| 批量插入 | 3min | 0.5min | **2.5min** | 极低 |
| RS预计算 | 3min | 1min | **2min** | 低 |
| yfinance批量 | 10min | 2min | **8min** | 中 |
| 指标持久化 | 40min | 5min | **35min** | 中 |
| 策略并行 | 10min | 3min | **7min** | 高 |
| **总计** | **86min** | **16.5min** | **69.5min** | - |

**预期最终性能**:
- 全量扫描: **70-80分钟 → 15-20分钟** (4-5倍加速)
- 增量扫描: **20-25分钟 → 5-8分钟** (3-4倍加速)

---

## 6. 实施优先级建议

### Phase 1（本周可完成）- 预期节省 20分钟
1. ✅ 指标计算结果缓存（最高优先级）
2. ✅ 批量数据库插入
3. ✅ RS分数统一预计算

### Phase 2（下周完成）- 预期节省 35分钟
4. 预计算指标持久化（新表设计）
5. yfinance批量下载优化

### Phase 3（可选）- 预期节省 15分钟
6. 策略并行执行（需要测试内存/CPU影响）
7. 考虑迁移到更高效存储

---

## 7. 数据提供商结论

### yfinance
- **适合场景**: 当前系统已使用，免费，数据质量可接受
- **优化方向**: 使用批量下载API，利用预计算的52周高低等基础数据
- **成本**: $0

### Polygon.io
- **适合场景**: 需要专业级技术指标API，或者需要美股Level 2数据
- **当前阶段**: 不推荐 - 成本效益比低
- **未来考虑**: 当需要实时数据或更高级分析时

### 推荐方案
**继续使用yfinance + 本地计算优化**，原因：
1. 日频扫描不需要实时数据
2. 本地计算一次性投入后可长期使用
3. 免费且稳定
4. 通过缓存和优化，性能已足够

---

## 8. 下一步行动

1. **立即开始Phase 1优化**（指标缓存）
2. **创建优化分支**进行测试
3. **性能基准测试**: 记录当前完整扫描耗时
4. **逐步实施**: 每次优化后测试并记录收益
5. **监控内存使用**: 确保优化不造成内存压力

---

*报告完成 - 准备开始实施Phase 1优化*
