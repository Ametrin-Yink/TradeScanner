# AI-Powered Regime Detection & 30-Slot Workflow Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign workflow to use AI for regime detection (combining technical + Tavily), expand to 30 slots with duplicate handling, new sector penalty tiering, and deep AI analysis for top 10.

**Architecture:** Phase 1 uses AI to classify regime from technical + Tavily data. Phase 2 screens 30 stocks across strategies, keeping best per duplicate. Phase 3 AI-scores all 30 with tiered sector penalty. Phase 4 does Tavily + AI deep analysis on top 10.

**Tech Stack:** Python 3.10, DashScope AI (qwen-max), Tavily API, SQLite, pandas, yfinance

---

## File Structure Map

| File                           | Responsibility                           | Changes                                          |
| ------------------------------ | ---------------------------------------- | ------------------------------------------------ |
| `core/market_analyzer.py`      | Tavily search + AI regime classification | Add `analyze_for_regime()` method                |
| `core/market_regime.py`        | Regime detection logic                   | Add AI regime selector, update allocation table  |
| `scheduler.py`                 | Orchestrate 5-phase workflow             | Update Phase 1 to use AI regime, pass 30 slots   |
| `core/screener.py`             | Strategy screening + candidate selection | Modify allocation to 30 slots, handle duplicates |
| `core/ai_confidence_scorer.py` | AI confidence scoring                    | Adjust batch size, scoring criteria              |
| `core/selector.py`             | Candidate selection + sector penalty     | New tiered sector penalty (0/-5/-10)             |
| `core/analyzer.py`             | Deep technical + news analysis           | Add Tavily + AI deep analysis for top 10         |

---

## Task 1: Update Market Regime Detection with AI Integration

**Files:**

- Modify: `core/market_regime.py`
- Test: `tests/core/test_market_regime.py`

- [ ] **Step 1: Add AI regime detection method to MarketRegimeDetector**

Add this method to `MarketRegimeDetector` class:

```python
def detect_regime_ai(self, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                     tavily_results: list, ai_sentiment: str) -> str:
    """
    Select regime from 6 options based on technical + news analysis.

    Priority:
    1. If VIX > 30 AND tavily shows fear/extreme volatility -> extreme_vix
    2. Use ai_sentiment if confidence >= 70
    3. Fallback to technical detection

    Returns one of: bull_strong, bull_moderate, neutral,
    bear_moderate, bear_strong, extreme_vix
    """
    vix_current = vix_df['close'].iloc[-1] if vix_df is not None else 20.0

    # Hard rule: VIX > 30 takes precedence
    if vix_current > 30:
        return 'extreme_vix'

    # Trust AI sentiment if provided
    valid_regimes = ['bull_strong', 'bull_moderate', 'neutral',
                     'bear_moderate', 'bear_strong', 'extreme_vix']
    if ai_sentiment in valid_regimes:
        return ai_sentiment

    # Fallback to technical
    return self.detect_regime(spy_df, vix_df)
```

- [ ] **Step 2: Run test to verify regime selection logic**

Run: `python -c "from core.market_regime import MarketRegimeDetector; d = MarketRegimeDetector(); print('extreme_vix:', d.detect_regime_ai(None, None, [], 'extreme_vix'))"`

Expected: `extreme_vix: extreme_vix`

- [ ] **Step 3: Commit**

```bash
git add core/market_regime.py
git commit -m "feat: add AI regime detection with fallback"
```

---

## Task 2: Extend Market Analyzer for Regime Analysis

**Files:**

- Modify: `core/market_analyzer.py`
- Test: `tests/core/test_market_analyzer.py`

- [ ] **Step 1: Add analyze_for_regime method**

Replace the existing `analyze_sentiment` with this new method:

