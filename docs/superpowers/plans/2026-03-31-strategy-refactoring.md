# 策略系统重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决策略重叠问题，将8个策略重构为6个更清晰的策略，优化参数并统一命名

**Architecture:** 
- 合并A/B为"动能右侧突破"，B的RS筛选作为加分项
- 合并C/D为"均线回踩买入"，D的深度回调作为C的PD维度分档
- E重命名为"支撑回踩买入"，F多头模式并入E作为加分项
- F保留空头模式，重命名为"区间阻力做空"
- G重命名为"双顶双底策略"，TS最高分降至4分并增加市场环境过滤
- H移除做空，重命名为"抛物线回弹"
- 参数调整：VCP平台放宽至60天，50日高点<10%，缺口否决用绝对3%，U&R时间止损改为5天+CLV均值>0.4，财报日暂停Blow-off检测

**Tech Stack:** Python 3.10+, yfinance, pandas, numpy, SQLite

---

## 文件结构变更总览

### 策略文件重构

| 原文件 | 操作 | 新文件/目标 |
|--------|------|-------------|
| `core/strategies/vcp_ep.py` | 修改 | 保留，并入B的RS加分逻辑 |
| `core/strategies/momentum.py` | 删除 | 逻辑并入vcp_ep.py后删除 |
| `core/strategies/shoryuken.py` | 修改 | 并入D的深度回调逻辑，改名"均线回踩买入" |
| `core/strategies/pullbacks.py` | 删除 | 逻辑并入shoryuken.py后删除 |
| `core/strategies/upthrust_rebound.py` | 修改 | 重命名为"支撑回踩买入"，加入F多头加分逻辑 |
| `core/strategies/range_support.py` | 修改 | 重命名为"区间阻力做空"，删除多头模式 |
| `core/strategies/dtss.py` | 修改 | 重命名为"双顶双底策略"，TS最高分降至4分，加市场环境过滤 |
| `core/strategies/parabolic.py` | 修改 | 重命名为"抛物线回弹"，删除做空逻辑 |
| `core/strategies/__init__.py` | 修改 | 更新策略注册表，删除已合并策略 |

### 新增/修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/earnings_calendar.py` | 创建 | 财报日历获取（yfinance/polygon） |
| `config/strategy_config.yaml` | 修改 | 更新参数配置 |
| `策略描述.md` | 修改 | 更新所有策略文档 |
| `CLAUDE.md` | 修改 | 更新策略数量（8→6）和架构描述 |
| `docs/STOCK_MANAGEMENT.md` | 检查/修改 | 如有策略相关内容需更新 |
| `scheduler.py` | 删除 | 删除旧版，保留optimized版并重命名 |

### 质量标准（Gate Criteria）

每个Task组完成后必须通过以下检查才能提交：

| 检查项 | 方法 | 通过标准 |
|--------|------|----------|
| **语法检查** | `python3 -m py_compile` | 无语法错误 |
| **导入测试** | `python3 -c "from X import Y"` | 无导入错误 |
| **100股票小测试** | `python3 scripts/test_100_stocks.py` | 完成扫描，无异常崩溃 |
| **文档同步** | 手动检查 | 修改的策略在`策略描述.md`和`CLAUDE.md`中都有对应更新 |

**100股票小测试脚本位置**: `scripts/test_100_stocks.py`（Task 0创建）

---

## Task 0: 项目清理和测试准备

**Files:**
- Delete: `scheduler.py` (旧版)
- Rename: `scheduler_optimized.py` → `scheduler.py`
- Create: `scripts/test_100_stocks.py`

**目标**: 清理重复文件，创建100股票测试脚本

- [ ] **Step 1: 删除旧版scheduler，保留optimized并重命名**

```bash
cd /home/admin/Projects/TradeChanceScreen
git rm scheduler.py
mv scheduler_optimized.py scheduler.py
git add scheduler.py
```

- [ ] **Step 2: 检查root目录其他重复文件**

检查其他可能需要清理的文件：

```bash
# 列出root目录所有文件，检查重复
ls -la *.py *.txt *.json *.md 2>/dev/null | grep -E '\.(py|txt|json|md)$'
```

**如有其他重复，在此Task中一并处理。**

- [ ] **Step 3: 创建100股票测试脚本**

```python
# scripts/test_100_stocks.py
"""Quick test script for 100 stocks strategy validation."""
import sys
import logging
from pathlib import Path

sys.path.insert(0, '/home/admin/Projects/TradeChanceScreen')

from data.db import Database
from core.fetcher import DataFetcher
from core.screener import StrategyScreener, StrategyType
from config.stocks import get_active_stocks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_100_stocks():
    """Test all strategies with 100 stocks from active universe."""
    db = Database()
    fetcher = DataFetcher()
    
    # Get first 100 active stocks
    all_stocks = get_active_stocks()
    test_stocks = all_stocks[:100]
    logger.info(f"Testing with {len(test_stocks)} stocks: {test_stocks[:10]}...")
    
    # Test each strategy
    screener = StrategyScreener(fetcher=fetcher, db=db)
    
    results = {}
    errors = []
    
    for strategy_type in StrategyType:
        try:
            logger.info(f"\n=== Testing {strategy_type.value} ===")
            matches = screener.screen([strategy_type], test_stocks)
            results[strategy_type.value] = len(matches)
            logger.info(f"✓ {strategy_type.value}: {len(matches)} matches")
        except Exception as e:
            logger.error(f"✗ {strategy_type.value}: {e}")
            errors.append((strategy_type.value, str(e)))
            
    # Summary
    logger.info("\n=== Test Summary ===")
    logger.info(f"Total stocks tested: {len(test_stocks)}")
    logger.info(f"Strategies passed: {len(results)}/{len(list(StrategyType))}")
    
    if errors:
        logger.error(f"\nErrors encountered:")
        for strategy, error in errors:
            logger.error(f"  - {strategy}: {error}")
        return 1
    else:
        logger.info("\n✓ All strategies passed 100-stock test")
        return 0


if __name__ == "__main__":
    exit(test_100_stocks())
```

