"""
Unit and integration tests for R6:
- Single-owner password authentication in hosted mode
- Fails closed when required secrets are missing
- Public minimal readiness endpoint (/healthz) leaks no content
- Logged-out access blocked on all protected routes
- CSRF validation on state-changing requests
- Bounded login attempts and rate limiting (lockout on 5 failures)
- Valid login and authenticated search/lookup/research flow
- Logout session clearance
- Read-only SQLite enforcement and fast restart without re-import
- Offline local mode compatibility
"""

import json
import os
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from wortklar.app import create_app
from wortklar.auth import hash_password, login_limiter
from wortklar.db import get_db_connection, init_schema, set_metadata


class TestR6HostedMode(unittest.TestCase):
    """Test suite for R6 hosted mode, security, and authentication."""

    @classmethod
    def setUpClass(cls):
        # Create a small isolated test database
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test_r6.db")
        conn = sqlite3.connect(cls.db_path)
        init_schema(conn)

        # Seed with a test entry
        with conn:
            conn.execute(
                "INSERT INTO entries (headword, part_of_speech, gender, article, source_edition) VALUES (?, ?, ?, ?, ?)",
                ("Haus", "noun", "neuter", "das", "en-wiktionary")
            )
            entry_id = 1
            conn.execute(
                "INSERT INTO senses (entry_id, sense_order, gloss_en) VALUES (?, ?, ?)",
                (entry_id, 1, "A building, house.")
            )
            conn.execute(
                "INSERT INTO search_index (term, lower_term, folded_term, entry_id, is_lemma, rank_priority, preview) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Haus", "haus", "haus", entry_id, 1, 1, "das Haus (noun) · A building, house.")
            )
        set_metadata(conn, "lemma_count", 1)
        set_metadata(conn, "form_count", 0)
        set_metadata(conn, "search_index_count", 1)
        conn.close()

        cls.secret_key = "test-secret-key-for-session-signing-at-least-32-chars"
        cls.test_password = "OwnerSecurePassword2026!"
        cls.password_hash = hash_password(cls.test_password)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        # Reset limiter records between tests
        login_limiter._records.clear()

    def test_fails_closed_missing_secret_key(self):
        """Hosted mode fails closed immediately if SECRET_KEY is missing."""
        env = {
            "HOSTED_MODE": "true",
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "SECRET_KEY": "",
            "WORTKLAR_SECRET_KEY": ""
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                create_app(self.db_path)
            self.assertIn("SECRET_KEY", str(ctx.exception))

    def test_fails_closed_missing_password_hash(self):
        """Hosted mode fails closed immediately if password hash is missing."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": "",
            "WORTKLAR_PASSWORD": ""
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                create_app(self.db_path)
            self.assertIn("WORTKLAR_PASSWORD_HASH", str(ctx.exception))

    def test_local_mode_remains_unauthenticated(self):
        """When HOSTED_MODE is not set, all endpoints operate without requiring login."""
        env = {"HOSTED_MODE": "false"}
        with patch.dict(os.environ, env, clear=True):
            app = create_app(self.db_path)
            client = app.test_client()

            # Index renders 200
            res = client.get("/")
            self.assertEqual(res.status_code, 200)

            # Suggest works without login
            res = client.get("/api/suggest?q=Haus")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["threshold_met"], True)

            # Lookup works without login
            res = client.get("/api/lookup?q=Haus")
            self.assertEqual(res.status_code, 200)

    def test_minimal_readiness_healthz_endpoint(self):
        """Readiness endpoint is public, returns 200 OK, and leaks zero content."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            app = create_app(self.db_path)
            client = app.test_client()

            res = client.get("/healthz")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data, {"status": "ok"})
            # Verify no DB content or counts are present in payload
            self.assertNotIn("lemma_count", data)
            self.assertNotIn("entries", data)
            self.assertNotIn("metadata", data)

    def test_healthz_fails_when_db_missing(self):
        """Healthz returns 503 when the database file does not exist."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            missing_db = os.path.join(self.temp_dir.name, "nonexistent.db")
            app = create_app(missing_db)
            client = app.test_client()

            res = client.get("/healthz")
            self.assertEqual(res.status_code, 503)
            data = res.get_json()
            self.assertEqual(data["status"], "unhealthy")

    def test_logged_out_requests_blocked(self):
        """All protected routes reject unauthenticated requests in hosted mode."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            app = create_app(self.db_path)
            client = app.test_client()

            # 1. Root page redirects to /login
            res = client.get("/")
            self.assertEqual(res.status_code, 302)
            self.assertIn("/login", res.headers.get("Location", ""))

            # 2. API status returns 401
            res = client.get("/api/status")
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["error"], "unauthorized")

            # 3. Suggest API returns 401
            res = client.get("/api/suggest?q=Haus")
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["error"], "unauthorized")

            # 4. Lookup API returns 401
            res = client.get("/api/lookup?q=Haus")
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["error"], "unauthorized")

            # 5. Online check API returns 401
            res = client.post("/api/check_online", json={"word": "Haus"})
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["error"], "unauthorized")

    def test_login_csrf_and_invalid_attempts_with_rate_limiting(self):
        """Test login CSRF requirement, invalid credentials, and 5-attempt rate-limiting lockout."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            app = create_app(self.db_path)
            client = app.test_client()

            # Fetch login page to get CSRF token
            get_res = client.get("/login")
            self.assertEqual(get_res.status_code, 200)
            csrf_match = re.search(r'name="csrf_token"\s+value="([a-f0-9]+)"', get_res.get_data(as_text=True))
            self.assertIsNotNone(csrf_match)
            csrf_token = csrf_match.group(1)

            # Attempt POST without CSRF token -> 403 Forbidden
            res = client.post("/login", data={"password": "wrong"})
            self.assertEqual(res.status_code, 403)

            # Attempt 1-4 with wrong password -> 401 Unauthorized
            for attempt in range(1, 5):
                res = client.post("/login", data={"password": "wrong-password", "csrf_token": csrf_token})
                self.assertEqual(res.status_code, 401, f"Attempt {attempt} should return 401")
                self.assertIn(b"Incorrect owner password", res.data)

            # Attempt 5 with wrong password -> 429 Too Many Requests (Lockout activated)
            res = client.post("/login", data={"password": "wrong-password", "csrf_token": csrf_token})
            self.assertEqual(res.status_code, 429)
            self.assertIn(b"Too many failed", res.data)

            # Attempt 6 even with correct password is still locked out
            res = client.post("/login", data={"password": self.test_password, "csrf_token": csrf_token})
            self.assertEqual(res.status_code, 429)

    def test_authenticated_session_flow_and_logout(self):
        """Test valid login sets session, allows access to protected routes, and logout invalidates session."""
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            app = create_app(self.db_path)
            client = app.test_client()

            # 1. Get login page and CSRF token
            res = client.get("/login")
            self.assertEqual(res.status_code, 200)
            csrf_token = re.search(r'name="csrf_token"\s+value="([a-f0-9]+)"', res.get_data(as_text=True)).group(1)

            # 2. Submit valid password
            login_res = client.post("/login", data={
                "password": self.test_password,
                "csrf_token": csrf_token,
                "next": "/"
            }, follow_redirects=False)

            self.assertEqual(login_res.status_code, 302)
            self.assertEqual(login_res.headers.get("Location"), "/")

            # 3. Follow redirect to root: should render 200 with Private session badge
            root_res = client.get("/")
            self.assertEqual(root_res.status_code, 200)
            self.assertIn(b"Private", root_res.data)
            self.assertIn(b"Log out", root_res.data)

            # Extract new CSRF token from meta tag
            meta_csrf = re.search(r'<meta name="csrf-token" content="([a-f0-9]+)">', root_res.get_data(as_text=True)).group(1)

            # 4. Query suggestion endpoint as authenticated user
            sug_res = client.get("/api/suggest?q=Haus")
            self.assertEqual(sug_res.status_code, 200)
            sug_data = sug_res.get_json()
            self.assertEqual(sug_data["threshold_met"], True)
            self.assertEqual(sug_data["suggestions"][0]["term"], "Haus")

            # 5. Query lookup endpoint
            lookup_res = client.get("/api/lookup?q=Haus")
            self.assertEqual(lookup_res.status_code, 200)
            lookup_data = lookup_res.get_json()
            self.assertEqual(lookup_data["exact_entries"][0]["headword"], "Haus")

            # 6. Perform logout
            logout_res = client.post("/logout", data={"csrf_token": meta_csrf}, follow_redirects=False)
            self.assertEqual(logout_res.status_code, 302)
            self.assertIn("/login", logout_res.headers.get("Location"))

            # 7. Verify subsequent query returns 401
            post_logout_res = client.get("/api/lookup?q=Haus")
            self.assertEqual(post_logout_res.status_code, 401)

    def test_sqlite_read_only_enforcement(self):
        """Verify that get_db_connection(read_only=True) prohibits any write operation."""
        conn = get_db_connection(self.db_path, read_only=True)
        # Select works
        cur = conn.execute("SELECT COUNT(*) FROM entries")
        self.assertEqual(cur.fetchone()[0], 1)

        # Insert raises OperationalError
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO metadata (key, value) VALUES ('k', 'v')")
        conn.close()

    def test_server_restart_instant_readiness_no_reimport(self):
        """Verify that restarting app with prebuilt index starts immediately without reimport."""
        import time
        env = {
            "HOSTED_MODE": "true",
            "SECRET_KEY": self.secret_key,
            "WORTKLAR_PASSWORD_HASH": self.password_hash,
            "WORTKLAR_COOKIE_SECURE": "false"
        }
        with patch.dict(os.environ, env, clear=True):
            t0 = time.time()
            app = create_app(self.db_path)
            client = app.test_client()
            res = client.get("/healthz")
            elapsed = time.time() - t0
            self.assertEqual(res.status_code, 200)
            # Startup and check took less than 200ms
            self.assertLess(elapsed, 0.2, f"Startup took {elapsed:.3f}s, expected < 0.2s")


if __name__ == "__main__":
    unittest.main()