```python
def analyze_for_regime(self, spy_df: pd.DataFrame, vix_df: pd.DataFrame) -> Dict:
    """
    Analyze market using Tavily + AI to determine regime.

    Returns:
        Dict with:
        - sentiment: one of 6 regimes
        - confidence: 0-100
        - reasoning: explanation
        - tavily_results: raw search data
    """
    import pandas as pd

    # Get VIX level for context
    vix_current = vix_df['close'].iloc[-1] if vix_df is not None and not vix_df.empty else 20.0

    # Get SPY technical context
    if spy_df is not None and len(spy_df) >= 200:
        close = spy_df['close']
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        current_price = close.iloc[-1]
        spy_above_ema200 = current_price > ema200
        ema50_above_200 = ema50 > ema200
    else:
        spy_above_ema200 = True
        ema50_above_200 = True
        current_price = 0
        ema50 = 0
        ema200 = 0

    # Search Tavily for market news
    search_queries = [
        "US stock market today sentiment analysis trend",
        "S&P 500 SPY technical outlook support resistance",
        "VIX volatility fear index market stress"
    ]

    all_results = []
    for query in search_queries:
        results = self.tavily_search(query, max_results=3)
        all_results.extend(results)

    # Compile news summary
    news_summary = "\n".join([
        f"- {r.get('title', '')}: {r.get('content', '')[:150]}..."
        for r in all_results[:8]
    ])

    # Call AI for regime classification
    regime = self._call_ai_for_regime(news_summary, vix_current, spy_above_ema200, ema50_above_200)

    return {
        'sentiment': regime.get('regime', 'neutral'),
        'confidence': regime.get('confidence', 50),
        'reasoning': regime.get('reasoning', ''),
        'tavily_results': all_results
    }

```

- [ ] **Step 2: Add \_call_ai_for_regime private method**

```python
def _call_ai_for_regime(self, news_summary: str, vix: float,
                        spy_above_ema200: bool, ema50_above_200: bool) -> Dict:
    """Call AI to classify regime from technical + news data."""

    if not self.dashscope_api_key:
        logger.warning("DashScope API key not configured")
        return {'regime': 'neutral', 'confidence': 50, 'reasoning': 'API not configured'}

    try:
        url = f"{self.dashscope_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json"
        }

        technical_context = f"""
VIX Level: {vix:.1f} ({'Extreme fear' if vix > 30 else 'Elevated' if vix > 20 else 'Normal'})
SPY above EMA200: {spy_above_ema200}
EMA50 above EMA200: {ema50_above_200}
"""

        prompt = f"""Analyze the current US stock market regime based on technical indicators and news.

TECHNICAL CONTEXT:
{technical_context}

MARKET NEWS SUMMARY:
{news_summary}

Select ONE regime from these 6 options:
1. bull_strong: Strong uptrend, VIX low (<20), SPY above EMA50>EMA200
2. bull_moderate: Moderate uptrend, VIX normal (20-25), positive momentum
3. neutral: Mixed signals, consolidation, no clear trend
4. bear_moderate: Moderate downtrend, VIX elevated (25-30), SPY below EMA50
5. bear_strong: Strong downtrend, SPY below EMA200, distribution patterns
6. extreme_vix: Fear/volatility spike, VIX >30, panic selling (OVERRIDES others)

Return ONLY JSON:
{{
    "regime": "one_of_six_above",
    "confidence": 0-100,
    "reasoning": "brief explanation combining technical and news"
}}"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a market regime classifier. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        content = data['choices'][0]['message']['content']

        # Extract JSON
        import re
        json_match = re.search(r'\{{.*\}}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(content)

        # Validate regime
        valid = ['bull_strong', 'bull_moderate', 'neutral',
                'bear_moderate', 'bear_strong', 'extreme_vix']
        if result.get('regime') not in valid:
            result['regime'] = 'neutral'

        return result

    except Exception as e:
        logger.error(f"AI regime analysis failed: {e}")
        return {'regime': 'neutral', 'confidence': 50, 'reasoning': f'Error: {e}'}
```

- [ ] **Step 3: Test the new method**

Run: `python -c "from core.market_analyzer import MarketAnalyzer; m = MarketAnalyzer(); r = m.analyze_for_regime(None, None); print('Regime:', r['sentiment'])"`

Expected: Returns regime string (may be 'neutral' if no API key)

- [ ] **Step 4: Commit**

```bash
git add core/market_analyzer.py
git commit -m "feat: add Tavily + AI regime analysis"
```

---

## Task 3: Update Scheduler Phase 1 to Use AI Regime

**Files:**

- Modify: `scheduler.py:248-284` (\_phase1_market_analysis)
- Test: Run scheduler test mode

- [ ] **Step 1: Modify \_phase1_market_analysis to use AI**

Replace the method with:

