"""
tests/test_validator_coverage.py

Coverage for the uncovered branches in agentic_core/validator.py — the actual
security boundary (intent allowlist, filesystem sandbox, keyword/command
filtering, HITL flagging).

tests/test_validator.py already covers the happy paths and the headline blocks.
This file targets the branches it does not reach, several of which are the
*asymmetric* ones — where the same keyword is blocked for one intent and
deliberately allowed for another. Those asymmetries are policy decisions, and
an untested policy decision is indistinguishable from a bug.

All tests assert against the real constants in config/constants.py rather than
hardcoded strings, so a future edit to the policy lists cannot silently make
these tests vacuous.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.validator import validate_sandbox, validate_steps
from config.constants import (
    SENSITIVE_CMD_WORDS,
    SENSITIVE_TARGETS,
    SOFT_SENSITIVE_TARGETS,
)


# ══════════════════════════════════════════════════════════════════════════════
# validate_sandbox — the SENSITIVE / SOFT_SENSITIVE pattern branches
# ══════════════════════════════════════════════════════════════════════════════
class TestSandboxSensitivePatterns:
    @pytest.mark.parametrize("pattern", sorted(SENSITIVE_TARGETS))
    def test_every_sensitive_target_is_blocked(self, pattern):
        """Parametrised over the real list: if someone adds a pattern to
        SENSITIVE_TARGETS, it is automatically covered here."""
        assert validate_sandbox(f"C:\\Users\\test\\{pattern.strip()}") is False

    @pytest.mark.parametrize("pattern", sorted(SOFT_SENSITIVE_TARGETS))
    def test_every_soft_sensitive_target_is_blocked_by_the_sandbox(self, pattern):
        """validate_sandbox() blocks soft-sensitive patterns unconditionally —
        unlike validate_steps(), which blocks them only for execution intents.
        The two functions apply the same list with deliberately different
        strictness; this pins the sandbox's stricter half."""
        assert validate_sandbox(f"C:\\Users\\test\\{pattern.strip()}") is False

    def test_internal_exception_fails_closed(self, monkeypatch):
        """The except branch must return False (deny), never True. A sandbox
        that fails OPEN on an internal error is worse than no sandbox, because
        it looks like it is protecting something."""
        import agentic_core.validator as v
        monkeypatch.setattr(v.os.path, "realpath", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        assert validate_sandbox("C:\\Users\\test\\file.txt") is False


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — intent aliasing
# ══════════════════════════════════════════════════════════════════════════════
class TestIntentAliasing:
    @pytest.mark.parametrize(("alias", "canonical"), [
        ("open_application", "ApplicationLaunchIntent"),
        ("launch_app", "ApplicationLaunchIntent"),
        ("open_app", "ApplicationLaunchIntent"),
        ("search_web", "InformationRetrievalIntent"),
        ("web_search", "InformationRetrievalIntent"),
        ("get_info", "InformationRetrievalIntent"),
        ("navigate_to", "WebNavigationIntent"),
        ("open_url", "WebNavigationIntent"),
        ("stream_media", "MediaStreamingIntent"),
        ("play_media", "MediaStreamingIntent"),
    ])
    def test_alias_is_rewritten_in_place_and_approved(self, alias, canonical):
        """Aliasing mutates the step dict in place — later pipeline stages read
        step['intent'], so a rewrite that only affected a local variable would
        approve the step here and then dispatch an unrecognised intent later."""
        step = {"intent": alias, "target": "notepad"}
        approved, reason, _ = validate_steps([step])
        assert approved is True, reason
        assert step["intent"] == canonical

    def test_unaliased_unknown_intent_is_still_rejected(self):
        approved, reason, _ = validate_steps([{"intent": "TotallyMadeUpIntent", "target": "x"}])
        assert approved is False
        assert "forbidden" in reason


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — the soft-target and soft-sensitive asymmetries
# ══════════════════════════════════════════════════════════════════════════════
class TestSoftTargetIntents:
    @pytest.mark.parametrize("intent", ["MediaStreamingIntent", "InformationRetrievalIntent"])
    def test_soft_target_intents_are_allowed_without_a_target(self, intent):
        """Deliberately permissive: the processor falls back to the raw prompt
        when extraction returns empty, so blocking here would break a path that
        actually recovers. Contrast with TARGET_REQUIRED intents below."""
        approved, reason, _ = validate_steps([{"intent": intent, "target": ""}])
        assert approved is True, reason

    @pytest.mark.parametrize("intent", [
        "ApplicationLaunchIntent", "WebNavigationIntent", "FileDeletionIntent",
    ])
    def test_hard_target_intents_are_rejected_without_a_target(self, intent):
        approved, reason, _ = validate_steps([{"intent": intent, "target": ""}])
        assert approved is False
        assert "requires a target" in reason


class TestHardSensitiveKeywordBlock:
    """SENSITIVE_TARGETS are a HARD block — rejected for every intent, with no
    read-only exemption. Contrast with the soft list below, which is
    intent-dependent. Getting these two backwards would either block
    legitimate queries or permit destructive ones."""

    @pytest.mark.parametrize("keyword", sorted(SENSITIVE_TARGETS))
    def test_hard_keyword_is_blocked_even_for_read_only_intents(self, keyword):
        """NOTE: the keyword is used VERBATIM, not .strip()ed. Some patterns
        carry significant whitespace — "format " has a deliberate trailing
        space so it matches the dangerous `format c:` while NOT blocking the
        ordinary English word ("what format is this file"). Stripping the
        pattern in a test silently destroys that distinction and makes the
        test assert something the validator never promised."""
        approved, reason, _ = validate_steps([
            {"intent": "InformationRetrievalIntent", "target": f"tell me about {keyword} now"}
        ])
        assert approved is False
        assert "Strict policy" in reason

    @pytest.mark.parametrize("benign_query", [
        "what file format is this",
        "how do i format my resume",
        "convert the format of this file",
        "what format should i use",
    ])
    def test_KNOWN_FALSE_POSITIVE_format_blocks_ordinary_english(self, benign_query):
        """DOCUMENTS A REAL FALSE POSITIVE — pinned as current behaviour, NOT
        endorsed as correct. Flagged for review rather than silently changed,
        because SENSITIVE_TARGETS is security policy.

        "format " (trailing space) is presumably intended to catch the
        destructive `format c:` while sparing the ordinary English word. It
        does not: in any sentence, "format" is followed by a space anyway, so
        every query below is hard-blocked as a security violation:

            "what file format is this"      -> BLOCKED
            "how do i format my resume"     -> BLOCKED
            "convert the format of this"    -> BLOCKED

        Only a trailing-position "format" (e.g. "the audio format") survives.
        A precise fix would need a regex anchored on the actual dangerous
        shape - roughly `\\bformat\\s+[a-z]:` (format + drive letter) - rather
        than a substring match, but choosing that pattern is a security
        decision with a real cost if it is drawn too loosely, so it is left to
        an explicit review rather than made here.

        If these tests start FAILING, the policy was tightened correctly and
        this whole class should be deleted."""
        approved, reason, _ = validate_steps([
            {"intent": "InformationRetrievalIntent", "target": benign_query}
        ])
        assert approved is False, "false positive resolved — remove this test class"
        assert "Strict policy" in reason

    def test_the_genuinely_dangerous_format_command_is_blocked(self):
        """The case the pattern actually exists for — must keep working
        regardless of how the false positive above is eventually resolved."""
        approved, _, _ = validate_steps([
            {"intent": "GeneralizedOSIntent", "target": "", "actions": [
                {"type": "shell", "payload": "format c:"}
            ]}
        ])
        assert approved is False


class TestFileDeletionSandboxCheck:
    def test_deletion_of_a_protected_path_is_blocked_by_the_sandbox(self):
        """FileDeletionIntent gets an extra validate_sandbox() pass on its
        target — the last line of defence before shutil.rmtree runs."""
        approved, reason, _ = validate_steps([
            {"intent": "FileDeletionIntent", "target": "C:\\"}
        ])
        assert approved is False
        assert "Sandbox violation" in reason

    def test_deletion_of_an_ordinary_user_path_is_permitted(self):
        approved, reason, requires_confirmation = validate_steps([
            {"intent": "FileDeletionIntent", "target": "C:\\Users\\test\\Documents\\notes.txt"}
        ])
        assert approved is True, reason
        assert requires_confirmation is True


class TestSoftSensitiveAsymmetry:
    """SOFT_SENSITIVE_TARGETS are blocked for execution intents but only
    logged for read-only ones. This asymmetry is the single most subtle policy
    decision in the validator, and was previously untested in both directions."""

    @pytest.mark.parametrize("intent", [
        "ApplicationLaunchIntent", "FileDeletionIntent", "GeneralizedOSIntent",
    ])
    def test_execution_intents_are_blocked_on_soft_sensitive_keywords(self, intent):
        approved, reason, _ = validate_steps([{"intent": intent, "target": "c:\\windows\\notepad.exe"}])
        assert approved is False
        assert "unsafe" in reason.lower()

    @pytest.mark.parametrize("intent", ["InformationRetrievalIntent", "WebNavigationIntent"])
    def test_read_only_intents_are_allowed_to_mention_soft_sensitive_keywords(self, intent):
        """Asking *about* the registry is not the same as executing regedit.
        If this starts failing, the validator has become over-strict and will
        block legitimate informational queries."""
        approved, reason, _ = validate_steps([{"intent": intent, "target": "what is the windows registry"}])
        assert approved is True, reason


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — dangerous command words (word-boundary matching)
# ══════════════════════════════════════════════════════════════════════════════
class TestDangerousCommandWords:
    @pytest.mark.parametrize("cmd_word", sorted(SENSITIVE_CMD_WORDS))
    def test_dangerous_command_word_in_target_is_blocked(self, cmd_word):
        approved, reason, _ = validate_steps([
            {"intent": "InformationRetrievalIntent", "target": f"{cmd_word} something"}
        ])
        assert approved is False
        assert "Dangerous command" in reason

    @pytest.mark.parametrize(("benign", "contains"), [
        ("model results", "del"),
        ("rdp connection guide", "rd"),
        ("warm weather", "rm"),
    ])
    def test_word_boundary_prevents_substring_false_positives(self, benign, contains):
        """The whole point of the \\b regex: 'model' contains 'del' but is not
        a delete command. A substring match here would block ordinary queries."""
        assert contains in benign  # sanity: the substring really is present
        approved, reason, _ = validate_steps([
            {"intent": "InformationRetrievalIntent", "target": benign}
        ])
        assert approved is True, f"{benign!r} wrongly blocked: {reason}"


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — GeneralizedOSIntent shell action scanning
# ══════════════════════════════════════════════════════════════════════════════
def _os_step(actions):
    return [{"intent": "GeneralizedOSIntent", "target": "", "actions": actions}]


class TestShellActionScanning:
    def test_sensitive_keyword_inside_a_shell_payload_is_blocked(self):
        approved, reason, _ = validate_steps(_os_step([
            {"type": "shell", "payload": "shutdown /s /t 0"}
        ]))
        assert approved is False
        assert "Keyword" in reason

    @pytest.mark.parametrize("cmd_word", sorted(SENSITIVE_CMD_WORDS))
    def test_dangerous_command_word_inside_a_shell_payload_is_blocked(self, cmd_word):
        approved, _reason, _ = validate_steps(_os_step([
            {"type": "shell", "payload": f"{cmd_word} C:\\Users\\test\\notes.txt"}
        ]))
        assert approved is False

    def test_sandbox_violation_via_env_var_path_in_shell_payload_is_blocked(self):
        """Fix 1.6's stated purpose: catch %VAR%\\path even unquoted. Uses an
        env-var path that expands into a protected location."""
        approved, _reason, _ = validate_steps(_os_step([
            {"type": "shell", "payload": "type %SYSTEMROOT%\\system32\\config\\sam"}
        ]))
        assert approved is False

    def test_benign_shell_payload_is_approved(self):
        approved, reason, _ = validate_steps(_os_step([
            {"type": "shell", "payload": "echo hello"}
        ]))
        assert approved is True, reason

    def test_action_with_no_actions_array_is_approved_not_crashed(self):
        """An empty actions list is the executor's error to report, not the
        validator's — it must not raise here."""
        approved, _, _ = validate_steps([
            {"intent": "GeneralizedOSIntent", "target": "", "actions": []}
        ])
        assert approved is True


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — HITL confirmation flag
# ══════════════════════════════════════════════════════════════════════════════
class TestConfirmationFlag:
    def test_confirmation_survives_across_a_multi_step_plan(self):
        """The flag is accumulated across all steps. If a later benign step
        reset it, a destructive step could execute without confirmation."""
        approved, _, requires_confirmation = validate_steps([
            {"intent": "FileDeletionIntent", "target": "C:\\Users\\test\\old.txt"},
            {"intent": "ApplicationLaunchIntent", "target": "notepad"},
        ])
        assert approved is True
        assert requires_confirmation is True

    def test_no_confirmation_for_a_plan_with_no_destructive_step(self):
        _, _, requires_confirmation = validate_steps([
            {"intent": "ApplicationLaunchIntent", "target": "notepad"},
        ])
        assert requires_confirmation is False


# ══════════════════════════════════════════════════════════════════════════════
# validate_steps — malformed input must fail closed
# ══════════════════════════════════════════════════════════════════════════════
class TestMalformedInput:
    @pytest.mark.parametrize("bad", [None, "not a list", 42, {}])
    def test_non_list_input_is_rejected(self, bad):
        approved, _reason, confirm = validate_steps(bad)
        assert approved is False
        assert confirm is False
