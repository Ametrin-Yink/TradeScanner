# Trade Scanner Complete Workflow Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the complete Trade Scanner pipeline from data fetch to report generation, with checkpoints at each step to verify success before proceeding.

**Architecture:** Sequential 5-step pipeline: 1) Market sentiment analysis, 2) Symbol screening with 6 strategy plugins (streaming batches), 3) AI scoring and selection, 4) Deep AI analysis per opportunity, 5) Report generation. Web server verification at end.

**Tech Stack:** Python 3.12, yfinance, DashScope AI, SQLite, Flask, matplotlib

---

## Pre-Flight Checks

### Task 0: Environment Verification

**Files:**
- Read: `config/settings.py`
- Read: `config/secrets.json`
- Read: `requirements.txt`
- Verify: Database exists at `data/market_data.db`

- [ ] **Step 1: Check Python environment**

```bash
cd /home/admin/Projects/TradeChanceScreen
source venv/bin/activate
python --version
```
Expected: `Python 3.12.x`

- [ ] **Step 2: Verify API keys configured**

```bash
python -c "from config.settings import settings; print('API Key present:', bool(settings.get_dashscope_api_key()))"
```
Expected: `API Key present: True`

- [ ] **Step 3: Check database connectivity**

```bash
python -c "from data.db import Database; db = Database(); print('Stocks count:', len(db.get_active_stocks()))"
```
Expected: Number of stocks in database (e.g., `518`)

- [ ] **Step 4: Verify web server status**

```bash
ss -tlnp | grep 19801 || echo "Server not running"
```
Note: Server may or may not be running - we'll start it if needed.

---

## Phase 1: BUG-002 Fix (Market Sentiment Parsing)

### Task 1: Fix AI Market Sentiment Parse Bug

**Files:**
- Read: `core/market_analyzer.py`
- Modify: `core/market_analyzer.py`
- Test: Run sentiment analysis

**Context:** BUG-002 shows AI returns empty sentiment value causing `Market sentiment: ,` in logs. The sentiment parsing logic needs investigation.

- [ ] **Step 1: Read market_analyzer.py to understand sentiment parsing**

Read the file and identify where sentiment is parsed from AI response.

- [ ] **Step 2: Identify the parse issue**

Look for:
1. How AI response is parsed
2. Expected JSON fields (sentiment, confidence, etc.)
3. Default/fallback values when parsing fails
4. The regex JSON extraction pattern

- [ ] **Step 3: Fix the sentiment parsing logic**

Common issues to check:
- Field name mismatch (e.g., AI returns `market_sentiment` but code looks for `sentiment`)
- Missing default values when keys are absent
- Case sensitivity issues
- Wrong variable being returned

Example fix pattern:
```python
# Before (buggy):
sentiment = result.get('sentiment', 'neutral')

# After (fixed):
sentiment = result.get('sentiment') or result.get('market_sentiment', 'neutral')
```

- [ ] **Step 4: Test the fix**

```bash
python -c "
from core.market_analyzer import MarketAnalyzer
ma = MarketAnalyzer()
result = ma.analyze_sentiment()
print('Sentiment:', result.get('sentiment'))
print('Confidence:', result.get('confidence'))
print('Full result:', result)
"
```
Expected: sentiment should be one of `bullish`, `bearish`, `neutral`, `watch` with numeric confidence

- [ ] **Step 5: Commit the fix**

```bash
git add core/market_analyzer.py
git commit -m "fix(BUG-002): Fix AI market sentiment parsing

- Fixed field name mismatch in sentiment extraction
- Added proper default values for missing fields
- Verified sentiment now returns valid values (bullish/bearish/neutral/watch)

Fixes BUG-002"
```

---

## Phase 2: Workflow Execution

### Checkpoint Format
Each phase ends with a checkpoint. Mark as:
- ✅ **SUCCESS** - Step completed, output verified
- ❌ **FAILED** - Step failed, fix required before proceeding
- ⚠️ **PARTIAL** - Step completed with warnings

---

### Task 2: Step 1/5 - Market Sentiment Analysis

**Files:**
- Run: `scheduler.py` (specifically market_analyzer)
- Verify: Log output shows valid sentiment

- [ ] **Step 1: Run market sentiment analysis**

```bash
cd /home/admin/Projects/TradeChanceScreen
source venv/bin/activate
python -c "
import logging
logging.basicConfig(level=logging.INFO)
from core.market_analyzer import MarketAnalyzer
ma = MarketAnalyzer()
result = ma.analyze_sentiment()
print('=== CHECKPOINT: Step 1/5 ===')
print(f'Sentiment: {result.get(\"sentiment\", \"ERROR\")}')
print(f'Confidence: {result.get(\"confidence\", \"ERROR\")}')
print(f'Success: {result.get(\"sentiment\") in [\"bullish\", \"bearish\", \"neutral\", \"watch\"]}')
"
```

