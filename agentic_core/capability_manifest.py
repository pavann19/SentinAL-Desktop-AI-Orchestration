# agentic_core/capability_manifest.py
# P2-4 — MCP tool-contract manifest + parallel contract dispatch.
#
# Reads config/capability_contracts.py and exposes:
#   - manifest()            : the full JSON-serialisable tool manifest
#   - contract_for(intent)  : one contract
#   - validate_params(...)  : an ADVISORY schema pre-check (does not replace
#                             agentic_core/validator.py, which still runs the
#                             real allow/deny in the pipeline)
#   - dispatch_via_contract : call a capability THROUGH its contract
#
# dispatch_via_contract is the "dynamic dispatch of one migrated capability"
# P2-4 deliverable. It is wired for exactly one capability today
# (SchedulerIntent) and is NOT called from the running pipeline —
# agentic_core/executor.py keeps its own if/elif dispatch byte-for-byte.
# Full cutover (routing every intent through contracts) is deferred: it means
# rewriting that chain, and executor.py is frozen for the current work.
#
# Import-time consistency check: every allowlisted intent (except UnknownIntent)
# must have exactly one contract, and no contract may exist for a
# non-allowlisted intent. Drift raises here, so the manifest cannot silently
# rot as intents are added.

from __future__ import annotations

import importlib
import json

from config.capability_contracts import CONTRACTS, CapabilityContract
from config.constants import ALLOWLIST_INTENTS

_INTENTS_WITH_CONTRACTS = [c.intent for c in CONTRACTS]
CONTRACT_MAP: dict[str, CapabilityContract] = {c.intent: c for c in CONTRACTS}


def _check_consistency() -> None:
    dupes = {i for i in _INTENTS_WITH_CONTRACTS if _INTENTS_WITH_CONTRACTS.count(i) > 1}
    if dupes:
        raise RuntimeError(f"capability_contracts: duplicate contract(s) for {sorted(dupes)}")

    expected = set(ALLOWLIST_INTENTS) - {"UnknownIntent"}
    have = set(CONTRACT_MAP)
    missing = expected - have
    extra = have - expected
    if missing:
        raise RuntimeError(f"capability_contracts: no contract for allowlisted intent(s) {sorted(missing)}")
    if extra:
        raise RuntimeError(f"capability_contracts: contract for non-allowlisted intent(s) {sorted(extra)}")


_check_consistency()


class ContractDispatchUnavailable(RuntimeError):
    """Raised when dispatch_via_contract() is asked to run an intent whose
    contract has no handler (i.e. every capability not yet migrated)."""


class ContractParamError(ValueError):
    """Raised when params fail the contract's schema pre-check."""


# ── introspection ──────────────────────────────────────────────────────────

def manifest() -> list[dict]:
    """The full tool manifest, newest MCP-style shape, JSON-serialisable."""
    return [CONTRACT_MAP[i].to_dict() for i in sorted(CONTRACT_MAP)]


def contract_for(intent: str) -> CapabilityContract | None:
    return CONTRACT_MAP.get(intent)


# ── advisory schema pre-check ──────────────────────────────────────────────

_TYPE_MAP = {"str": str, "bool": bool, "int": int, "list": list, "dict": dict}


def validate_params(intent: str, params: dict) -> tuple[bool, str]:
    """(ok, reason). ADVISORY only — a client or the planner can call this
    before dispatch; it never substitutes for validator.py. Unknown intent is
    a hard False (no contract to check against)."""
    c = CONTRACT_MAP.get(intent)
    if c is None:
        return False, f"no contract for intent '{intent}'"
    if not isinstance(params, dict):
        return False, "params must be a dict"

    for name, spec in c.params.items():
        present = name in params and params[name] not in (None, "")
        if spec.get("required") and not present:
            return False, f"missing required param '{name}'"
        if not present:
            continue
        want = _TYPE_MAP.get(spec.get("type", "str"), str)
        val = params[name]
        # bool is a subclass of int — keep them distinct
        if want is int and isinstance(val, bool):
            return False, f"param '{name}' must be int, got bool"
        if not isinstance(val, want):
            return False, f"param '{name}' must be {spec.get('type')}, got {type(val).__name__}"
        enum = spec.get("enum")
        if enum and val not in enum:
            return False, f"param '{name}' must be one of {enum}"
    return True, ""


# ── parallel contract dispatch (one migrated capability) ────────────────────

def dispatch_via_contract(intent: str, params: dict, *, cancel_event=None):
    """Call a capability THROUGH its contract: schema-check, import the
    declared handler, invoke it. Only works for a contract with a `handler`
    (SchedulerIntent today). Not wired into the pipeline.

    Raises ContractParamError on a bad param set (before the handler is
    imported), ContractDispatchUnavailable for an unmigrated intent."""
    c = CONTRACT_MAP.get(intent)
    if c is None:
        raise ContractDispatchUnavailable(f"no contract for intent '{intent}'")
    if not c.handler:
        raise ContractDispatchUnavailable(
            f"'{intent}' has no contract handler — dispatch still goes through executor.py"
        )

    ok, reason = validate_params(intent, params)
    if not ok:
        raise ContractParamError(f"{intent}: {reason}")

    mod_path, _, func_name = c.handler.partition(":")
    func = getattr(importlib.import_module(mod_path), func_name)

    # The migrated family all take (target, prompt). Keep this explicit rather
    # than **params so a schema change can't silently pass unexpected kwargs.
    if intent == "SchedulerIntent":
        return func(params.get("target", ""), params.get("prompt", ""))

    raise ContractDispatchUnavailable(f"no invocation mapping wired for '{intent}'")


if __name__ == "__main__":  # python -m agentic_core.capability_manifest
    print(json.dumps(manifest(), indent=2))
