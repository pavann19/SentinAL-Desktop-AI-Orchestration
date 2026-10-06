"""Regression tests for target extraction fallback."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.processor import _FALLBACK_STRIP_PATTERNS


def _strip(intent: str, query: str) -> str:
    pattern = _FALLBACK_STRIP_PATTERNS[intent]
    return re.sub(pattern, "", query, flags=re.IGNORECASE).strip()


class TestFallbackCoversEveryTargetRequiringIntent:
    """The five intents processor.py's needs_target requires a target for.
    Missing an entry here means that intent falls through to an empty
    target with no fallback at all, exactly the bug this file guards."""

    @pytest.mark.parametrize("intent", [
        "ApplicationLaunchIntent", "WebNavigationIntent", "FileDeletionIntent",
        "MediaStreamingIntent", "InformationRetrievalIntent",
    ])
    def test_pattern_exists_for_intent(self, intent):
        assert intent in _FALLBACK_STRIP_PATTERNS


class TestWebNavigationFallback:
    @pytest.mark.parametrize(("query", "expected"), [
        ("open github", "github"),
        ("open up github", "github"),
        ("go to github", "github"),
        ("navigate to github", "github"),
        ("visit github", "github"),
        ("take me to github", "github"),
        ("pull up github", "github"),
        ("browse to github", "github"),
        ("check out github", "github"),
        ("load github", "github"),
        ("Open GitHub", "GitHub"),  # case-insensitive match, target case preserved
    ])
    def test_strips_navigation_verb(self, query, expected):
        assert _strip("WebNavigationIntent", query) == expected

    def test_open_wikipedia_resolves_to_bare_site_name(self):
        """The exact case from the benchmark: 'open wikipedia in my browser'
        must reduce to something a site lookup can resolve, not stay as the
        full sentence."""
        result = _strip("WebNavigationIntent", "open wikipedia in my browser")
        assert result.lower().startswith("wikipedia")


class TestFileDeletionFallback:
    @pytest.mark.parametrize(("query", "expected"), [
        ("delete the file report.txt", "report.txt"),
        ("delete report.txt", "report.txt"),
        ("remove the file report.txt", "report.txt"),
        ("erase report.txt", "report.txt"),
        ("get rid of the file report.txt", "report.txt"),
        ("trash the file report.txt", "report.txt"),
        ("delete the folder old_project", "old_project"),
        ("remove the directory old_project", "old_project"),
    ])
    def test_strips_deletion_verb_and_object_noun(self, query, expected):
        assert _strip("FileDeletionIntent", query) == expected

    def test_absolute_windows_path_survives_stripping(self):
        result = _strip("FileDeletionIntent", r"delete the file C:\Users\test\report.txt")
        assert result == r"C:\Users\test\report.txt"


class TestApplicationLaunchFallback:
    @pytest.mark.parametrize(("query", "expected"), [
        ("open calculator", "calculator"),
        ("launch calculator", "calculator"),
        ("start calculator", "calculator"),
        ("run calculator", "calculator"),
        ("bring up calculator", "calculator"),
        ("fire up calculator", "calculator"),
        ("boot up calculator", "calculator"),
    ])
    def test_strips_launch_verb(self, query, expected):
        assert _strip("ApplicationLaunchIntent", query) == expected


class TestMediaAndInformationRetrievalFallbackUnchanged:
    """Guards that extending the fallback to 5 intents did not alter the
    behaviour of the 2 that already had it."""

    def test_media_streaming_strips_play(self):
        assert _strip("MediaStreamingIntent", "play baahubali songs") == "baahubali songs"

    def test_information_retrieval_strips_search_for(self):
        result = _strip("InformationRetrievalIntent", "search for best restaurants in hyderabad")
        assert result == "best restaurants in hyderabad"


class TestFallbackDoesNotOverStrip:
    def test_web_navigation_preserves_a_target_that_contains_the_verb_word(self):
        """'open' only strips as a LEADING verb (anchored with ^), not from
        inside the target - 'go to open source projects' must not become
        'source projects'."""
        result = _strip("WebNavigationIntent", "go to open source projects")
        assert result == "open source projects"
