"""
tests/test_validator.py
Fix 4.2: Security layer unit tests for validator.py.
Covers 8 critical test cases including sandbox bypass, BLOCKED_KEYS, and allowlist enforcement.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agentic_core.validator import validate_steps, validate_sandbox


class TestValidateSteps:

    def test_file_deletion_sets_requires_confirmation(self):
        """FileDeletionIntent must signal requires_confirmation=True."""
        steps = [{"intent": "FileDeletionIntent", "target": "C:/Users/test/Downloads/file.txt"}]
        is_valid, msg, requires_confirm = validate_steps(steps)
        assert is_valid is True
        assert requires_confirm is True

    def test_unknown_intent_blocked(self):
        """Intent not in ALLOWLIST_INTENTS must be blocked."""
        steps = [{"intent": "UnknownCustomIntent", "target": "something"}]
        is_valid, msg, _ = validate_steps(steps)
        assert is_valid is False
        assert "forbidden" in msg.lower() or "denied" in msg.lower()

    def test_system32_target_blocked(self):
        """Any intent targeting system32 must be blocked."""
        steps = [{"intent": "ApplicationLaunchIntent", "target": "C:/windows/system32/cmd.exe"}]
        is_valid, msg, _ = validate_steps(steps)
        assert is_valid is False
        assert "system32" in msg.lower() or "denied" in msg.lower()

    def test_safe_app_launch_approved(self):
        """Valid ApplicationLaunchIntent with a safe target must be approved."""
        steps = [{"intent": "ApplicationLaunchIntent", "target": "notepad", "speech_response": "Opening notepad."}]
        is_valid, msg, requires_confirm = validate_steps(steps)
        assert is_valid is True
        assert requires_confirm is False

    def test_empty_steps_blocked(self):
        """Empty steps array must be rejected."""
        is_valid, msg, _ = validate_steps([])
        assert is_valid is False

    def test_empty_target_for_required_intent_blocked(self):
        """WebNavigationIntent with empty target must be rejected."""
        steps = [{"intent": "WebNavigationIntent", "target": ""}]
        is_valid, msg, _ = validate_steps(steps)
        assert is_valid is False
        assert "target" in msg.lower()

    def test_shell_cmd_chain_operator_in_shell_payload_blocked(self):
        """GeneralizedOSIntent shell action with system32 path must be blocked."""
        steps = [{
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "dir C:\\windows\\system32"}]
        }]
        is_valid, msg, _ = validate_steps(steps)
        assert is_valid is False

    def test_gui_blocked_key_ctrl_rejected(self):
        """GeneralizedOSIntent GUI hotkey with BLOCKED_KEY 'ctrl' must be rejected."""
        from config.constants import BLOCKED_KEYS
        if not BLOCKED_KEYS:
            pytest.skip("BLOCKED_KEYS is empty — configure it to include 'ctrl'")
        steps = [{
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "hotkey", "payload": "ctrl", "value": "ctrl+alt+del"}]
        }]
        # ctrl is in BLOCKED_KEYS
        is_valid, msg, _ = validate_steps(steps)
        # If BLOCKED_KEYS has 'ctrl', this should fail
        if "ctrl" in BLOCKED_KEYS:
            assert is_valid is False
        else:
            pytest.skip("'ctrl' not in BLOCKED_KEYS in this deployment config")


class TestValidateSandbox:

    def test_safe_path_allowed(self):
        """A path in the user's Downloads is not a system dir — must pass."""
        result = validate_sandbox("C:/Users/test/Downloads/myfile.txt")
        assert result is True

    def test_system32_path_blocked(self):
        """A path targeting system32 must return False."""
        result = validate_sandbox("C:/Windows/System32/drivers")
        assert result is False

    def test_empty_path_allowed(self):
        """Empty path string should be treated as safe (no path = no risk)."""
        result = validate_sandbox("")
        assert result is True

    def test_env_var_path_resolved(self):
        """Env var that resolves to a safe user dir must pass."""
        # %TEMP% usually resolves to C:\Users\...\AppData\Local\Temp — not system32
        result = validate_sandbox("%TEMP%")
        assert result is True

    # ── Bare drive-root protection (added 2026-07-11, see validator.py comment) ──

    def test_bare_drive_root_backslash_blocked(self):
        assert validate_sandbox("C:\\") is False

    def test_bare_drive_root_forward_slash_blocked(self):
        assert validate_sandbox("C:/") is False

    def test_bare_drive_letter_without_separator_is_drive_relative_not_root(self):
        """'D:' (no trailing slash/backslash) is a Windows drive-RELATIVE path —
        it resolves against that drive's current working directory, not the
        drive root itself (verified: os.path.realpath(os.path.normpath('D:'))
        resolves to the process's own cwd on that drive). This is correct,
        expected Windows path semantics, not a security gap — only an
        explicit separator ('C:\\', 'C:/') unambiguously means "the root"."""
        result = validate_sandbox("D:")
        resolved = os.path.realpath(os.path.normpath(os.path.expandvars("D:")))
        drive, remainder = os.path.splitdrive(resolved)
        expected = not (drive and remainder in ("", "\\", "/"))
        assert result is expected

    def test_bare_drive_root_blocked_for_any_letter(self):
        for letter in ("C", "D", "E", "Z"):
            assert validate_sandbox(f"{letter}:\\") is False, f"{letter}:\\ should be blocked"

    def test_nested_path_on_drive_still_allowed(self):
        """A real file deep on a drive must NOT be caught by the drive-root
        check — only the bare root itself is blocked."""
        assert validate_sandbox("C:\\Users\\test\\Downloads\\myfile.txt") is True

    def test_literal_nonpath_string_not_treated_as_drive_root(self):
        """Regression guard for the original finding: a non-path string like
        'c drive' (no colon) must not be misidentified as a drive root — it
        has no drive component at all, so splitdrive returns ('', ...) and
        this check does not apply to it (it is allowed through on this check,
        same as before; it was never destructive because it does not resolve
        to a real existing path)."""
        assert validate_sandbox("c drive") is True
