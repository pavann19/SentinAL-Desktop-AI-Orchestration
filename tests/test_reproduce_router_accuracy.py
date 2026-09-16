# tests/test_reproduce_router_accuracy.py
# scripts/reproduce_router_accuracy.py is a thin wrapper around the real
# instrument (eval/measure_intent_accuracy.py --mode router-only). These
# tests check the wrapper's own logic (command construction, key-stripping,
# default run-id) with subprocess mocked — they do NOT re-run the real
# (slow, exhaustive) eval; that's verified by hand / eval's own tests.

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
reproduce = importlib.import_module("reproduce_router_accuracy")


def test_default_run_id_is_timestamped(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reproduce_router_accuracy.py"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        reproduce.main()
    cmd = mock_run.call_args[0][0]
    assert "--run-id" in cmd
    run_id = cmd[cmd.index("--run-id") + 1]
    assert run_id.startswith("repro_")


def test_explicit_run_id_used_verbatim(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reproduce_router_accuracy.py", "--run-id", "my-label"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        reproduce.main()
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--run-id") + 1] == "my-label"


def test_mode_is_always_router_only(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reproduce_router_accuracy.py"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        reproduce.main()
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--mode") + 1] == "router-only"


def test_cloud_keys_stripped_from_child_env(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reproduce_router_accuracy.py"])
    monkeypatch.setenv("GROQ_API_KEY", "should-not-reach-child")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "should-not-reach-child")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        reproduce.main()
    child_env = mock_run.call_args.kwargs["env"]
    assert "GROQ_API_KEY" not in child_env
    assert "DEEPGRAM_API_KEY" not in child_env


def test_returns_child_exit_code(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["reproduce_router_accuracy.py"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 3
        assert reproduce.main() == 3


def test_dataset_override_passed_through(monkeypatch):
    monkeypatch.setattr(sys, "argv",
                        ["reproduce_router_accuracy.py", "--dataset", "some/other.json"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        reproduce.main()
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--dataset") + 1] == "some/other.json"
