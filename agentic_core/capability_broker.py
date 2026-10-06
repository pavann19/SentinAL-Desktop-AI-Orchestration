
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.capability_tiers import T0, T1, T2, T3, tier_for

_logger = logging.getLogger("CapabilityBroker")


@dataclass
class GrantDecision:
    """Outcome of a broker check for one step or a whole plan."""
    allowed: bool
    tier: str
    requires_confirmation: bool
    reason: str


def grant(step: dict, *, autonomous: bool = False) -> GrantDecision:
    """
    Containment decision for a single validated step.

    Args:
        step:        an already-validate_steps()-approved step dict.
        autonomous:  True when the caller is a background/proactive goal with no
                     human in the loop for this specific action. False (default)
                     when a human directly issued the command.
    """
    tier = tier_for(step)
    intent = str(step.get("intent", "") or "").strip() or "UnknownIntent"

    if tier in (T0, T1):
        return GrantDecision(
            allowed=True,
            tier=tier,
            requires_confirmation=False,
            reason=f"{intent} is {tier} (autonomous-safe).",
        )

    if tier == T2:
        if autonomous:
            return GrantDecision(
                allowed=False,
                tier=tier,
                requires_confirmation=False,
                reason=(
                    f"{intent} is T2 and cannot run autonomously: supported path snapshots "
                    f"do not provide complete rollback for this capability."
                ),
            )
        return GrantDecision(
            allowed=True,
            tier=tier,
            requires_confirmation=True,
            reason=f"{intent} is T2 — needs human confirmation; complete rollback is unavailable.",
        )

    # tier == T3
    if autonomous:
        return GrantDecision(
            allowed=False,
            tier=tier,
            requires_confirmation=False,
            reason=f"{intent} is T3 (irreversible) and is never permitted to run autonomously.",
        )
    return GrantDecision(
        allowed=True,
        tier=tier,
        requires_confirmation=True,
        reason=f"{intent} is T3 (irreversible) — needs explicit human confirmation.",
    )


# Tier ordering for "highest wins" aggregation.
_TIER_RANK = {T0: 0, T1: 1, T2: 2, T3: 3}


def grant_all(steps: list, *, autonomous: bool = False) -> GrantDecision:
    """
    Containment decision for a whole plan.

    - allowed:                True only if every step is allowed.
    - tier:                   the highest tier among the steps.
    - requires_confirmation:  True if any step needs confirmation.
    - reason:                 the first blocking step's reason, else the
                              highest-tier step's reason.
    """
    if not steps or not isinstance(steps, list):
        return GrantDecision(
            allowed=False, tier=T3, requires_confirmation=False,
            reason="No steps to evaluate.",
        )

    decisions = [grant(s, autonomous=autonomous) for s in steps if isinstance(s, dict)]
    if not decisions:
        return GrantDecision(
            allowed=False, tier=T3, requires_confirmation=False,
            reason="No valid step dicts to evaluate.",
        )

    blocking = next((d for d in decisions if not d.allowed), None)
    highest = max(decisions, key=lambda d: _TIER_RANK.get(d.tier, 3))

    decision = GrantDecision(
        allowed=all(d.allowed for d in decisions),
        tier=highest.tier,
        requires_confirmation=any(d.requires_confirmation for d in decisions),
        reason=(blocking.reason if blocking else highest.reason),
    )

    log = _logger.warning if (not decision.allowed or decision.requires_confirmation) else _logger.info
    log(
        f"[broker] plan tier={decision.tier} allowed={decision.allowed} "
        f"confirm={decision.requires_confirmation} autonomous={autonomous} :: {decision.reason}"
    )
    return decision