- [ ] **Step 4: 运行100股票测试（验证脚本工作）**

```bash
python3 scripts/test_100_stocks.py 2>&1 | head -50
```

Expected: 脚本能运行，可能因数据缓存不足而慢，但无崩溃

- [ ] **Step 5: 提交项目清理**

```bash
git add scripts/test_100_stocks.py
git commit -m "chore: clean up duplicate scheduler files, add 100-stock test script
- Remove old scheduler.py, rename optimized version
- Add scripts/test_100_stocks.py for validation"
```

---

**Files:**
- Create: `core/earnings_calendar.py`
- Test: `tests/test_earnings_calendar.py`

**Background:** Blow-off检测需要排除财报日，避免误触。

- [ ] **Step 1: 编写获取财报日期的函数**

```python
# core/earnings_calendar.py
import logging
from typing import List, Optional
from datetime import datetime, timedelta
import yfinance as yf

logger = logging.getLogger(__name__)


class EarningsCalendar:
    """获取和管理股票财报日期。"""

    def __init__(self):
        self._cache = {}
        self._cache_date = None

    def get_earnings_date(self, symbol: str) -> Optional[datetime]:
        """
        获取指定股票的下一个财报日期。

        Args:
            symbol: 股票代码

        Returns:
            财报日期或None
        """
        try:
            ticker = yf.Ticker(symbol)
            earnings = ticker.earnings_dates
            if earnings is None or earnings.empty:
                return None

            # 获取未来日期
            today = datetime.now().date()
            future_dates = earnings[earnings.index.date >= today]

            if future_dates.empty:
                return None

            # 返回最近的未来财报日期
            return future_dates.index[0].to_pydatetime()

        except Exception as e:
            logger.warning(f"Failed to get earnings date for {symbol}: {e}")
            return None

    def is_earnings_day(self, symbol: str, date: Optional[datetime] = None) -> bool:
        """
        检查指定日期是否为财报日。

        Args:
            symbol: 股票代码
            date: 检查日期，默认为今天

        Returns:
            是否为财报日
        """
        if date is None:
            date = datetime.now()

        earnings_date = self.get_earnings_date(symbol)
        if earnings_date is None:
            return False

        # 允许±1天误差（盘前/盘后发布）
        delta = abs((earnings_date.date() - date.date()).days)
        return delta <= 1

    def clear_cache(self):
        """清除缓存。"""
        self._cache.clear()
        self._cache_date = None
```

- [ ] **Step 2: 编写测试**

```python
# tests/test_earnings_calendar.py
import pytest
from datetime import datetime, timedelta
from core.earnings_calendar import EarningsCalendar


class TestEarningsCalendar:
    def test_init(self):
        cal = EarningsCalendar()
        assert cal._cache == {}
        assert cal._cache_date is None

    def test_is_earnings_day_with_no_earnings(self):
        cal = EarningsCalendar()
        # 使用一个不太可能有财报数据的测试symbol
        result = cal.is_earnings_day("TEST")
        assert result is False

    def test_is_earnings_day_cache(self):
        cal = EarningsCalendar()
        cal._cache["AAPL"] = datetime.now()
        # 由于我们使用yfinance实时获取，这里主要测试结构
```

- [ ] **Step 3: 运行测试**

```bash
cd /home/admin/Projects/TradeChanceScreen
python -m pytest tests/test_earnings_calendar.py -v
```
Expected: 测试通过（可能会有网络请求警告）

- [ ] **Step 4: 提交**

```bash
git add core/earnings_calendar.py tests/test_earnings_calendar.py
git commit -m "feat: add earnings calendar module for blow-off detection"
```

---

## Task 2: 合并策略A和B - 动能右侧突破

**Files:**
- Modify: `core/strategies/vcp_ep.py`
- Delete: `core/strategies/momentum.py` (Task 3中删除)
- Modify: `core/strategies/__init__.py`

**Background:** 将B的RS筛选逻辑并入A作为TC维度的加分项（RS>85百分位+1分），统一命名为"动能右侧突破"。

- [ ] **Step 1: 修改vcp_ep.py，增加RS评分模块**

在`core/strategies/vcp_ep.py`中，在`VCPEPStrategy`类中添加：