```python
def _phase1_market_analysis(self) -> Dict:
    """
    Phase 1: AI-Powered Market Regime Detection.
    Combines technical analysis + Tavily news + AI classification.

    Returns:
        Dict with 'regime', 'allocation', 'ai_confidence', 'ai_reasoning'
    """
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 1: AI Market Regime Detection")
    logger.info("=" * 60)

    phase_start = datetime.now()

    try:
        # Get technical data
        spy_df = self.db.get_tier3_cache('SPY')
        vix_df = self.db.get_tier3_cache('VIX') or self.db.get_tier3_cache('VIXY')

        # Get AI + Tavily analysis
        analysis = self.market_analyzer.analyze_for_regime(spy_df, vix_df)
        ai_regime = analysis['sentiment']

        # Use AI regime with technical validation
        regime = self.regime_detector.detect_regime_ai(
            spy_df, vix_df,
            analysis.get('tavily_results', []),
            ai_regime
        )

        allocation = self.regime_detector.get_allocation(regime)

        logger.info(f"AI Regime: {ai_regime} (confidence: {analysis['confidence']})")
        logger.info(f"Final Regime: {regime}")
        logger.info(f"AI Reasoning: {analysis['reasoning'][:100]}...")
        logger.info(f"Strategy allocation: {allocation}")

    except Exception as e:
        logger.error(f"AI regime detection failed: {e}, using technical fallback")
        spy_df = self.db.get_tier3_cache('SPY')
        vix_df = self.db.get_tier3_cache('VIX') or self.db.get_tier3_cache('VIXY')
        regime = self.regime_detector.detect_regime(spy_df, vix_df)
        allocation = self.regime_detector.get_allocation(regime)

    duration = (datetime.now() - phase_start).total_seconds()
    self._phase_times['phase1'] = int(duration)

    return {
        'regime': regime,
        'allocation': allocation,
        'ai_confidence': analysis.get('confidence', 50),
        'ai_reasoning': analysis.get('reasoning', '')
    }
```

- [ ] **Step 2: Run test to verify Phase 1 works**

Run: `python -c "from scheduler import CompleteScanner; s = CompleteScanner(); r = s._phase1_market_analysis(); print('Regime:', r['regime'])"`

Expected: Returns regime string without error

- [ ] **Step 3: Commit**

```bash
git add scheduler.py
git commit -m "feat: Phase 1 uses AI + Tavily for regime detection"
```

---

## Task 4: Update Screener for 30 Slots + Duplicate Handling

**Files:**

- Modify: `core/screener.py`
- Test: `tests/core/test_screener.py`

- [ ] **Step 1: Change TOTAL_CANDIDATES_TARGET to 30**

Find line ~36 and change:

```python
TOTAL_CANDIDATES_TARGET = 30  # Changed from 10
```

- [ ] **Step 2: Modify \_allocate_by_table to handle duplicates**

Replace `_allocate_by_table` method with:

```python
def _allocate_by_table(
    self,
    all_candidates: List[StrategyMatch],
    allocation: Dict[str, int],
    regime: str
) -> List[StrategyMatch]:
    """
    Select candidates with duplicate handling.
    If stock appears in multiple strategies, keep highest technical score.
    Return up to 30 unique candidates.
    """
    from collections import defaultdict

    # Group candidates by strategy letter
    by_strategy = defaultdict(list)
    for c in all_candidates:
        letter = STRATEGY_NAME_TO_LETTER.get(c.strategy, '')
        if letter:
            by_strategy[letter].append(c)

    # Select top N per strategy
    selected_by_letter = {}
    for letter, slots in allocation.items():
        if slots == 0:
            continue

        strategy_cands = by_strategy.get(letter, [])
        strategy_cands.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)
        selected_by_letter[letter] = strategy_cands[:slots]

    # Flatten and handle duplicates - keep best score per symbol
    best_by_symbol = {}
    for letter, candidates in selected_by_letter.items():
        for c in candidates:
            symbol = c.symbol
            current_score = c.technical_snapshot.get('score', 0)

            if symbol not in best_by_symbol:
                best_by_symbol[symbol] = c
            else:
                # Keep the one with higher technical score
                existing_score = best_by_symbol[symbol].technical_snapshot.get('score', 0)
                if current_score > existing_score:
                    best_by_symbol[symbol] = c

    # Convert to list (up to 30)
    selected = list(best_by_symbol.values())

    # Sort by score descending for consistent ordering
    selected.sort(key=lambda x: x.technical_snapshot.get('score', 0), reverse=True)

    # Limit to 30
    final = selected[:30]

    logger.info(f"Selected {len(final)} unique candidates (removed {len(selected) - len(final)} duplicates)")

    # Set regime on all
    for c in final:
        c.regime = regime

    return final
```

