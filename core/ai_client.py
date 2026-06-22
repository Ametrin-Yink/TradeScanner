"""AI client for DeepSeek API with web search via DuckDuckGo pre-search."""
import json
import hashlib
import logging
import time
import requests
from datetime import datetime
from typing import Optional, Dict, List

from config.settings import settings
from data.db import db

logger = logging.getLogger(__name__)

API_KEY = settings.get_secret("dashscope.api_key")
API_BASE = settings.get_secret("dashscope.api_base") or "https://api.deepseek.com/v1"
MODEL = settings.get_secret("dashscope.model") or "deepseek-v4-pro"

# In-memory cache: (call_type, sector_name, date) -> result
_ai_cache = {}


def _execute_search(query: str) -> str:
    """Execute a DuckDuckGo web search and return formatted results."""
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
    temperature: float = 0.0,
    max_tokens: int = 8000,
    enable_search: bool = False,
    search_query: Optional[str] = None,
    timeout: int = 300,
    seed: int = 42,
    call_type: str = 'unknown',
    sector_name: str = '',
) -> Optional[str]:
    """Send a chat request with optional native web search.

    Uses DeepSeek's native tool-calling for web search.
    Deterministic: temperature=0.0, seed=42, json_object response format.
    Results cached by (call_type, sector_name, date) for 24h.
    """
    if not API_KEY:
        logger.error("No API key configured")
        return None

    # Check cache
    today = datetime.now().strftime('%Y-%m-%d')
    cache_key = f"{call_type}:{sector_name}:{today}"
    if cache_key in _ai_cache:
        logger.info(f"AI cache hit: {cache_key}")
        return _ai_cache[cache_key]

    url = f"{API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})

    # Pre-search: execute web search and inject results into the prompt
    if enable_search:
        query = search_query or (messages[-1]["content"] if messages else "")
        search_results = _execute_search(query)
        search_block = (
            f"\n\n[WEB SEARCH RESULTS for: \"{query}\"]\n"
            f"{search_results}\n"
            f"[/WEB SEARCH RESULTS]\n\n"
            f"Based on the search results above, answer the user's question."
        )
        augmented = messages[-1]["content"] + search_block
        msgs.append({"role": "user", "content": augmented})
    else:
        msgs.extend(messages)

    payload = {
        "model": MODEL,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": seed,
        "response_format": {"type": "json_object"},
    }

    prompt_text = json.dumps(msgs, sort_keys=True)
    prompt_hash = hashlib.sha256(prompt_text.encode()).hexdigest()[:16]

    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)

            if response.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                wait = 2 ** attempt
                logger.warning(f"Server error {response.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"].get("content", "")

            # Audit logging
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            response_hash = hashlib.sha256((content or "").encode()).hexdigest()[:16]

            # Cost estimate (DeepSeek pricing)
            cost = (tokens_in * 0.28 + tokens_out * 1.10) / 1_000_000

            logger.info(
                f"AI call: {call_type} {sector_name} -- "
                f"{tokens_in}+{tokens_out} tokens, ${cost:.4f}, "
                f"hash={response_hash}"
            )

            # Persist audit log
            db.log_ai_call(
                call_type=call_type,
                sector_name=sector_name,
                prompt_hash=prompt_hash,
                response_hash=response_hash,
                model=MODEL,
                temperature=temperature,
                seed=seed,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
            )

            # Cache result
            if content:
                _ai_cache[cache_key] = content

            return content or None

        except requests.exceptions.Timeout:
            logger.warning(f"AI call timeout (attempt {attempt+1}/3)")
            if attempt == 2:
                return None
        except Exception as e:
            logger.error(f"AI call failed (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                return None

    return None