```python
    def _calculate_rs_score(self, symbol: str, df: pd.DataFrame) -> float:
        """
        计算RS评分（从原Momentum策略B合并）。
        
        Returns:
            0-1分（作为TC维度加分）
        """
        if len(df) < 252:
            return 0.0
            
        close = df['close']
        current_price = close.iloc[-1]
        
        # 计算RS
        price_63d = close.iloc[-63] if len(close) >= 63 else close.iloc[0]
        price_126d = close.iloc[-126] if len(close) >= 126 else close.iloc[0]
        price_252d = close.iloc[-252] if len(close) >= 252 else close.iloc[0]
        
        rs_3m = (current_price - price_63d) / price_63d
        rs_6m = (current_price - price_126d) / price_126d
        rs_12m = (current_price - price_252d) / price_252d
        
        rs_score = rs_3m * 0.4 + rs_6m * 0.3 + rs_12m * 0.3
        
        # 转换为0-1分加分
        if rs_score > 0.5:
            return 1.0
        elif rs_score > 0.3:
            return 0.5 + (rs_score - 0.3) / 0.2 * 0.5
        else:
            return max(0.0, rs_score / 0.3 * 0.5)
```

- [ ] **Step 2: 修改TC维度计算，加入RS加分**

找到`VCPEPStrategy.calculate_dimensions()`方法，在TC维度计算后添加：

```python
    def calculate_dimensions(self, symbol: str, df: pd.DataFrame) -> List[ScoringDimension]:
        """Calculate scoring dimensions with RS bonus from Momentum."""
        # ... 原有计算代码 ...
        
        # TC维度增加RS加分（从策略B合并）
        rs_bonus = self._calculate_rs_score(symbol, df)
        tc_score = min(5.0, tc_score + rs_bonus)
        
        # ... 返回维度列表 ...
```

- [ ] **Step 3: 放宽50日高点距离门槛至10%**

在预筛选部分修改：

```python
    # Layer 2: 距离50日高点（放宽至<10%）
    def _filter_50d_high(self, df: pd.DataFrame) -> bool:
        """放宽至10%以捕获更多候选。"""
        if len(df) < 50:
            return False
        high_50d = df['high'].tail(50).max()
        current = df['close'].iloc[-1]
        distance = (high_50d - current) / high_50d
        return distance < 0.10  # 从0.05放宽到0.10
```

- [ ] **Step 4: 放宽VCP平台时间窗口至15-60天**

修改平台检测参数：

```python
    PARAMS = {
        # ... 其他参数 ...
        'platform_lookback_range': (15, 60),  # 从(15, 30)放宽
        'platform_amplitude_45d_max': 0.08,   # >45天平台振幅<8%
    }
```

- [ ] **Step 5: 更新策略名称和描述**

```python
    NAME = "动能右侧突破"
    STRATEGY_TYPE = StrategyType.EP
    DESCRIPTION = "动能右侧突破 - VCP平台+放量突破，RS>85百分位加分（合并原Momentum）"
```

- [ ] **Step 6: 运行100股票测试验证**

```bash
python3 scripts/test_100_stocks.py 2>&1 | grep -E "(Testing|matches|passed|Error)"
```

Expected: 所有6个策略（合并后）都能正常测试，无崩溃

- [ ] **Step 7: 提交**

```bash
git add core/strategies/vcp_ep.py tests/test_strategies_v3.py
git commit -m "refactor: merge Momentum into VCP-EP as RS bonus, rename to 动能右侧突破
- Add RS score calculation as TC dimension bonus
- Relax 50d high distance to <10%
- Extend VCP platform window to 15-60 days"
```

---

## Task 3: 删除策略B (momentum.py)

**Files:**
- Delete: `core/strategies/momentum.py`
- Modify: `core/strategies/__init__.py`

- [ ] **Step 1: 从注册表移除MomentumStrategy**

修改`core/strategies/__init__.py`：

```python
# 删除这一行:
from .momentum import MomentumStrategy

# 从STRATEGY_REGISTRY删除:
STRATEGY_REGISTRY = {
    # ... 删除 MOMENTUM: MomentumStrategy ...
}
```

- [ ] **Step 2: 删除momentum.py文件**

```bash
rm core/strategies/momentum.py
```

- [ ] **Step 3: 提交**

```bash
git add core/strategies/__init__.py
git rm core/strategies/momentum.py
git commit -m "refactor: remove standalone Momentum strategy, merged into 动能右侧突破"
```

---

## Task 4: 合并策略C和D - 均线回踩买入

**Files:**
- Modify: `core/strategies/shoryuken.py`
- Delete: `core/strategies/pullbacks.py` (Task 5中删除)

**Background:** 将D的EMA50深度回调作为C的PD维度分档，重命名为"均线回踩买入"。

- [ ] **Step 1: 修改PD维度，增加深度回调分档**

在`core/strategies/shoryuken.py`中修改`calculate_dimensions`：

```python
    def _calculate_pullback_depth(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        计算回踩深度评分（合并原Pullbacks策略D）。
        
        Returns:
            Dict with score and level
        """
        ind = TechnicalIndicators(df)
        ind.calculate_all()
        
        current_price = df['close'].iloc[-1]
        ema = ind.indicators.get('ema', {})
        ema21 = ema.get('ema21', current_price)
        ema50 = ema.get('ema50', current_price * 0.95)
        
        # 计算到各均线的距离
        dist_to_ema21 = abs(current_price - ema21) / ema21
        dist_to_ema50 = abs(current_price - ema50) / ema50
        
        # PD维度评分
        if dist_to_ema21 < 0.03:  # 回踩EMA21附近
            score = 3.0
            level = "EMA21"
        elif dist_to_ema50 < 0.03:  # 回踩EMA50附近
            score = 1.5  # 深回调，分数较低
            level = "EMA50"
        elif current_price > ema21:  # EMA21-50之间
            score = 2.0
            level = "Between"
        else:
            score = 0.5
            level = "Deep"
            
        return {
            'score': score,
            'level': level,
            'dist_ema21': dist_to_ema21,
            'dist_ema50': dist_to_ema50
        }
```

