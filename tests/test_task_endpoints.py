# tests/test_task_endpoints.py
# REST surface for background-task monitoring: GET /api/tasks and
# GET /api/tasks/{watch_id}. Same auth/rate-limit contract as every other
# authenticated route in main.py (see test_api_auth.py).

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

_TEST_TOKEN = "unit-test-token-do-not-use-in-production"


@pytest.fixture(scope="module")
def client():
    os.environ["SENTINAL_API_TOKEN"] = _TEST_TOKEN
    from fastapi.testclient import TestClient
    import main
    main.API_TOKEN = _TEST_TOKEN
    return TestClient(main.app)


def _auth(token=_TEST_TOKEN):
    return {"Authorization": f"Bearer {token}"}


class TestAuthRequired:
    def test_list_requires_token(self, client):
        assert client.get("/api/tasks").status_code == 401

    def test_get_one_requires_token(self, client):
        assert client.get("/api/tasks/some-id").status_code == 401

    def test_wrong_token_rejected(self, client):
        assert client.get("/api/tasks", headers=_auth("wrong")).status_code == 401


class TestListTasks:
    def test_returns_whatever_the_registry_has(self, client):
        rows = [
            {"watch_id": "a", "label": "npm install", "status": "pending"},
            {"watch_id": "b", "label": "codeact", "status": "completed"},
        ]
        with patch("agentic_core.process_supervisor.list_tasks", return_value=rows):
            r = client.get("/api/tasks", headers=_auth())
        assert r.status_code == 200
        assert r.json() == rows

    def test_empty_registry_returns_empty_list(self, client):
        with patch("agentic_core.process_supervisor.list_tasks", return_value=[]):
            r = client.get("/api/tasks", headers=_auth())
        assert r.status_code == 200
        assert r.json() == []


class TestGetOneTask:
    def test_known_id_returns_its_record(self, client):
        row = {"watch_id": "abc123", "label": "dependency_install", "status": "pending"}
        with patch("agentic_core.process_supervisor.get_task_status", return_value=row):
            r = client.get("/api/tasks/abc123", headers=_auth())
        assert r.status_code == 200
        assert r.json() == row

    def test_unknown_id_returns_404(self, client):
        with patch("agentic_core.process_supervisor.get_task_status", return_value=None):
            r = client.get("/api/tasks/does-not-exist", headers=_auth())
        assert r.status_code == 404
