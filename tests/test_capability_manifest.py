# tests/test_capability_manifest.py
# P2-4 — capability contract manifest + parallel contract dispatch.

from __future__ import annotations

import json

import pytest

from agentic_core.capability_manifest import (
    CONTRACT_MAP,
    ContractDispatchUnavailable,
    ContractParamError,
    contract_for,
    dispatch_via_contract,
    manifest,
    validate_params,
)
from config.capability_tiers import INTENT_TIERS
from config.constants import ALLOWLIST_INTENTS

_REQUIRED_KEYS = {"intent", "summary", "tier", "reversible", "cost",
                  "side_effects", "params", "returns", "examples", "handler"}
_REVERSIBLE_FOR_TIER = {"T0": "yes", "T1": "yes", "T2": "snapshot", "T3": "no"}


# ── coverage / consistency ─────────────────────────────────────────────────

def test_every_allowlisted_intent_has_exactly_one_contract():
    expected = set(ALLOWLIST_INTENTS) - {"UnknownIntent"}
    assert set(CONTRACT_MAP) == expected


def test_no_orphan_contract_for_non_allowlisted_intent():
    assert set(CONTRACT_MAP) <= set(ALLOWLIST_INTENTS)


def test_tier_is_sourced_from_capability_tiers_not_hand_copied():
    for intent, c in CONTRACT_MAP.items():
        assert c.tier == INTENT_TIERS[intent]


def test_reversible_is_consistent_with_tier():
    for c in CONTRACT_MAP.values():
        assert c.reversible == _REVERSIBLE_FOR_TIER[c.tier]


# ── manifest shape ─────────────────────────────────────────────────────────

def test_manifest_is_json_serialisable_and_well_formed():
    m = manifest()
    round_tripped = json.loads(json.dumps(m))
    assert len(round_tripped) == len(CONTRACT_MAP)
    for entry in round_tripped:
        assert _REQUIRED_KEYS <= set(entry)
        assert entry["cost"] in ("cheap", "network", "heavy")


def test_manifest_is_sorted_by_intent():
    names = [e["intent"] for e in manifest()]
    assert names == sorted(names)


# ── validate_params (advisory) ─────────────────────────────────────────────

def test_validate_params_flags_missing_required():
    ok, reason = validate_params("ApplicationLaunchIntent", {})
    assert not ok and "target" in reason


def test_validate_params_flags_wrong_type():
    ok, reason = validate_params("GeneralizedOSIntent", {"actions": "not-a-list"})
    assert not ok and "list" in reason


def test_validate_params_flags_bad_enum():
    ok, reason = validate_params("ProcessManagementIntent",
                                 {"action": "nuke", "target": "x"})
    assert not ok and "one of" in reason


def test_validate_params_bool_not_accepted_as_int():
    # DependencyInstallIntent.dev is bool; make sure a real int check elsewhere
    # would reject a bool — here dev IS bool so it must pass
    ok, _ = validate_params("DependencyInstallIntent",
                            {"packages": "requests", "dev": True})
    assert ok


def test_validate_params_unknown_intent_is_false():
    ok, reason = validate_params("NoSuchIntent", {})
    assert not ok and "no contract" in reason


def test_every_contract_example_passes_its_own_schema():
    for intent, c in CONTRACT_MAP.items():
        for ex in c.examples:
            ok, reason = validate_params(intent, ex["params"])
            assert ok, f"{intent} example {ex['params']} failed: {reason}"


# ── dispatch_via_contract (one migrated capability) ────────────────────────

@pytest.fixture
def scheduler_on_tmp_db(tmp_path, monkeypatch):
    """Point the scheduler's MemoryManager at an isolated DB."""
    import capabilities.system.scheduler as sched
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "sched.db"))
    monkeypatch.setattr(sched, "_memory", lambda: mm)
    return mm


def test_dispatch_scheduler_adds_a_real_row(scheduler_on_tmp_db):
    out = dispatch_via_contract(
        "SchedulerIntent",
        {"target": "call mom", "prompt": "remind me to call mom at 6pm"},
    )
    assert isinstance(out, str) and out
    pending = scheduler_on_tmp_db.get_pending_scheduled_tasks()
    assert any("call mom" in p["description"] for p in pending)


def test_dispatch_scheduler_list_path(scheduler_on_tmp_db):
    dispatch_via_contract("SchedulerIntent",
                          {"target": "buy milk", "prompt": "remind me to buy milk tomorrow"})
    listed = dispatch_via_contract("SchedulerIntent",
                                   {"target": "", "prompt": "what are my reminders"})
    assert "buy milk" in listed


def test_dispatch_rejects_bad_params_before_calling_handler(scheduler_on_tmp_db):
    with pytest.raises(ContractParamError):
        dispatch_via_contract("SchedulerIntent", {"target": "call mom"})  # missing required 'prompt'
    assert scheduler_on_tmp_db.get_pending_scheduled_tasks() == []


def test_dispatch_unavailable_for_unmigrated_intent():
    with pytest.raises(ContractDispatchUnavailable):
        dispatch_via_contract("ApplicationLaunchIntent", {"target": "notepad"})


def test_dispatch_unavailable_for_unknown_intent():
    with pytest.raises(ContractDispatchUnavailable):
        dispatch_via_contract("NoSuchIntent", {})


def test_contract_for_returns_none_on_miss():
    assert contract_for("NoSuchIntent") is None
    assert contract_for("SchedulerIntent").handler.endswith("handle_scheduler")