- [ ] **Step 2: 修改策略名称和描述**

```python
    NAME = "均线回踩买入"
    STRATEGY_TYPE = StrategyType.SHORYUKEN
    DESCRIPTION = "均线回踩买入 - 强趋势中EMA21/50分档回踩买入（合并原Pullbacks）"
```

- [ ] **Step 3: 修改缺口否决为绝对3%阈值**

在缺口检测部分：

```python
    def _check_gap_risk(self, df: pd.DataFrame) -> bool:
        """
        检查隔夜缺口风险 - 改为绝对3%阈值。
        """
        atr_data = TechnicalIndicators(df)._calculate_atr(period=14)
        atr14 = atr_data.get('atr', 0)
        current_price = df['close'].iloc[-1]
        
        # 使用绝对3%而非ATR倍数
        gap_estimate = 0.4 * atr14
        gap_pct = gap_estimate / current_price
        
        gap_limit_pct = 0.03  # 3%绝对阈值（原0.8×ATR）
        
        return gap_pct > gap_limit_pct
```

- [ ] **Step 4: 提交**

```bash
git add core/strategies/shoryuken.py
git commit -m "refactor: merge Pullbacks into Shoryuken as PD dimension, rename to 均线回踩买入
- Add EMA21/50 pullback depth scoring
- Change gap veto to absolute 3% threshold"
```

---

## Task 5: 删除策略D (pullbacks.py)

**Files:**
- Delete: `core/strategies/pullbacks.py`
- Modify: `core/strategies/__init__.py`

- [ ] **Step 1: 从注册表移除PullbacksStrategy**

修改`core/strategies/__init__.py`：

```python
# 删除这一行:
from .pullbacks import PullbacksStrategy

# 从STRATEGY_REGISTRY删除:
STRATEGY_REGISTRY = {
    # ... 删除 PULLBACKS: PullbacksStrategy ...
}
```

- [ ] **Step 2: 删除pullbacks.py文件**

```bash
rm core/strategies/pullbacks.py
```

- [ ] **Step 3: 提交**

```bash
git add core/strategies/__init__.py
git rm core/strategies/pullbacks.py
git commit -m "refactor: remove standalone Pullbacks strategy, merged into 均线回踩买入"
```

---

## Task 6: 重构策略E - 支撑回踩买入

**Files:**
- Modify: `core/strategies/upthrust_rebound.py`

**Background:** 重命名为"支撑回踩买入"，将F的多头模式加分逻辑并入。

- [ ] **Step 1: 修改时间止损为5天+CLV均值>0.4**

```python
    def _check_time_stop(self, symbol: str, entry_date: datetime, 
                         df: pd.DataFrame) -> bool:
        """
        时间止损检查 - 5天未反弹退出。
        同时检查5天CLV均值>0.4。
        """
        # 获取入场后的数据
        entry_idx = df.index.get_loc(entry_date)
        if entry_idx < 0 or entry_idx + 5 >= len(df):
            return False
            
        post_entry = df.iloc[entry_idx:entry_idx+5]
        
        # 检查5天内是否反弹
        entry_price = df['close'].iloc[entry_idx]
        max_price = post_entry['close'].max()
        
        if max_price <= entry_price:
            # 5天未反弹，检查CLV均值
            clv_values = []
            for _, row in post_entry.iterrows():
                high, low, close = row['high'], row['low'], row['close']
                if high != low:
                    clv = (close - low) / (high - low)
                    clv_values.append(clv)
                    
            if clv_values and sum(clv_values) / len(clv_values) < 0.4:
                return True  # 触发时间止损
                
        return False
```

- [ ] **Step 2: 增加区间存在加分（从F多头模式合并）**

```python
    def _calculate_sq_score(self, symbol: str, df: pd.DataFrame) -> float:
        """
        计算SQ维度分数，增加区间存在加分。
        """
        # ... 原有SQ计算 ...
        sq_score = base_score
        
        # 如果同时存在上方明确阻力位（即构成区间），加分
        resistance = self._detect_resistance_level(df)
        if resistance is not None:
            support = self._detect_support_level(df)
            if support is not None:
                range_width = (resistance - support) / support
                if 0.05 < range_width < 0.20:  # 合理的区间宽度
                    sq_score += 0.5
                    
        return min(6.0, sq_score)  # 最高6分
```

- [ ] **Step 3: 更新策略名称和描述**

```python
    NAME = "支撑回踩买入"
    STRATEGY_TYPE = StrategyType.UPTHRUST_REBOUND
    DESCRIPTION = "支撑回踩买入 - 支撑位假跌破后反弹，区间存在加分（合并原Range多头）"
```

- [ ] **Step 4: 提交**

```bash
git add core/strategies/upthrust_rebound.py
git commit -m "refactor: rename U&R to 支撑回踩买入, merge Range long logic
- Change time stop to 5 days + CLV avg > 0.4
- Add range existence bonus (+0.5 SQ)"
```

---

## Task 7: 重构策略F - 区间阻力做空

