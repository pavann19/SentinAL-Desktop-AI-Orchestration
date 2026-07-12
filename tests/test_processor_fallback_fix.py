"""
Independent verification tests for the LLM-fallback JSON parsing fix in
agentic_core/processor.py (commit 00e46d8, landed directly to main without
gates — written after the fact per VERIFICATION_PROTOCOL.md Gate 2, since
the fix was never dispatched through the normal context-pack/branch flow).

The fix changed the fallback prompt (agentic_core/processor.py, inside
extract_intent) from asking the LLM to "Output EXACTLY the intent name,
nothing else" (a bare string) to asking for a JSON array
'[{"intent": "..."}]'. It kept the old bare-string parsing as a secondary
fallback when JSON parsing fails, so this suite verifies BOTH paths still
work and that a step_query with genuinely low router confidence gets
correctly attributed to whichever intent the LLM (mocked here) returns.
"""
from unittest.mock import MagicMock, patch

import agentic_core.processor as processor


def _mock_router(confidence, intent="UnknownIntent"):
    m = MagicMock()
    m.route.return_value = {"intent": intent, "confidence": confidence}
    return m


def _mock_llm(response_text):
    llm = MagicMock()
    resp = MagicMock()
    resp.content = response_text
    llm.invoke.return_value = resp
    return llm


def test_fallback_parses_new_json_array_format(monkeypatch):
    """The new, intended format: a JSON array with an 'intent' key."""
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: _mock_llm(
        '[{"intent": "InformationRetrievalIntent"}]'
    ))
    with patch("agentic_core.router.router", _mock_router(0.1)):
        steps = processor.extract_intent("some genuinely obscure phrasing xyz")
    assert steps[0]["intent"] == "InformationRetrievalIntent"
    # prompt/confidence auto-filled per the fix's new lines
    assert steps[0]["prompt"] == "some genuinely obscure phrasing xyz"
    assert steps[0]["confidence"] == 1.0


def test_fallback_still_parses_old_bare_string_format(monkeypatch):
    """Backward-compat path: if the LLM ignores the new instruction and
    returns a bare intent name (the OLD expected format), it must still work
    via the secondary fallback parsing — this is what made the fix safe to
    ship without a hard behavior break."""
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: _mock_llm(
        "InformationRetrievalIntent"
    ))
    with patch("agentic_core.router.router", _mock_router(0.1)):
        steps = processor.extract_intent("some genuinely obscure phrasing xyz")
    # bare-string path doesn't append to final_pipeline directly; it sets
    # matched_intent and falls through to phase-2 parameter extraction —
    # confirm the resulting step still carries the correct intent.
    assert steps[0]["intent"] == "InformationRetrievalIntent"


def test_fallback_garbage_response_does_not_crash_and_stays_unknown(monkeypatch):
    """Neither valid JSON nor a recognized bare intent name — must not raise,
    must not silently invent an intent; stays UnknownIntent (the original,
    documented failure mode this whole investigation started from)."""
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: _mock_llm(
        "I'm not sure what you mean by that, could you clarify?"
    ))
    with patch("agentic_core.router.router", _mock_router(0.1)):
        steps = processor.extract_intent("some genuinely obscure phrasing xyz")
    assert steps[0]["intent"] == "UnknownIntent"


def test_fallback_json_object_missing_intent_key_falls_through_safely(monkeypatch):
    """A JSON array where the object has no 'intent' key at all — must not
    KeyError, must not crash the pipeline."""
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: _mock_llm(
        '[{"something_else": "value"}]'
    ))
    with patch("agentic_core.router.router", _mock_router(0.1)):
        steps = processor.extract_intent("some genuinely obscure phrasing xyz")
    # It's still a valid list -> gets extended into final_pipeline as-is,
    # with prompt/confidence backfilled; intent key legitimately absent here
    # (this documents real behavior — not asserting an intent that isn't set).
    assert "intent" not in steps[0] or steps[0].get("intent") is None
    assert steps[0]["prompt"] == "some genuinely obscure phrasing xyz"


def test_fallback_not_triggered_when_confidence_is_high(monkeypatch):
    """Sanity guard: the fallback must only trigger below the 0.35 threshold
    with matched_intent == UnknownIntent — a confident real match should
    never reach the LLM fallback at all."""
    llm = _mock_llm("SHOULD_NOT_BE_CALLED")
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: llm)
    with patch("agentic_core.router.router", _mock_router(0.9, intent="ConversationalIntent")):
        processor.extract_intent("some genuinely obscure phrasing xyz")
    llm.invoke.assert_not_called()
