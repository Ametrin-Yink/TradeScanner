# Polygon.io 免费套餐深度调研报告

> 调研日期: 2026-03-29
> 免费套餐限制: 5 API calls/minute
> 文档来源: https://massive.com/docs/rest/

---

## 1. Polygon.io 免费套餐能力

### 1.1 API限制
- **调用频率**: 5 calls/minute = 300 calls/hour = 7,200 calls/day
- **延迟**: 15分钟延迟（非实时）
- **数据范围**: 历史数据2年

---

## 2. Snapshots API - 批量数据获取

### 2.1 Full Market Snapshot
**端点**: `GET /v2/snapshot/locale/us/markets/stocks/tickers`

**返回数据** (每只股票的快照):
```json
{
  "ticker": {
    "ticker": "AAPL",
    "day": {
      "c": 150.0,      // 当日收盘价
      "h": 152.0,      // 当日最高价
      "l": 149.0,      // 当日最低价
      "o": 151.0,      // 当日开盘价
      "v": 1000000,    // 当日成交量
      "vw": 150.5      // 当日VWAP
    },
    "prevDay": {
      "c": 149.0,      // 前日收盘价
      // ...
    },
    "min": {
      "c": 150.0,      // 最新分钟收盘价
      "h": 150.5,
      "l": 149.5,
      "o": 150.0,
      "v": 10000
    },
    "todaysChange": 1.0,
    "todaysChangePerc": 0.67
  }
}
```

**关键价值**:
- ✅ **1次调用获取全市场所有股票** (2,002只股票)
- ✅ 包含OHLCV、涨跌幅、VWAP
- ✅ 包含前日收盘价（可计算日回报）

**限制**:
- ❌ 不包含历史数据（仅当日）
- ❌ 不包含技术指标（EMA/RSI/ATR等）

---

## 3. Technical Indicators API

### 3.1 支持的指标
Polygon.io 提供4个技术指标的REST端点：

| 指标 | 端点 | 参数 |
|------|------|------|
| **SMA** | `/v1/indicators/sma/{stockTicker}` | window, series_type |
| **EMA** | `/v1/indicators/ema/{stockTicker}` | window, series_type |
| **RSI** | `/v1/indicators/rsi/{stockTicker}` | window, series_type |
| **MACD** | `/v1/indicators/macd/{stockTicker}` | short_window, long_window, signal_window |

### 3.2 调用成本分析

**当前系统需要的指标**:
- EMA8, EMA21, EMA50 (3 calls per stock)
- RSI14 (1 call per stock)
- MACD (可选，1 call per stock)

**计算**: 2000只股票 × 4指标 = **8,000 calls/day**

**免费套餐限制**: 7,200 calls/day

❌ **结论**: 免费套餐不足以支撑全量技术指标获取

---

## 4. 优化方案 - 结合Polygon.io免费套餐

### 4.1 推荐策略: 混合架构

```
┌─────────────────────────────────────────────────────────────┐
│                    数据获取策略                             │
├─────────────────────────────────────────────────────────────┤
│  Polygon.io (5 calls/min)      │  yfinance (本地计算)       │
│  ──────────────────────────    │  ─────────────────────     │
│  1. 全市场Snapshot (1 call)    │  1. 历史OHLCV数据          │
│     → 当日价格、涨跌幅          │     → 用于计算指标         │
│                                │                            │
│  2. 关键股票指标 (4 calls/min) │  2. 未被Polygon覆盖的股票  │
│     → 仅Top候选股票的EMA/RSI    │     → fallback方案         │
│                                │                            │
│  利用率: 1 + 20 = 21 calls     │  利用率: 主要数据源          │
│  (远低于300/hour限制)          │                            │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 具体实施建议

#### Phase 1: 使用Snapshot API优化当日数据获取

**当前问题**:
- 每天早上需要获取昨日收盘价来计算回报
- 需要调用yfinance 2000次获取最新价格

**优化方案**:
```python
import requests

class PolygonDataFetcher:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.polygon.io"
        self._call_count = 0
        self._last_call_time = 0

    def _rate_limited_call(self, endpoint):
        """确保不超过5 calls/minute"""
        elapsed = time.time() - self._last_call_time
        if elapsed < 12:  # 60/5 = 12 seconds between calls
            time.sleep(12 - elapsed)

        url = f"{self.base_url}{endpoint}?apiKey={self.api_key}"
        response = requests.get(url)
        self._last_call_time = time.time()
        self._call_count += 1
        return response.json()

    def get_market_snapshot(self) -> Dict[str, Dict]:
        """
        1次调用获取全市场快照
        包含: 当日OHLCV、前日收盘价、涨跌幅
        """
        data = self._rate_limited_call("/v2/snapshot/locale/us/markets/stocks/tickers")

        result = {}
        for ticker_data in data.get('tickers', []):
            ticker = ticker_data['ticker']
            result[ticker] = {
                'open': ticker_data['day']['o'],
                'high': ticker_data['day']['h'],
                'low': ticker_data['day']['l'],
                'close': ticker_data['day']['c'],
                'volume': ticker_data['day']['v'],
                'prev_close': ticker_data['prevDay']['c'],
                'change_pct': ticker_data['todaysChangePerc'],
                'vwap': ticker_data['day']['vw']
            }
        return result
