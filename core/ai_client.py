"""AI client for DeepSeek API with web search via tool calling.

Handles the multi-turn tool-calling loop: sends request with search_web tool,
executes the search when DeepSeek requests it, sends results back for final answer.
"""
import json
import logging
import requests
from typing import Optional, Dict, List

from config.settings import settings

logger = logging.getLogger(__name__)

API_KEY = settings.get_secret("dashscope.api_key")
API_BASE = settings.get_secret("dashscope.api_base") or "https://api.deepseek.com/v1"
MODEL = settings.get_secret("dashscope.model") or "deepseek-v4-pro"

def _execute_search(query: str) -> str:
    """Execute a web search and return formatted results."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(f"Title: {r.get('title', '')}\nURL: {r.get('href', '')}\nSnippet: {r.get('body', '')}")
        if not results:
            return f"No results found for: {query}"
        return "\n\n".join(results)
    except Exception as e:
        logger.warning(f"Search failed for '{query}': {e}")
        return f"Search failed: {e}"


def chat(
    messages: List[Dict],
    system: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 8000,
    enable_search: bool = False,
    search_query: Optional[str] = None,
    timeout: int = 300,
) -> Optional[str]:
    """Send a chat request. If enable_search, searches first and includes results.

    Uses pre-search approach: executes the search before calling the AI,
    then includes results in the prompt. Avoids tool-calling loops.
    """
    if not API_KEY:
        logger.error("No API key configured")
        return None

    url = f"{API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    # Build message list
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})

    # Pre-search: execute web search and inject results into the prompt
    if enable_search:
        query = search_query or messages[-1]["content"] if messages else ""
        search_results = _execute_search(query)
        search_block = f"\n\n[WEB SEARCH RESULTS for: \"{query}\"]\n{search_results}\n[/WEB SEARCH RESULTS]\n\nBased on the search results above, answer the user's question."
        # Append search context to the last user message
        augmented = messages[-1]["content"] + search_block
        msgs.append({"role": "user", "content": augmented})
    else:
        msgs.extend(messages)

    payload = {
        "model": MODEL,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"].get("content", "")
        return content or None
    except Exception as e:
        logger.error(f"AI API call failed: {e}")
        return None
