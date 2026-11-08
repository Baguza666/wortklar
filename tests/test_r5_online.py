"""
Test suite for R5: Online Wiktionary Verification and Optional Gemini Integration.
Tests live Wiktionary MediaWiki Action API, omitted-entry test database,
wrong-language rejection, bad evidence IDs, error handling, CSRF protections,
and structured outputs.
"""

import json
import os
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from wortklar.app import create_app
from wortklar.db import init_schema
from wortklar.online import (
    check_wiktionary_evidence,
    check_word_online,
    generate_gemini_explanation,
    GeminiExplanationSchema
)


class TestR5Online(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an isolated test database with a known entry ('Kummerspeck') omitted
        cls.test_db_path = "tests/test_omitted.db"
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)

        conn = sqlite3.connect(cls.test_db_path)
        init_schema(conn)
        # Populate with basic Haus entry, intentionally omitting Kummerspeck
        conn.execute("""
            INSERT INTO entries (headword, part_of_speech, gender, article, source_edition, source_url)
            VALUES ('Haus', 'noun', 'neuter', 'das', 'en', 'https://en.wiktionary.org/wiki/Haus')
        """)
        eid = conn.execute("SELECT id FROM entries WHERE headword = 'Haus'").fetchone()[0]
        conn.execute("""
            INSERT INTO search_index (term, lower_term, folded_term, entry_id, is_lemma, rank_priority)
            VALUES ('Haus', 'haus', 'haus', ?, 1, 1)
        """, (eid,))
        conn.commit()
        conn.close()

        cls.app = create_app(db_path=cls.test_db_path)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            os.remove(cls.test_db_path)

    def test_01_real_wiktionary_response_live(self):
        """Verify real MediaWiki Action API response on live entry."""
        res = check_wiktionary_evidence("Kummerspeck")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("matched_title"), "Kummerspeck")
        self.assertGreater(res.get("revid", 0), 0)
        self.assertTrue(res.get("source_url", "").startswith("https://de.wiktionary.org/wiki/"))

        # Verify evidence records
        evidence = res.get("evidence", [])
        self.assertGreater(len(evidence), 0)
        for ev in evidence:
            self.assertIn("id", ev)
            self.assertIn("title", ev)
            self.assertIn("revid", ev)
            self.assertIn("text", ev)
            self.assertLessEqual(len(ev["text"]), 255)

        # Verify mapped facts
        online_entry = res.get("online_entry", {})
        self.assertEqual(online_entry.get("headword"), "Kummerspeck")
        self.assertEqual(online_entry.get("article"), "der")
        self.assertEqual(online_entry.get("gender"), "masculine")
        self.assertIn("no plural", online_entry.get("plural", "").lower())
        self.assertGreater(len(online_entry.get("meanings", [])), 0)

    def test_02_omitted_entry_missing_word_path(self):
        """
        Verify missing word path:
        1. Local lookup for omitted word returns no match.
        2. Check online finds the real word and returns evidence without disturbing local db.
        """
        # Step 1: Local lookup returns no match
        resp_local = self.client.get("/api/lookup?q=Kummerspeck")
        self.assertEqual(resp_local.status_code, 200)
        data_local = resp_local.get_json()
        self.assertEqual(len(data_local["exact_entries"]), 0)

        # Step 2: Online check retrieves live evidence
        resp_online = self.client.post(
            "/api/check_online",
            json={"word": "Kummerspeck"},
            headers={"Sec-Fetch-Site": "same-origin"}
        )
        self.assertEqual(resp_online.status_code, 200)
        data_online = resp_online.get_json()
        wiktionary = data_online.get("wiktionary", {})
        self.assertEqual(wiktionary.get("status"), "success")
        self.assertEqual(wiktionary.get("matched_title"), "Kummerspeck")

        # Step 3: Verify local database was not corrupted and still works
        resp_local_haus = self.client.get("/api/lookup?q=Haus")
        data_haus = resp_local_haus.get_json()
        self.assertEqual(len(data_haus["exact_entries"]), 1)
        self.assertEqual(data_haus["exact_entries"][0]["headword"], "Haus")

    def test_03_wrong_language_page(self):
        """Verify that a page existing on Wiktionary but lacking German is rejected with non_german_page."""
        res = check_wiktionary_evidence("bonjour")
        self.assertEqual(res.get("status"), "non_german_page")
        self.assertIn("does not contain a German", res.get("message", ""))
        self.assertTrue(res.get("source_url", "").startswith("https://"))

    def test_04_nonexistent_entry(self):
        """Verify that a completely nonexistent word returns not_found."""
        res = check_wiktionary_evidence("qxjzvk987nonsenseword")
        self.assertEqual(res.get("status"), "not_found")

    def test_05_bounded_capitalization_variant(self):
        """Verify lowercase 'kummerspeck' resolves to capitalized 'Kummerspeck'."""
        res = check_wiktionary_evidence("kummerspeck")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("matched_title"), "Kummerspeck")

    def test_06_cross_origin_blocking(self):
        """Verify cross-origin requests to /api/check_online are rejected."""
        resp = self.client.post(
            "/api/check_online",
            json={"word": "Haus"},
            headers={"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_07_gemini_smoke_or_pending(self):
        """
        Check Gemini configuration:
        - If key is present: run live smoke test and verify response schema without logging key.
        - If key is absent: verify ai_status is 'gemini_disabled' and Wiktionary facts still work.
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            evidence = [
                {"id": 1, "title": "Haus", "revid": 100, "text": "Substantiv n, Gebäude zum Wohnen."},
                {"id": 2, "title": "Haus", "revid": 100, "text": "Plural: Häuser"}
            ]
            explanation, status = generate_gemini_explanation("Haus", evidence)
            self.assertEqual(status, "success")
            self.assertIsNotNone(explanation)
            self.assertIn("english_explanation", explanation)
            self.assertIn("evidence_ids", explanation)
            # Ensure key is never present in explanation
            self.assertNotIn(api_key, json.dumps(explanation))
            print("\n[Gemini Provider Smoke Test] LIVE GEMINI CALL PASSED!")
        else:
            evidence = [{"id": 1, "title": "Haus", "revid": 100, "text": "Gebäude"}]
            explanation, status = generate_gemini_explanation("Haus", evidence)
            self.assertIsNone(explanation)
            self.assertEqual(status, "gemini_disabled")
            print("\n[Gemini Provider Smoke Test] GEMINI_API_KEY absent; marked LIVE VERIFICATION PENDING.")

    def test_08_gemini_fixture_adapter_and_bad_evidence_ids(self):
        """Verify that server validates referenced evidence IDs and strips hallucinations."""
        valid_evidence = [
            {"id": 1, "title": "Haus", "revid": 100, "text": "Gebäude zum Wohnen"},
            {"id": 2, "title": "Haus", "revid": 100, "text": "Plural Häuser"}
        ]

        # Mock model response returning ID 1 and non-existent ID 999
        mock_model_response = MagicMock()
        mock_model_response.text = json.dumps({
            "english_explanation": "A building where people live; a house.",
            "evidence_ids": [1, 999],  # 999 is invalid!
            "learner_note": "A1 core noun."
        })

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_model_response

            explanation, status = generate_gemini_explanation("Haus", valid_evidence, api_key="fake_key_for_test")
            self.assertEqual(status, "success")
            self.assertIsNotNone(explanation)
            # Server must have filtered out 999!
            self.assertEqual(explanation["evidence_ids"], [1])
            self.assertNotIn(999, explanation["evidence_ids"])

    def test_09_gemini_quota_and_timeout_errors_leave_lookup_working(self):
        """Verify that 429 quota errors or timeouts leave Wiktionary facts intact."""
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            # Simulate 429 quota error
            mock_client.models.generate_content.side_effect = Exception("429 Resource has been exhausted (quota)")

            evidence = [{"id": 1, "title": "Haus", "revid": 100, "text": "Gebäude"}]
            explanation, status = generate_gemini_explanation("Haus", evidence, api_key="fake_key")
            self.assertIsNone(explanation)
            self.assertEqual(status, "rate_limited")

        # Simulate timeout
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("Request timeout")

            explanation, status = generate_gemini_explanation("Haus", evidence, api_key="fake_key")
            self.assertIsNone(explanation)
            self.assertEqual(status, "timeout")

    def test_10_typing_makes_zero_external_requests(self):
        """Verify that autocomplete /api/suggest never calls external APIs."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            resp = self.client.get("/api/suggest?q=haus")
            self.assertEqual(resp.status_code, 200)
            # urlopen should NEVER have been called!
            mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

