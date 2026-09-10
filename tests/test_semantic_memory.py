# tests/test_semantic_memory.py
# S6 semantic memory, increment 1.
#
# The embedder is stubbed with a tiny deterministic fake (token bag-of-words
# over a fixed vocabulary) so the real all-MiniLM-L6-v2 model never loads:
# fast, hermetic, and still gives "share more words -> higher cosine".

from __future__ import annotations

import importlib

import numpy as np
import pytest

import agentic_core.semantic_memory as sm


# ---------------------------------------------------------------------------
# deterministic fake embedder
# ---------------------------------------------------------------------------
_VOCAB = [
    "open", "close", "file", "notepad", "browser", "delete", "create",
    "folder", "search", "weather", "email", "music", "screenshot", "python",
]
_DIM = len(_VOCAB)


class _FakeModel:
    """Bag-of-words over _VOCAB. Deterministic, no network, no torch."""

    def encode(self, texts):
        out = []
        for t in texts:
            toks = str(t).lower().split()
            v = np.zeros(_DIM, dtype=np.float32)
            for i, w in enumerate(_VOCAB):
                if w in toks:
                    v[i] = 1.0
            out.append(v)
        return np.asarray(out, dtype=np.float32)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Fresh module state: flag ON, fake model, isolated sqlite DB."""
    monkeypatch.setenv("SENTINAL_SEMANTIC_MEMORY_ENABLED", "true")
    mod = importlib.reload(sm)

    monkeypatch.setattr(mod, "_model", lambda: _FakeModel())

    from agentic_core.memory_hook import MemoryManager

    mm = MemoryManager(db_path=str(tmp_path / "sem.db"))
    monkeypatch.setattr(mod, "_memory", lambda: mm)
    mod._mem = mm
    yield mod
    mod._mem = None


# ---------------------------------------------------------------------------
# _embed
# ---------------------------------------------------------------------------
def test_embed_is_unit_normalised_and_stable(store):
    a = store._embed("open notepad file")
    b = store._embed("open notepad file")
    assert a is not None
    np.testing.assert_allclose(a, b)
    assert np.isclose(np.linalg.norm(a), 1.0)


def test_embed_empty_text_returns_none(store):
    assert store._embed("") is None


def test_embed_no_model_returns_none(store, monkeypatch):
    monkeypatch.setattr(store, "_model", lambda: None)
    assert store._embed("open notepad") is None


# ---------------------------------------------------------------------------
# remember + retrieve
# ---------------------------------------------------------------------------
def test_retrieve_ranks_semantically_closest_first(store):
    store.remember("open notepad and edit the file", {"intent": "GeneralizedOSIntent"})
    store.remember("check the weather forecast", {"intent": "InformationRetrievalIntent"})
    store.remember("play some music", {"intent": "MediaIntent"})

    hits = store.retrieve("open the notepad file", min_similarity=0.1)
    assert hits
    assert "notepad" in hits[0]["text"]


def test_min_similarity_filters_unrelated(store):
    store.remember("play some music", {"intent": "MediaIntent"})
    # query shares no vocabulary tokens -> cosine 0
    assert store.retrieve("delete folder", min_similarity=0.35) == []


def test_k_caps_result_count(store):
    for i in range(5):
        store.remember(f"open file notepad browser {i}", {"intent": "GeneralizedOSIntent"})
    assert len(store.retrieve("open file notepad browser", k=2, min_similarity=0.1)) == 2


def test_empty_store_returns_empty(store):
    assert store.retrieve("open notepad") == []


# ---------------------------------------------------------------------------
# disabled / fallback safety
# ---------------------------------------------------------------------------
def test_flag_off_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINAL_SEMANTIC_MEMORY_ENABLED", "false")
    mod = importlib.reload(sm)
    monkeypatch.setattr(mod, "_model", lambda: _FakeModel())
    mod.remember("open notepad")           # must not raise
    assert mod.retrieve("open notepad") == []
    importlib.reload(sm)


def test_model_less_router_is_noop(store, monkeypatch):
    monkeypatch.setattr(store, "_model", lambda: None)
    store.remember("open notepad")         # must not raise
    assert store.retrieve("open notepad") == []


def test_remember_swallows_storage_error(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(store._memory(), "add_semantic_memory", boom)
    store.remember("open notepad")         # must not raise


# ---------------------------------------------------------------------------
# format_for_prompt
# ---------------------------------------------------------------------------
def test_format_for_prompt_empty_is_blank(store):
    assert store.format_for_prompt([]) == ""


def test_format_for_prompt_has_header_and_respects_cap(store):
    rows = [
        {"intent": "GeneralizedOSIntent", "target": "notepad", "result": "x" * 500}
        for _ in range(50)
    ]
    out = store.format_for_prompt(rows)
    assert out.startswith("[RELEVANT PAST CONTEXT]")
    assert len(out) <= 1000 + len("... [context truncated]")
