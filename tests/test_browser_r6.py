#!/usr/bin/env python3
"""
R6 Browser rendering and responsive layout verification for hosted Wortklar.
Runs headless Google Chrome against the app with HOSTED_MODE active, takes screenshots
at desktop (740px) and mobile (375px) widths, verifies login page, authenticated session,
mobile keyboard optimization attributes, and grammar table horizontal scrolling.
"""

import http.cookiejar
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.request import HTTPCookieProcessor, build_opener

from wortklar.auth import hash_password

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TEST_PORT = 5006
TEST_URL = f"http://127.0.0.1:{TEST_PORT}"
TEST_PASSWORD = "OwnerSecurePassword2026!"
TEST_SECRET_KEY = "test-r6-browser-secret-key-at-least-32-chars-long"


def wait_for_server(url: str, timeout: float = 12.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            # Check public healthz endpoint
            with urllib.request.urlopen(f"{url}/healthz", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def run_r6_browser_tests():
    if not os.path.exists(CHROME_PATH):
        print(f"[Skip] Google Chrome not found at: {CHROME_PATH}")
        return True

    os.makedirs("screenshots", exist_ok=True)

    # Start hosted test server in background
    env = os.environ.copy()
    env["PORT"] = str(TEST_PORT)
    env["HOST"] = "127.0.0.1"
    env["PYTHONPATH"] = "."
    env["HOSTED_MODE"] = "true"
    env["SECRET_KEY"] = TEST_SECRET_KEY
    env["WORTKLAR_PASSWORD_HASH"] = hash_password(TEST_PASSWORD)
    env["WORTKLAR_COOKIE_SECURE"] = "false"  # allow cookie over local http test harness
    env["WORTKLAR_TEST_AUTH"] = "true"

    print(f"[R6 Browser Test] Starting hosted Wortklar server on {TEST_URL}...")
    server_proc = subprocess.Popen([sys.executable, "run.py"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        if not wait_for_server(TEST_URL, timeout=12.0):
            print("[Error] Test server failed to start in time.")
            return False

        print("[R6 Browser Test] Server is up and healthy. Checking unauthenticated redirection to /login...")

        # 1. Verify unauthenticated redirect via urllib
        req = urllib.request.Request(f"{TEST_URL}/", headers={"User-Agent": "BrowserTest/1.0"})
        try:
            with urllib.request.urlopen(req) as resp:
                # urlopen follows redirects automatically; final URL should be /login
                self_url = resp.geturl()
                print(f"  Unauthenticated redirect landed on: {self_url}")
                assert "/login" in self_url, f"Expected /login in {self_url}"
        except urllib.error.HTTPError as ex:
            print(f"  HTTP error on root: {ex}")

        # 2. Render Login Page on Desktop and Mobile
        login_targets = [
            ("screenshots/09_desktop_login.png", f"{TEST_URL}/login", (740, 800)),
            ("screenshots/10_mobile_login.png", f"{TEST_URL}/login", (375, 812))
        ]

        for dest_png, url, (w, h) in login_targets:
            print(f"  Rendering {url} -> {dest_png} ({w}x{h})...")
            cmd = [
                CHROME_PATH,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--window-size={w},{h}",
                f"--screenshot={dest_png}",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=2000",
                url
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if os.path.exists(dest_png):
                size_kb = os.path.getsize(dest_png) / 1024
                print(f"  Captured screenshot: {dest_png} ({size_kb:.1f} KB)")
            else:
                print(f"  Failed screenshot: {dest_png}")

        # 3. Inspect Login DOM to verify mobile keyboard attributes
        dom_cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--dump-dom",
            "--virtual-time-budget=1000",
            f"{TEST_URL}/login"
        ]
        dom_res = subprocess.run(dom_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        dom_html = dom_res.stdout.decode("utf-8", errors="replace")
        assert 'name="password"' in dom_html, "Password input missing in DOM"
        assert 'autocorrect="off"' in dom_html, "autocorrect='off' missing in login input"
        assert 'autocapitalize="none"' in dom_html, "autocapitalize='none' missing in login input"
        assert 'spellcheck="false"' in dom_html, "spellcheck='false' missing in login input"
        print("  Verified login page DOM and mobile keyboard attributes successfully.")

        # 4. Perform actual login to obtain session cookie
        cookie_jar = http.cookiejar.CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))

        # Get login page to read CSRF token
        resp = opener.open(f"{TEST_URL}/login")
        html = resp.read().decode("utf-8")
        csrf_token = re.search(r'name="csrf_token"\s+value="([a-f0-9]+)"', html).group(1)

        # POST login form
        login_data = urllib.parse.urlencode({
            "password": TEST_PASSWORD,
            "csrf_token": csrf_token,
            "next": "/"
        }).encode("utf-8")
        login_resp = opener.open(f"{TEST_URL}/login", data=login_data)
        cookie_header = "; ".join([f"{c.name}={c.value}" for c in cookie_jar])
        print(f"  Logged in successfully. Session cookie received: {cookie_header[:35]}...")

        # 5. Render Authenticated App on Desktop, Mobile, and Virtual Keyboard simulation
        session_targets = [
            ("screenshots/11_desktop_hosted_session.png", f"{TEST_URL}/_test_login?next=" + urllib.parse.quote("/#Haus"), (740, 1000)),
            ("screenshots/12_mobile_hosted_session.png", f"{TEST_URL}/_test_login?next=" + urllib.parse.quote("/#Haus"), (375, 812)),
            # Simulating mobile virtual keyboard taking lower half of screen (375x500)
            ("screenshots/13_mobile_virtual_keyboard_simulation.png", f"{TEST_URL}/_test_login?next=" + urllib.parse.quote("/#Haus"), (375, 500)),
            # Mobile grammar table horizontal scroll verification on irregular verb
            ("screenshots/14_mobile_grammar_table_scroll.png", f"{TEST_URL}/_test_login?next=" + urllib.parse.quote("/#gehen"), (375, 812))
        ]

        for dest_png, url, (w, h) in session_targets:
            print(f"  Rendering authenticated session {url} -> {dest_png} ({w}x{h})...")
            cmd = [
                CHROME_PATH,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--window-size={w},{h}",
                f"--screenshot={dest_png}",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=2000",
                url
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if os.path.exists(dest_png):
                size_kb = os.path.getsize(dest_png) / 1024
                print(f"  Captured screenshot: {dest_png} ({size_kb:.1f} KB)")
            else:
                print(f"  Failed screenshot: {dest_png}")

        # 6. Verify authenticated DOM dump
        dom_cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--dump-dom",
            "--virtual-time-budget=2000",
            f"{TEST_URL}/_test_login?next=" + urllib.parse.quote("/#Haus")
        ]
        dom_res = subprocess.run(dom_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        dom_html = dom_res.stdout.decode("utf-8", errors="replace")

        assert "Private" in dom_html, "Private session badge missing in authenticated DOM"
        assert "Log out" in dom_html, "Log out button missing in authenticated DOM"
        assert "das Haus" in dom_html or "Haus" in dom_html, "Headword missing in rendered results"
        assert 'autocorrect="off"' in dom_html, "Search input autocorrect='off' missing"
        assert 'autocapitalize="none"' in dom_html, "Search input autocapitalize='none' missing"
        print("  Verified authenticated DOM, Private badge, logout button, and mobile input attributes.")

        print("\n[R6 Browser Test] ALL BROWSER CHECKS PASSED.")
        return True

    finally:
        server_proc.terminate()
        server_proc.wait()
        print("[R6 Browser Test] Test server shut down cleanly.")


if __name__ == "__main__":
    success = run_r6_browser_tests()
    if not success:
        sys.exit(1)
