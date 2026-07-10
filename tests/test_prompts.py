"""
tests/test_prompts.py
Tests for config/prompts.py — verifies all system prompts are well-formed.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from config.prompts import EXTRACTION_SYSTEM_PROMPT, CORRECTION_SYSTEM_PROMPT


class TestExtractionSystemPrompt:

    def test_is_non_empty_string(self):
        assert isinstance(EXTRACTION_SYSTEM_PROMPT, str)
        assert len(EXTRACTION_SYSTEM_PROMPT) > 100

    def test_contains_allowed_intents(self):
        required_intents = [
            "ConversationalIntent", "ApplicationLaunchIntent",
            "WebNavigationIntent", "InformationRetrievalIntent",
            "GeneralizedOSIntent", "MediaStreamingIntent",
            "FileDeletionIntent", "ContinuationIntent"
        ]
        for intent in required_intents:
            assert intent in EXTRACTION_SYSTEM_PROMPT, f"Missing intent: {intent}"

    def test_instructs_json_only_output(self):
        assert "JSON" in EXTRACTION_SYSTEM_PROMPT or "json" in EXTRACTION_SYSTEM_PROMPT

    def test_no_trailing_whitespace_lines(self):
        lines = EXTRACTION_SYSTEM_PROMPT.split("\n")
        trailing = [l for l in lines if l != l.rstrip()]
        assert len(trailing) == 0, f"{len(trailing)} lines have trailing whitespace"

    def test_no_windows_crlf_line_endings(self):
        assert "\r\n" not in EXTRACTION_SYSTEM_PROMPT, "CRLF line endings detected in prompt"


class TestCorrectionSystemPrompt:

    def test_is_non_empty_string(self):
        assert isinstance(CORRECTION_SYSTEM_PROMPT, str)
        assert len(CORRECTION_SYSTEM_PROMPT) > 50

    def test_contains_output_only_rule(self):
        lower = CORRECTION_SYSTEM_PROMPT.lower()
        assert "output" in lower and ("only" in lower or "nothing" in lower)

    def test_contains_examples(self):
        assert "INPUT" in CORRECTION_SYSTEM_PROMPT or "input" in CORRECTION_SYSTEM_PROMPT

    def test_instructs_not_to_answer_questions(self):
        lower = CORRECTION_SYSTEM_PROMPT.lower()
        assert "never answer" in lower or "not answer" in lower or "do not answer" in lower

    def test_no_windows_crlf_line_endings(self):
        assert "\r\n" not in CORRECTION_SYSTEM_PROMPT
