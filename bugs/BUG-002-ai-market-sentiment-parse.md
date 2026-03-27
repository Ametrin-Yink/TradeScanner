---
bug_id: BUG-002
title: "AI市场情绪分析返回格式异常，sentiment显示为空"
severity: P2
status: 🆕 New
created_date: 2026-03-27
resolved_date:
assignee:
---

# BUG-002: AI市场情绪分析返回格式异常，sentiment显示为空

## 问题描述
在市场情绪分析阶段（Step 1/5），AI分析完成但输出的市场情绪值为空。日志显示：
```
2026-03-27 23:04:10,802 - core.market_analyzer - INFO - AI sentiment analysis: ,  (confidence: None)
2026-03-27 23:04:10,804 - __main__ - INFO - Market sentiment: ,
```

虽然AI调用成功，但解析出的sentiment和confidence值异常，导致后续策略权重使用默认值。

## 复现步骤
1. 运行完整扫描：python scheduler.py
2. 观察第一步"Analyzing market sentiment"
3. 查看日志输出，发现sentiment显示为", "
4. 检查生成的报告，市场情绪显示为"WATCH"（默认值）

## 期望结果
市场情绪应该显示为：bullish / bearish / neutral / watch 之一
```
Market sentiment: bullish (confidence: 75)
```

## 实际结果
```
Market sentiment: ,
```

## 环境信息
- 版本/分支：master
- Python版本：3.10
- 操作系统：Ubuntu 22.04
- API：DashScope kimi-k2.5
- 相关文件：core/market_analyzer.py

## 错误日志
```
2026-03-27 23:04:08,552 - core.market_analyzer - INFO - Tavily search returned 3 results for: US stock market today sentiment analysis
2026-03-27 23:04:08,607 - core.market_analyzer - INFO - Tavily search returned 3 results for: S&P 500 market outlook news
2026-03-27 23:04:08,663 - core.market_analyzer - INFO - Tavily search returned 3 results for: Federal Reserve interest rates impact stocks
2026-03-27 23:04:10,802 - core.market_analyzer - INFO - AI sentiment analysis: ,  (confidence: None)
2026-03-27 23:04:10,804 - __main__ - INFO - Market sentiment: ,
```

## 初步分析
可能原因：
1. AI返回的JSON字段名与预期不符
2. JSON解析成功但字段映射错误
3. Tavily搜索结果为空或格式异常

需要进一步调试查看AI返回的原始内容。

## 临时解决方案
当前系统会使用默认的'neutral'情绪继续运行，不影响整体流程。

---

## 解决记录（修复后填写）

### 根本原因
[待调查]

### 解决方案
[待填写]

### 学到的知识
[待填写]

### 相关Commit
-

### 验证结果
- [ ] 按复现步骤测试通过
- [ ] 回归测试通过
- [ ] 代码审查通过

### 预防措施

### 影响范围
- core/market_analyzer.py - 待修复

### 解决时间
- 发现时间：2026-03-27 23:04
- 解决时间：
- 耗时：
