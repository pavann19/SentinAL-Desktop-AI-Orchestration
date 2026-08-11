# brain_config.py
# Unified LLM Configuration & Failover Management for SentinAL.

import os

from dotenv import load_dotenv

# Load environment variables at module level
load_dotenv()


def _is_rate_limit_error(exc: Exception) -> bool:
    """
    Groq/OpenAI-style clients raise a generic exception whose message contains
    the HTTP status and error code rather than a distinct exception type, so
    matching the message is the only reliable signal without a hard dependency
    on groq's internal exception classes.

    Deliberately narrow (429 / rate_limit_exceeded only): a bad key, a network
    error, or a genuine model outage must NOT trigger rotation — those need
    the real fix (get_routed_llm()'s existing fallback to Ollama), not a key
    swap that will fail identically.
    """
    msg = str(exc)
    return "429" in msg or "rate_limit_exceeded" in msg.lower()


class _RotatingGroqLLM:
    """
    Thin wrapper around ChatGroq that rotates to the next configured API key
    when one hits a 429 rate limit, then retries the SAME call transparently.

    Exists because found live, mid-benchmark: BrainConfig.get_routed_llm()
    already pinged Groq with a throwaway "ping" call before returning it, but
    that only catches a key that is ALREADY exhausted at request time — not one
    that runs out mid-session, which is exactly what happened (a 40x3 benchmark
    run tonight burned through Groq's 100k-token daily quota partway through,
    and target extraction failed silently afterward with no fallback).

    A wrapper is required rather than switching keys inside get_cloud_llm(),
    because the actual failure happens in callers' llm.invoke(...) — e.g.
    agentic_core/processor.py's target-extraction call — which happens AFTER
    BrainConfig has already handed back a client. Wrapping .invoke() is the one
    place that can retry the call itself, transparently to every existing call
    site, with the same interface (.invoke) LangChain callers already use.
    """

    def __init__(self, api_keys: list[str], model_name: str, temperature: float = 0, max_tokens: int = 1024):
        self._api_keys = api_keys
        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._index = 0
        self._client = self._build_client(self._index)

    def _build_client(self, index: int):
        from langchain_groq import ChatGroq
        return ChatGroq(
            model_name=self._model_name, groq_api_key=self._api_keys[index],
            temperature=self._temperature, max_tokens=self._max_tokens,
        )

    def invoke(self, *args, **kwargs):
        # Bounded by len(api_keys): every key gets exactly one attempt, so a
        # request that genuinely exhausts ALL configured keys raises (on its
        # last attempt's `raise`) rather than looping — there is nothing
        # further to fall back to here.
        while True:
            try:
                return self._client.invoke(*args, **kwargs)
            except Exception as exc:
                if not _is_rate_limit_error(exc) or self._index + 1 >= len(self._api_keys):
                    raise
                self._index += 1
                print(f"[BrainConfig] Groq key {self._index} rate-limited; "
                      f"rotating to key {self._index + 1}/{len(self._api_keys)}.")
                self._client = self._build_client(self._index)


class BrainConfig:
    """
    Centralized factory for LLM instances.
    Implements failover chains and standardizes model parameters.
    """

    @staticmethod
    def get_local_llm(num_predict: int = 1024):
        """Returns a ChatOllama instance (local-first priority)."""
        from langchain_ollama import ChatOllama
        model_name = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        return ChatOllama(model=model_name, temperature=0, num_predict=num_predict)

    @staticmethod
    def _groq_api_keys() -> list[str]:
        """
        Collects every configured Groq key, in priority order: GROQ_API_KEY,
        then GROQ_API_KEY_2, GROQ_API_KEY_3, ... (checked up to _6 — a generous
        bound, not a real limit; raise it if ever needed). Duplicates are
        dropped so the same key twice in .env doesn't get "rotated" onto itself.
        """
        keys = []
        primary = os.getenv("GROQ_API_KEY", "").strip(' \'"')
        if primary:
            keys.append(primary)
        for n in range(2, 7):
            extra = os.getenv(f"GROQ_API_KEY_{n}", "").strip(' \'"')
            if extra and extra not in keys:
                keys.append(extra)
        return keys

    @staticmethod
    def get_cloud_llm(max_tokens: int = 1024):
        """
        Returns a Groq-backed LLM (cloud-first priority). With one configured
        key this is a plain ChatGroq, unchanged from before. With more than
        one, returns a _RotatingGroqLLM that fails over between them on a 429.
        """
        api_keys = BrainConfig._groq_api_keys()
        if not api_keys:
            return None

        model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if len(api_keys) == 1:
            from langchain_groq import ChatGroq
            return ChatGroq(model_name=model_name, groq_api_key=api_keys[0], temperature=0, max_tokens=max_tokens)
        return _RotatingGroqLLM(api_keys, model_name, max_tokens=max_tokens)

    @staticmethod
    def get_routed_llm(prompt: str, purpose: str = "Execution"):
        """
        Privacy-aware routing with an automatic failover chain:
        1. Analyzes prompt for PII/Sensitive data via privacy_guard.
        2. If 'local' route: returns Ollama.
        3. If 'cloud' route: tries Groq, fails over to Ollama if API/Network fails.
        """
        from system_services.privacy_router import privacy_guard
        decision = privacy_guard.analyze(prompt)
        route = decision["route"]
        reason = decision["reason"]

        if route == "local":
            print(f"[AUDIT] Privacy Router [{purpose}]: LOCAL-ONLY - {reason}")
            return BrainConfig.get_local_llm()

        print(f"[AUDIT] Privacy Router [{purpose}]: CLOUD-SAFE - {reason}")
        
        # Cloud Failover Chain: Groq -> Ollama
        # V2.7 FIX: Actually invoke a ping to verify connectivity (was a no-op before)
        cloud_llm = BrainConfig.get_cloud_llm()
        if cloud_llm:
            try:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(cloud_llm.invoke, [("system", "ping")])
                    future.result(timeout=2.0)  # 2 second connectivity test
                return cloud_llm
            except concurrent.futures.TimeoutError:
                print("[RELIABILITY] Cloud LLM ping timed out. Falling back to local.")
            except Exception as e:
                print(f"[RELIABILITY] Cloud LLM ping failed ({e}). Falling back to local.")

        return BrainConfig.get_local_llm()

    @staticmethod
    def get_correction_llm():
        """Specialized lightweight instance for STT polishing."""
        return BrainConfig.get_local_llm(num_predict=100)
