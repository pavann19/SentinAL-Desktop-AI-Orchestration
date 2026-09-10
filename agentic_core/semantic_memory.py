# agentic_core/semantic_memory.py
# S6 proactive autonomy — semantic memory, increment 1.
#
# interaction_history / get_context_for_prompt() give the agent RECENCY memory
# (the last few things you did). This adds retrieval by MEANING: on a new
# request, surface the past interactions most semantically similar to it, even
# if they were days ago.
#
# Reuses the embedding model the router already loaded (all-MiniLM-L6-v2 on
# CPU) — no second model, no new dependency, no vector server. Storage is a
# BLOB column in the existing SQLite DB; retrieval is a brute-force cosine scan
# over the most-recent N rows (fine at personal-assistant scale — thousands,
# not millions; add an index only if it is ever measurably slow).
#
# Never raises. Off unless SENTINAL_SEMANTIC_MEMORY_ENABLED, and a no-op if the
# router is in keyword-fallback mode (no model). Off by default because the
# retrieved context feeds the LLM prompt and can shift intent extraction /
# benchmark results — opt in, then flip once validated.

from __future__ import annotations

import logging
import os
import time

import numpy as np

_logger = logging.getLogger("SemanticMemory")

ENABLED = os.getenv("SENTINAL_SEMANTIC_MEMORY_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")
K = int(os.getenv("SENTINAL_SEMANTIC_MEMORY_K", "3"))
MIN_SIM = float(os.getenv("SENTINAL_SEMANTIC_MEMORY_MIN_SIM", "0.35"))
MAX_ROWS = int(os.getenv("SENTINAL_SEMANTIC_MEMORY_MAX_ROWS", "5000"))

_EMB_DTYPE = np.float32


def _model():
    """The router's already-loaded SentenceTransformer, or None if it is in
    keyword-fallback mode."""
    try:
        from agentic_core.router import router
        return getattr(router, "model", None)
    except Exception:
        return None


def _embed(text: str) -> np.ndarray | None:
    """A unit-normalised embedding for `text`, or None if no model."""
    m = _model()
    if m is None or not text:
        return None
    try:
        vec = np.asarray(m.encode([text]), dtype=_EMB_DTYPE).reshape(-1)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec
    except Exception as e:
        _logger.debug(f"embed failed (non-fatal): {e}")
        return None


_mem = None


def _memory():
    """Lazy module-level MemoryManager singleton (one sqlite connection, not
    one per call — the leak fixed in data_modeler/academic_research/scheduler)."""
    global _mem
    if _mem is None:
        from agentic_core.memory_hook import MemoryManager
        _mem = MemoryManager()
    return _mem


def remember(text: str, meta: dict | None = None) -> None:
    """Embed and store one interaction. No-op when disabled or model-less."""
    if not ENABLED:
        return
    vec = _embed(text)
    if vec is None:
        return
    meta = meta or {}
    try:
        _memory().add_semantic_memory(
            text=text,
            embedding_blob=vec.tobytes(),
            intent=meta.get("intent"),
            target=meta.get("target"),
            result=(str(meta.get("result"))[:200] if meta.get("result") is not None else None),
            ts=float(meta.get("ts", time.time())),
        )
    except Exception as e:
        _logger.debug(f"remember failed (non-fatal): {e}")


def retrieve(query: str, k: int | None = None, min_similarity: float | None = None) -> list[dict]:
    """Top-k stored interactions most similar to `query`, above the similarity
    floor, newest-first among ties. [] when disabled, model-less, or empty."""
    if not ENABLED:
        return []
    qv = _embed(query)
    if qv is None:
        return []
    k = K if k is None else k
    floor = MIN_SIM if min_similarity is None else min_similarity
    try:
        rows = _memory().recent_semantic_memories(limit=MAX_ROWS)
    except Exception as e:
        _logger.debug(f"retrieve scan failed (non-fatal): {e}")
        return []
    if not rows:
        return []

    scored = []
    for r in rows:
        try:
            v = np.frombuffer(r["embedding"], dtype=_EMB_DTYPE)
            if v.shape != qv.shape:
                continue
            sim = float(np.dot(qv, v))  # both unit-normalised -> cosine
        except Exception:
            continue
        if sim >= floor:
            scored.append((sim, r))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [
        {"text": r["text"], "intent": r["intent"], "target": r["target"],
         "result": r["result"], "ts": r["ts"], "similarity": round(sim, 3)}
        for sim, r in scored[:k]
    ]


def format_for_prompt(results: list[dict]) -> str:
    """A capped [RELEVANT PAST CONTEXT] block for LLM injection, same length
    discipline as memory_hook.get_context_for_prompt()."""
    if not results:
        return ""
    lines = ["[RELEVANT PAST CONTEXT]"]
    for r in results:
        intent = r.get("intent") or "?"
        target = r.get("target") or ""
        res = (r.get("result") or "")[:80]
        line = f"- {intent}: {target} -> {res}".strip()
        lines.append(line[:150])
    out = "\n".join(lines)
    return out[:1000] + "... [context truncated]" if len(out) > 1000 else out
