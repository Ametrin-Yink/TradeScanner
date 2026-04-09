# Trade Scanner Bug 库

本项目Bug库用于系统化跟踪、管理和解决Trade Scanner项目中的所有bug。

## 文件结构

```
bugs/
├── README.md              # 本文件：Bug库使用规范
├── bug-inventory.md       # Bug目录：所有bug的索引和状态
└── BUG-XXX-*.md          # 单个Bug详细报告（位于bugs/目录下）
```

## Bug严重程度分级

| 级别 | 标识        | 说明                             | 响应时间 |
| ---- | ----------- | -------------------------------- | -------- |
| P0   | 🔴 Critical | 系统崩溃、数据丢失、安全漏洞     | 立即     |
| P1   | 🟠 High     | 核心功能不可用、严重影响用户体验 | 24小时内 |
| P2   | 🟡 Medium   | 功能异常、有临时解决方案         | 3天内    |
| P3   | 🟢 Low      | 轻微问题、优化建议               | 1周内    |

## Bug状态流转

```
🆕 New → 🔧 In Progress → 🧪 Testing → ✅ Resolved → 📚 Documented
            ↓
         ❌ Won't Fix / ⏸️ On Hold
```

## Bug处理流程

### 1. 发现Bug

当发现bug时，立即按照以下步骤操作：

```bash
# 1. 创建Bug报告文件
# 使用递增编号：BUG-001, BUG-002, ...
```

### 2. 记录Bug

复制 `bug-template.md` 模板，填写：

- Bug标题和编号
- 严重程度
- 复现步骤
- 期望结果 vs 实际结果
- 环境信息
- 截图/日志

### 3. 更新目录

在 `bug-inventory.md` 中添加该bug的索引条目

### 4. 调用Superpowers解决

使用 `/superpowers` 调用相关技能进行debug：

```
/superpowers:debugging-agent
/superpowers:code-reviewer
```

### 5. 开发修复

- 创建feature分支（如 `fix/BUG-001-ai-json-parse`）
- 实施修复
- 本地测试

### 6. 测试验证

- 按照复现步骤验证bug已修复
- 检查是否引入新的问题（回归测试）
- 更新bug报告中的"验证结果"

### 7. 提交代码

```bash
git add .
git commit -m "fix: BUG-001 修复AI JSON解析错误

- 移除了不兼容的response_format参数
- 添加了JSON提取正则表达式
- 添加了类型检查防止异常

Closes BUG-001"
```

### 8. 更新Bug记录

在以下文件更新bug状态：

- `bug-inventory.md`: 更新状态为"✅ Resolved"，添加解决日期
- `bugs/BUG-XXX.md`: 补充：
  - 根本原因
  - 解决方案
  - 学到的知识
  - 相关commit

### 9. 关闭Bug

在bug-inventory.md中标记为已关闭，移动到新位置

## Bug报告模板

新建bug时复制以下内容：

```markdown
---
bug_id: BUG-001
title: "简要描述"
severity: P1/P2/P3
status: New/In Progress/Testing/Resolved
created_date: 2026-03-27
resolved_date:
assignee:
---

# BUG-XXX: [标题]

## 问题描述

[详细描述bug表现]

## 复现步骤

1. [步骤1]
2. [步骤2]
3. [步骤3]

## 期望结果

[应该发生什么]

## 实际结果

[实际发生什么]

## 环境信息

- 版本/分支：
- Python版本：
- 操作系统：
- 相关配置：

## 错误日志
```

[粘贴相关日志]

```

## 截图
[如有]

## 初步分析
[可选：对原因的猜测]

---

## 解决记录（修复后填写）

### 根本原因
[技术层面的根本原因]

### 解决方案
[具体的代码/配置修改]

### 学到的知识
[经验教训，避免再次犯错]

### 相关Commit
- `abc1234`: [commit message]

### 验证结果
- [x] 按复现步骤测试通过
- [x] 回归测试通过
- [x] 代码审查通过
```

## 当前Bug统计

查看 `bug-inventory.md` 获取最新统计

## 最佳实践

1. **及时记录**：发现bug立即记录，不要依赖记忆
2. **详细复现**：提供精确的复现步骤，确保他人能重现
3. **单一职责**：每个bug报告只描述一个问题
4. **关联代码**：在bug报告中引用相关代码文件和行号
5. **知识沉淀**：解决后一定要补充"学到的知识"

## 联系

如有bug库相关问题，请联系项目维护者。
