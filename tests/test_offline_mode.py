# tests/test_offline_mode.py
# SENTINAL_OFFLINE=1: no cloud key needed, local Ollama used if reachable,
# else a deterministic mock so the pipeline stays runnable with nothing
# installed. No network calls in this file — ollama_reachable() is mocked.
#
# Deliberately does NOT importlib.reload(config.settings): that would create
# a NEW BrainConfig class object, breaking identity for every module that
# already did `from config.settings import BrainConfig` (planner.py,
# processor.py, ...) — any test elsewhere in the same pytest run that
# patches "config.settings.BrainConfig.get_routed_llm" would silently stop
# intercepting the real call, because the patch and the call site would then
# reference two different classes. monkeypatch.setattr on the already-
# imported module's OFFLINE constant does the same job without that hazard,
# and reverts automatically at teardown.

from __future__ import annotations

import pytest

from agentic_core.mock_llm import DeterministicMockLLM, _flatten
from config import settings

# ── BrainConfig.get_cloud_llm ────────────────────────────────────────────

def test_cloud_llm_is_none_when_offline(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE", True)
    monkeypatch.setenv("GROQ_API_KEY", "some-real-looking-key")
    assert settings.BrainConfig.get_cloud_llm() is None


def test_cloud_llm_unaffected_when_not_offline(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE", False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for n in range(2, 7):
        monkeypatch.delenv(f"GROQ_API_KEY_{n}", raising=False)
    # no keys configured -> still None, but for the ORIGINAL reason (no keys),
    # not because of the offline flag
    assert settings.BrainConfig.get_cloud_llm() is None


# ── BrainConfig.get_local_llm ────────────────────────────────────────────

def test_local_llm_uses_mock_when_offline_and_ollama_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE", True)
    monkeypatch.setattr("agentic_core.mock_llm.ollama_reachable", lambda timeout=0.75: False)
    llm = settings.BrainConfig.get_local_llm()
    assert isinstance(llm, DeterministicMockLLM)


def test_local_llm_uses_real_ollama_when_offline_and_reachable(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE", True)
    monkeypatch.setattr("agentic_core.mock_llm.ollama_reachable", lambda timeout=0.75: True)

    created = {}

    class _FakeChatOllama:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr("langchain_ollama.ChatOllama", _FakeChatOllama)
    llm = settings.BrainConfig.get_local_llm()
    assert isinstance(llm, _FakeChatOllama)
    assert created["model"]


def test_local_llm_never_checks_ollama_when_not_offline(monkeypatch):
    monkeypatch.setattr(settings, "OFFLINE", False)
    calls = []
    monkeypatch.setattr("agentic_core.mock_llm.ollama_reachable",
                        lambda timeout=0.75: calls.append(1) or True)

    class _FakeChatOllama:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("langchain_ollama.ChatOllama", _FakeChatOllama)
    settings.BrainConfig.get_local_llm()
    assert calls == []  # reachability check is offline-only


# ── DeterministicMockLLM ─────────────────────────────────────────────────

def test_mock_llm_returns_json_array_for_extraction_prompt():
    resp = DeterministicMockLLM().invoke([("system", "Output ONLY the raw JSON array.")])
    assert resp.content.strip().startswith("[")


def test_mock_llm_returns_step_shape_for_planner_prompt():
    resp = DeterministicMockLLM().invoke([("system", "decompose into step_id, depends_on, goal")])
    assert '"step_id"' in resp.content


def test_mock_llm_returns_canned_text_otherwise():
    resp = DeterministicMockLLM().invoke([("human", "what's the weather like")])
    assert "offline mode" in resp.content.lower()


def test_mock_llm_handles_plain_string_input():
    resp = DeterministicMockLLM().invoke("just a plain string prompt")
    assert resp.content


def test_flatten_handles_tuple_list_and_string():
    assert _flatten("plain") == "plain"
    assert "hello" in _flatten([("system", "hello"), ("human", "world")])


@pytest.fixture(autouse=True)
def _restore_offline_default():
    """Belt-and-braces: even though every test above uses monkeypatch (which
    self-reverts), guarantee OFFLINE is back to its real env-derived value
    for every other test file in the same session."""
    import os
    real = os.getenv("SENTINAL_OFFLINE", "false").strip().lower() not in ("0", "false", "no", "")
    yield
    assert settings.OFFLINE == real
