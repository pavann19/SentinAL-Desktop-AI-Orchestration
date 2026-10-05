"""HUD measurements must not imply an availability SLA or security clearance."""
from types import SimpleNamespace

import main


def test_telemetry_reports_seconds_and_no_invented_security_fields(monkeypatch):
    monkeypatch.setattr(main, "SERVER_START_TIME", 100)
    monkeypatch.setattr(main.time, "time", lambda: 160)
    monkeypatch.setattr(main, "task_manager", SimpleNamespace(current_task_id=None))
    result = main.build_system_telemetry({"cpu_percent": 5, "ram_percent": 30})
    assert result["uptime_seconds"] == 60
    assert result["resource_load"] == "NORMAL"
    assert result["ai_core_status"] == "IDLE"
    assert result["build_version"] == "9.0.0-prototype"
    assert "uptime_percent" not in result
    assert "threat_level" not in result
    assert main.SYSTEM_CONFIG["clearance"] == "LOCAL USER"


def test_resource_load_and_execution_status_are_independent(monkeypatch):
    monkeypatch.setattr(main, "task_manager", SimpleNamespace(current_task_id="task"))
    result = main.build_system_telemetry({"cpu_percent": 2, "ram_percent": 99})
    assert result["resource_load"] == "CRITICAL"
    assert result["ai_core_status"] == "EXECUTING"
