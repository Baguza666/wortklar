"""
Tests for Vercel deployment entrypoint (api/index.py).
Verifies:
1. Local Database Mode (serves Wortklar app directly when DB exists)
2. Diagnostic Setup Mode (when DB and BACKEND_URL are absent)
3. Edge Proxy Mode (when BACKEND_URL is set, proxies requests upstream)
"""

import unittest
import os
from unittest.mock import patch, MagicMock
from io import BytesIO


class TestVercelEntrypoint(unittest.TestCase):

    def test_local_database_mode(self):
        """When DB_PATH is present, api/index.py loads full Wortklar app."""
        import api.index as vercel_module
        app = vercel_module.create_vercel_app()
        client = app.test_client()

        # Check healthz or index
        resp = client.get("/healthz")
        self.assertEqual(resp.status_code, 200)

        # Check lookup
        resp = client.get("/api/lookup?q=Haus")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["query"], "Haus")

    def test_diagnostic_mode_when_no_db_and_no_backend(self):
        """When DB is missing and BACKEND_URL is not set, renders diagnostics."""
        with patch("api.index.Path.is_file", return_value=False):
            with patch("api.index.BACKEND_URL", ""):
                import api.index as vercel_module
                app = vercel_module.create_vercel_app()
                client = app.test_client()

                resp = client.get("/")
                self.assertEqual(resp.status_code, 200)
                html = resp.get_data(as_text=True)
                self.assertIn("Wortklar Ready for Connection", html)
                self.assertIn("BACKEND_URL", html)

                # healthz returns pending
                health_resp = client.get("/healthz")
                self.assertEqual(health_resp.status_code, 503)

    @patch("urllib.request.urlopen")
    def test_edge_proxy_mode(self, mock_urlopen):
        """When BACKEND_URL is set, proxies upstream requests and responses."""
        # Setup mock upstream response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"query":"Hund","count":1}'
        mock_response.getheaders.return_value = [("Content-Type", "application/json")]
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch("api.index.Path.is_file", return_value=False):
            with patch("api.index.BACKEND_URL", "https://wortklar-test.onrender.com"):
                import api.index as vercel_module
                app = vercel_module.create_vercel_app()
                client = app.test_client()

                resp = client.get("/api/lookup?q=Hund")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data, b'{"query":"Hund","count":1}')


if __name__ == "__main__":
    unittest.main()
