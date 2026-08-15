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
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from capabilities.system import postcondition_observer as pco
from capabilities.system.api_wrapper import _derive_expected_state, _site_label
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
    def test_application_launch_derives_process_name(self):
        """Renamed from test_application_launch_unchanged: the behaviour is no
        longer unchanged. A settle_timeout_ms key was added deliberately (two
        back-to-back launches raced the postcondition check), so asserting
        byte-for-byte dict equality was asserting something we intentionally
        changed. The process_name derivation — the actual contract — is what
        must stay stable, and that is what is asserted now."""
        assert _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": "notepad"}
        )["process_name"] == "notepad"

    def test_application_launch_has_settle_window(self):
        derived = _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": "notepad"}
        )
        assert derived["settle_timeout_ms"] > 0

    def test_application_launch_strips_path_to_basename(self):
        derived = _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": r"C:\Windows\System32\notepad.exe"}
        )
        assert derived["process_name"] == "notepad.exe"

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

    def test_generalized_os_mkdir_expects_directory_to_exist(self):
        derived = _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "mkdir", "value": r"C:\tmp\sentinal-new-dir"}],
        })
        assert derived == {"path_exists": os.path.abspath(r"C:\tmp\sentinal-new-dir")}

    def test_generalized_os_mkdir_combined_payload_expects_directory_to_exist(self):
        derived = _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "md relative-dir"}],
        })
        assert derived == {"path_exists": os.path.abspath(os.path.join(os.getcwd(), "relative-dir"))}

    def test_generalized_os_mkdir_value_with_spaces_expects_single_directory(self):
        derived = _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "mkdir", "value": r"C:\tmp\folder with spaces"}],
        })
        assert derived == {"path_exists": os.path.abspath(r"C:\tmp\folder with spaces")}

    def test_generalized_os_mkdir_unquoted_combined_spaces_has_no_postcondition(self):
        assert _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "mkdir first second"}],
        }) is None

    def test_generalized_os_non_mkdir_shell_has_no_postcondition(self):
        assert _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "taskkill /IM notepad.exe /F"}],
        }) is None

    def test_generalized_os_gui_action_has_no_postcondition(self):
        assert _derive_expected_state({
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "gui", "payload": "press", "value": "enter"}],
        }) is None

    @pytest.mark.parametrize("intent", [
        "SysUtilityIntent",
        "MediaControlIntent",
        "DictationIntent",
        "SchedulerIntent",
        "AcademicResearchIntent",
        "DataModelingIntent",
        "DependencyInstallIntent",
        "CodeActIntent",
        "InformationRetrievalIntent",
        "ConversationalIntent",
        "ContinuationIntent",
    ])
    def test_evaluated_uncheckable_intents_remain_unwired(self, intent):
        assert _derive_expected_state({
            "intent": intent,
            "target": "example",
            "prompt": "example",
            "packages": "requests",
        }) is None

    def test_generalized_os_mkdir_mismatch_is_classified_end_to_end(self, tmp_path, monkeypatch):
        missing = tmp_path / "was-not-created"
        step = {
            "intent": "GeneralizedOSIntent",
            "actions": [{"type": "shell", "payload": "mkdir", "value": str(missing)}],
        }
        step["expected_state"] = _derive_expected_state(step)

        from agentic_core import executor
        monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "claimed success")
        monkeypatch.setattr(executor, "MAX_REPLANS", 0)

        observed = executor.execute_pipeline_observed([step])

        assert observed["failure_category"] == "postcondition_mismatch"
        assert observed["step_observations"][0]["observation"].tier_used == "filesystem"