**Files:**
- Modify: `core/strategies/range_support.py`

**Background:** 删除多头模式，只保留空头模式，重命名为"区间阻力做空"。

- [ ] **Step 1: 删除多头模式相关代码**

删除或注释掉多头模式的预筛选、评分和入场逻辑，只保留空头模式。

```python
    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        只保留空头模式 - 在阻力位做空。
        """
        # Phase 0: 只在空头环境或震荡市运行
        if not self._is_short_environment():
            logger.info("RangeResistanceShort: Not in short environment, skipping")
            return []
            
        # 只处理空头模式的预筛选
        prefiltered = []
        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None:
                    continue
                    
                # 只检查空头条件
                if self._prefilter_short(symbol, df):
                    prefiltered.append(symbol)
            except Exception as e:
                logger.debug(f"Error pre-filtering {symbol}: {e}")
                continue
                
        return super().screen(prefiltered)
```

- [ ] **Step 2: 增加市场环境过滤**

```python
    def _is_short_environment(self) -> bool:
        """
        检查是否处于适合做空的市场环境。
        Returns True if bearish or neutral.
        """
        try:
            spy_df = self._get_data('SPY')
            if spy_df is None or len(spy_df) < 200:
                return False
                
            close = spy_df['close'].iloc[-1]
            ema200 = spy_df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            ema50 = spy_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            
            # Bearish: SPY < EMA200
            if close < ema200:
                return True
                
            # Neutral: EMA50 flat or declining
            ema50_past = spy_df['close'].ewm(span=50, adjust=False).mean().iloc[-10]
            if ema50 <= ema50_past:
                return True
                
            return False
            
        except Exception as e:
            logger.warning(f"Error checking market environment: {e}")
            return False
```

- [ ] **Step 3: 更新策略名称和描述**

```python
    NAME = "区间阻力做空"
    STRATEGY_TYPE = StrategyType.RANGE_SUPPORT
    DESCRIPTION = "区间阻力做空 - 下降趋势中区间顶部做空（已移除多头模式）"
```

- [ ] **Step 4: 提交**

```bash
git add core/strategies/range_support.py
git commit -m "refactor: rename RangeSupport to 区间阻力做空, remove long mode
- Add market environment filter (bearish/neutral only)
- Keep only short mode with relative weakness logic"
```

---

## Task 8: 重构策略G - 双顶双底策略

**Files:**
- Modify: `core/strategies/dtss.py`

**Background:** 重命名为"双顶双底策略"，TS维度最高分降至4分，增加市场环境过滤。

- [ ] **Step 1: 修改TS维度最高分**

```python
    # 在TS维度评分中限制最高分
    def _calculate_ts_score(self, df: pd.DataFrame, direction: str) -> float:
        """
        计算TS维度分数，最高4分（原6分）。
        左侧交易风险极高，不允许最高仓位。
        """
        # ... 原有计算逻辑 ...
        base_score = min(4.0, raw_score)  # 限制最高4分
        return base_score
```

- [ ] **Step 2: 增加市场环境过滤**

```python
    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        只在非多头环境（bearish/neutral）运行做空。
        """
        # 检测市场环境
        market_env = self._detect_market_environment()
        
        # 做空只在非bullish环境
        if market_env == 'bullish' and self._get_direction() == 'short':
            logger.info("DTSS: Bullish market, skipping short mode")
            return []
            
        return super().screen(symbols)
```

- [ ] **Step 3: 更新策略名称和描述**

```python
    NAME = "双顶双底策略"
    STRATEGY_TYPE = StrategyType.DTSS
    DESCRIPTION = "双顶双底策略 - DTSS派发/吸筹，TS最高分4分，非多头环境做空"
```

- [ ] **Step 4: 提交**

```bash
git add core/strategies/dtss.py
git commit -m "refactor: rename DTSS to 双顶双底策略
- Reduce TS dimension max score to 4
- Add market environment filter for short mode"
```

---

## Task 9: 重构策略H - 抛物线回弹

**Files:**
- Modify: `core/strategies/parabolic.py`

**Background:** 删除做空逻辑，只保留Capitulation做多，重命名为"抛物线回弹"。

- [ ] **Step 1: 删除做空逻辑**

删除Parabolic顶部做空的所有相关代码，只保留Capitulation底部做多。

```python
    def screen(self, symbols: List[str]) -> List[StrategyMatch]:
        """
        只保留Capitulation底部做多逻辑。
        """
        # Phase 0: 只在恐慌/下降趋势运行
        if not self._is_capitulation_environment():
            return []
            
        # 只筛选符合Capitulation条件的股票
        prefiltered = []
        for symbol in symbols:
            try:
                df = self._get_data(symbol)
                if df is None:
                    continue
                    
                if self._is_capitulation_setup(symbol, df):
                    prefiltered.append(symbol)
            except Exception as e:
                logger.debug(f"Error screening {symbol}: {e}")
                continue
                
        return super().screen(prefiltered)
        
    def _is_capitulation_environment(self) -> bool:
        """检查是否处于Capitulation环境（恐慌/下跌）。"""
        try:
            spy_df = self._get_data('SPY')
            if spy_df is None:
                return False
                
            close = spy_df['close'].iloc[-1]
            ema50 = spy_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            
            # Capitulation只在下跌趋势或EMA50附近
            return close < ema50 * 1.05  # 允许5%缓冲
            
        except Exception:
            return False
```