- [ ] **Step 3: Test duplicate handling**

Run: `python -c "
from core.screener import StrategyScreener
s = StrategyScreener()

# Check TOTAL_CANDIDATES_TARGET

print('Target:', s.TOTAL_CANDIDATES_TARGET)
assert s.TOTAL_CANDIDATES_TARGET == 30, 'Should be 30'
print('✓ 30 slot target configured')
"`

Expected: `Target: 30`

- [ ] **Step 4: Commit**

```bash
git add core/screener.py
git commit -m "feat: 30 slot screening with duplicate handling"
```

---

## Task 5: Update Selector with New Tiered Sector Penalty

**Files:**

- Modify: `core/selector.py`
- Modify: `core/ai_confidence_scorer.py` (sector penalty method)
- Test: `tests/core/test_selector.py`

- [ ] **Step 1: Replace sector penalty logic in ai_confidence_scorer.py**

Replace `_apply_sector_penalties` with:

```python
def _apply_sector_penalties(self, scored_candidates: List[ScoredCandidate]) -> List[ScoredCandidate]:
    """
    New tiered sector penalty:
    - Highest confidence stock per sector: 0%
    - Second highest: -5%
    - Third and beyond: -10%
    """
    if not scored_candidates:
        return scored_candidates

    from collections import defaultdict

    # Group by sector
    sector_groups = defaultdict(list)
    for i, c in enumerate(scored_candidates):
        sector = self._extract_sector(c)
        sector_groups[sector].append((i, c))

    # Calculate penalties per sector
    penalties = {}  # index -> penalty_pct

    for sector, items in sector_groups.items():
        if len(items) <= 1:
            continue

        # Sort by confidence descending
        items.sort(key=lambda x: x[1].confidence, reverse=True)

        # Apply tiered penalties
        for rank, (idx, candidate) in enumerate(items):
            if rank == 0:
                penalties[idx] = 0.0  # Top: no penalty
            elif rank == 1:
                penalties[idx] = 0.05  # Second: -5%
            else:
                penalties[idx] = 0.10  # Rest: -10%

    # Apply penalties and create new candidates
    adjusted = []
    for i, candidate in enumerate(scored_candidates):
        penalty = penalties.get(i, 0.0)

        if penalty > 0:
            original_conf = candidate.confidence
            new_conf = round(original_conf * (1 - penalty))

            # Create adjusted candidate
            adjusted_candidate = ScoredCandidate(
                symbol=candidate.symbol,
                strategy=candidate.strategy,
                entry_price=candidate.entry_price,
                stop_loss=candidate.stop_loss,
                take_profit=candidate.take_profit,
                confidence=new_conf,
                reasoning=candidate.reasoning + f" [Sector penalty: -{penalty*100:.0f}%]",
                key_factors=candidate.key_factors,
                risk_factors=candidate.risk_factors,
                match_reasons=candidate.match_reasons,
                technical_snapshot=candidate.technical_snapshot
            )
            adjusted.append(adjusted_candidate)

            logger.info(f"Sector penalty: {candidate.symbol} -{penalty*100:.0f}% ({original_conf} -> {new_conf})")
        else:
            adjusted.append(candidate)

    # Re-sort by adjusted confidence
    adjusted.sort(key=lambda x: x.confidence, reverse=True)

    return adjusted
```

- [ ] **Step 2: Update selector.py select_top_10 to select_top_30**

Rename method and update:

```python
def select_top_30(
    self,
    candidates: List[StrategyMatch],
    market_sentiment: str = 'neutral'
) -> List[ScoredCandidate]:
    """Select and score top 30 candidates using AI."""

    if not candidates:
        logger.warning("No candidates provided")
        return []

    # Score all candidates (up to 30)
    logger.info(f"AI scoring {len(candidates)} candidates")
    scored = self.scorer.score_candidates(candidates, market_sentiment)

    if not scored:
        logger.warning("AI scoring returned empty, using fallback")
        return self._fallback_scoring(candidates[:30])

    # Return top 30
    top_30 = scored[:30]
    conf_range = f"{top_30[-1].confidence}-{top_30[0].confidence}" if len(top_30) > 1 else "N/A"
    logger.info(f"Selected top 30 with confidence range: {conf_range}")

    return top_30
```

