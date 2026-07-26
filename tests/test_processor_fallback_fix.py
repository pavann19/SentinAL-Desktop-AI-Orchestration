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

import pytest

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
    """Sanity guard: the fallback must only trigger when matched_intent is
    UnknownIntent — a confident real match should never reach the LLM
    fallback at all, regardless of its confidence value."""
    llm = _mock_llm("SHOULD_NOT_BE_CALLED")
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: llm)
    with patch("agentic_core.router.router", _mock_router(0.9, intent="ConversationalIntent")):
        processor.extract_intent("some genuinely obscure phrasing xyz")
    llm.invoke.assert_not_called()


# ── Dead-zone fix (0.35 <= confidence < 0.40, matched_intent == UnknownIntent) ──
# Regression suite for the fix documented in processor.py's "Fix [dead-zone]"
# comment. Measured impact before this fix: 54/704 (7.7%) of
# eval/intent_dataset.json fell in this band and failed permanently with zero
# recovery attempt, because the old condition required BOTH confidence < 0.35
# AND matched_intent == "UnknownIntent" — a redundant, harmful extra gate,
# since router.py's own logic already guarantees matched_intent can only be
# "UnknownIntent" when confidence < 0.40 in the first place.

def test_fallback_now_triggers_in_the_former_dead_zone(monkeypatch):
    """The specific band (0.35 <= confidence < 0.40) that used to be silently
    dropped must now reach the LLM fallback."""
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: _mock_llm(
        '[{"intent": "InformationRetrievalIntent"}]'
    ))
    with patch("agentic_core.router.router", _mock_router(0.3767, intent="UnknownIntent")):
        steps = processor.extract_intent("create a new react app please")
    assert steps[0]["intent"] == "InformationRetrievalIntent"


@pytest.mark.parametrize("confidence", [0.0, 0.1, 0.34, 0.35, 0.3767, 0.399, 0.3999])
def test_fallback_triggers_across_the_entire_unknown_confidence_range(monkeypatch, confidence):
    """Every confidence value that router.py can legitimately pair with
    matched_intent='UnknownIntent' (i.e. anything in [0.0, 0.40)) must reach
    the fallback — not just the old sub-0.35 slice."""
    llm = _mock_llm('[{"intent": "ConversationalIntent"}]')
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: llm)
    with patch("agentic_core.router.router", _mock_router(confidence, intent="UnknownIntent")):
        processor.extract_intent("some genuinely obscure phrasing xyz")
    llm.invoke.assert_called_once()


def test_fallback_still_not_triggered_for_confident_non_unknown_match_near_boundary(monkeypatch):
    """Defensive guard: even a real (non-UnknownIntent) match sitting exactly
    at the 0.40 boundary must not trigger the FALLBACK-CATEGORIZATION prompt
    — only the intent label matters, not the confidence value, per the fix.

    NOTE: a matched (non-Unknown) intent like WebNavigationIntent still makes
    ITS OWN, separate LLM call downstream for target/parameter extraction —
    that is correct, expected, unrelated behavior. This test asserts the
    fallback's specific categorization prompt text was never sent, not that
    zero LLM calls happened overall."""
    llm = _mock_llm('{"target": "SHOULD_NOT_BE_CALLED"}')
    monkeypatch.setattr(processor, "_get_routing_llm", lambda *a, **k: llm)
    with patch("agentic_core.router.router", _mock_router(0.40, intent="WebNavigationIntent")):
        processor.extract_intent("some genuinely obscure phrasing xyz")
    for call in llm.invoke.call_args_list:
        sent_text = str(call)
        assert "Categorize this short command" not in sent_text, (
            "the fallback-categorization prompt must not fire for a confident, "
            "non-UnknownIntent match"
        )