**Checkpoint 1 Result:**
```
=== CHECKPOINT: Step 1/5 ===
Sentiment: [bullish/bearish/neutral/watch]
Confidence: [number]
Success: True
```

- [ ] **Mark Checkpoint 1:**
  - [ ] ✅ SUCCESS - Sentiment parsed correctly
  - [ ] ❌ FAILED - Still showing empty values

---

### Task 3: Step 2/5 - Symbol Screening with 6 Strategies

**Files:**
- Run: `scheduler.py --test --symbols AAPL,MSFT,NVDA`
- Verify: Screening completes, candidates found

- [ ] **Step 1: Run test scan with limited symbols**

```bash
cd /home/admin/Projects/TradeChanceScreen
source venv/bin/activate
python scheduler.py --test --symbols AAPL,MSFT,NVDA 2>&1 | tee /tmp/scan_step2.log
```

- [ ] **Step 2: Verify screening output**

```bash
grep -E "(Step 2/5|Found.*candidates|screening.*success)" /tmp/scan_step2.log
```
Expected output patterns:
- `Step 2/5: Screening symbols with 6 strategies`
- `Found N total candidates`
- No ERROR-level log messages about screening failures

- [ ] **Step 3: Check strategy plugin execution**

```bash
grep -E "MomentumBreakout|PullbackEntry|SupportBounce|RangeShort|DoubleTopBottom|CapitulationRebound" /tmp/scan_step2.log | head -20
```
Expected: Evidence that strategy plugins are being called

**Checkpoint 2 Result:**
```
=== CHECKPOINT: Step 2/5 ===
Screened: [N] symbols
Candidates found: [N]
Strategies active: 6
Success: True/False
```

- [ ] **Mark Checkpoint 2:**
  - [ ] ✅ SUCCESS - Screening completed with candidates
  - [ ] ❌ FAILED - Screening errors or no candidates
  - [ ] ⚠️ PARTIAL - Some strategies failed but scan continued

---

### Task 4: Step 3/5 - AI Scoring and Selection

**Files:**
- Verify: `core/selector.py` AI calls work
- Check: Log output for AI scoring

- [ ] **Step 1: Verify AI scoring in logs**

```bash
grep -E "(Step 3/5|AI scoring|select.*top|confidence)" /tmp/scan_step2.log
```
Expected:
- `Step 3/5: AI scoring and selecting top 10...`
- `Selected N opportunities`
- Confidence values shown

- [ ] **Step 2: Check for AI parsing errors**

```bash
grep -E "ERROR.*AI|Failed.*analyze|JSON" /tmp/scan_step2.log
```
Expected: No ERROR lines related to AI analysis

**Checkpoint 3 Result:**
```
=== CHECKPOINT: Step 3/5 ===
Opportunities selected: [N]
Confidence range: [min]-[max]%
AI errors: 0
Success: True/False
```

- [ ] **Mark Checkpoint 3:**
  - [ ] ✅ SUCCESS - AI scoring completed
  - [ ] ❌ FAILED - AI errors or no selections

---

### Task 5: Step 4/5 - Deep AI Analysis

**Files:**
- Verify: `core/analyzer.py` deep analysis
- Check: Per-opportunity analysis in logs

- [ ] **Step 1: Verify deep analysis in logs**

```bash
grep -E "(Step 4/5|Analyzing [A-Z]+|deep AI analysis)" /tmp/scan_step2.log
```
Expected:
- `Step 4/5: Running deep AI analysis...`
- `Analyzing SYMBOL (N/M)...` for each opportunity
- `Analyzed N opportunities`

- [ ] **Step 2: Check for analysis failures**

```bash
grep -E "Failed to analyze|ERROR.*analyze" /tmp/scan_step2.log
```
Expected: No errors (or minimal graceful failures)

**Checkpoint 4 Result:**
```
=== CHECKPOINT: Step 4/5 ===
Opportunities analyzed: [N]
Analysis errors: [N]
Success: True/False
```

- [ ] **Mark Checkpoint 4:**
  - [ ] ✅ SUCCESS - Deep analysis completed
  - [ ] ❌ FAILED - Multiple analysis failures

---

### Task 6: Step 5/5 - Report Generation

**Files:**
- Verify: `core/reporter.py` generates report
- Check: Report file created

