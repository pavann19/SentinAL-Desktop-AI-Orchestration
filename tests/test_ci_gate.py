"""The aggregate CI result must never turn incomplete validation green."""
import unittest

from scripts.ci_gate import unsuccessful_jobs


class RequiredChecksTests(unittest.TestCase):
    def test_accepts_all_successful_jobs(self):
        self.assertEqual(unsuccessful_jobs({"lint": {"result": "success"}, "test": {"result": "success"}}), [])

    def test_rejects_every_non_success_state(self):
        for state in ("failure", "cancelled", "skipped", "queued", "", None):
            with self.subTest(state=state):
                self.assertEqual(unsuccessful_jobs({"test": {"result": state}}), ["test"])

    def test_rejects_missing_result(self):
        self.assertEqual(unsuccessful_jobs({"test": {}}), ["test"])

    def test_rejects_malformed_job(self):
        self.assertEqual(unsuccessful_jobs({"test": None}), ["test"])

    def test_rejects_empty_or_wrong_result_container(self):
        for value in ({}, [], None, "success"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unsuccessful_jobs(value)
