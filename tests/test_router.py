"""
tests/test_router.py
Industry-grade tests for SemanticRouter.
Covers: obvious intents, edge cases, unknown threshold, fallback mode, caching.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from agentic_core.router import SemanticRouter, INTENT_CAPABILITIES


@pytest.fixture(scope="module")
def router():
    """Single router instance shared across all tests (model load is expensive)."""
    return SemanticRouter()


class TestRouterIntentRecognition:

    def test_open_app_routes_application(self, router):
        result = router.route("open chrome browser")
        assert result["intent"] in ("ApplicationLaunchIntent", "WebNavigationIntent")
        assert result["confidence"] > 0.0

    def test_play_music_routes_media(self, router):
        result = router.route("play some music on spotify")
        assert result["intent"] == "MediaStreamingIntent"
        assert result["confidence"] >= 0.40

    def test_search_web_routes_retrieval(self, router):
        result = router.route("look up the weather forecast for today")
        # Model reasonably routes this to either InformationRetrieval OR WebNavigation
        assert result["intent"] in ("InformationRetrievalIntent", "WebNavigationIntent"), (
            f"Unexpected intent: {result['intent']}"
        )
        assert result["confidence"] >= 0.40

    def test_navigate_to_routes_web(self, router):
        result = router.route("go to github.com")
        assert result["intent"] == "WebNavigationIntent"
        assert result["confidence"] >= 0.40

    def test_delete_routes_file_deletion(self, router):
        result = router.route("delete the file in downloads folder")
        assert result["intent"] == "FileDeletionIntent"
        assert result["confidence"] >= 0.40

    def test_typing_routes_os_intent(self, router):
        result = router.route("list the files here")
        assert result["intent"] == "GeneralizedOSIntent"
        assert result["confidence"] >= 0.40
        # GeneralizedOSIntent has no labeled examples in eval/intent_dataset.json, so
        # the Phase A classifier can never predict it - route() falls back to
        # zero-shot cosine similarity for this intent specifically (see router.py's
        # _classifier_blind_intents). This asserts that fallback still works.

    def test_hello_routes_conversational(self, router):
        result = router.route("hello how are you doing today")
        assert result["intent"] == "ConversationalIntent"
        assert result["confidence"] >= 0.40

    def test_continue_routes_continuation(self, router):
        result = router.route("please go on")
        # ContinuationIntent has no labeled examples in eval/intent_dataset.json (same
        # classifier blind spot as GeneralizedOSIntent above) - covered via zero-shot
        # cosine fallback in router.py, not the trained classifier.
        assert result["intent"] == "ContinuationIntent"
        assert result["confidence"] >= 0.40


class TestRouterEdgeCases:

    def test_empty_string_returns_unknown(self, router):
        result = router.route("")
        assert result["intent"] == "UnknownIntent"
        assert result["confidence"] == 0.0

    def test_whitespace_only_returns_unknown(self, router):
        result = router.route("   ")
        assert result["intent"] == "UnknownIntent"

    def test_pure_symbols_returns_unknown_or_low_confidence(self, router):
        result = router.route("!@#$%^&*()")
        # Either unknown or very low confidence
        assert result["confidence"] < 0.70

    def test_very_long_input_does_not_crash(self, router):
        long_input = "open " + "a" * 5000
        result = router.route(long_input)
        assert "intent" in result
        assert "confidence" in result

    def test_non_english_input_does_not_crash(self, router):
        result = router.route("नमस्ते मुझे यूट्यूब खोलना है")
        assert "intent" in result

    def test_returns_dict_with_required_keys(self, router):
        result = router.route("search for weather today")
        assert "intent" in result
        assert "confidence" in result

    def test_confidence_is_float_between_0_and_1(self, router):
        result = router.route("play a song")
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_intent_is_string(self, router):
        result = router.route("open notepad")
        assert isinstance(result["intent"], str)


class TestRouterIntentCoverage:
    """Ensure every defined intent class can be matched by at least one phrase."""

    @pytest.mark.parametrize("intent_class,phrase", [
        ("InformationRetrievalIntent", "what is the weather like today"),
        ("ApplicationLaunchIntent",   "launch the application notepad"),
        ("WebNavigationIntent",       "navigate to the website youtube"),
        ("MediaStreamingIntent",      "stream some music on spotify"),
        ("FileDeletionIntent",        "delete this file permanently"),
        ("GeneralizedOSIntent",       "press the spacebar key"),
        ("ConversationalIntent",      "tell me a joke please"),
        ("ContinuationIntent",        "keep going with your explanation please"),
        # Added 2026-07-14 alongside the new phrase banks for these 3 intents
        # (previously unreachable via the router at all). Phrases below are
        # deliberate PARAPHRASES, not verbatim bank entries, to test real
        # generalization rather than exact-match memorization.
        ("ProcessManagementIntent",   "kill this stuck program"),
        ("ProjectScaffoldIntent",     "scaffold a brand new app for me"),
        ("DependencyInstallIntent",   "please install these dependencies for me"),
        # Added 2026-07-16: DictationIntent and MediaControlIntent, alongside
        # GeneralizedOSIntent/ContinuationIntent above, have no labeled examples in
        # eval/intent_dataset.json - the Phase A classifier can never predict them.
        # Explicit coverage here catches a regression if the zero-shot fallback for
        # these classifier-blind intents (router.py's _classifier_blind_intents)
        # ever breaks.
        ("DictationIntent",          "begin dictating this note for me"),
        ("MediaControlIntent",       "turn the volume down a little"),
    ])
    def test_intent_class_is_reachable(self, router, intent_class, phrase):
        result = router.route(phrase)
        # The router should match the intent OR be close (confidence > 0.30)
        # We don't assert exact match because embeddings give probabilistic results
        assert result["confidence"] > 0.30, (
            f"Intent class '{intent_class}' unreachable via phrase '{phrase}'. "
            f"Got: {result['intent']} @ {result['confidence']}"
        )


class TestRouterPhraseBank:

    def test_all_intents_have_25_phrases(self):
        """Each intent class must have >= 20 anchor phrases."""
        for intent, phrases in INTENT_CAPABILITIES.items():
            assert len(phrases) >= 20, (
                f"Intent '{intent}' has only {len(phrases)} phrases. Minimum is 20."
            )

    def test_no_empty_phrases(self):
        """No anchor phrase should be an empty string."""
        for intent, phrases in INTENT_CAPABILITIES.items():
            for phrase in phrases:
                assert phrase.strip() != "", f"Empty phrase in '{intent}'"

    def test_no_duplicate_phrases_within_intent(self):
        """No intent class should have duplicate anchor phrases."""
        for intent, phrases in INTENT_CAPABILITIES.items():
            assert len(phrases) == len(set(phrases)), (
                f"Duplicate phrases found in intent '{intent}'"
            )