# ══════════════════════════════════════════════════════════════════════════════
# Settle/timeout polling — what unblocked the browser intents
# ══════════════════════════════════════════════════════════════════════════════
class TestSettleTimeout:
    def test_verified_result_returns_immediately_without_waiting(self, monkeypatch):
        """The core performance property: success pays no timeout. If this
        regresses, every successful browser navigation stalls for the full
        settle window."""
        monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda t: True)
        start = time.time()
        obs = observe_postcondition({"window_title": "GitHub", "settle_timeout_ms": 5000})
        assert obs.verified is True
        assert (time.time() - start) < 1.0

    def test_polls_and_succeeds_once_the_window_appears(self, monkeypatch):
        """The whole point: 'not yet' must be distinguishable from 'never'."""
        attempts = {"n": 0}

        def _appears_on_third_check(_title):
            attempts["n"] += 1
            return attempts["n"] >= 3

        monkeypatch.setattr(pco.gui_resolver, "window_exists", _appears_on_third_check)
        obs = observe_postcondition({"window_title": "GitHub", "settle_timeout_ms": 4000})
        assert obs.verified is True
        assert attempts["n"] >= 3

    def test_gives_up_after_the_deadline(self, monkeypatch):
        monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda t: False)
        start = time.time()
        obs = observe_postcondition({"window_title": "Nope", "settle_timeout_ms": 700})
        elapsed = time.time() - start
        assert obs.verified is False
        assert 0.5 < elapsed < 4.0

    def test_zero_timeout_is_a_single_check(self, monkeypatch):
        """Default behaviour must be byte-for-byte the pre-settle behaviour."""
        attempts = {"n": 0}

        def _count(_title):
            attempts["n"] += 1
            return False

        monkeypatch.setattr(pco.gui_resolver, "window_exists", _count)
        observe_postcondition({"window_title": "Nope", "settle_timeout_ms": 0})
        assert attempts["n"] == 1

    def test_absent_settle_key_is_a_single_check(self, monkeypatch):
        attempts = {"n": 0}

        def _count(_title):
            attempts["n"] += 1
            return False

        monkeypatch.setattr(pco.gui_resolver, "window_exists", _count)
        observe_postcondition({"window_title": "Nope"})
        assert attempts["n"] == 1

    def test_vlm_tier_is_never_polled(self, monkeypatch):
        """Each VLM check is a screenshot plus model inference. Polling it would
        spend many inferences to answer one question."""
        attempts = {"n": 0}

        def _count(_q):
            attempts["n"] += 1
            return False

        monkeypatch.setattr(pco.vision_module, "verify_screen_state", _count)
        observe_postcondition({"vlm_query": "is it open?", "settle_timeout_ms": 2000})
        assert attempts["n"] == 1

    def test_settle_applies_to_filesystem_tier_too(self, tmp_path, monkeypatch):
        """Scaffolding writes a directory asynchronously — the tier is generic,
        not browser-specific."""
        target = tmp_path / "late-project"
        attempts = {"n": 0}
        real_exists = os.path.exists

        def _appears_late(p):
            attempts["n"] += 1
            if attempts["n"] >= 3:
                return real_exists(p) or str(p) == str(target)
            return False

        monkeypatch.setattr(pco.os.path, "exists", _appears_late)
        obs = observe_postcondition({"path_exists": str(target), "settle_timeout_ms": 3000})
        assert obs.verified is True

    def test_malformed_settle_value_degrades_to_single_check(self, monkeypatch):
        """A garbage timeout must not raise inside the pipeline."""
        monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda t: False)
        obs = observe_postcondition({"window_title": "x", "settle_timeout_ms": "not-a-number"})
        assert obs.verified is False
        assert obs.tier_used == "window"


# ══════════════════════════════════════════════════════════════════════════════
# Browser intents — now wired, on top of the settle mechanism
# ══════════════════════════════════════════════════════════════════════════════
class TestBrowserIntentsAreWired:
    def test_web_navigation_derives_site_label_with_settle_window(self):
        derived = _derive_expected_state(
            {"intent": "WebNavigationIntent", "target": "https://github.com"}
        )
        assert derived["window_title"] == "github"
        assert derived["settle_timeout_ms"] > 0

    def test_media_streaming_defaults_to_youtube(self):
        derived = _derive_expected_state(
            {"intent": "MediaStreamingIntent", "target": "some song"}
        )
        assert derived["window_title"] == "youtube"
        assert derived["settle_timeout_ms"] > 0

    def test_media_streaming_honours_explicit_platform(self):
        """Platform lives in step['value'] — mirrors the executor's
        _resolve_url_template(step, default_platform='youtube')."""
        derived = _derive_expected_state(
            {"intent": "MediaStreamingIntent", "target": "some song", "value": "spotify"}
        )
        assert derived["window_title"] == "spotify"


