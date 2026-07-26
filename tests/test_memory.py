import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from agentic_core.memory_hook import MemoryManager

class TestMemoryManager(unittest.TestCase):

    def setUp(self):
        # Use a temporary database for testing
        self.db_path = "test_memory_temp.db"
        self.manager = MemoryManager(db_path=self.db_path)

    def tearDown(self):
        self.manager.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_store_and_retrieve_template(self):
        self.manager.save_url_template("youtube", "https://youtube.com/search?q={query}")
        template = self.manager.get_url_template("youtube")
        self.assertEqual(template, "https://youtube.com/search?q={query}")

    def test_retrieve_non_existent_template(self):
        template = self.manager.get_url_template("non_existent")
        self.assertIsNone(template)

    def test_update_template(self):
        self.manager.save_url_template("google", "https://google.com/search?q={query}")
        self.manager.save_url_template("google", "https://google.com/new_search?q={query}")
        template = self.manager.get_url_template("google")
        self.assertEqual(template, "https://google.com/new_search?q={query}")

    def test_invalid_template_security(self):
        with self.assertRaises(ValueError):
            self.manager.save_url_template("malicious", "http://unsecure.com")
        with self.assertRaises(ValueError):
            self.manager.save_url_template("missing", "https://safe.com/no_placeholder")

    # Fix 4.8: New interaction history tests

    def test_log_and_retrieve_interaction(self):
        """log_interaction() must persist and be retrievable via get_recent_interactions."""
        self.manager.log_interaction("2026-04-21T00:00:00", "ConversationalIntent", "hello", "Success")
        rows = self.manager.get_recent_interactions(limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "ConversationalIntent")

    def test_get_context_for_prompt_format(self):
        """get_context_for_prompt() must return string starting with context header."""
        self.manager.log_interaction("2026-04-21T00:00:00", "ApplicationLaunchIntent", "chrome", "Success")
        context = self.manager.get_context_for_prompt(limit=1)
        self.assertIn("[PAST INTERACTION CONTEXT]", context)

    def test_get_context_limit_respected(self):
        """get_context_for_prompt(limit=1) must return only 1 interaction line."""
        for i in range(5):
            self.manager.log_interaction(f"2026-04-21T00:00:0{i}", "ConversationalIntent", f"q{i}", "Success")
        context = self.manager.get_context_for_prompt(limit=1)
        lines = [line for line in context.strip().split("\n") if line.startswith("- ")]
        self.assertEqual(len(lines), 1)

    def test_context_truncated_at_limit(self):
        """Context exceeding ~1000 chars must be truncated to prevent LLM bloat."""
        long_target = "x" * 500
        for i in range(4):
            self.manager.log_interaction("2026-04-21T00:00:00", "InformationRetrievalIntent", long_target, "Success")
        context = self.manager.get_context_for_prompt(limit=10)
        self.assertLessEqual(len(context), 1100, f"Context not truncated: {len(context)} chars")


if __name__ == '__main__':
    unittest.main()
