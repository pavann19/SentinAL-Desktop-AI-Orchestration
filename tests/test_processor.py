import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from agentic_core.processor import extract_intent

class TestProcessor(unittest.TestCase):

    def test_greeting_bypass_returns_conversational(self):
        """Greeting triggers hardcoded bypass before any LLM call."""
        steps = extract_intent("hello")
        self.assertEqual(steps[0]["intent"], "ConversationalIntent")
        self.assertIn("speech_response", steps[0])

    def test_empty_input_returns_unknown(self):
        """Empty or very short input must return UnknownIntent immediately."""
        steps = extract_intent("  ")
        self.assertEqual(steps[0]["intent"], "UnknownIntent")

    def test_hey_greeting_returns_conversational(self):
        """'hey' (in _GREETING_TRIGGERS) must return ConversationalIntent."""
        steps = extract_intent("hey")
        self.assertEqual(steps[0]["intent"], "ConversationalIntent")

    def test_good_morning_returns_conversational(self):
        """'good morning' must return ConversationalIntent via greeting bypass."""
        steps = extract_intent("good morning")
        self.assertEqual(steps[0]["intent"], "ConversationalIntent")

    def test_time_fast_path(self):
        """'what time is it' must hit the deterministic fast path."""
        steps = extract_intent("what time is it")
        self.assertEqual(steps[0]["intent"], "ConversationalIntent")
        # Response must contain a formatted time
        msg = steps[0].get("message", "")
        self.assertIn("time", msg.lower())


if __name__ == '__main__':
    unittest.main()