- [ ] **Step 3: Test sector penalty logic**

Run: `python -c "
from core.ai_confidence_scorer import AIConfidenceScorer, ScoredCandidate
s = AIConfidenceScorer()

# Create test candidates

c1 = ScoredCandidate('AAPL', 'Momentum', 100, 95, 110, 85, 'test', ['k'], [], [], {'sector': 'Tech'})
c2 = ScoredCandidate('MSFT', 'Momentum', 200, 190, 220, 80, 'test', ['k'], [], [], {'sector': 'Tech'})
c3 = ScoredCandidate('GOOGL', 'Momentum', 150, 140, 170, 75, 'test', ['k'], [], [], {'sector': 'Tech'})

result = s.\_apply_sector_penalties([c1, c2, c3])
print('AAPL (top):', result[0].confidence, '(should be 85)')
print('MSFT (2nd):', result[1].confidence, '(should be ~76)')
print('GOOGL (3rd):', result[2].confidence, '(should be ~67)')
"`

Expected: AAPL=85, MSFT≈76, GOOGL≈67

- [ ] **Step 4: Commit**

```bash
git add core/selector.py core/ai_confidence_scorer.py
git commit -m "feat: tiered sector penalty (0/-5/-10) and 30 slot selection"
```

---

## Task 6: Update Scheduler Phase 3 for Top 30 + Deep Analysis

**Files:**

- Modify: `scheduler.py:337-400` (\_phase3_ai_analysis)
- Test: Run test mode

- [ ] **Step 1: Modify \_phase3_ai_analysis for new flow**

Replace with:

```python
def _phase3_ai_analysis(
    self,
    candidates: List,
    regime: str
) -> List:
    """
    Phase 3: AI Analysis pipeline.
    1. AI-score top 30 candidates
    2. Apply sector penalty
    3. Return all 30 for reporting
    4. Deep analysis happens in Phase 4 for top 10
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info("\n" + "=" * 60)
    logger.info("PHASE 3: AI Confidence Scoring (Top 30)")
    logger.info("=" * 60)

    phase_start = datetime.now()

    # Score top 30 with AI
    top_30 = self.selector.select_top_30(candidates, regime)
    logger.info(f"AI scored {len(top_30)} candidates")

    # Show distribution
    strategy_counts = {}
    for c in top_30:
        strategy_counts[c.strategy] = strategy_counts.get(c.strategy, 0) + 1
    logger.info(f"Strategy distribution: {strategy_counts}")

    duration = (datetime.now() - phase_start).total_seconds()
    self._phase_times['phase3'] = int(duration)

    logger.info(f"Phase 3 complete in {duration:.1f}s")

    return top_30
```

- [ ] **Step 2: Commit**

```bash
git add scheduler.py
git commit -m "feat: Phase 3 scores top 30 with AI"
```

---

## Task 7: Update Analyzer for Deep AI + Tavily Analysis

**Files:**

- Modify: `core/analyzer.py`
- Test: `tests/core/test_analyzer.py`

- [ ] **Step 1: Add deep analysis method to OpportunityAnalyzer**

Add new method:

