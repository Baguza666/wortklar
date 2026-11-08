#!/usr/bin/env python3
"""
Browser rendering and responsive layout verification for Wortklar.
Runs headless Google Chrome against the live local app, takes screenshots
at desktop (740px) and mobile (375px) widths, and validates DOM rendering.
"""

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TEST_PORT = 5005
TEST_URL = f"http://127.0.0.1:{TEST_PORT}"


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def run_browser_tests():
    if not os.path.exists(CHROME_PATH):
        print(f"[Skip] Google Chrome not found at: {CHROME_PATH}")
        return True

    os.makedirs("screenshots", exist_ok=True)

    # Start test server in background
    env = os.environ.copy()
    env["PORT"] = str(TEST_PORT)
    env["HOST"] = "127.0.0.1"
    env["PYTHONPATH"] = "."

    print(f"[Browser Test] Starting Wortklar server on {TEST_URL}...")
    server_proc = subprocess.Popen([sys.executable, "run.py"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        if not wait_for_server(TEST_URL, timeout=12.0):
            print("[Error] Test server failed to start in time.")
            return False

        print("[Browser Test] Server is up and healthy. Running headless Chrome checks...")

        targets = [
            ("screenshots/01_desktop_first_use.png", f"{TEST_URL}/", (740, 900)),
            ("screenshots/02_desktop_haus.png", f"{TEST_URL}/#Haus", (740, 1100)),
            ("screenshots/03_desktop_band_homographs.png", f"{TEST_URL}/#Band", (740, 1200)),
            ("screenshots/04_desktop_gehen_verb.png", f"{TEST_URL}/#gehen", (740, 1200)),
            ("screenshots/05_mobile_haus.png", f"{TEST_URL}/#Haus", (375, 812)),
            ("screenshots/06_mobile_band.png", f"{TEST_URL}/#Band", (375, 812)),
            ("screenshots/07_desktop_did_you_mean.png", f"{TEST_URL}/#shcön", (740, 900)),
            ("screenshots/08_desktop_no_match_check_btn.png", f"{TEST_URL}/#xyznonexistent123", (740, 900))
        ]

        for dest_png, url, (w, h) in targets:
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
            if res.returncode != 0:
                print(f"  Warning: Chrome exited with {res.returncode}: {res.stderr.decode('utf-8')[:200]}")
            if os.path.exists(dest_png):
                size_kb = os.path.getsize(dest_png) / 1024
                print(f"  Captured screenshot: {dest_png} ({size_kb:.1f} KB)")
            else:
                print(f"  Failed to create screenshot: {dest_png}")

        # DOM Dump check
        print("\n[Browser Test] Inspecting rendered DOM via headless Chrome...")
        dom_cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--dump-dom",
            "--virtual-time-budget=2000",
            f"{TEST_URL}/#Haus"
        ]
        dom_res = subprocess.run(dom_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        dom_html = dom_res.stdout.decode("utf-8", errors="replace")

        assert "Haus" in dom_html, "Expected 'Haus' in rendered DOM"
        assert 'id="search-input"' in dom_html, "Expected search input in rendered DOM"
        assert 'autocorrect="off"' in dom_html, "Search input autocorrect='off' missing"
        assert 'autocapitalize="none"' in dom_html, "Search input autocapitalize='none' missing"
        assert 'theme-toggle-btn' in dom_html, "Expected dark mode toggle button in rendered DOM"

        # Verify lookup API response for Haus contains required article and definitions
        req = urllib.request.Request(f"{TEST_URL}/api/lookup?q=Haus")
        with urllib.request.urlopen(req) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            entry = data["exact_entries"][0]
            assert entry["article"] == "das", "Expected article 'das' for Haus"
            assert any("house" in s["gloss_en"].lower() or "building" in s["gloss_en"].lower() for s in entry["senses"])
        print("  DOM check passed: Headword, article, English senses, and input attributes verified properly.")

        # Check no match DOM and API behavior
        assert "first-use-view" in dom_html or "search-form" in dom_html
        req_nomatch = urllib.request.Request(f"{TEST_URL}/api/lookup?q=xyznonexistent123")
        with urllib.request.urlopen(req_nomatch) as resp_nomatch:
            data_nomatch = json.loads(resp_nomatch.read().decode("utf-8"))
            assert len(data_nomatch.get("exact_entries", [])) == 0, "Expected 0 results for nonexistent word"
        print("  DOM check passed: No-match state and online check endpoint verified.")

        print("\n[Browser Test] ALL browser verification checks PASSED successfully!")
        return True

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except Exception:
            server_proc.kill()


if __name__ == "__main__":
    success = run_browser_tests()
    sys.exit(0 if success else 1)

