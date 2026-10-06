"""Request-scoped authorization for resolved actions.

This boundary protects against untrusted planner output, not hostile Python code
already running inside the process. Callers without a request context are treated
as autonomous. Confirmation covers exact action contents, never a capability tier.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agentic_core.capability_broker import grant
from agentic_core.validator import validate_steps

_METADATA = frozenset({"step_id", "depends_on", "status", "replan_count", "result",
                       "observation", "expected_state", "planner_hint", "_source_prompt"})


def resolve_action(step: dict[str, Any]) -> dict[str, Any]:
    """Freeze destructive paths and shell environment expansion before approval."""
    if not isinstance(step, dict):
        raise AuthorizationDenied("An executable action must be an object.")
    resolved = copy.deepcopy(step)
    if resolved.get("intent") == "SysUtilityIntent":
        from capabilities.system.sys_utility import resolve_system_action
        resolved["action"] = resolve_system_action(resolved.get("target", ""), resolved.get("prompt", ""))
    if resolved.get("intent") == "FileDeletionIntent" and resolved.get("target"):
        resolved["target"] = os.path.abspath(os.path.expandvars(str(resolved["target"])))
    if resolved.get("intent") == "GeneralizedOSIntent":
        for action in resolved.get("actions", []):
            if action.get("type", "").lower() == "shell":
                action["payload"] = os.path.expandvars(str(action.get("payload", "")))
                action["value"] = os.path.expandvars(str(action.get("value", "")))
    return resolved


def action_fingerprint(step: dict[str, Any]) -> str:
    """Include all executable arguments and the trusted policy-derived tier."""
    from config.capability_tiers import tier_for

    action = {key: value for key, value in resolve_action(step).items() if key not in _METADATA}
    for key, default in (("prompt", ""), ("target", ""), ("actions", [])):
        action.setdefault(key, default)
    action["capability_tier"] = tier_for(step)
    encoded = json.dumps(action, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionAuthority:
    prompt: str = ""
    autonomous: bool = True
    confirmed_actions: frozenset[str] = frozenset()


_authority: ContextVar[ExecutionAuthority | None] = ContextVar(
    "execution_authority", default=None,
)


@contextmanager
def execution_scope(authority: ExecutionAuthority) -> Iterator[None]:
    token = _authority.set(authority)
    try:
        yield
    finally:
        _authority.reset(token)


class AuthorizationDenied(ValueError):
    """A resolved action cannot run under the current request authority."""


def authorize_action(step: dict[str, Any]) -> dict[str, Any]:
    """Copy, validate and authorize the exact action immediately before dispatch."""
    resolved = resolve_action(step)
    authority = _authority.get() or ExecutionAuthority()
    if authority.prompt:
        resolved["_source_prompt"] = authority.prompt
    valid, reason, _ = validate_steps([resolved])
    if not valid:
        raise AuthorizationDenied(reason)
    decision = grant(resolved, autonomous=authority.autonomous)
    if not decision.allowed:
        raise AuthorizationDenied(decision.reason)
    if decision.requires_confirmation and action_fingerprint(resolved) not in authority.confirmed_actions:
        raise AuthorizationDenied("Resolved action requires a fresh human confirmation.")
    return resolved


def trusted_postconditions(step: dict[str, Any]) -> dict[str, Any]:
    """Discard planner predicates; only deterministic action-derived checks verify."""
    from capabilities.system.api_wrapper import _derive_expected_state

    resolved = copy.deepcopy(step)
    hint = resolved.pop("expected_state", None)
    if hint is not None:
        resolved["planner_hint"] = hint
    expected = _derive_expected_state(resolved)
    if expected:
        resolved["expected_state"] = expected
    return resolved


def run_with_authority(function, authority: ExecutionAuthority, *args):
    """Install authority inside a worker thread without widening another request."""
    with execution_scope(authority):
        return function(*args)
