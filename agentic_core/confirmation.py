
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

CONFIRM_TTL_SECONDS = float(os.getenv("SENTINAL_CONFIRM_TTL_SECONDS", "300"))

# Guarded direct-human actions require a one-time confirmation by default.
REQUIRE_CONFIRMATION = os.getenv(
    "SENTINAL_REQUIRE_CONFIRMATION", "true"
).strip().lower() not in ("0", "false", "no", "")


def _request_fingerprint(prompt: str, steps: list) -> str:
    """Bind a one-time token to the original prompt and all executable action fields."""
    from agentic_core.execution_authority import action_fingerprint

    shape = [action_fingerprint(s) for s in steps if isinstance(s, dict)]
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
        details = {key: value for key, value in s.items()
                   if key not in {"intent", "target", "_source_prompt", "expected_state", "planner_hint",
                                  "step_id", "depends_on", "status", "replan_count", "result", "observation"}}
        parts.append(f"{intent}" + (f" -> {target}" if target else "")
                     + (f"; arguments={json.dumps(details, sort_keys=True)}" if details else ""))
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
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def issue(self, prompt: str, steps: list, tier: str) -> str:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            now = time.time()
            for tok in [t for t, p in self._store.items() if p.expired(now)]:
                self._store.pop(tok, None)

    def pending_count(self) -> int:
        with self._lock:
            self._gc()
            return len(self._store)


# Process-wide store.
pending_confirmations = PendingConfirmations()
