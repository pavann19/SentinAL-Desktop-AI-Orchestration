"""
tests/test_benchmark_regressions.py

Unit-level regression tests for the five defects found by the 40x3 end-to-end
benchmark baseline (74.2%, commit 9cb48b6). Each test names the benchmark task
that exposed it, so the link between the measurement and the fix stays visible.

These are the cheap, fast guard rails; benchmarks/run_benchmark.py remains the
real end-to-end verification.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.processor import (
    deterministic_fast_path,
    extract_app_query,
    split_multistep,
)


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1 — target extraction (5 of 11 baseline failures)
# ══════════════════════════════════════════════════════════════════════════════
class TestAppQueryExtraction:
    """Benchmark: app_calc_article, app_calc_casual, app_calc_indirect all
    failed 3/3 while app_calc_plain passed 3/3 — same intent, same app,
    defeated by an article and two unrecognised verbs."""

    @pytest.mark.parametrize(("utterance", "expected"), [
        ("open calculator", "calculator"),
        ("open the calculator", "calculator"),
        ("bring up calculator", "calculator"),
        ("i need to do some math, open the calculator", "calculator"),
        ("can you launch notepad for me", "notepad"),
        ("please open up notepad", "notepad"),
        ("start the paint app", "paint"),
        ("pull up chrome", "chrome"),
        ("fire up spotify", "spotify"),
        ("run notepad please", "notepad"),
        ("open my calculator", "calculator"),
        ("i want to jot something down, open notepad", "notepad"),
    ])
    def test_reduces_to_bare_app_name(self, utterance, expected):
        assert extract_app_query(utterance) == expected

    @pytest.mark.parametrize("utterance", [
        "show me the running programs",
        "what processes are running",
        "hello, who are you",
        "what can you do",
        "delete the file C:/tmp/x.txt",
    ])
    def test_returns_none_without_a_launch_verb(self, utterance):
        """Must not coerce non-launch utterances into an app launch — that is
        how 'show me the running programs' became an ApplicationLaunchIntent."""
        assert extract_app_query(utterance) is None

    def test_running_does_not_match_the_run_verb(self):
        """Word-boundary check: 'running' must not be read as the verb 'run'."""
        assert extract_app_query("show me the running programs") is None

    def test_empty_input_is_safe(self):
        assert extract_app_query("") is None
        assert extract_app_query(None) is None


class TestFastPathResolvesPhrasings:
    @pytest.mark.parametrize("utterance", [
        "open calculator", "open the calculator", "bring up calculator",
        "i need to do some math, open the calculator",
    ])
    def test_calculator_phrasings_all_resolve(self, utterance):
        plan = deterministic_fast_path(utterance)
        assert plan is not None, f"{utterance!r} did not resolve via the fast path"
        assert plan[0]["intent"] == "ApplicationLaunchIntent"
        assert plan[0]["target"] == "calc"


# ══════════════════════════════════════════════════════════════════════════════
# Bug 4 — router misroute
# ══════════════════════════════════════════════════════════════════════════════
class TestProcessListRouting:
    """Benchmark: proc_list_casual ('show me the running programs') routed to
    ApplicationLaunchIntent with an unusable target, failing 3/3."""

    @pytest.mark.parametrize("utterance", [
        "show me the running programs",
        "show me the running processes",
        "list the running apps",
        "what processes are running",
        "what programs are running",
        "display the active applications",
        "list all processes",
    ])
    def test_routes_to_process_management(self, utterance):
        plan = deterministic_fast_path(utterance)
        assert plan is not None, f"{utterance!r} was not caught by the fast path"
        assert plan[0]["intent"] == "ProcessManagementIntent"
        assert plan[0]["action"] == "list"

    @pytest.mark.parametrize("utterance", ["open notepad", "close notepad", "what time is it"])
    def test_does_not_hijack_unrelated_commands(self, utterance):
        plan = deterministic_fast_path(utterance)
        if plan:
            assert plan[0]["intent"] != "ProcessManagementIntent"


# ══════════════════════════════════════════════════════════════════════════════
# Bug 5 — multi-step splitting
# ══════════════════════════════════════════════════════════════════════════════
class TestMultiStepSplitting:
    """Benchmark: multi_open_two_apps ('open notepad and calculator') produced a
    single ApplicationLaunchIntent, so one of the two apps was never opened."""

    def test_splits_two_apps_with_a_one_word_second_part(self):
        parts = split_multistep("open notepad and calculator")
        assert len(parts) == 2, f"expected 2 steps, got {parts}"

    def test_still_refuses_unresolvable_one_word_splits(self):
        """The original guard must survive: a single-word part the registry
        cannot resolve is an object fragment, not a command, so no split."""
        parts = split_multistep("search for pizza and calories")
        assert len(parts) == 1, f"object fragment was wrongly split: {parts}"

    def test_known_limitation_multiword_object_phrases_still_split(self):
        """Documents pre-existing behaviour, NOT a regression.

        split_multistep()'s docstring long claimed it prevents
        'search for pizza and calorie info' from splitting. It never did:
        'calorie info' is exactly 2 words and satisfies the word-count guard.
        Verified identical against the pre-fix code. Correctly rejecting this
        needs semantic understanding of whether a fragment is a standalone
        command, which the deterministic splitter does not attempt.

        Asserted so the real behaviour is pinned and the limitation stays
        visible rather than being mistaken for a new bug later.
        """
        parts = split_multistep("search for pizza and calorie info")
        assert len(parts) == 2

    def test_splits_two_full_clauses(self):
        parts = split_multistep("open notepad and then close it")
        assert len(parts) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2 — sys_utility reporting failure as success
# ══════════════════════════════════════════════════════════════════════════════
class TestSysUtilityFailsHonestly:
    """Benchmark: sys_light_mode and unimpl_timer both returned
    'I didn't catch the system utility command.' with execution="Success",
    because api_wrapper keys status on the ERROR prefix."""

    def test_empty_input_is_error_prefixed(self):
        from capabilities.system.sys_utility import handle_sys_utility
        result = handle_sys_utility("", "")
        assert result.startswith("ERROR"), (
            "A failure message without the ERROR prefix is reported to the user "
            "as execution='Success'."
        )

    def test_accepts_prompt_when_target_is_empty(self):
        """Extraction returned an empty target for 'switch to light mode'; the
        handler must fall back to the prompt like every comparable handler."""
        from capabilities.system import sys_utility

        captured = {}

        class _FakeLLM:
            def invoke(self, msgs):
                captured["prompt"] = str(msgs)
                class _R:
                    content = "light_mode"
                return _R()

        with patch.object(sys_utility, "_get_routing_llm", create=True, return_value=_FakeLLM()), \
             patch("agentic_core.processor._get_routing_llm", return_value=_FakeLLM()), \
             patch("subprocess.run") as run:
            run.return_value = None
            result = sys_utility.handle_sys_utility("", "switch to light mode")

        assert "light mode" in captured.get("prompt", "").lower()
        assert not result.startswith("ERROR"), result


# ══════════════════════════════════════════════════════════════════════════════
# Bug 3 — silent Google-search fallback
# ══════════════════════════════════════════════════════════════════════════════
class TestWebNavigationHonesty:
    """Benchmark: web_wikipedia and web_stackoverflow opened
    google.com/search?q=... while responding 'I have opened the website ...'."""

    @pytest.mark.parametrize(("target", "expected_host"), [
        ("wikipedia", "wikipedia.org"),
        ("stack overflow", "stackoverflow.com"),
        ("stackoverflow", "stackoverflow.com"),
    ])
    def test_known_sites_navigate_directly(self, target, expected_host):
        from agentic_core import executor

        opened = {}
        with patch.object(executor.webbrowser, "open", lambda u: opened.setdefault("url", u)):
            executor.execute_pipeline([{"intent": "WebNavigationIntent", "target": target}])

        assert expected_host in opened.get("url", ""), opened
        assert "google.com/search" not in opened.get("url", "")

    def test_unresolvable_target_does_not_claim_the_site_was_opened(self):
        from agentic_core import executor

        with patch.object(executor.webbrowser, "open", lambda u: None):
            result = executor.execute_pipeline(
                [{"intent": "WebNavigationIntent", "target": "!!"}]
            )

        assert "I have opened the website" not in result
