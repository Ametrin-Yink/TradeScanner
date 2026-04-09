# BUG-004: 扫描在策略筛选阶段卡住/超时

## 状态

- **Status**: `RESOLVED`
- **Severity**: HIGH
- **Component**: `core/screener.py`, `core/strategies/base_strategy.py`, `core/strategies/shoryuken.py`
- **Opened**: 2026-03-29
- **Closed**: 2026-03-29

## 根本原因

1. **缺少进度日志**：策略执行没有进度汇报，无法判断是否卡住
2. **代码 Bug**：Shoryuken 策略在遍历字典时删除元素，导致 `dictionary changed size during iteration` 错误

## 解决方案

### 1. 添加详细进度日志 (core/screener.py)

```
======================================================================
STRATEGY SCREENING PHASE
======================================================================
Total symbols to screen: 2002
Number of strategies: 8
----------------------------------------------------------------------

>>> [1/8] Running EP strategy...
    Started at: 11:40:33
    [EP] Starting screening of 2002 symbols...
    [EP] Progress: 500/2002 (25%) - 2 matches - 15s elapsed
    [EP] Progress: 1000/2002 (50%) - 4 matches - 32s elapsed
    [EP] Completed: 5 matches from 2002 symbols (65.3s)
    ✓ EP: 5 candidates
    Completed at: 11:41:38 (took 65.3s)
```

### 2. 修复 Shoryuken Bug (core/strategies/shoryuken.py)

原代码：

```python
for symbol, data in symbol_data.items():
    ...
    del symbol_data[symbol]  # ❌ 遍历时删除
```

修复后：

```python
symbols_to_remove = []
for symbol, data in symbol_data.items():
    ...
    symbols_to_remove.append(symbol)

for symbol in symbols_to_remove:
    symbol_data.pop(symbol, None)  # ✅ 遍历后删除
```

### 3. 添加策略内部进度 (core/strategies/base_strategy.py)

每处理 500 只股票汇报一次进度，显示匹配数和耗时。

## 验证

✅ 测试通过，进度日志正常显示
✅ 语法检查通过
✅ Shoryuken 策略不再报错
