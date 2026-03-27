# Bug 目录 (Bug Inventory)

> 最后更新：2026-03-27

## 统计摘要

| 状态 | 数量 |
|------|------|
| 🔴 Critical (P0) | 0 |
| 🟠 High (P1) | 0 |
| 🟡 Medium (P2) | 2 |
| 🟢 Low (P3) | 0 |
| **总计** | **2** |

---

## 活跃Bug (Active Bugs)

### 🟡 Medium Priority

| ID | 标题 | 状态 | 创建日期 | 解决日期 | 备注 |
|----|------|------|----------|----------|------|
| [BUG-002](./BUG-002-ai-market-sentiment-parse.md) | AI市场情绪分析返回格式异常 | 🆕 New | 2026-03-27 | - | 需要修复AI返回解析 |
| [BUG-001](./BUG-001-ai-json-parse.md) | kimi-k2.5不兼容response_format参数导致JSON解析失败 | ✅ Resolved | 2026-03-27 | 2026-03-27 | 已修复，见commit |

---

## 已解决Bug (Resolved Bugs)

| ID | 标题 | 严重程度 | 解决日期 | 解决方案概要 |
|----|------|----------|----------|--------------|
| BUG-001 | kimi-k2.5不兼容response_format参数导致JSON解析失败 | P2 | 2026-03-27 | 移除response_format，使用正则提取JSON |

---

## Bug趋势

### 本月新增
- 2个 (2026-03)

### 本月解决
- 1个 (2026-03-27)

### 平均解决时间
- P2: 2小时

---

## 分类标签

### 按模块
- `core/analyzer`: 1
- `core/selector`: 1
- `core/market_analyzer`: 1

### 按类型
- API兼容性: 1
- JSON解析: 2

### 按根本原因
- 第三方API行为差异: 1
