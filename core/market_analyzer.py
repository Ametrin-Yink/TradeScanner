"""Market environment analyzer using DashScope enable_search and AI."""
import logging
import json
from typing import Dict

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """Analyze market sentiment using DashScope built-in web search and AI."""

    # Specific search topics the AI must cover before classifying regime
    SEARCH_TOPICS = [
        ("VIX / volatility", "VIX volatility outlook latest market analysis"),
        ("Macro economy", "Federal Reserve interest rate policy latest economic data"),
        ("Market breadth", "US stock market breadth advance decline sector rotation today"),
        ("Geopolitical risks", "geopolitical risk trade war market impact current"),
    ]

    def __init__(self):
        """Initialize with API keys from settings."""
        self.dashscope_api_key = settings.get_secret('dashscope.api_key')
        self.dashscope_base = settings.get_secret('dashscope.api_base') or settings.get('ai', {}).get('api_base', 'https://coding.dashscope.aliyuncs.com/v1')
        self.model = settings.get_secret('dashscope.model') or settings.get('ai', {}).get('model', 'qwen-max')

    def analyze_for_regime(self, spy_df, vix_df) -> Dict:
        """
        Analyze market using DashScope enable_search + AI to determine regime.

        Args:
            spy_df: SPY price DataFrame with 'close' column
            vix_df: VIX price DataFrame with 'close' column

        Returns:
            Dict with:
            - sentiment: one of 6 regimes
            - confidence: 0-100
            - reasoning: explanation
        """
        import numpy as np
        import pandas as pd

        vix_current = vix_df['close'].iloc[-1] if vix_df is not None and not vix_df.empty else 20.0

        if spy_df is not None and len(spy_df) >= 200:
            close = spy_df['close']
            ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1]
            ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            current_price = close.iloc[-1]
            ret_5d = ((current_price / close.iloc[-5]) - 1) * 100
            high_52w = close.rolling(252).max().iloc[-1]
            low_52w = close.rolling(252).min().iloc[-1]
            pct_in_range = ((current_price - low_52w) / (high_52w - low_52w)) * 100
            spy_above_ema200 = current_price > ema200
            ema50_above_200 = ema50 > ema200
        else:
            ema8 = ema21 = ema50 = ema200 = current_price = 0
            ret_5d = 0
            high_52w = low_52w = 0
            pct_in_range = 0
            spy_above_ema200 = True
            ema50_above_200 = True

        # QQQ / IWM context
        from data.db import db
        qqq_above_ema50, qqq_below_ema200 = self._get_ema_status(db, 'QQQ')
        iwm_above_ema50, iwm_below_ema200 = self._get_ema_status(db, 'IWM')

        # Build search topics list
        search_topics = self.SEARCH_TOPICS

        regime = self._call_ai_for_regime(
            current_price, ema8, ema21, ema50, ema200,
            spy_above_ema200, ema50_above_200, ret_5d,
            high_52w, low_52w, pct_in_range,
            vix_current,
            qqq_above_ema50, iwm_above_ema50, iwm_below_ema200,
            search_topics
        )

        return {
            'sentiment': regime.get('regime', 'neutral'),
            'confidence': regime.get('confidence', 50),
            'reasoning': regime.get('reasoning', ''),
        }

    def _get_ema_status(self, db, symbol: str):
        """Get above-EMA50 and below-EMA200 status for a symbol from tier3 cache."""
        try:
            df = db.get_tier3_cache(symbol)
            if df is not None and len(df) >= 200:
                close = df['close']
                price = close.iloc[-1]
                ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
                ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
                return price > ema50, price < ema200
        except Exception as e:
            logger.warning(f"Failed to load {symbol} data: {e}")
        return None, None

    def _call_ai_for_regime(
        self, price, ema8, ema21, ema50, ema200,
        spy_above_ema200, ema50_above_200, ret_5d,
        high_52w, low_52w, pct_in_range,
        vix,
        qqq_above_ema50, iwm_above_ema50, iwm_below_ema200,
        search_topics
    ) -> Dict:
        """Call DashScope AI with enable_search to classify regime."""

        if not self.dashscope_api_key:
            logger.warning("DashScope API key not configured")
            return {'regime': 'neutral', 'confidence': 50, 'reasoning': 'API not configured'}

        vix_label = 'Extreme fear' if vix > 30 else 'Elevated' if vix > 20 else 'Normal'
        search_instructions = '\n'.join(
            f'{i+1}. {name}: search "{query}"'
            for i, (name, query) in enumerate(search_topics)
        )

        technical_block = f"""- SPY current price: {price:.1f}
- SPY 8-day EMA: {ema8:.1f}
- SPY 21-day EMA: {ema21:.1f}
- SPY 50-day EMA: {ema50:.1f}
- SPY 200-day EMA: {ema200:.1f}
- SPY above EMA200: {spy_above_ema200}
- EMA50 above EMA200 (golden cross): {ema50_above_200}
- SPY 5-day return: {ret_5d:+.2f}%
- SPY 52-week range: {low_52w:.1f} - {high_52w:.1f} (current at {pct_in_range:.0f}% of range)
- VIX level: {vix:.1f} ({vix_label})
- QQQ above EMA50: {qqq_above_ema50}
- IWM above EMA50: {iwm_above_ema50}
- IWM below EMA200: {iwm_below_ema200}"""

        regime_defs = """- bull_strong: Strong sustained uptrend, very low fear, broad participation, risk-on
- bull_moderate: Uptrend intact but cautious, normal volatility, some headwinds present
- neutral: Mixed signals, consolidation phase, no clear directional edge
- bear_moderate: Clear downtrend with occasional relief rallies, elevated fear
- bear_strong: Severe selloff, broad panic, breakdown below key support levels
- extreme_vix: Panic-level volatility spike, VIX >30, market stress"""

        prompt = f"""You are a professional macro US stock market trader. Determine the current US market regime by combining live web search with technical analysis.

STEP 1 — WEB SEARCH
Search for each of these topics using the exact queries below:
{search_instructions}

STEP 2 — MARKET NARRATIVE
Write a brief summary of what the web search reveals about current market conditions. Focus on:
- What is driving the market RIGHT NOW (specific events, data releases, Fed actions)
- What sectors are leading/lagging and why
- Any geopolitical or macro risks affecting trader behavior
Do NOT mention technical indicators in this section — focus only on news/events.

STEP 3 — TECHNICAL REALITY CHECK
Compare the news narrative against the technical data below. Do they confirm or contradict each other? Note any divergences. For example: "News is bullish on rate cut hopes, but SPY has broken below EMA50 and VIX has spiked — technicals tell a different story."

STEP 4 — CLASSIFY
Based on BOTH sources, select ONE regime. Explain your reasoning in plain English. Do NOT list indicator values — the reader already sees them. Instead, explain what they MEAN together with the news.

Example of GOOD reasoning: "Markets are pricing in two Fed rate cuts this year, but the latest CPI print came in hotter than expected, cooling dovish bets. SPY remains above all EMAs with broad sector participation, yet the VIX climb to 22 suggests growing complacency concerns. Technicals remain bullish but news flow indicates increasing caution — this fits a moderate bull regime with declining conviction."
Example of BAD reasoning: "SPY is at 612 which is above the EMA50 of 590 and the VIX is 22 which is elevated."

TECHNICAL DATA (pre-computed, reference these but do NOT list them verbatim):
{technical_block}

REGIME DEFINITIONS (quantitative guides):
{regime_defs}

OUTPUT FORMAT:
First, provide a brief analysis (3-4 paragraphs) covering your search findings, technical reality check, and synthesis.
Then, at the very end, output a JSON code block with the regime classification:
```json
{{"regime": "one_of_six_above", "confidence": 0-100, "reasoning": "2-3 sentences explaining the market narrative and technical synthesis — do NOT list indicator values, explain what they mean"}}
```"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a market regime classifier. You MUST use web search. Provide brief analysis first, then end with a JSON code block containing regime, confidence, and reasoning."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "enable_search": True,
            "max_tokens": 4000
        }

        url = f"{self.dashscope_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.dashscope_api_key}",
            "Content-Type": "application/json"
        }

        import re
        attempt = 0
        while True:
            attempt += 1
            try:
                logger.info(f"Calling DashScope with enable_search (model: {self.model}, attempt {attempt})...")
                response = requests.post(url, headers=headers, json=payload, timeout=300)
                response.raise_for_status()

                data = response.json()
                content = data['choices'][0]['message']['content']

                logger.info(f"DashScope response (first 400 chars):\n{content[:400]}")

                # Extract JSON — look for code block first
                result = None

                code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if code_block:
                    try:
                        result = json.loads(code_block.group(1))
                    except json.JSONDecodeError:
                        pass

                # Fallback: find last JSON object in text
                if result is None:
                    start_idx = content.rfind('{')
                    if start_idx >= 0:
                        brace_count = 0
                        for i, char in enumerate(content[start_idx:], start_idx):
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    try:
                                        result = json.loads(content[start_idx:i+1])
                                        break
                                    except json.JSONDecodeError:
                                        pass

                if result is None:
                    logger.warning(f"JSON parse failed on attempt {attempt}, retrying...")
                    continue

                # Validate regime — retry if invalid
                valid = ['bull_strong', 'bull_moderate', 'neutral',
                        'bear_moderate', 'bear_strong', 'extreme_vix']
                if result.get('regime') not in valid:
                    logger.warning(f"Invalid regime '{result.get('regime')}' on attempt {attempt}, retrying...")
                    continue

                return result

            except Exception as e:
                logger.warning(f"API error on attempt {attempt}: {e}, retrying...")