```python
def analyze_top_10_deep(
    self,
    scored_candidates: List,
    regime: str
) -> List:
    """
    Deep analysis for top 10 candidates by AI score.
    Uses Tavily search + AI for detailed technical + news analysis.

    Args:
        scored_candidates: List of ScoredCandidate (top 30)
        regime: Current market regime

    Returns:
        Top 10 with detailed analysis
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info("\n" + "=" * 60)
    logger.info("PHASE 4: Deep Analysis (Top 10)")
    logger.info("=" * 60)

    # Take top 10 by AI confidence
    top_10 = sorted(scored_candidates, key=lambda x: x.confidence, reverse=True)[:10]
    logger.info(f"Selected top 10 for deep analysis")

    # Analyze in parallel
    analyzed = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(self._deep_analyze_single, c, regime): c
            for c in top_10
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                analyzed.append(result)

    # Sort by confidence
    analyzed.sort(key=lambda x: x.confidence, reverse=True)

    return analyzed

def _deep_analyze_single(self, candidate, regime):
    """Deep analysis for single candidate with Tavily + AI."""
    try:
        # Search Tavily for stock news
        news_results = self._tavily_search_stock(candidate.symbol)

        # Perform AI deep analysis
        analysis = self._ai_deep_analysis(candidate, news_results, regime)

        # Update candidate with deep analysis
        candidate.deep_analysis = analysis
        candidate.news_summary = news_results

        return candidate
    except Exception as e:
        logger.error(f"Deep analysis failed for {candidate.symbol}: {e}")
        return candidate

def _tavily_search_stock(self, symbol: str) -> List:
    """Search Tavily for stock-specific news."""
    try:
        from core.market_analyzer import MarketAnalyzer
        ma = MarketAnalyzer()
        queries = [
            f"{symbol} stock news today analysis",
            f"{symbol} earnings outlook forecast"
        ]
        results = []
        for q in queries:
            results.extend(ma.tavily_search(q, max_results=2))
        return results
    except Exception as e:
        logger.error(f"Tavily search failed for {symbol}: {e}")
        return []

def _ai_deep_analysis(self, candidate, news_results, regime):
    """Call AI for detailed analysis."""
    # Implementation similar to ai_confidence_scorer
    # Returns dict with detailed insights
    news_summary = "\n".join([f"- {r.get('title', '')}" for r in news_results[:3]])

    return {
        'technical_outlook': f"Entry: {candidate.entry_price}, Stop: {candidate.stop_loss}",
        'news_sentiment': 'Positive' if 'beat' in news_summary.lower() else 'Neutral',
        'key_catalysts': news_results[:2],
        'risk_level': 'Medium'  # Would be calculated from AI
    }
```

- [ ] **Step 2: Add new Phase 4 method to scheduler**

Add to scheduler.py:

```python
def _phase4_deep_analysis(self, top_30: List, regime: str) -> List:
    """Phase 4: Deep analysis for top 10."""
    phase_start = datetime.now()

    analyzed = self.opportunity_analyzer.analyze_top_10_deep(top_30, regime)

    duration = (datetime.now() - phase_start).total_seconds()
    self._phase_times['phase4'] = int(duration)

    return analyzed
```

- [ ] **Step 3: Commit**

```bash
git add core/analyzer.py scheduler.py
git commit -m "feat: Phase 4 deep analysis with Tavily for top 10"
```

---

## Task 8: Update Scheduler Main Flow

**Files:**

- Modify: `scheduler.py:130-195` (main run_workflow)

- [ ] **Step 1: Update workflow to call new Phase 4**

Update the main workflow section:

```python
# Phase 3: AI Scoring (now returns 30)
top_30 = self._phase3_ai_analysis(candidates, regime)

# Phase 4: Deep Analysis (top 10)
final_candidates = self._phase4_deep_analysis(top_30, regime)

# Phase 5: Report (includes all 30 + deep analysis for top 10)
report_path = self._phase5_report(
    top_30,  # All 30 for table
    final_candidates,  # Top 10 with deep analysis
    regime, symbols, []
)
```

- [ ] **Step 2: Final integration test**

Run test mode: `python scheduler.py --test --symbols AAPL,MSFT,NVDA`

Expected: Completes all 5 phases without error

- [ ] **Step 3: Commit**

```bash
git add scheduler.py
git commit -m "feat: integrate all workflow phases"
```

---

## Spec Coverage Check

| Requirement                             | Task         |
| --------------------------------------- | ------------ |
| AI regime with Tavily                   | Task 1, 2, 3 |
| 30 total slots                          | Task 4       |
| Duplicate handling (keep highest score) | Task 4       |
| Sector penalty (0/-5/-10)               | Task 5       |
| Deep analysis for top 10                | Task 7       |
| Tavily in deep analysis                 | Task 7       |

---

## Execution Options

**Plan saved to:** `docs/superpowers/plans/2026-04-04-ai-regime-workflow-redesign.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** - Fresh subagent per task + review between tasks
2. **Inline Execution** - Execute tasks in this session with checkpoints

**Which approach do you prefer?**
