# agentic_core/confirmation.py
# Direct-human confirmation channel for T2/T3 actions (P2-5 enforcement, the
# autonomous=False half — the autonomous half is the broker's outright deny in
# capabilities/system/api_wrapper.py::process_command).
#
# When SENTINAL_REQUIRE_CONFIRMATION is on and a direct-human request's plan
# needs confirmation (broker tier T2/T3), process_command returns a
# PendingConfirmation result carrying a one-time token bound to THAT exact
# request. The caller resends the same prompt with the token to proceed.
#
# The store is in-memory on purpose: a half-confirmed irreversible action must
# not survive a restart. Tokens are single-use and expire.

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field

CONFIRM_TTL_SECONDS = float(os.getenv("SENTINAL_CONFIRM_TTL_SECONDS", "300"))

# Master switch. Off by default: turning it on changes behaviour (a T2/T3
# direct-human request now needs a second round-trip), which existing REST
# callers and the benchmark do not expect. A real deployment should set it on.
REQUIRE_CONFIRMATION = os.getenv(
    "SENTINAL_REQUIRE_CONFIRMATION", "false"
).strip().lower() not in ("0", "false", "no", "")


def _request_fingerprint(prompt: str, steps: list) -> str:
    """A stable hash of the request a token is bound to. Includes the plan's
    intents and targets, so a token issued for 'delete A' cannot confirm a
    later 'delete B' that happens to reuse the same prompt text, and a token
    for one prompt cannot confirm a different one."""
    shape = [
        {
            "intent": s.get("intent"),
            "target": s.get("target"),
            "action": s.get("action"),
            "actions": s.get("actions"),
        }
        for s in steps if isinstance(s, dict)
    ]
    blob = json.dumps({"prompt": prompt.strip(), "steps": shape}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def summarize(steps: list, tier: str, reason: str) -> str:
    """Human-readable 'here is what you are approving' line."""
    parts = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        intent = s.get("intent", "?")
        target = str(s.get("target", "") or "").strip()
        parts.append(f"{intent}" + (f" -> {target}" if target else ""))
    what = "; ".join(parts) or "this action"
    return (
        f"Confirmation required ({tier}): {what}. {reason} "
        f"Resend the same request with the confirm token to proceed."
    )


@dataclass
class _Pending:
    fingerprint: str
    tier: str
    issued_at: float
    ttl: float = CONFIRM_TTL_SECONDS

    def expired(self, now: float) -> bool:
        return now - self.issued_at > self.ttl


@dataclass
class PendingConfirmations:
    """One-time, TTL-bound confirmation tokens, keyed by token string."""
    _store: dict[str, _Pending] = field(default_factory=dict)

    def issue(self, prompt: str, steps: list, tier: str) -> str:
        self._gc()
        token = secrets.token_urlsafe(24)
        self._store[token] = _Pending(
            fingerprint=_request_fingerprint(prompt, steps),
            tier=tier,
            issued_at=time.time(),
        )
        return token

    def check_and_consume(self, prompt: str, steps: list, token: str | None) -> bool:
        """True iff `token` was issued for this exact request and is still
        valid; consumes it (single use) on success."""
        if not token:
            return False
        self._gc()
        pending = self._store.get(token)
        if pending is None:
            return False
        now = time.time()
        if pending.expired(now):
            self._store.pop(token, None)
            return False
        if pending.fingerprint != _request_fingerprint(prompt, steps):
            return False
        # valid — consume it
        self._store.pop(token, None)
        return True

    def _gc(self) -> None:
        now = time.time()
        for tok in [t for t, p in self._store.items() if p.expired(now)]:
            self._store.pop(tok, None)

    def pending_count(self) -> int:
        self._gc()
        return len(self._store)


# Process-wide store.
pending_confirmations = PendingConfirmations()
