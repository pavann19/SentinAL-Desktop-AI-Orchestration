"""
tests/test_confirmation.py

Unit tests for agentic_core/confirmation.py — the direct-human confirm channel
(P2-5 enforcement, autonomous=False half).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.confirmation import (
    PendingConfirmations,
    _request_fingerprint,
    summarize,
)


@pytest.fixture()
def store():
    return PendingConfirmations()


_DELETE_A = [{"intent": "FileDeletionIntent", "target": r"C:\a.txt"}]
_DELETE_B = [{"intent": "FileDeletionIntent", "target": r"C:\b.txt"}]


class TestTokenLifecycle:

    def test_a_freshly_issued_token_confirms_the_same_request(self, store):
        tok = store.issue("delete a", _DELETE_A, "T3")
        assert store.check_and_consume("delete a", _DELETE_A, tok) is True

    def test_a_token_is_single_use(self, store):
        tok = store.issue("delete a", _DELETE_A, "T3")
        assert store.check_and_consume("delete a", _DELETE_A, tok) is True
        assert store.check_and_consume("delete a", _DELETE_A, tok) is False

    def test_none_or_unknown_token_is_rejected(self, store):
        assert store.check_and_consume("delete a", _DELETE_A, None) is False
        assert store.check_and_consume("delete a", _DELETE_A, "not-a-real-token") is False

    def test_expired_token_is_rejected_and_purged(self, store, monkeypatch):
        import agentic_core.confirmation as cm
        clock = {"t": 1000.0}
        monkeypatch.setattr(cm.time, "time", lambda: clock["t"])
        tok = store.issue("delete a", _DELETE_A, "T3")
        clock["t"] = 1000.0 + cm.CONFIRM_TTL_SECONDS + 1
        assert store.check_and_consume("delete a", _DELETE_A, tok) is False
        assert store.pending_count() == 0


class TestTokenBinding:

    def test_a_token_for_one_prompt_does_not_confirm_a_different_prompt(self, store):
        tok = store.issue("delete a", _DELETE_A, "T3")
        assert store.check_and_consume("delete something else entirely", _DELETE_A, tok) is False

    def test_a_token_for_one_plan_does_not_confirm_a_different_plan(self, store):
        # Same prompt text, different resolved target — the classic "reuse the
        # phrasing to smuggle a different action past the confirm" attack.
        tok = store.issue("delete the file", _DELETE_A, "T3")
        assert store.check_and_consume("delete the file", _DELETE_B, tok) is False

    def test_fingerprint_is_stable_across_key_order(self):
        a = [{"intent": "X", "target": "t", "action": None, "actions": None}]
        b = [{"target": "t", "actions": None, "intent": "X", "action": None}]
        assert _request_fingerprint("p", a) == _request_fingerprint("p", b)


class TestSummarize:

    def test_summary_names_the_intent_target_and_tier(self):
        s = summarize(_DELETE_A, "T3", "irreversible action")
        assert "T3" in s
        assert "FileDeletionIntent" in s
        assert r"C:\a.txt" in s
        assert "confirm token" in s.lower()

    def test_summary_handles_a_targetless_step(self):
        s = summarize([{"intent": "SysUtilityIntent"}], "T2", "real system write")
        assert "SysUtilityIntent" in s
        assert "T2" in s
