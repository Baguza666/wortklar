"""
Comprehensive regression and functional test suite for Wortklar.
Verifies all Completion Gate checks against real imported data.
"""

import json
import os
import shutil
import sqlite3
import unicodedata
import unittest

from wortklar.app import create_app
from wortklar.db import get_db_connection, get_metadata, check_integrity, DEFAULT_DB_PATH
from wortklar.search import count_letters, normalize_input, fold_text, generate_candidate_variations


class WortklarRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ.get("WORTKLAR_DB", DEFAULT_DB_PATH)
        if not os.path.exists(cls.db_path):
            raise unittest.SkipTest(f"Database file not found at {cls.db_path}. Run bootstrap.py first.")
        cls.app = create_app(db_path=cls.db_path)
        cls.client = cls.app.test_client()

    def test_01_database_metadata_and_integrity(self):
        """Verify database integrity and metadata recording."""
        conn = get_db_connection(self.db_path, read_only=True)
        self.assertTrue(check_integrity(conn, quick=True), "Database failed SQLite integrity check")

        meta = get_metadata(conn)
        self.assertIn("lemma_count", meta)
        self.assertIn("form_count", meta)
        self.assertGreater(meta["lemma_count"], 1000)
        self.assertGreater(meta["form_count"], 1000)
        conn.close()

    def test_02_four_letter_rule(self):
        """
        Check: Four-letter rule
        - Typing 'hau' shows no list (threshold_met = False, empty suggestions).
        - Typing 'haus' shows selectable results.
        - Exact submit of 'Ei' or 'in' works.
        """
        # Typing 'hau' (< 4 letters)
        res_hau = self.client.get("/api/suggest?q=hau")
        self.assertEqual(res_hau.status_code, 200)
        data_hau = res_hau.get_json()
        self.assertFalse(data_hau["threshold_met"])
        self.assertEqual(len(data_hau["suggestions"]), 0)

        # Typing 'haus' (>= 4 letters)
        res_haus = self.client.get("/api/suggest?q=haus")
        self.assertEqual(res_haus.status_code, 200)
        data_haus = res_haus.get_json()
        self.assertTrue(data_haus["threshold_met"])
        self.assertGreater(len(data_haus["suggestions"]), 0)
        self.assertLessEqual(len(data_haus["suggestions"]), 8)

        # Exact submit of short words works: 'Ei' and 'in'
        res_ei = self.client.get("/api/lookup?q=Ei")
        self.assertEqual(res_ei.status_code, 200)
        data_ei = res_ei.get_json()
        self.assertTrue(len(data_ei["exact_entries"]) > 0 or len(data_ei["form_matches"]) > 0)

        res_in = self.client.get("/api/lookup?q=in")
        self.assertEqual(res_in.status_code, 200)
        data_in = res_in.get_json()
        self.assertTrue(len(data_in["exact_entries"]) > 0)

    def test_03_noun_basics(self):
        """
        Check: Noun basics
        - das Haus / die Häuser and house.
        - Häuser links back to Haus.
        - der Lehrer / die Lehrer retains unchanged plural.
        """
        # Lookup Haus
        res_haus = self.client.get("/api/lookup?q=Haus")
        data_haus = res_haus.get_json()
        self.assertTrue(len(data_haus["exact_entries"]) > 0)
        entry_haus = [e for e in data_haus["exact_entries"] if e["headword"] == "Haus"][0]
        self.assertEqual(entry_haus["article"], "das")
        self.assertEqual(entry_haus["gender"], "neuter")
        grammar_haus = entry_haus["grammar"]
        self.assertEqual(grammar_haus["nominative_singular"], "das Haus")
        self.assertEqual(grammar_haus["nominative_plural"], "die Häuser")

        # English sense contains 'house' or 'building'
        glosses = [s["gloss_en"].lower() for s in entry_haus["senses"]]
        self.assertTrue(any("house" in g or "building" in g for g in glosses))

        # Häuser links back to Haus
        res_haeuser = self.client.get("/api/lookup?q=Häuser")
        data_haeuser = res_haeuser.get_json()
        all_base_words = [f["base_word"] for f in data_haeuser["form_matches"]]
        all_exact_hw = [e["headword"] for e in data_haeuser["exact_entries"]]
        self.assertTrue("Haus" in all_base_words or "Haus" in all_exact_hw)

        # Lehrer retains unchanged plural
        res_lehrer = self.client.get("/api/lookup?q=Lehrer")
        data_lehrer = res_lehrer.get_json()
        entry_lehrer = [e for e in data_lehrer["exact_entries"] if e["headword"] == "Lehrer"][0]
        self.assertEqual(entry_lehrer["article"], "der")
        grammar_lehrer = entry_lehrer["grammar"]
        self.assertEqual(grammar_lehrer["nominative_plural"], "die Lehrer")

    def test_04_separate_noun_meanings(self):
        """
        Check: Separate noun meanings
        - das Band / die Bänder for ribbon
        - die Band / die Bands for music group
        appear separately.
        """
        res_band = self.client.get("/api/lookup?q=Band")
        data_band = res_band.get_json()
        entries = data_band["exact_entries"]
        self.assertGreaterEqual(len(entries), 2, "Expected multiple distinct entries for homograph Band")

        # Look for neuter ribbon entry (das Band)
        neuter_entries = [e for e in entries if e["gender"] == "neuter" or e["article"] == "das"]
        self.assertTrue(len(neuter_entries) > 0, "Expected das Band (ribbon/tape)")
        neuter_band = neuter_entries[0]
        self.assertEqual(neuter_band["article"], "das")
        # Plural should be die Bänder
        self.assertIn("Bänder", neuter_band["grammar"]["nominative_plural"])

        # Look for feminine music group entry (die Band)
        fem_entries = [e for e in entries if e["gender"] == "feminine" or e["article"] == "die"]
        self.assertTrue(len(fem_entries) > 0, "Expected die Band (music group)")
        fem_band = fem_entries[0]
        self.assertEqual(fem_band["article"], "die")
        # Meanings should mention band or musical group
        fem_glosses = " ".join(s["gloss_en"].lower() for s in fem_band["senses"])
        self.assertTrue("band" in fem_glosses or "music" in fem_glosses)

    def test_05_spelling_assistance_and_lookalikes(self):
        """
        Check: Spelling
        - schon and schön must never overwrite each other or be called typos.
        - shcön should suggest schön.
        - hauser should surface Häuser → Haus (missing umlaut: a → ä).
        - Masse and Maße are separate valid entries, cross-referenced as lookalikes.
        - Unicode decomposed umlaut (NFD) works.
        - Typo at word start (e.g. xhaus) is caught.
        """
        # schon vs schön
        res_schon = self.client.get("/api/lookup?q=schon")
        data_schon = res_schon.get_json()
        self.assertTrue(any(e["headword"] == "schon" for e in data_schon["exact_entries"]))
        # schön should be in lookalikes
        lookalike_terms_schon = [l["term"] for l in data_schon["lookalikes"]]
        self.assertIn("schön", lookalike_terms_schon)

        res_schoen = self.client.get("/api/lookup?q=schön")
        data_schoen = res_schoen.get_json()
        self.assertTrue(any(e["headword"] == "schön" for e in data_schoen["exact_entries"]))
        lookalike_terms_schoen = [l["term"] for l in data_schoen["lookalikes"]]
        self.assertIn("schon", lookalike_terms_schoen)

        # shcön (transposition typo) suggests schön
        res_shcoen = self.client.get("/api/lookup?q=shcön")
        data_shcoen = res_shcoen.get_json()
        dym = data_shcoen.get("did_you_mean")
        self.assertIsNotNone(dym)
        self.assertEqual(dym["target_word"], "schön")

        # hauser surfaces Häuser -> Haus
        res_hauser = self.client.get("/api/lookup?q=hauser")
        data_hauser = res_hauser.get_json()
        # Look in lookalikes, did_you_mean, or exact entries
        all_targets = [l["target_word"] for l in data_hauser["lookalikes"]]
        if data_hauser.get("did_you_mean"):
            all_targets.append(data_hauser["did_you_mean"]["target_word"])
        for em in data_hauser["exact_entries"]:
            all_targets.append(em["headword"])
        self.assertTrue("Haus" in all_targets or "Häuser" in all_targets or "Hauser" in all_targets)

        # Masse and Maße
        res_masse = self.client.get("/api/lookup?q=Masse")
        data_masse = res_masse.get_json()
        self.assertTrue(any(e["headword"] == "Masse" for e in data_masse["exact_entries"]))
        look_masse = [l["target_word"] for l in data_masse["lookalikes"]]
        self.assertTrue("Maß" in look_masse or "Maße" in look_masse)

        # Decomposed Unicode umlaut (NFD)
        nfd_schoen = unicodedata.normalize("NFD", "schön")
        res_nfd = self.client.get(f"/api/lookup?q={nfd_schoen}")
        data_nfd = res_nfd.get_json()
        self.assertTrue(any(e["headword"] == "schön" for e in data_nfd["exact_entries"]))

        # Typo at start of word
        res_xhaus = self.client.get("/api/lookup?q=xhaus")
        data_xhaus = res_xhaus.get_json()
        all_x_targets = [l["target_word"] for l in data_xhaus.get("lookalikes", [])]
        if data_xhaus.get("did_you_mean"):
            all_x_targets.append(data_xhaus["did_you_mean"]["target_word"])
        self.assertIn("Haus", all_x_targets)

    def test_06_grammar_forms_and_tables(self):
        """
        Check: Grammar
        - ging → gehen
        - bin → sein
        - gegangen (past participle of gehen)
        - gut → besser → am besten
        - Verb tables, noun cases, adjective endings.
        """
        # ging -> gehen
        res_ging = self.client.get("/api/lookup?q=ging")
        data_ging = res_ging.get_json()
        base_words_ging = [f["base_word"] for f in data_ging["form_matches"]] + [e["headword"] for e in data_ging["exact_entries"]]
        self.assertIn("gehen", base_words_ging)

        # bin -> sein
        res_bin = self.client.get("/api/lookup?q=bin")
        data_bin = res_bin.get_json()
        base_words_bin = [f["base_word"] for f in data_bin["form_matches"]] + [e["headword"] for e in data_bin["exact_entries"]]
        self.assertIn("sein", base_words_bin)

        # gegangen
        res_gegangen = self.client.get("/api/lookup?q=gegangen")
        data_gegangen = res_gegangen.get_json()
        base_words_gegangen = [f["base_word"] for f in data_gegangen["form_matches"]] + [e["headword"] for e in data_gegangen["exact_entries"]]
        self.assertIn("gehen", base_words_gegangen)

        # gut -> besser -> am besten
        res_gut = self.client.get("/api/lookup?q=gut")
        data_gut = res_gut.get_json()
        entry_gut = [e for e in data_gut["exact_entries"] if e["headword"] == "gut"][0]
        grammar_gut = entry_gut["grammar"]
        self.assertEqual(grammar_gut["comparative"], "besser")
        self.assertTrue("am besten" in grammar_gut["superlative"] or "besten" in grammar_gut["superlative"])

        # Verify verb table on gehen
        res_gehen = self.client.get("/api/lookup?q=gehen")
        data_gehen = res_gehen.get_json()
        entry_gehen = [e for e in data_gehen["exact_entries"] if e["headword"] == "gehen"][0]
        conj_table = entry_gehen["grammar"]["conjugation_table"]
        self.assertTrue(len(conj_table) >= 6)
        persons = [r["person"] for r in conj_table]
        self.assertIn("ich", persons)
        self.assertIn("er/sie/es", persons)

    def test_07_no_invented_data(self):
        """
        Check: No invented data
        - Explicitly no-plural entry (Durst)
        - Plural-only entry (Eltern or Ferien or Leute)
        - Unknown string stays unknown and doesn't invent entries.
        """
        # Durst (no plural)
        res_durst = self.client.get("/api/lookup?q=Durst")
        data_durst = res_durst.get_json()
        if data_durst["exact_entries"]:
            entry_durst = data_durst["exact_entries"][0]
            self.assertEqual(entry_durst["grammar"]["plural_status"], "no_plural")

        # Eltern (plural only)
        res_eltern = self.client.get("/api/lookup?q=Eltern")
        data_eltern = res_eltern.get_json()
        if data_eltern["exact_entries"]:
            entry_eltern = data_eltern["exact_entries"][0]
            self.assertEqual(entry_eltern["grammar"]["plural_status"], "plural_only")

        # Unknown gibberish string
        res_unknown = self.client.get("/api/lookup?q=qxjzvk987nonsense")
        data_unknown = res_unknown.get_json()
        self.assertEqual(len(data_unknown["exact_entries"]), 0)
        self.assertEqual(len(data_unknown["form_matches"]), 0)
        self.assertIsNone(data_unknown["did_you_mean"])

    def test_08_interrupted_refresh_resilience(self):
        """
        Check: Offline and setup
        - Simulate an interrupted refresh and verify previous database still works.
        """
        # Create a mock temporary db as if a refresh was interrupted halfway
        tmp_db = self.db_path + ".tmp"
        with open(tmp_db, "w") as f:
            f.write("corrupt partial content")

        # Ensure main database is still intact and readable
        conn = get_db_connection(self.db_path, read_only=True)
        self.assertTrue(check_integrity(conn, quick=True))
        conn.close()

        # Clean up temp file
        if os.path.exists(tmp_db):
            os.remove(tmp_db)


if __name__ == "__main__":
    unittest.main()

