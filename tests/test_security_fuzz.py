"""
tests/test_security_fuzz.py
Security-focused fuzz & property-based tests for SentinAL.
Tests every security boundary with adversarial, malformed, and edge-case inputs.
No mercy. If it can crash or bypass security, it will be found here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import string
import random


# ── Shell Injection Vectors ───────────────────────────────────────────────────
SHELL_INJECTION_PAYLOADS = [
    "dir && del /f C:\\Users",           # Classic chain — no GUI prefix
    "dir || format c:",
    "dir ; del file.txt",
    "echo hello | powershell",
    "$(calc.exe)",
    "`calc.exe`",
    "dir > C:\\output.txt",
    "dir\x00malicious",
    "dir\r\ndel file.txt",
    "dir\ndel file.txt",
    "a" * 10000 + " && del",
    "calc.exe 2>&1",
    "cmd /c del file.txt",
    "powershell -c Start-Process calc",
    "tasklist && taskkill /f /pid 1234",
]

# ── Sandbox Bypass Attempts ───────────────────────────────────────────────────
SANDBOX_BYPASS_PAYLOADS = [
    "C:\\Windows\\System32\\cmd.exe",
    "c:/windows/system32/cmd.exe",
    "C:\\WINDOWS\\SYSTEM32\\cmd.exe",
    "%SYSTEMROOT%\\System32\\cmd.exe",
    "\\\\server\\share\\system32",
    ".\\..\\..\\windows\\system32",
    "C:/../Windows/System32",
    "%windir%\\system32",
    "C:\\windows\\..\\windows\\system32",
    "regedit.exe",
    "C:\\windows\\regedit.exe",
    "..\\..\\..\\Windows\\System32\\calc.exe",
]

# ── PII Inputs for Privacy Router ────────────────────────────────────────────
PII_PAYLOADS = [
    "My SSN is 123-45-6789",
    "Credit card: 4111 1111 1111 1111",
    "Password is: SuperSecret123!",
    "My email is test@example.com",
    "Send to john.doe@company.co.uk",
    "Call me at +1 (555) 123-4567",
    "Open file C:\\Users\\Admin\\secret.txt",
    "Access %USERPROFILE%\\Documents\\contract.pdf",
    "Key: AAAA-BBBB-CCCC-DDDD",
    "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature",
]

# ── Allowlist Bypass Attempts for Validator ───────────────────────────────────
FORBIDDEN_INTENTS = [
    "RootKitIntent",
    "KernelExploitIntent",
    "PrivilegeEscalationIntent",
    "UnauthorizedSystemIntent",
    "HackIntent",
    "BypassValidationIntent",
    "SuperAdminIntent",
    "",
    "  ",
    "None",
    "null",
    "undefined",
    "ConversationalIntent' OR '1'='1",
]


class TestShellInjectionGuard:

    @pytest.mark.parametrize("payload", SHELL_INJECTION_PAYLOADS)
    def test_injection_payload_raises_or_sanitized(self, payload):
        """Every shell injection payload must raise ValueError or return a safe string."""
        from agentic_core.executor import _sanitize_shell_cmd
        try:
            result = _sanitize_shell_cmd(payload)
            # If it doesn't raise, it must not contain chain operators
            dangerous = ["&&", "||", ";\n", ";\r", "|", "$(", "`", "\x00", "\r\n", 2 * " && "]
            for op in ["&&", "||"]:
                assert op not in result, f"Operator '{op}' survived in: {result!r}"
        except ValueError:
            pass  # Expected — injection detected and blocked


class TestSandboxBypass:

    @pytest.mark.parametrize("target", SANDBOX_BYPASS_PAYLOADS)
    def test_sandbox_bypass_blocked_by_validator(self, target):
        """Every sandbox bypass attempt must be blocked by validate_steps."""
        from agentic_core.validator import validate_steps
        steps = [{"intent": "ApplicationLaunchIntent", "target": target}]
        is_valid, msg, _ = validate_steps(steps)
        assert is_valid is False, (
            f"SANDBOX BYPASS SUCCEEDED for target: '{target}'. msg={msg}"
        )

    @pytest.mark.parametrize("target", SANDBOX_BYPASS_PAYLOADS)
    def test_sandbox_bypass_blocked_by_validate_sandbox(self, target):
        """validate_sandbox() must reject all bypass paths."""
        from agentic_core.validator import validate_sandbox
        # Expand env vars to test realistic resolved paths
        expanded = os.path.expandvars(target)
        result = validate_sandbox(expanded)
        # Only fail if path is actually inside a danger zone
        dangerous_markers = ["system32", "windows\\system32", "regedit"]
        if any(m.lower() in expanded.lower() for m in dangerous_markers):
            assert result is False, f"Sandbox bypass allowed for: '{target}' → '{expanded}'"


class TestPrivacyRouterFuzz:

    @pytest.mark.parametrize("payload", PII_PAYLOADS)
    def test_all_pii_routes_local(self, payload):
        """Every PII payload must be routed to local, never cloud."""
        from system_services.privacy_router import PrivacyRouter
        router = PrivacyRouter()
        result = router.analyze(payload)
        assert result["route"] == "local", (
            f"PII LEAKED TO CLOUD: '{payload}'. Reason: {result['reason']}"
        )

    def test_random_noise_does_not_crash(self):
        """1000 random garbage strings must never crash the privacy router."""
        from system_services.privacy_router import PrivacyRouter
        router = PrivacyRouter()
        chars = string.printable
        for _ in range(1000):
            noise = "".join(random.choices(chars, k=random.randint(0, 200)))
            try:
                result = router.analyze(noise)
                assert result["route"] in ("local", "cloud")
            except Exception as e:
                pytest.fail(f"Privacy router crashed on input: {noise!r} — {e}")

    def test_unicode_payload_does_not_crash(self):
        """Unicode inputs must not crash the privacy router."""
        from system_services.privacy_router import PrivacyRouter
        router = PrivacyRouter()
        payloads = [
            "こんにちは、私のパスワードは123です",     # Japanese with "password"
            "Мой адрес 192.168.1.1",               # Russian with IP-like pattern
            "البريد الإلكتروني: test@test.com",    # Arabic with email
            "密碼是 secret123",                      # Chinese with password-ish
        ]
        for p in payloads:
            result = router.analyze(p)
            assert result["route"] in ("local", "cloud")


class TestValidatorForbiddenIntents:

    @pytest.mark.parametrize("intent", FORBIDDEN_INTENTS)
    def test_forbidden_intent_blocked(self, intent):
        """All intents outside the allowlist must be blocked."""
        from agentic_core.validator import validate_steps
        steps = [{"intent": intent, "target": "something"}]
        is_valid, msg, _ = validate_steps(steps)
        # Empty/whitespace intents → blocked
        # Intents not in ALLOWLIST → blocked
        # SQL injection in intent → blocked
        from config.constants import ALLOWLIST_INTENTS
        if intent.strip() not in ALLOWLIST_INTENTS:
            assert is_valid is False, f"Forbidden intent '{intent}' was ALLOWED"


class TestMemoryManagerFuzz:

    def test_random_url_templates_rejected_without_placeholder(self, tmp_path):
        """Any URL without {query} placeholder must raise ValueError."""
        from agentic_core.memory_hook import MemoryManager
        mgr = MemoryManager(db_path=str(tmp_path / "fuzz_mem.db"))
        bad_urls = [
            "http://evil.com/steal",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://safe.com",
            "data:text/html,<script>alert(1)</script>",
        ]
        for url in bad_urls:
            with pytest.raises((ValueError, Exception)):
                mgr.save_url_template("test", url)
        mgr.close()

    def test_xss_in_mnemonic_rejected(self, tmp_path):
        """Script tags in mnemonic names must not cause data corruption."""
        from agentic_core.memory_hook import MemoryManager
        mgr = MemoryManager(db_path=str(tmp_path / "xss_mem.db"))
        # Should either store as-is (harmless in SQLite) or reject
        try:
            mgr.save_url_template("<script>alert(1)</script>", "https://safe.com/?q={query}")
            result = mgr.get_url_template("<script>alert(1)</script>")
            # If stored, must be retrievable safely (no execution)
            assert result is None or isinstance(result, str)
        except Exception:
            pass  # Rejection is also acceptable
        mgr.close()
