"""
tests/test_rate_limit.py
Regression tests for per-endpoint rate limiting.

Context: bearer-token auth (tests/test_api_auth.py) stops unauthenticated
abuse of /api/command, but a valid token alone doesn't protect against a
runaway client loop, a buggy retry, or a script hammering the endpoint -
each call can trigger a real OS action and/or a real LLM request. These
tests lock in that a client (even an authenticated one) is capped.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

_TEST_TOKEN = "unit-test-token-do-not-use-in-production"


@pytest.fixture(scope="module")
def client():
    """Module-scoped: main.py's imports (sentence-transformers, router init,
    etc.) are expensive, so we load it once, not per test."""
    os.environ["SENTINAL_API_TOKEN"] = _TEST_TOKEN
    import main
    main.API_TOKEN = _TEST_TOKEN
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state():
    """slowapi's in-memory storage persists across requests within a process
    and is keyed by client IP - without a reset, later tests would inherit
    an already-exhausted count from earlier ones (TestClient always uses the
    same source IP). Reset before every test instead of reloading the whole
    (expensive) main module."""
    import main
    main.limiter.reset()
    yield


def _auth():
    return {"Authorization": f"Bearer {_TEST_TOKEN}"}


class TestCommandEndpointRateLimit:
    """/api/command is capped at 30/minute — the highest-cost endpoint
    (real OS actions, potential LLM calls)."""

    def test_requests_within_limit_all_succeed(self, client):
        for _ in range(30):
            r = client.post("/api/command", json={"prompt": "hello"}, headers=_auth())
            assert r.status_code != 429

    def test_request_beyond_limit_returns_429(self, client):
        for _ in range(30):
            client.post("/api/command", json={"prompt": "hello"}, headers=_auth())
        r = client.post("/api/command", json={"prompt": "hello"}, headers=_auth())
        assert r.status_code == 429


class TestLogsEndpointRateLimit:
    """/api/logs is capped at 60/minute - lighter limit, it's read-only
    diagnostics rather than an action-triggering endpoint."""

    def test_requests_within_limit_all_succeed(self, client):
        for _ in range(60):
            r = client.get("/api/logs", headers=_auth())
            assert r.status_code == 200

    def test_request_beyond_limit_returns_429(self, client):
        for _ in range(60):
            client.get("/api/logs", headers=_auth())
        r = client.get("/api/logs", headers=_auth())
        assert r.status_code == 429


class TestHealthEndpointIsNeverRateLimited:
    """Health checks must stay usable for process supervisors / container
    probes regardless of how much traffic the rate-limited endpoints see."""

    def test_health_survives_command_endpoint_being_rate_limited(self, client):
        for _ in range(35):
            client.post("/api/command", json={"prompt": "hello"}, headers=_auth())
        r = client.get("/api/health")
        assert r.status_code == 200
