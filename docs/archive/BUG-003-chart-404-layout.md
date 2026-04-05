---
bug_id: BUG-003
title: "Plotly图表404错误及布局问题"
severity: P1
status: ✅ Resolved
created_date: 2026-03-28
resolved_date: 2026-03-28
assignee: Claude
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

## 根本原因
1. **iframe路径问题**: HTML交互式图表使用iframe嵌入，但路径生成和端口处理有问题
2. **端口不匹配**: 服务器在19801端口运行，但iframe相对路径未正确处理
3. **图表过大**: 600x900像素的图表不适合与文字并排显示

## 解决方案
改用静态PNG图片，使用`<img>`标签直接嵌入，避免iframe跨域和路径问题。

---

## 解决记录

### 根本原因
1. `generate_plotly_chart()`返回的相对路径与iframe src不匹配
2. iframe方式需要额外的服务器路由配置，且容易出错
3. 用户明确表示"交互性不重要"，静态图片更符合需求

### 解决方案
1. **改用静态PNG**: 使用`generate_static_plotly_chart()`替代`generate_plotly_chart()`
2. **使用img标签**: 将`<iframe>`替换为`<img src="...">`
3. **并排布局**: 使用flex布局将图表和Analysis并排放置
4. **缩小尺寸**: 图表尺寸从600x900改为350x500
5. **响应式设计**: 添加@media查询，小屏幕时自动堆叠

### 代码修改

**core/reporter.py:**
- 导入改为`generate_static_plotly_chart`
- `_generate_kline_chart()`简化，直接返回PNG路径
- HTML结构改为`<div class="analysis-row">`包含ai-analysis和chart
- CSS添加`.analysis-row`, `.chart-image`, 响应式规则

**core/plotly_charts.py:**
- `generate_static_plotly_chart()`尺寸改为height=350, width=500
- 边距调整为l=40, r=40, t=40, b=40

### 学到的知识
1. iframe嵌入容易遇到路径/端口问题，静态资源更简单可靠
2. 用户明确说"不重要"的功能，优先选择简单方案
3. flex布局是实现并排显示的最佳方式
4. 响应式设计要考虑移动端体验

### 相关Commit
- 508ec8e fix: BUG-003 修复图表404错误并优化布局

### 验证结果
- [x] 图表正常显示为PNG图片
- [x] 图表与Analysis并排显示
- [x] 图表大小适中（350x500）
- [x] 无404错误
- [x] 响应式布局工作正常

### 影响范围
- core/plotly_charts.py - 静态图表尺寸调整
- core/reporter.py - 布局和渲染逻辑重写

### 解决时间
- 发现时间：2026-03-28
- 解决时间：2026-03-28
- 耗时：15分钟