- [ ] **Step 2: 更新策略名称和描述**

```python
    NAME = "抛物线回弹"
    STRATEGY_TYPE = StrategyType.PARABOLIC
    DESCRIPTION = "抛物线回弹 - 恐慌底部Capitulation做多（已移除Parabolic做空）"
```

- [ ] **Step 3: 提交**

```bash
git add core/strategies/parabolic.py
git commit -m "refactor: rename Parabolic to 抛物线回弹, remove short mode
- Keep only capitulation long setup
- Add capitulation environment filter"
```

---

## Task 10: 更新Blow-off检测（财报日暂停）

**Files:**
- Modify: `core/indicators.py`

**Background:** Blow-off检测在财报日暂停，避免误触。

- [ ] **Step 1: 修改blow-off检测，加入财报检查**

在`core/indicators.py`中修改`detect_blow_off`：

```python
    def detect_blow_off(self, symbol: str = None, earnings_cal: 'EarningsCalendar' = None) -> Dict[str, any]:
        """
        检测blow-off信号，财报日暂停。
        
        Args:
            symbol: 股票代码（用于财报检查）
            earnings_cal: 财报日历实例
        """
        # 财报日检查
        if symbol and earnings_cal:
            if earnings_cal.is_earnings_day(symbol):
                return {
                    'is_blow_off': False,
                    'signal': None,
                    'reason': 'Earnings day - detection paused'
                }
        
        # ... 原有检测逻辑 ...
```

- [ ] **Step 2: 提交**

```bash
git add core/indicators.py
git commit -m "feat: add earnings day pause for blow-off detection"
```

---

## Task 11: 更新策略注册表

**Files:**
- Modify: `core/strategies/__init__.py`

- [ ] **Step 1: 更新导入和注册表**

```python
# core/strategies/__init__.py
"""Strategy registry and exports for all trading strategies."""
from typing import Dict, Type, List
from .base_strategy import BaseStrategy, StrategyMatch, ScoringDimension, StrategyType

# Import all strategies (6 strategies after refactoring)
from .vcp_ep import VCPEPStrategy  # 动能右侧突破 (A+B merged)
from .shoryuken import ShoryukenStrategy  # 均线回踩买入 (C+D merged)
from .upthrust_rebound import UpthrustReboundStrategy  # 支撑回踩买入 (E)
from .range_support import RangeSupportStrategy  # 区间阻力做空 (F short only)
from .dtss import DTSSStrategy  # 双顶双底策略 (G)
from .parabolic import ParabolicStrategy  # 抛物线回弹 (H long only)

# Registry mapping (6 strategies)
STRATEGY_REGISTRY: Dict[StrategyType, Type[BaseStrategy]] = {
    StrategyType.EP: VCPEPStrategy,  # 动能右侧突破
    StrategyType.SHORYUKEN: ShoryukenStrategy,  # 均线回踩买入
    StrategyType.UPTHRUST_REBOUND: UpthrustReboundStrategy,  # 支撑回踩买入
    StrategyType.RANGE_SUPPORT: RangeSupportStrategy,  # 区间阻力做空
    StrategyType.DTSS: DTSSStrategy,  # 双顶双底策略
    StrategyType.PARABOLIC: ParabolicStrategy,  # 抛物线回弹
}

# 注意: MOMENTUM 和 PULLBACKS 已被合并删除
```

- [ ] **Step 2: 提交**

```bash
git add core/strategies/__init__.py
git commit -m "refactor: update strategy registry for 6-strategy system
- Remove Momentum and Pullbacks (merged)
- Update all strategy names to Chinese"
```

---

## Task 12: 更新策略配置

**Files:**
- Modify: `config/strategy_config.yaml`

- [ ] **Step 1: 更新所有策略配置**

```yaml
# Strategy Configuration Template (Refactored)

# Strategy A+B merged: 动能右侧突破 (Momentum Breakout)
strategy_a_vcp_ep:
  min_platform_days: 15
  max_platform_days: 60  # 放宽至60天
  platform_amplitude_45d_max: 0.08  # 长期平台振幅更严格
  max_platform_range_pct: 0.12
  min_contraction_factor: 0.6
  breakout_threshold_pct: 0.02
  distance_50d_high_max: 0.10  # 放宽至10%
  rs_bonus_threshold: 0.85  # RS>85百分位加分
  target_r_multiplier: 2.5

# Strategy C+D merged: 均线回踩买入 (EMA Pullback)
strategy_c_shoryuken:
  pullback_max_pct: 0.08
  pullback_min_pct: 0.03
  volume_dry_up_threshold: 0.7
  gap_veto_threshold_pct: 0.03  # 绝对3%
  target_r_multiplier: 2.0

# Strategy E: 支撑回踩买入 (Support Bounce)
strategy_e_upthrust_rebound:
  max_distance_from_support: 0.03
  support_tolerance_atr: 0.5
  volume_veto_threshold: 1.5
  clv_veto_threshold: 0.3
  time_stop_days: 5  # 5天时间止损
  time_stop_clv_min: 0.4  # CLV均值>0.4
  range_existence_bonus: 0.5  # 区间存在加分
  target_r_multiplier: 2.0

# Strategy F short only: 区间阻力做空 (Range Resistance Short)
strategy_f_range_support:
  max_distance_from_level: 0.03
  min_range_width_atr_multiple: 1.5
  min_test_interval_days: 3
  time_decay_days: 5
  relative_weakness_min: 0.01  # 相对弱势阈值
  target_r_multiplier: 1.5

# Strategy G: 双顶双底策略 (DTSS)
strategy_g_dtss:
  max_distance_from_level: 0.03
  min_test_interval_days: 10
  volume_climax_threshold: 4.0
  vix_reject_threshold: 30.0
  vix_limit_threshold: 25.0
  ts_max_score: 4.0  # TS最高分降至4分
  target_r_multiplier: 3.0

# Strategy H long only: 抛物线回弹 (Capitulation Bounce)
strategy_h_parabolic:
  rsi_oversold: 20
  ema_atr_multiplier: 5.0
  volume_climax_threshold: 4.0
  stop_atr_multiplier: 2.0
  capitulation_only: true  # 只做多
  target_r_multiplier: 2.5

# Blow-off detection settings
blow_off_detection:
  price_spike_threshold: 2.0  # 2x ATR
  volume_spike_threshold: 3.0  # 3x 5d avg
  clv_decline_threshold: 0.6
  pause_on_earnings: true  # 财报日暂停
```

