"""
tests/test_capability_broker.py

Unit tests for agentic_core/capability_broker.py + config/capability_tiers.py
(S4 containment substrate — the risk-tier decision layer).

Covers: tier assignment for every allowlisted intent, sub-action overrides,
the autonomous vs direct-human split (T2/T3 deny when autonomous, flag-only
when not), grant_all aggregation, and the invariant that the broker never
loosens what the validator already decided.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.capability_broker import GrantDecision, grant, grant_all
from config.capability_tiers import (
    INTENT_TIERS,
    T0,
    T1,
    T2,
    T3,
    tier_for,
)
from config.constants import ALLOWLIST_INTENTS


class TestTierMapCompleteness:
    def test_every_allowlisted_intent_has_a_tier(self):
        """No allowlisted intent may be missing from the tier map — a gap would
        silently fall through to the T3 default and over-restrict a safe intent."""
        missing = ALLOWLIST_INTENTS - set(INTENT_TIERS)
        assert not missing, f"intents with no explicit tier: {missing}"

    def test_all_tiers_are_valid(self):
        assert set(INTENT_TIERS.values()) <= {T0, T1, T2, T3}

    def test_unknown_intent_defaults_to_t3(self):
        assert tier_for({"intent": "SomethingNobodyDefined"}) == T3

    def test_non_dict_input_defaults_to_t3(self):
        assert tier_for("not a dict") == T3
        assert tier_for(None) == T3


class TestTierAssignments:
    @pytest.mark.parametrize("intent", [
        "ConversationalIntent", "ContinuationIntent", "InformationRetrievalIntent",
    ])
    def test_read_only_intents_are_t0(self, intent):
        assert tier_for({"intent": intent}) == T0

    @pytest.mark.parametrize("intent", [
        "ApplicationLaunchIntent", "WebNavigationIntent", "MediaStreamingIntent",
        "MediaControlIntent", "WindowManagementIntent", "SchedulerIntent",
        "DataModelingIntent", "AcademicResearchIntent",
    ])
    def test_low_harm_intents_are_t1(self, intent):
        assert tier_for({"intent": intent}) == T1

    @pytest.mark.parametrize("intent", [
        "DictationIntent", "SysUtilityIntent", "ProjectScaffoldIntent",
        "DependencyInstallIntent",
    ])
    def test_real_write_intents_are_t2(self, intent):
        assert tier_for({"intent": intent}) == T2

    @pytest.mark.parametrize("intent", [
        "FileDeletionIntent", "CodeActIntent", "GeneralizedOSIntent",
        "ProcessManagementIntent",
    ])
    def test_irreversible_intents_are_t3(self, intent):
        assert tier_for({"intent": intent}) == T3


class TestSubActionOverrides:
    def test_process_management_list_is_t0_not_t3(self):
        assert tier_for({"intent": "ProcessManagementIntent", "action": "list"}) == T0

    def test_process_management_kill_keeps_t3_default(self):
        assert tier_for({"intent": "ProcessManagementIntent", "action": "kill"}) == T3

    def test_process_management_no_action_keeps_t3_default(self):
        assert tier_for({"intent": "ProcessManagementIntent"}) == T3

    def test_scheduler_list_is_t0(self):
        assert tier_for({"intent": "SchedulerIntent", "action": "list"}) == T0

    def test_scheduler_add_keeps_t1_default(self):
        assert tier_for({"intent": "SchedulerIntent", "action": "add"}) == T1

    def test_override_lookup_is_case_insensitive(self):
        assert tier_for({"intent": "ProcessManagementIntent", "action": "LIST"}) == T0
        assert tier_for({"intent": "ProcessManagementIntent", "action": "  List "}) == T0


class TestGrantDirectHuman:
    """autonomous=False — every caller today. T2/T3 flag confirmation, nothing
    is hard-blocked (no confirmation channel exists yet)."""

    def test_t0_proceeds_without_confirmation(self):
        d = grant({"intent": "ConversationalIntent"})
        assert d.allowed is True
        assert d.tier == T0
        assert d.requires_confirmation is False

    def test_t1_proceeds_without_confirmation(self):
        d = grant({"intent": "ApplicationLaunchIntent", "target": "notepad"})
        assert d.allowed is True
        assert d.tier == T1
        assert d.requires_confirmation is False

    def test_t2_proceeds_but_flags_confirmation(self):
        d = grant({"intent": "SysUtilityIntent"})
        assert d.allowed is True
        assert d.tier == T2
        assert d.requires_confirmation is True

    def test_t3_proceeds_but_flags_confirmation(self):
        d = grant({"intent": "FileDeletionIntent", "target": "junk.txt"})
        assert d.allowed is True
        assert d.tier == T3
        assert d.requires_confirmation is True


class TestGrantAutonomous:
    """autonomous=True — the S6 background-goal case. T2 and T3 are denied
    outright; T0/T1 still proceed."""

    def test_t0_still_proceeds(self):
        d = grant({"intent": "InformationRetrievalIntent"}, autonomous=True)
        assert d.allowed is True
        assert d.requires_confirmation is False

    def test_t1_still_proceeds(self):
        d = grant({"intent": "WebNavigationIntent", "target": "example.com"}, autonomous=True)
        assert d.allowed is True

    def test_t2_is_denied(self):
        d = grant({"intent": "DependencyInstallIntent"}, autonomous=True)
        assert d.allowed is False
        assert d.tier == T2
        assert "autonomously" in d.reason

    def test_t3_is_denied(self):
        d = grant({"intent": "CodeActIntent"}, autonomous=True)
        assert d.allowed is False
        assert d.tier == T3
        assert "never" in d.reason.lower()

    def test_process_kill_is_denied_autonomously(self):
        d = grant({"intent": "ProcessManagementIntent", "action": "kill", "target": "notepad"}, autonomous=True)
        assert d.allowed is False
        assert d.tier == T3

    def test_process_list_still_allowed_autonomously(self):
        d = grant({"intent": "ProcessManagementIntent", "action": "list"}, autonomous=True)
        assert d.allowed is True
        assert d.tier == T0


class TestGrantAll:
    def test_highest_tier_wins(self):
        steps = [
            {"intent": "ConversationalIntent"},       # T0
            {"intent": "ApplicationLaunchIntent"},    # T1
            {"intent": "FileDeletionIntent"},         # T3
        ]
        d = grant_all(steps)
        assert d.tier == T3

    def test_any_step_needing_confirmation_flags_the_plan(self):
        steps = [
            {"intent": "ConversationalIntent"},   # no confirm
            {"intent": "SysUtilityIntent"},       # T2 -> confirm
        ]
        d = grant_all(steps)
        assert d.requires_confirmation is True

    def test_all_low_tier_plan_needs_no_confirmation(self):
        steps = [
            {"intent": "InformationRetrievalIntent"},
            {"intent": "WebNavigationIntent", "target": "x.com"},
        ]
        d = grant_all(steps)
        assert d.requires_confirmation is False
        assert d.allowed is True

    def test_plan_is_blocked_autonomously_if_any_step_is_t3(self):
        steps = [
            {"intent": "InformationRetrievalIntent"},  # fine
            {"intent": "FileDeletionIntent"},          # T3 -> denied when autonomous
        ]
        d = grant_all(steps, autonomous=True)
        assert d.allowed is False
        assert "irreversible" in d.reason.lower() or "never" in d.reason.lower()

    def test_empty_or_invalid_plan_is_not_allowed(self):
        assert grant_all([]).allowed is False
        assert grant_all(None).allowed is False
        assert grant_all(["not a dict", 42]).allowed is False

    def test_returns_a_grant_decision(self):
        assert isinstance(grant_all([{"intent": "ConversationalIntent"}]), GrantDecision)


class TestBrokerNeverLoosensValidator:
    """The broker runs alongside validate_steps(), not instead of it. It has no
    path that turns an allowed=False into allowed=True, and it never inspects
    allowlist/denylist membership — that stays entirely with the validator."""

    def test_grant_has_no_allowlist_logic(self):
        # A step whose intent is NOT in the allowlist still gets a tier decision
        # (defensively T3) — the broker does not try to be a second allowlist.
        d = grant({"intent": "TotallyMadeUpIntent"})
        assert d.tier == T3
        # Direct-human context: it flags confirmation rather than blocking,
        # because rejecting-on-unknown-intent is the validator's job, already
        # done before this point in the real pipeline.
        assert d.requires_confirmation is True