```

**收益**:
- ✅ 1次调用替代2000次yfinance调用
- ✅ 获取前日收盘价（无需本地历史数据）
- ✅ 计算日回报更简单

#### Phase 2: 关键股票指标预获取

**策略**: 只对候选股票获取Polygon技术指标

```python
def fetch_indicators_for_candidates(self, candidates: List[str]):
    """
    只为候选股票获取技术指标
    假设30个候选 × 4指标 = 120 calls
    耗时: 120 × 12秒 = 24分钟（在可接受范围内）
    """
    indicators = {}

    for symbol in candidates:
        indicators[symbol] = {
            'ema8': self._get_ema(symbol, window=8),
            'ema21': self._get_ema(symbol, window=21),
            'ema50': self._get_ema(symbol, window=50),
            'rsi14': self._get_rsi(symbol, window=14)
        }

    return indicators

    def _get_ema(self, symbol: str, window: int) -> float:
        """获取单个EMA值"""
        endpoint = f"/v1/indicators/ema/{symbol}"
        params = f"window={window}&series_type=close&order=desc&limit=1"
        data = self._rate_limited_call(f"{endpoint}?{params}")
        return data.get('results', {}).get('values', [{}])[0].get('value')
```

**优化**: 只在筛选后获取Top 30候选股票的指标，而非全部2000只

#### Phase 3: 本地计算 + Polygon验证

**混合策略**:
```python
class HybridIndicatorCalculator:
    """结合本地计算和Polygon API验证"""

    def __init__(self, polygon_fetcher, use_polygon_for_candidates=True):
        self.polygon = polygon_fetcher
        self.use_polygon = use_polygon_for_candidates

    def calculate_for_screening(self, symbols: List[str]) -> Dict:
        """
        筛选阶段：使用本地计算（快速）
        """
        # 本地pandas计算，不调用API
        return self._local_calculation(symbols)

    def calculate_for_finalists(self, symbols: List[str]) -> Dict:
        """
        最终候选：使用Polygon API（精确）
        """
        if self.use_polygon and len(symbols) <= 50:
            # 只为少数候选调用API
            return self.polygon.fetch_indicators_for_candidates(symbols)
        else:
            return self._local_calculation(symbols)
```

---

## 5. 时间规划 - 免费套餐内完成扫描

### 5.1 优化后的每日流程

| 阶段 | 操作 | API Calls | 耗时 |
|------|------|-----------|------|
| 1 | 获取全市场Snapshot | 1 | 2秒 |
| 2 | yfinance获取历史数据（增量） | 0 | 3分钟 |
| 3 | 本地计算指标 + 策略筛选 | 0 | 5分钟 |
| 4 | 获取Top 30候选的Polygon指标 | 120 | 24分钟 |
| 5 | AI分析和报告生成 | 0 | 5分钟 |
| **总计** | | **121** | **37分钟** |

**可行性**:
- API Calls: 121 < 7,200 (✅)
- 时间: 37分钟 (✅ 比当前25分钟稍长，但数据更精确)

### 5.2 纯本地计算对比

| 方案 | 耗时 | 数据质量 | 复杂度 |
|------|------|---------|--------|
| 纯yfinance + 本地优化 | 15-20分钟 | 中 | 低 |
| Polygon Snapshot + 本地指标 | 20-25分钟 | 高 | 中 |
| Polygon Snapshot + Polygon指标 | 40-50分钟 | 极高 | 高 |

**推荐**: **纯yfinance + 本地优化** 或 **Polygon Snapshot + 本地指标**

---

## 6. 实施建议

### 6.1 立即可实施（本周）

#### 1. 集成Polygon Snapshot API
```python
# 新增: core/polygon_fetcher.py
class PolygonSnapshotFetcher:
    """专门用于获取全市场快照"""
    pass
```

**价值**:
- 验证当日数据与yfinance的一致性
- 作为yfinance的fallback
- 获取实时涨跌幅（无需本地计算）

#### 2. 保留本地计算为主
```
理由:
1. 免费Polygon不足以支撑全量指标获取
2. 本地计算优化后足够快（15-20分钟）
3. 避免外部依赖，系统更稳定
```

### 6.2 中期实施（下周）

#### 3. 候选股票Polygon指标验证
- 只为最终Top 10-30候选股票获取Polygon技术指标
- 用于交叉验证本地计算结果
- 提高高置信度候选的质量

---

## 7. 结论

### Polygon.io免费套餐评估

| 能力 | 可用性 | 评价 |
|------|--------|------|
| Snapshot（全市场） | ✅ 优秀 | 1次调用获取全部，强烈推荐 |
| 技术指标（EMA/RSI） | ⚠️ 有限 | 速率限制，只能用于少量股票 |
| 历史数据 | ❌ 不足 | 需要多次调用，免费套餐不够 |

### 最终建议

**最优架构**: **以yfinance本地计算为主，Polygon Snapshot为辅**

```
┌─────────────────────────────────────────────────────────┐
│                   推荐架构                               │
├─────────────────────────────────────────────────────────┤
│  数据获取                                                │
│  ├── yfinance: 历史OHLCV数据（主要数据源）               │
│  └── Polygon Snapshot: 当日快照（验证 + 涨跌幅）         │
│                                                         │
│  指标计算                                                │
│  ├── 本地pandas: 全量股票EMA/RSI/ATR（优化后15分钟）     │
│  └── Polygon API: Top 30候选验证（可选）                 │
│                                                         │
│  预期性能: 15-20分钟完成全量扫描                         │
└─────────────────────────────────────────────────────────┘
```

### 下一步行动

1. **实施本地优化**（指标缓存 + 批量插入）→ 节省20分钟
2. **集成Polygon Snapshot** → 额外数据验证
3. **监控和对比**两种数据源的一致性
4. **根据实际表现**决定是否扩展Polygon使用

---

*报告完成 - Polygon.io免费套餐有价值，但不足以替代本地计算，建议作为补充数据源*