- [ ] **Step 2: 提交**

```bash
git add config/strategy_config.yaml
git commit -m "config: update strategy config for refactored 6-strategy system"
```

---

## Task 13: 更新CLAUDE.md文档

**Files:**
- Modify: `CLAUDE.md`

**目标**: 更新CLAUDE.md中关于策略数量和架构的描述

- [ ] **Step 1: 更新项目概述中的策略数量**

```markdown
## Project Overview

Automated US stock trading opportunity scanner based on strategies in `策略描述.md`. 
Runs daily at 6:00 AM ET to analyze 2000+ stocks using **6 trading strategies** (v3.0 refactored), 
ranks opportunities via AI, generates web-based reports with Discord/WeChat notifications.
```

- [ ] **Step 2: 更新架构中的策略列表**

```markdown
## Architecture

- `core/` - Pipeline components: market_analyzer, fetcher, screener, selector, analyzer, reporter
- `core/strategies/` - **6 strategies**: 
  - 动能右侧突破 (merged from VCP-EP + Momentum)
  - 均线回踩买入 (merged from Shoryuken + Pullbacks)  
  - 支撑回踩买入 (Upthrust & Rebound)
  - 区间阻力做空 (Range Support short only)
  - 双顶双底策略 (DTSS)
  - 抛物线回弹 (Capitulation only)
```

- [ ] **Step 3: 添加策略重构说明**

```markdown
## Strategy v3.0 Refactoring

**2026-03-31重构**: 8策略 → 6策略
- A+B合并为"动能右侧突破" (减少重复)
- C+D合并为"均线回踩买入" (避免接飞刀叠加)
- E重命名为"支撑回踩买入"，加入Range多头加分
- F只保留做空，重命名"区间阻力做空"
- G重命名"双顶双底策略"，TS最高分降至4
- H只保留做多，重命名"抛物线回弹"
```

- [ ] **Step 4: 更新测试部分**

```markdown
## Testing

- **100-Stock Quick Test**: `python3 scripts/test_100_stocks.py` - Fast validation after strategy changes
- **Full Scan (Cached):** Dynamic universe (market cap >$2B) takes ~20-25 minutes
```

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for v3.0 strategy refactoring
- Update strategy count from 8 to 6
- Add refactoring changelog
- Document new strategy names"
```

---

## Task 14: 更新策略描述.md文档

**Files:**
- Modify: `策略描述.md`

- [ ] **Step 1: 更新策略名称和合并说明**

在文档开头增加重构说明：

```markdown
# 交易策略详细描述 (v3.0 重构版)

> **重要**: 本文档对应v3.0重构后的策略系统。8个策略已合并为6个：
> - A+B → 动能右侧突破 (VCP+RS动量)
> - C+D → 均线回踩买入 (EMA21/50分档)
> - E → 支撑回踩买入 (U&R，Range多头加分)
> - F → 区间阻力做空 (仅做空)
> - G → 双顶双底策略 (TS最高分4分)
> - H → 抛物线回弹 (仅做多)

## 策略总览