class TestGlobRecentTier:
    """For actions whose output filename is generated at execution time, so the
    derivation site cannot know the exact path in advance."""

    def test_verified_when_a_fresh_match_exists(self, tmp_path):
        (tmp_path / "SentinAL_Screenshot_20260804_120000.png").write_bytes(b"x")
        obs = observe_postcondition({
            "glob_recent": str(tmp_path / "SentinAL_Screenshot_*.png"),
            "within_seconds": 120,
        })
        assert obs.verified is True
        assert obs.tier_used == "filesystem"

    def test_unverified_when_no_file_matches(self, tmp_path):
        obs = observe_postcondition({"glob_recent": str(tmp_path / "nothing_*.png")})
        assert obs.verified is False
        assert obs.tier_used == "filesystem"

    def test_stale_match_does_not_count(self, tmp_path):
        """The freshness bound is the whole point: a screenshot from last week
        matching the same pattern is not evidence this step just took one."""
        old = tmp_path / "SentinAL_Screenshot_old.png"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 9999, time.time() - 9999))
        obs = observe_postcondition({
            "glob_recent": str(tmp_path / "SentinAL_Screenshot_*.png"),
            "within_seconds": 60,
        })
        assert obs.verified is False
        assert "no file newer" in obs.detail

    def test_picks_the_newest_match_for_reporting(self, tmp_path):
        (tmp_path / "SentinAL_Screenshot_a.png").write_bytes(b"x")
        newest = tmp_path / "SentinAL_Screenshot_b.png"
        newest.write_bytes(b"x")
        os.utime(newest, None)
        obs = observe_postcondition({
            "glob_recent": str(tmp_path / "SentinAL_Screenshot_*.png"),
            "within_seconds": 120,
        })
        assert obs.verified is True

    def test_malformed_within_seconds_degrades_to_default(self, tmp_path):
        (tmp_path / "SentinAL_Screenshot_x.png").write_bytes(b"x")
        obs = observe_postcondition({
            "glob_recent": str(tmp_path / "SentinAL_Screenshot_*.png"),
            "within_seconds": "not-a-number",
        })
        assert obs.verified is True


class TestWindowManagementDerivation:
    def test_screenshot_request_derives_a_glob_check(self):
        derived = _derive_expected_state(
            {"intent": "WindowManagementIntent", "prompt": "take a screenshot", "target": ""}
        )
        assert derived is not None
        assert "SentinAL_Screenshot_" in derived["glob_recent"]
        assert derived["within_seconds"] > 0

    def test_non_screenshot_window_actions_are_not_derived(self):
        """The handler picks its action via an LLM at execution time, so this
        site cannot know what will happen. Snap/minimize also leave no durable
        artifact to check."""
        for prompt in ("snap this window left", "minimize everything", "maximize"):
            assert _derive_expected_state(
                {"intent": "WindowManagementIntent", "prompt": prompt, "target": ""}
            ) is None

    def test_matches_the_handlers_own_fallback_signal(self):
        """handle_window_management()'s no-LLM fallback is
        `action = "screenshot" if "screenshot" in prompt_text.lower()`. Keying on
        the same signal means this cannot disagree with the handler more often
        than the handler disagrees with itself."""
        assert _derive_expected_state(
            {"intent": "WindowManagementIntent", "prompt": "", "target": "screenshot please"}
        ) is not None


class TestSiteLabelExtraction:
    @pytest.mark.parametrize(("target", "expected"), [
        ("https://www.youtube.com", "youtube"),
        ("https://github.com", "github"),
        ("http://mail.google.com", "google"),
        ("https://www.youtube.com/watch?v=abc123", "youtube"),
        ("github", "github"),
        ("spotify", "spotify"),
        ("https://open.spotify.com/search/x", "spotify"),
        ("www.netflix.com", "netflix"),
        ("https://localhost:3000", "localhost"),
    ])
    def test_reduces_target_to_brand_label(self, target, expected):
        """Window titles are page titles ('GitHub · Where software is built'),
        which contain the brand but never the full hostname — so matching on
        'www.github.com' would fail on a page that is plainly open."""
        assert _site_label(target) == expected

    def test_empty_target_yields_no_label(self):
        assert _site_label("") is None
        assert _site_label(None) is None


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
