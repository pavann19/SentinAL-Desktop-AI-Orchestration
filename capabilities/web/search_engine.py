import os
import re
import time
import logging
from dotenv import load_dotenv

# Neural layer research tool.
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    print("[SRE] Warning: 'tavily-python' not installed. Research capabilities will be limited.")

load_dotenv()

# Fix 2.8: max_results now configurable via env var
_MAX_RESULTS   = int(os.getenv("TAVILY_MAX_RESULTS", "3"))
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Fix 2.8: Module-level singleton client — only instantiated once, not per call
_tavily_client: "TavilyClient | None" = None


def _get_client() -> "TavilyClient | None":
    """Lazy-init singleton Tavily client."""
    global _tavily_client
    if _tavily_client is None and TAVILY_AVAILABLE and _TAVILY_API_KEY:
        _tavily_client = TavilyClient(api_key=_TAVILY_API_KEY)
    return _tavily_client


def get_live_research(query: str, max_results: int = _MAX_RESULTS) -> dict:
    """
    Neural layer research tool. Standardized to return a dictionary
    containing 'context' or 'error' for precise backend mapping.

    V2.0 Fixes (Fix 2.8):
    - TavilyClient is now a module-level singleton (not re-created per call)
    - 2-attempt retry with 1s delay on transient 429/timeout errors
    - max_results driven by TAVILY_MAX_RESULTS env var
    """
    # ── INPUT VALIDATION ────────────────────────────────────────────────────────
    clean_query = (query or "").strip()
    if not clean_query or len(clean_query) < 2:
        print(f"[RELIABILITY ERROR] Search rejected: query too short ('{query}')")
        return {"error": "Search query is too short or empty.", "code": 400}

    alpha_ratio = len(re.sub(r'[^a-zA-Z0-9 ]', '', clean_query)) / max(len(clean_query), 1)
    if alpha_ratio < 0.3:
        print(f"[RELIABILITY ERROR] Search rejected: mostly symbols ('{query}')")
        return {"error": "Search query appears to be invalid.", "code": 400}

    if not TAVILY_AVAILABLE:
        return {"error": "Search engine library ('tavily') is not installed.", "code": 500}

    if not _TAVILY_API_KEY:
        print("[SRE] Tavily API key not configured. Set TAVILY_API_KEY in .env")
        return {"error": "TAVILY_API_KEY not configured.", "code": 500}

    client = _get_client()
    if not client:
        return {"error": "Could not initialize Tavily client.", "code": 500}

    # ── 2-ATTEMPT RETRY LOOP ────────────────────────────────────────────────────
    last_error = None
    for attempt in range(1, 3):
        try:
            print(f"[AUDIT] Tavily query (attempt {attempt}): {clean_query}")
            response = client.search(
                query=clean_query,
                search_depth="basic",
                max_results=max_results
            )
            results = response.get("results", [])
            if not results:
                return {"error": "No live search results found.", "code": 404}

            context = "\n".join([f"Snippet: {r['content']}" for r in results])
            print("[AUDIT] Tavily data retrieved successfully.")
            return {"context": context, "results": results}

        except Exception as e:
            last_error = str(e)
            err_lower  = last_error.lower()
            # Only retry on transient errors (rate-limit / timeout / connection)
            if "429" in last_error or "timeout" in err_lower or "connection" in err_lower:
                if attempt < 2:
                    print(f"[RELIABILITY] Tavily transient error (attempt {attempt}): {e}. Retrying...")
                    time.sleep(1.0)
                    continue
            # Non-retriable errors — break immediately
            break

    print(f"[SRE] Tavily error (final): {last_error}")
    return {"error": last_error, "code": 500}