---
bug_id: BUG-003
title: "Plotly图表404错误及布局问题"
severity: P1
status: In Progress
created_date: 2026-03-28
resolved_date:
assignee:
---

# BUG-003: Plotly图表404错误及布局问题

## 问题描述
报告页面中图表区域显示"Not Found"错误，iframe请求的URL无法找到对应文件。同时图表尺寸过大(620px高)，与Analysis板块不协调。

## 复现步骤
1. 运行完整扫描：python scheduler.py --force
2. 等待报告生成完成
3. 在浏览器打开报告页面（如 http://47.90.229.136:19801/reports/report_2026-03-28.html）
4. 查看Top 10 Opportunities中的图表区域
5. 观察到404错误："The requested URL was not found on the server"

## 期望结果
- 图表正常显示（静态图片即可，交互性不重要）
- 图表与Analysis板块并排显示，高度相近
- 图表大小适中，不占用过多空间

## 实际结果
- 图表区域显示404错误
- iframe高度620px过大

## 环境信息
- 版本/分支：master
- Python版本：3.10
- 操作系统：Ubuntu 22.04
- 服务器：Flask on port 19801
- 相关文件：
  - core/plotly_charts.py
  - core/reporter.py
  - api/server.py

## 错误日志
浏览器显示：
```
Not Found
The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.
```

## 初步分析

### 根本原因1：路径生成不一致
`plotly_charts.py`第151行返回：`data/charts/AAPL_20260328.html`
但iframe使用的是相对路径，服务器路由期望的是文件名。

### 根本原因2：端口问题
服务器运行在19801端口，但iframe的相对路径可能未正确处理端口。

### 根本原因3：图表类型
当前使用交互式HTML图表，但用户更偏好静态图片，且要求与Analysis并排布局。

## 解决方案

### 方案1：改用静态PNG图片（推荐）
- 使用 `generate_static_plotly_chart()` 生成PNG
- PNG图片更轻量，无404风险
- 易于控制尺寸，适合并排布局

### 方案2：修复HTML图表路径
- 修改路径生成逻辑
- 确保iframe src包含正确的主机和端口

## 临时解决方案
无，需要修复代码。

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
- core/plotly_charts.py
- core/reporter.py

### 解决时间
- 发现时间：2026-03-28
- 解决时间：
- 耗时：
