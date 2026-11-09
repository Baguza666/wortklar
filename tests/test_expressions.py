"""
Tests for fast indexed lookup and German expression / phrase breakdown with AI schema.
"""

import os
import unittest
from wortklar.app import create_app
from wortklar.db import DEFAULT_DB_PATH
from wortklar.online import GeminiExpressionExplanationSchema


class ExpressionAndSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ.get("WORTKLAR_DB", DEFAULT_DB_PATH)
        if not os.path.exists(cls.db_path):
            raise unittest.SkipTest(f"Database file not found at {cls.db_path}.")
        cls.app = create_app(db_path=cls.db_path)
        cls.client = cls.app.test_client()

    def test_fast_lookup_viele(self):
        """Verify indexed candidate lookup executes cleanly and returns 'viele'."""
        res = self.client.get("/api/lookup?q=viele")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("exact_entries", data)
        self.assertGreaterEqual(len(data["exact_entries"]), 1)
        self.assertEqual(data["exact_entries"][0]["headword"], "viele")

    def test_expression_phrase_breakdown(self):
        """Verify multi-word expression 'relativ klein' breaks down constituent words."""
        res = self.client.get("/api/lookup?q=relativ%20klein")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsNotNone(data.get("phrase_breakdown"))
        breakdown = data["phrase_breakdown"]
        self.assertEqual(breakdown["phrase"], "relativ klein")
        self.assertGreaterEqual(len(breakdown["words"]), 2)
        headwords = [w["headword"] for w in breakdown["words"]]
        self.assertIn("relativ", headwords)
        self.assertIn("klein", headwords)

    def test_gemini_expression_schema_validation(self):
        """Verify GeminiExpressionExplanationSchema validates structured AI payload."""
        sample_payload = {
            "phrase": "relativ klein",
            "english_meaning": "relatively small",
            "breakdown": "relativ (adverb) + klein (adjective)",
            "example_sentence": "Mein Zimmer ist relativ klein.",
            "example_translation": "My room is relatively small.",
            "learner_note": "Use relativ before adjectives to soften them."
        }
        validated = GeminiExpressionExplanationSchema.model_validate(sample_payload)
        self.assertEqual(validated.phrase, "relativ klein")
        self.assertEqual(validated.english_meaning, "relatively small")
        self.assertEqual(validated.example_sentence, "Mein Zimmer ist relativ klein.")
