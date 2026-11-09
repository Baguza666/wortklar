"""
Tests for Goethe A1 Curriculum Hub, smart difficulty tracking, and category filtering.
"""

import os
import unittest
from wortklar.app import create_app
from wortklar.db import DEFAULT_DB_PATH
from wortklar.progress import load_goethe_words, get_goethe_word_info, record_word_interaction, get_a1_hub_data


class GoetheA1HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ.get("WORTKLAR_DB", DEFAULT_DB_PATH)
        if not os.path.exists(cls.db_path):
            raise unittest.SkipTest(f"Database file not found at {cls.db_path}.")
        cls.app = create_app(db_path=cls.db_path)
        cls.client = cls.app.test_client()

    def test_goethe_words_loaded(self):
        """Verify Goethe A1 words list loads and contains key A1 words."""
        words = load_goethe_words()
        self.assertGreater(len(words), 400)
        kaffee = get_goethe_word_info("Kaffee")
        self.assertIsNotNone(kaffee)
        self.assertEqual(kaffee["category"], "food")
        self.assertEqual(kaffee["article"], "der")

    def test_hub_endpoint(self):
        """Verify /api/a1/hub endpoint returns stats and wordlist."""
        res = self.client.get("/api/a1/hub")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("stats", data)
        self.assertIn("words", data)
        self.assertIn("categories", data)
        self.assertGreater(data["stats"]["total"], 400)

    def test_category_filter(self):
        """Verify filtering words by category."""
        res = self.client.get("/api/a1/hub?category=food")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        for w in data["words"]:
            self.assertEqual(w["category"], "food")

    def test_track_interaction_and_smart_difficulty(self):
        """Verify tracking word interaction and auto-upgrading to hard after 3 lookups."""
        record_word_interaction("testwort", action="reset")
        p1 = record_word_interaction("testwort", action="lookup")
        self.assertEqual(p1["lookup_count"], 1)
        self.assertEqual(p1["status"], "learning")

        record_word_interaction("testwort", action="lookup")
        p3 = record_word_interaction("testwort", action="lookup")
        self.assertEqual(p3["lookup_count"], 3)
        self.assertEqual(p3["difficulty"], "hard")

        pm = record_word_interaction("testwort", action="master")
        self.assertEqual(pm["status"], "mastered")
