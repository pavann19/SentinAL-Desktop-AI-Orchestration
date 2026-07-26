"""
tests/test_api_auth.py
Regression tests for REST API authentication.

Context: /api/command executes real OS actions and was previously reachable
with no credentials. CORS did not protect it (CORS is browser-enforced only,
so curl/scripts/other local processes bypassed it entirely), and the server
defaulted to binding 0.0.0.0, publishing it to every network interface.
These tests lock in the fix so it cannot silently regress.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

_TEST_TOKEN = "unit-test-token-do-not-use-in-production"


@pytest.fixture(scope="module")
def client():
    """TestClient with a known token, so tests never depend on a generated one."""
    os.environ["SENTINAL_API_TOKEN"] = _TEST_TOKEN
    from fastapi.testclient import TestClient
    import main
    # Re-resolve in case another test module imported main first with no token set.
    main.API_TOKEN = _TEST_TOKEN
    return TestClient(main.app)


def _auth(token=_TEST_TOKEN):
    return {"Authorization": f"Bearer {token}"}


class TestHealthIsPublic:
    """Health checks must stay unauthenticated for supervisors/container probes."""

    @pytest.mark.parametrize("path", ["/", "/health", "/api/health"])
    def test_health_endpoints_need_no_token(self, client, path):
        assert client.get(path).status_code == 200


class TestCommandEndpointRequiresAuth:
    """The command endpoint executes real OS actions — it must never be open."""

    def test_no_token_rejected(self, client):
        r = client.post("/api/command", json={"prompt": "hello"})
        assert r.status_code == 401

    def test_wrong_token_rejected(self, client):
        r = client.post("/api/command", json={"prompt": "hello"}, headers=_auth("wrong-token"))
        assert r.status_code == 401

    def test_malformed_authorization_header_rejected(self, client):
        r = client.post("/api/command", json={"prompt": "hello"},
                        headers={"Authorization": _TEST_TOKEN})  # missing "Bearer "
        assert r.status_code == 401

    def test_empty_bearer_rejected(self, client):
        r = client.post("/api/command", json={"prompt": "hello"},
                        headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_wrong_scheme_rejected(self, client):
        r = client.post("/api/command", json={"prompt": "hello"},
                        headers={"Authorization": f"Basic {_TEST_TOKEN}"})
        assert r.status_code == 401


class TestLogsEndpointRequiresAuth:
    """Diagnostic logs may contain user prompts — not public."""

    def test_no_token_rejected(self, client):
        assert client.get("/api/logs").status_code == 401

    def test_valid_token_accepted(self, client):
        assert client.get("/api/logs", headers=_auth()).status_code == 200


class TestTokenResolution:
    """Token generation must not silently produce a weak or empty credential."""

    def test_generated_token_is_long_and_random(self):
        import main
        prev = os.environ.pop("SENTINAL_API_TOKEN", None)
        token_file = main._TOKEN_FILE
        backup = None
        try:
            if os.path.exists(token_file):
                with open(token_file, "r", encoding="utf-8") as fh:
                    backup = fh.read()
                os.remove(token_file)
            generated = main._resolve_api_token()
            assert len(generated) >= 32, "generated token is too short to resist guessing"
            second = main._resolve_api_token()
            assert second == generated, "token must persist across calls, not regenerate per request"
        finally:
            if backup is not None:
                with open(token_file, "w", encoding="utf-8") as fh:
                    fh.write(backup)
            elif os.path.exists(token_file):
                os.remove(token_file)
            if prev is not None:
                os.environ["SENTINAL_API_TOKEN"] = prev

    def test_env_token_takes_precedence(self):
        import main
        os.environ["SENTINAL_API_TOKEN"] = "explicit-env-token"
        try:
            assert main._resolve_api_token() == "explicit-env-token"
        finally:
            os.environ["SENTINAL_API_TOKEN"] = _TEST_TOKEN
