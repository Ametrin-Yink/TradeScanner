---
bug_id: BUG-001
title: "kimi-k2.5不兼容response_format参数导致JSON解析失败"
severity: P2
status: ✅ Resolved
created_date: 2026-03-27
resolved_date: 2026-03-27
assignee: Claude
---

# BUG-001: kimi-k2.5不兼容response_format参数导致JSON解析失败

## 问题描述
使用DashScope API调用kimi-k2.5模型时，设置了`response_format: {"type": "json_object"}`参数，期望AI返回标准JSON格式。但实际返回的JSON结构混乱，包含嵌套错误和无效字符，导致`json.loads()`解析失败。

错误表现：
```
AI analysis failed for AAPL: Invalid control character at: line 1 column 3 (char 2)
'float' object has no attribute 'get'
'str' object has no attribute 'get'
```

## 复现步骤
1. 启动扫描：python scheduler.py
2. 等待AI分析阶段（Step 4/5）
3. 观察日志显示AI解析错误
4. 查看生成的报告，AI分析字段为空或异常

## 期望结果
AI应该返回标准JSON格式：
```json
{
    "sentiment": "bullish",
    "confidence": 75,
    "reasoning": "分析理由...",
    "key_factors": ["factor1", "factor2"]
}
```

## 实际结果
AI返回格式混乱的JSON：
```json
{"sentiment":{"sentiment":{": ":", "}},"confidence":75}
```

## 环境信息
- 版本/分支：master
- Python版本：3.10
- 操作系统：Ubuntu 22.04
- API：DashScope kimi-k2.5
- 相关文件：core/analyzer.py, core/selector.py, core/market_analyzer.py

## 错误日志
```
2026-03-27 22:48:20,823 - core.analyzer - ERROR - AI analysis failed for AAPL: Invalid control character at: line 1 column 3 (char 2)
2026-03-27 22:48:28,413 - core.analyzer - ERROR - Failed to analyze TSLA: 'str' object has no attribute 'get'
2026-03-27 23:12:49,218 - core.selector - ERROR - AI selection failed: 'float' object has no attribute 'get'
```

## 初步分析
可能是kimi-k2.5模型不支持OpenAI格式的`response_format`参数，导致参数被误解，返回了混乱的JSON结构。

---

## 解决记录

### 根本原因
kimi-k2.5模型（通过DashScope API）不支持`response_format: {"type": "json_object"}`参数。当设置此参数时，模型没有正确解析，导致返回的JSON结构嵌套混乱。

测试验证：
```python
# 有response_format时返回：
{"sentiment":{"sentiment":{": ":", "}},"confidence":75}

# 无response_format时返回：
{"sentiment": "neutral", "confidence": 55, "reasoning": "..."}
```

### 解决方案
1. **移除response_format参数**：在三个AI调用文件中移除该参数
2. **添加JSON提取逻辑**：使用正则表达式从响应中提取JSON部分
3. **添加类型检查**：确保返回结果始终为字典类型

修改文件：
- `core/analyzer.py`：移除response_format，添加JSON提取
- `core/selector.py`：同上
- `core/market_analyzer.py`：同上

关键代码变更：
```python
# 修改前
payload = {
    "model": self.model,
    "messages": [...],
    "temperature": 0.3,
    "response_format": {"type": "json_object"}  # 移除这行
}
result = json.loads(content)

# 修改后
payload = {
    "model": self.model,
    "messages": [...],
    "temperature": 0.3
}
# 添加JSON提取
import re
json_match = re.search(r'\{.*\}', content, re.DOTALL)
if json_match:
    result = json.loads(json_match.group())
else:
    result = json.loads(content)
```

### 学到的知识

1. **API兼容性陷阱**：不是所有声称兼容OpenAI API的模型都完全支持所有参数。`response_format`是较新的参数，部分模型可能不支持。

2. **防御性编程**：
   - 永远不要假设API返回的数据类型
   - 添加类型检查：`if not isinstance(result, dict)`
   - 使用try-except包装解析逻辑

3. **测试验证**：在修改前先用简单脚本验证假设：
   ```python
   # 快速测试API行为
   response = requests.post(url, headers=headers, json=payload)
   print('Raw content:', repr(response.json()['choices'][0]['message']['content']))
   ```

4. **正则提取JSON**：当API返回可能包含markdown代码块或额外文本时，使用正则提取JSON部分：
   ```python
   import re
   json_match = re.search(r'\{.*\}', content, re.DOTALL)
   ```

5. **模型特定行为**：kimi-k2.5在移除response_format后，能够很好地遵循系统指令返回纯JSON格式。

### 相关Commit
- `b859c1a`: docs: update CLAUDE.md with deployment learnings
- （后续commit包含在完整扫描测试中）

### 验证结果
- [x] 按复现步骤测试通过 - 重新运行完整扫描，AI分析正常
- [x] 回归测试通过 - 518只股票扫描，10个AI分析全部成功
- [x] 代码审查通过 - 三个文件修改一致，添加防御性检查

验证命令：
```bash
venv/bin/python scheduler.py
# 输出显示：AI analysis complete for XXX，无ERROR
```

报告生成验证：
- 访问 http://47.90.229.136:19801/reports/report_2026-03-27.html
- AI分析字段正常显示：Reasoning、Catalyst、Risk Factors等

### 预防措施
1. 在CLAUDE.md中记录此兼容性问题
2. 未来添加新AI模型时，先测试response_format支持
3. 所有AI调用都使用统一的JSON提取逻辑

### 影响范围
- ✅ core/analyzer.py - 已修复
- ✅ core/selector.py - 已修复
- ✅ core/market_analyzer.py - 已修复

### 解决时间
- 发现时间：2026-03-27 22:48
- 解决时间：2026-03-27 23:14
- 耗时：约26分钟
