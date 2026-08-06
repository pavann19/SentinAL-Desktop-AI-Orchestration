"""
tests/test_postcondition_coverage.py

S1 regression tests: postcondition verification beyond ApplicationLaunchIntent.

Context: execute_pipeline_observed() has had a full observe/classify/replan loop
since P1-1/P1-2/P1-4, but _derive_expected_state() only ever returned a
postcondition for ApplicationLaunchIntent — so 14 of the 15 intents in
ALLOWLIST_INTENTS executed blind, reporting success whenever they failed to
raise. These tests lock in the deterministic tiers added to close that gap
(filesystem exists/absent, process-absent) and the intents now wired to them.

They also lock in the DELIBERATE omissions: WebNavigationIntent and
MediaStreamingIntent must stay unwired until observe_postcondition() grows a
settle/timeout mechanism, because a false mismatch there triggers a whole-pipeline
replan and duplicates the side effect (a second browser tab).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from capabilities.system.api_wrapper import _derive_expected_state
from capabilities.system.postcondition_observer import observe_postcondition


# ══════════════════════════════════════════════════════════════════════════════
# Filesystem tier — the new deterministic observer tiers
# ══════════════════════════════════════════════════════════════════════════════
class TestFilesystemTier:
    def test_path_exists_verified_when_present(self, tmp_path):
        target = tmp_path / "present.txt"
        target.write_text("x")
        obs = observe_postcondition({"path_exists": str(target)})
        assert obs.verified is True
        assert obs.tier_used == "filesystem"
        assert obs.confidence == 1.0

    def test_path_exists_unverified_when_missing(self, tmp_path):
        obs = observe_postcondition({"path_exists": str(tmp_path / "nope.txt")})
        assert obs.verified is False
        assert obs.tier_used == "filesystem"

    def test_path_absent_verified_when_gone(self, tmp_path):
        obs = observe_postcondition({"path_absent": str(tmp_path / "deleted.txt")})
        assert obs.verified is True
        assert obs.tier_used == "filesystem"

    def test_path_absent_unverified_when_still_there(self, tmp_path):
        survivor = tmp_path / "survivor.txt"
        survivor.write_text("x")
        obs = observe_postcondition({"path_absent": str(survivor)})
        assert obs.verified is False
        assert obs.tier_used == "filesystem"

    def test_directory_counts_for_path_exists(self, tmp_path):
        """Scaffolding creates a directory, not a file — exists() must cover both."""
        d = tmp_path / "scaffolded-project"
        d.mkdir()
        assert observe_postcondition({"path_exists": str(d)}).verified is True

    def test_filesystem_tier_never_raises_on_garbage_input(self):
        """The observer's contract is that it never raises — a malformed path
        must degrade to an unverified Observation, not blow up the pipeline."""
        obs = observe_postcondition({"path_exists": "\x00invalid\x00path"})
        assert obs.verified is False
        assert obs.tier_used == "filesystem"


# ══════════════════════════════════════════════════════════════════════════════
# Process-absent tier — inverse of the existing process tier
# ══════════════════════════════════════════════════════════════════════════════
class TestProcessAbsentTier:
    def test_absent_verified_for_process_that_is_not_running(self):
        obs = observe_postcondition({"process_absent": "definitely-not-a-real-process-xyz"})
        assert obs.verified is True
        assert obs.tier_used == "process"

    def test_absent_unverified_for_a_process_that_is_running(self):
        """This test process itself is running, so python must be found."""
        obs = observe_postcondition({"process_absent": "python"})
        assert obs.verified is False
        assert obs.tier_used == "process"
        assert "still running" in obs.detail

    def test_process_name_still_works_unchanged(self):
        """The pre-existing tier must be untouched by the additions."""
        obs = observe_postcondition({"process_name": "python"})
        assert obs.verified is True
        assert obs.tier_used == "process"


# ══════════════════════════════════════════════════════════════════════════════
# Tier priority — additions must not shadow the pre-existing tiers
# ══════════════════════════════════════════════════════════════════════════════
class TestTierPriority:
    def test_process_name_takes_priority_over_new_tiers(self, tmp_path):
        obs = observe_postcondition({"process_name": "python", "path_exists": str(tmp_path)})
        assert obs.tier_used == "process"

    def test_empty_expectation_still_reports_none_tier(self):
        """Guards _classify_result(): tier_used="none" must NOT count as a
        postcondition mismatch, or malformed input would burn a real replan."""
        obs = observe_postcondition({})
        assert obs.verified is False
        assert obs.tier_used == "none"

    def test_unrecognized_key_reports_none_tier(self):
        obs = observe_postcondition({"something_unsupported": "value"})
        assert obs.tier_used == "none"


# ══════════════════════════════════════════════════════════════════════════════
# _derive_expected_state — which intents are now wired
# ══════════════════════════════════════════════════════════════════════════════
class TestDeriveExpectedState:
    def test_application_launch_unchanged(self):
        """Pre-existing behaviour must survive the extension byte-for-byte."""
        assert _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": "notepad"}
        ) == {"process_name": "notepad"}

    def test_application_launch_strips_path_to_basename(self):
        derived = _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": r"C:\Windows\System32\notepad.exe"}
        )
        assert derived == {"process_name": "notepad.exe"}

    def test_file_deletion_expects_path_absent_absolute(self):
        derived = _derive_expected_state(
            {"intent": "FileDeletionIntent", "target": r"C:\tmp\gone.txt"}
        )
        assert derived is not None
        assert "path_absent" in derived
        assert derived["path_absent"] == os.path.abspath(r"C:\tmp\gone.txt")

    def test_file_deletion_resolves_relative_path_like_the_executor_does(self):
        """The executor resolves cwd-relative targets via abspath(join(cwd, target)).
        If the observer resolved differently it would check the wrong path and
        report a false 'verified', which is worse than no check at all."""
        derived = _derive_expected_state(
            {"intent": "FileDeletionIntent", "target": "relative/file.txt"}
        )
        assert derived["path_absent"] == os.path.abspath(
            os.path.join(os.getcwd(), "relative/file.txt")
        )

    def test_process_kill_expects_process_absent(self):
        derived = _derive_expected_state(
            {"intent": "ProcessManagementIntent", "action": "kill", "target": "notepad.exe"}
        )
        assert derived == {"process_absent": "notepad.exe"}

    def test_process_list_has_no_postcondition(self):
        """'list' is read-only — inventing a postcondition for it would produce
        pure noise and could trigger meaningless replans."""
        assert _derive_expected_state(
            {"intent": "ProcessManagementIntent", "action": "list", "target": "chrome"}
        ) is None

    def test_process_kill_without_target_has_no_postcondition(self):
        assert _derive_expected_state(
            {"intent": "ProcessManagementIntent", "action": "kill", "target": ""}
        ) is None

    def test_project_scaffold_expects_directory_to_exist(self):
        derived = _derive_expected_state({
            "intent": "ProjectScaffoldIntent",
            "framework": "react",
            "project_name": "my-app",
            "location": r"C:\projects",
        })
        assert derived == {"path_exists": os.path.abspath(os.path.join(r"C:\projects", "my-app"))}

    def test_project_scaffold_defaults_to_cwd_when_no_location(self):
        derived = _derive_expected_state(
            {"intent": "ProjectScaffoldIntent", "project_name": "my-app"}
        )
        assert derived["path_exists"] == os.path.abspath(os.path.join(os.getcwd(), "my-app"))

    def test_project_scaffold_without_name_has_no_postcondition(self):
        assert _derive_expected_state({"intent": "ProjectScaffoldIntent", "framework": "react"}) is None


# ══════════════════════════════════════════════════════════════════════════════
# Deliberate omissions — these must stay unwired, and it must be on purpose
# ══════════════════════════════════════════════════════════════════════════════
class TestTimingSensitiveIntentsStayUnwired:
    """A false postcondition mismatch triggers a bounded WHOLE-PIPELINE replan,
    which re-runs the side effect. For browser-opening intents the window may not
    have rendered when checked, making 'not found' indistinguishable from 'still
    loading' — so wiring them now would trade silent failures for duplicate tabs.
    They stay unwired until observe_postcondition() gains a settle/timeout poll.

    If you are here because you just added that mechanism: these are the tests
    to update, deliberately, rather than delete."""

    def test_web_navigation_not_yet_wired(self):
        assert _derive_expected_state(
            {"intent": "WebNavigationIntent", "target": "https://github.com"}
        ) is None

    def test_media_streaming_not_yet_wired(self):
        assert _derive_expected_state(
            {"intent": "MediaStreamingIntent", "target": "some song"}
        ) is None


class TestDeriveExpectedStateRobustness:
    def test_non_dict_input_returns_none(self):
        assert _derive_expected_state("not a dict") is None
        assert _derive_expected_state(None) is None

    def test_unknown_intent_returns_none(self):
        assert _derive_expected_state({"intent": "ConversationalIntent", "target": "hi"}) is None

    def test_missing_target_returns_none(self):
        assert _derive_expected_state({"intent": "ApplicationLaunchIntent"}) is None

    def test_none_target_does_not_raise(self):
        """The LLM envelope can produce an explicit null target — that must
        degrade to 'no postcondition', not a TypeError inside the pipeline."""
        assert _derive_expected_state(
            {"intent": "FileDeletionIntent", "target": None}
        ) is None


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: derived expectation feeds the observer coherently
# ══════════════════════════════════════════════════════════════════════════════
class TestDerivedStateFeedsObserver:
    def test_deletion_postcondition_verifies_after_real_delete(self, tmp_path):
        """The whole point of S1: derive -> act -> observe must agree on the
        same path, so a real deletion actually verifies."""
        victim = tmp_path / "victim.txt"
        victim.write_text("x")

        derived = _derive_expected_state(
            {"intent": "FileDeletionIntent", "target": str(victim)}
        )
        assert observe_postcondition(derived).verified is False  # not deleted yet

        os.remove(victim)
        assert observe_postcondition(derived).verified is True

    def test_scaffold_postcondition_verifies_after_real_mkdir(self, tmp_path):
        derived = _derive_expected_state({
            "intent": "ProjectScaffoldIntent",
            "project_name": "app",
            "location": str(tmp_path),
        })
        assert observe_postcondition(derived).verified is False

        (tmp_path / "app").mkdir()
        assert observe_postcondition(derived).verified is True
