# BUG-005: 多个策略插件缺少必需抽象方法

## 基本信息

| 字段         | 值               |
| ------------ | ---------------- |
| **ID**       | BUG-005          |
| **严重程度** | P1 (High)        |
| **状态**     | ✅ 已解决        |
| **创建日期** | 2026-03-30       |
| **解决日期** | 2026-03-30       |
| **模块**     | core/strategies/ |
| **发现者**   | Phase 0 测试循环 |

---

## 问题描述

在 Phase 0 测试循环中，发现多个策略插件类无法实例化，因为缺少 `BaseStrategy` 抽象类要求的必需方法。

### 错误信息

```
TypeError: Can't instantiate abstract class UpthrustReboundStrategy
without an implementation for abstract methods
'build_match_reasons', 'calculate_dimensions', 'calculate_entry_exit'
```

---

## 影响范围

| 策略文件              | 状态    | 缺少方法           |
| --------------------- | ------- | ------------------ |
| `upthrust_rebound.py` | ❌ 损坏 | 3个方法            |
| `range_support.py`    | ❌ 损坏 | 4个方法 (含filter) |
| `dtss.py`             | ❌ 损坏 | 4个方法 (含filter) |
| `parabolic.py`        | ❌ 损坏 | 4个方法 (含filter) |

**影响**：

- `StrategyScreener` 无法初始化
- 整个 Step 2 (策略筛选) 无法运行
- Phase 0 测试无法完成

---

## 根本原因

1. **插件架构迁移不完整**：在将策略从 `core/screener.py` 迁移到 `core/strategies/` 目录时，部分策略未完成全部抽象方法的实现
2. **缺少完整性检查**：没有自动化的测试来验证所有策略插件都实现了必需方法
3. **代码审查遗漏**：重构时未检查所有策略文件的完整性

---

## 解决方案

### 1. 修复 `core/screener.py`

**问题**：重复的 `__init__` 方法 (第53-77行和第189-208行)

**修复**：删除第189-208行的重复 `__init__`

```python
# 删除第二个 __init__ 方法
```

### 2. 修复 `UpthrustReboundStrategy`

**添加方法**：

- `filter(symbol, df) -> bool` - 带成交量否决检查的过滤
- `calculate_dimensions(symbol, df) -> List[ScoringDimension]` - 3维度评分 (SQ, VD, RB)
- `calculate_entry_exit(...)` - 计算入场/止损/目标价
- `build_match_reasons(...)` - 构建可读匹配原因

**评分维度**：

- **SQ (Structure Quality)**: 0-5分，基于支撑位距离和质量
- **VD (Volume Dry-up)**: 0-5分，成交量萎缩程度
- **RB (Rebound Bias)**: 0-5分，反弹偏向性

### 3. 修复 `RangeSupportStrategy`

**添加方法**：

- `filter(symbol, df) -> bool` - 双向过滤（多/空）
- `calculate_dimensions(symbol, df)` - 3维度评分 (PL, TS, VC)
- `calculate_entry_exit(...)` - 基于S/R的入场/止损/目标
- `build_match_reasons(...)`

**评分维度**：

- **PL (Platform Quality)**: 0-5分，平台质量
- **TS (Test Strength)**: 0-5分，测试强度（支撑测试次数）
- **VC (Volume Character)**: 0-5分，成交量特征

### 4. 修复 `DTSSStrategy`

**添加方法**：

- `filter(symbol, df) -> bool` - 基于市场方向的多/空过滤
- `calculate_dimensions(symbol, df)` - 3维度评分 (PL, TS, VC)
- `calculate_entry_exit(...)` - 基于60日高/低的入场/止损/目标
- `build_match_reasons(...)`

**评分维度**：

- **PL (Price Level)**: 0-5分，价格水平（接近60日高/低）
- **TS (Trend Structure)**: 0-5分，趋势结构（EMA排列）
- **VC (Volume Confirmation)**: 0-5分，成交量确认

### 5. 修复 `ParabolicStrategy`

**添加方法**：

- `filter(symbol, df) -> bool` - 基于VIX和极端条件的过滤
- `calculate_dimensions(symbol, df)` - 3维度评分 (MO, EX, VC)
- `calculate_entry_exit(...)` - 基于近期高/低的入场/止损/目标
- `build_match_reasons(...)`

**评分维度**：

- **MO (Momentum Extreme)**: 0-5分，动量极端（RSI）
- **EX (Extension)**: 0-5分，偏离程度（价格vs EMA50）
- **VC (Volume Climax)**: 0-5分，成交量高潮

---

## 验证

### 测试脚本

```bash
python3 test_phase0.py
```

### 测试结果

```
Phase 0 Test Summary: 10 passed, 0 failed
Total symbols processed: 10

✓ AAPL: All fields valid
✓ ABBV: All fields valid
✓ ABT: All fields valid
✓ ACN: All fields valid
✓ ADBE: All fields valid
✓ ADI: All fields valid
✓ AMD: All fields valid
✓ AMGN: All fields valid
✓ AMZN: All fields valid
✓ ASML: All fields valid
```

### 验证点

- [x] `StrategyScreener` 成功初始化
- [x] 所有 8 个策略插件成功实例化
- [x] Phase 0 预计算生成所有必需字段
- [x] 10 只测试股票全部通过验证

---

## 预防措施

1. **自动化测试**：添加 `test_all_strategies.py` 验证所有策略可实例化
2. **代码模板**：创建策略开发模板，包含所有必需方法
3. **CI检查**：在提交前运行策略完整性检查

---

## 相关文件

| 文件                                  | 变更                  |
| ------------------------------------- | --------------------- |
| `core/screener.py`                    | 删除重复 `__init__`   |
| `core/strategies/upthrust_rebound.py` | 添加 4 个方法         |
| `core/strategies/range_support.py`    | 添加 4 个方法         |
| `core/strategies/dtss.py`             | 添加 4 个方法         |
| `core/strategies/parabolic.py`        | 添加 4 个方法         |
| `test_phase0.py`                      | 新增 Phase 0 测试脚本 |

---

## 经验教训

1. **重构后必须立即测试**：插件架构迁移后应立即运行完整性测试
2. **抽象类强制约束**：Python 的 ABC 抽象类会在实例化时检查方法实现，是很好的安全网
3. **增量验证**：大型重构应分阶段验证，而不是等到最后