- [ ] **Step 1: Verify report generation in logs**

```bash
grep -E "(Step 5/5|Generating report|Report:|report_.*html)" /tmp/scan_step2.log
```
Expected:
- `Step 5/5: Generating report...`
- `Report: /home/admin/Projects/TradeChanceScreen/web/reports/report_YYYY-MM-DD.html`

- [ ] **Step 2: Verify report file exists**

```bash
REPORT_PATH=$(grep -oP 'Report: \K.*' /tmp/scan_step2.log | tail -1)
ls -la "$REPORT_PATH"
```
Expected: File exists with non-zero size

- [ ] **Step 3: Verify report content**

```bash
grep -E "(Market Sentiment|Opportunities|Strategy)" "$REPORT_PATH" | head -5
```
Expected: HTML content with market sentiment and opportunities sections

**Checkpoint 5 Result:**
```
=== CHECKPOINT: Step 5/5 ===
Report file: [path]
Report size: [N] bytes
Content verified: True/False
Success: True/False
```

- [ ] **Mark Checkpoint 5:**
  - [ ] ✅ SUCCESS - Report generated and validated
  - [ ] ❌ FAILED - Report missing or empty

---

### Task 7: Web Server Verification

**Files:**
- Run: `api/server.py`
- Verify: Server serves report at port 19801

- [ ] **Step 1: Start web server (if not running)**

```bash
cd /home/admin/Projects/TradeChanceScreen
source venv/bin/activate

# Check if already running
if ss -tlnp | grep -q 19801; then
    echo "Server already running"
else
    python api/server.py &
    sleep 3
fi
```

- [ ] **Step 2: Verify server responds**

```bash
curl -s http://localhost:19801/ | head -20
```
Expected: HTML response with dashboard content

- [ ] **Step 3: Verify report is accessible**

```bash
REPORT_NAME=$(basename "$REPORT_PATH")
curl -s "http://localhost:19801/reports/$REPORT_NAME" | head -10
```
Expected: HTML content of the generated report

- [ ] **Step 4: Verify charts directory**

```bash
ls -la /home/admin/Projects/TradeChanceScreen/data/charts/ | head -10
```
Expected: PNG chart files for opportunities

**Checkpoint 6 Result:**
```
=== CHECKPOINT: Web Server ===
Server status: running/not running
Report accessible: True/False
Charts available: True/False
Success: True/False
```

- [ ] **Mark Checkpoint 6:**
  - [ ] ✅ SUCCESS - Web server serving reports correctly
  - [ ] ❌ FAILED - Server not accessible

---

## Final Verification

### Task 8: Complete Workflow Validation

- [ ] **Step 1: Summary of all checkpoints**

```bash
echo "=== WORKFLOW EXECUTION SUMMARY ==="
echo "Checkpoint 1 (Market Sentiment): [result]"
echo "Checkpoint 2 (Symbol Screening): [result]"
echo "Checkpoint 3 (AI Scoring): [result]"
echo "Checkpoint 4 (Deep Analysis): [result]"
echo "Checkpoint 5 (Report Generation): [result]"
echo "Checkpoint 6 (Web Server): [result]"
echo ""
echo "Overall Status: [ALL SUCCESS / SOME FAILURES]"
```

- [ ] **Step 2: Update BUG-002 status if fixed**

If BUG-002 was fixed during execution:
- Update `bugs/BUG-002-ai-market-sentiment-parse.md` with resolution
- Update `bugs/bug-inventory.md` status

---

## Error Handling Procedures

### If Checkpoint Fails:

1. **Stop execution** - Do not proceed to next checkpoint
2. **Log the failure** - Capture error messages and context
3. **Diagnose** - Use debugging tools to identify root cause
4. **Fix** - Apply fix to resolve the issue
5. **Re-run failed checkpoint** - Verify fix works
6. **Continue** - Proceed to next checkpoint only after success

### Common Issues:

**Market Sentiment Empty (BUG-002):**
- Check field name mapping in `core/market_analyzer.py`
- Verify AI response format matches expected keys

**Screening No Candidates:**
- Check if market data is stale
- Verify strategy plugins are loading correctly
- Check for data fetching errors

**AI Analysis Errors:**
- Check API key validity
- Verify JSON parsing regex
- Check rate limiting

**Report Generation Fails:**
- Check disk space
- Verify `web/reports/` directory exists and is writable
- Check for missing chart files

---

## Plan Complete

This plan executes the complete Trade Scanner workflow with checkpoints at each step. Mark each checkpoint as it completes before proceeding to the next step.