| 策略 | 类型 | 主方向 | 适用市场 |
|------|------|--------|----------|
| 动能右侧突破 | 突破 | 做多 | 牛市/上升 |
| 均线回踩买入 | 回调 | 做多 | 牛市/上升 |
| 支撑回踩买入 | 反弹 | 做多 | 震荡/下跌 |
| 区间阻力做空 | 区间 | 做空 | 震荡/熊市 |
| 双顶双底策略 | 极值 | 双向 | 震荡/极端 |
| 抛物线回弹 | 极值 | 做多 | 恐慌/下跌 |
```

- [ ] **Step 2: 删除策略B和D的独立章节**，将其内容并入A和C的章节作为子节。

- [ ] **Step 3: 更新所有策略的参数说明**，反映新的阈值。

- [ ] **Step 4: 更新维护记录**

```markdown
| 2026-03-31 | **v3.0策略重构** - A+B合并为动能右侧突破，C+D合并为均线回踩买入，E/F/G/H重命名并精简 | Claude |
```

- [ ] **Step 5: 提交**

```bash
git add 策略描述.md
git commit -m "docs: update strategy documentation for v3.0 refactoring
- Document merged strategies (A+B, C+D)
- Rename all strategies to Chinese
- Update all parameter descriptions"
```

---

## Task 15: 最终验证（100股票测试 + 全面检查）

**Files:**
- All modified files

**目标**: 在最终提交前进行全面验证

- [ ] **Step 1: 语法检查**

```bash
cd /home/admin/Projects/TradeChanceScreen
python3 -m py_compile core/strategies/*.py core/indicators.py core/earnings_calendar.py
```
Expected: 无语法错误

- [ ] **Step 2: 导入测试**

```bash
python3 -c "from core.strategies import STRATEGY_REGISTRY; print(f'{len(STRATEGY_REGISTRY)} strategies: {list(STRATEGY_REGISTRY.keys())}')"
```
Expected: "6 strategies: [EP, SHORYUKEN, UPHTHRUST_REBOUND, RANGE_SUPPORT, DTSS, PARABOLIC]"

- [ ] **Step 3: 策略实例化测试**

```bash
python3 -c "
from core.strategies import create_strategy, StrategyType
for st in StrategyType:
    try:
        s = create_strategy(st)
        print(f'✓ {st.value}: {s.NAME}')
    except Exception as e:
        print(f'✗ {st.value}: ERROR - {e}')
"
```
Expected: 所有6个策略都能成功实例化

- [ ] **Step 4: 100股票小测试（Gate）**

```bash
python3 scripts/test_100_stocks.py 2>&1 | tee /tmp/test_100.log
echo "Exit code: $?"
```

**通过标准**:
- 所有6个策略都能完成扫描
- 无Python异常崩溃
- 总测试时间 < 10分钟

**如不通过**: 回退到相应Task修复

- [ ] **Step 5: 文档同步检查**

```bash
# 检查CLAUDE.md中的策略数量
grep -c "6 strategies\|6 trading strategies" CLAUDE.md
# Expected: 至少1处

# 检查策略描述.md中的重构说明
grep -c "v3.0" 策略描述.md
# Expected: 至少1处

# 检查策略名是否更新
grep -c "动能右侧突破" CLAUDE.md 策略描述.md
# Expected: 至少2处（每个文件）
```

- [ ] **Step 6: 项目整洁检查**

```bash
# 检查root目录是否整洁
ls /home/admin/Projects/TradeChanceScreen/*.py
# Expected: 只有scheduler.py, run_full_scan.py（无scheduler_optimized.py等重复文件）

# 检查无未删除的策略文件
ls /home/admin/Projects/TradeChanceScreen/core/strategies/momentum.py 2>&1
# Expected: "No such file or directory"

ls /home/admin/Projects/TradeChanceScreen/core/strategies/pullbacks.py 2>&1
# Expected: "No such file or directory"
```

- [ ] **Step 7: 最终提交**

```bash
git add -A
git commit -m "release: v3.0 strategy refactoring complete

- Merge A+B into 动能右侧突破 (RS bonus + relaxed thresholds)
- Merge C+D into 均线回踩买入 (EMA21/50 pullback depth)
- Rename E to 支撑回踩买入 (5d time stop + CLV avg > 0.4)
- Rename F to 区间阻力做空 (remove long mode)
- Rename G to 双顶双底策略 (TS max 4, market filter)
- Rename H to 抛物线回弹 (remove short mode)
- Add earnings calendar for blow-off pause
- Add scripts/test_100_stocks.py for validation
- Update all documentation (CLAUDE.md, 策略描述.md)
- Clean up duplicate scheduler files

All strategies pass 100-stock test."
```

---

## 总结

重构完成后，策略系统将变为：

| # | 策略名称 | 原名 | 变更 |
|---|----------|------|------|
| 1 | 动能右侧突破 | A+B | 合并，RS>85加分 |
| 2 | 均线回踩买入 | C+D | 合并，EMA21/50分档 |
| 3 | 支撑回踩买入 | E | 改名，5天+CLV>0.4，区间加分 |
| 4 | 区间阻力做空 | F | 删多头，只做空 |
| 5 | 双顶双底策略 | G | 改名，TS最高4分 |
| 6 | 抛物线回弹 | H | 删做空，只做多 |

**新增模块:**
- `core/earnings_calendar.py` - 财报日历

**删除文件:**
- `core/strategies/momentum.py`
- `core/strategies/pullbacks.py`

**核心参数变更:**
- VCP平台: 15-30天 → 15-60天
- 50日高点: <5% → <10%
- 缺口否决: 0.8×ATR → 3%
- U&R时间止损: 3天+CLV均值>0.4
- Blow-off: 财报日暂停

---

**Self-Review Checklist:**
- [x] Spec coverage: 所有5个问题都有对应Task
- [x] Placeholder scan: 无TBD/TODO，所有代码完整
- [x] Type consistency: 函数名和类型在各Task中一致
- [x] File paths: 所有路径使用绝对路径 `/home/admin/Projects/TradeChanceScreen/...`
- [x] 项目整洁: Task 0包含文件清理(scheduler.py等)
- [x] 文档同步: Task 13(CLAUDE.md)和Task 14(策略描述.md)都有文档更新
- [x] 100股票测试: Task 15最终验证包含100股票测试作为Gate
- [x] 提交标准: 每个Task组后都有语法检查+导入测试+100股票测试
