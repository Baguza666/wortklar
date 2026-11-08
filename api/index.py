"""
Vercel Serverless Entrypoint for Wortklar.

Architecture Note for Vercel:
Vercel Serverless Functions have an uncompressed bundle size limit of 250 MB.
The Wortklar full dictionary SQLite database is ~3.9 GB and is gitignored.

This entrypoint provides three operational modes:
1. Local Database Mode: If wortklar.db (or WORTKLAR_DB_PATH) is present locally, serves the
   app directly with the packaged SQLite index.
2. Edge Proxy Mode: If BACKEND_URL environment variable is set (e.g. pointing to
   your Render service: https://wortklar.onrender.com), acts as a transparent, high-speed
   edge proxy forwarding requests, headers, cookies, and streams.
3. Diagnostic Setup Page: If neither a database nor BACKEND_URL is configured, serves a
   clean, responsive diagnostics dashboard explaining how to complete the 1-step Vercel setup.
"""

import os
import sys
from pathlib import Path

# Add project root to path so wortklar package can be imported
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import urllib.request
import urllib.error
from flask import Flask, request, Response, render_template_string

BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
DB_PATH = os.environ.get("WORTKLAR_DB_PATH", str(ROOT_DIR / "wortklar.db"))

DIAGNOSTIC_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wortklar on Vercel - Connection Setup</title>
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151c2c;
      --border: #242f42;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --accent: #2563eb;
      --success: #10b981;
      --warn: #f59e0b;
      --code-bg: #0f172a;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 32px 16px;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      max-width: 680px;
      width: 100%;
      padding: 32px 28px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.5);
    }
    .badge {
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      background: linear-gradient(135deg, var(--accent), var(--primary));
      color: #fff;
      padding: 4px 10px;
      border-radius: 6px;
      margin-bottom: 12px;
    }
    h1 {
      font-size: 1.75rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin-bottom: 8px;
    }
    p { color: var(--text-muted); margin-bottom: 16px; }
    .status-box {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 20px;
      margin-bottom: 24px;
    }
    .status-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      font-size: 0.9375rem;
    }
    .status-row:last-child { border-bottom: none; }
    .pill {
      font-size: 0.75rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 9999px;
    }
    .pill.success { background: rgba(16, 185, 129, 0.2); color: var(--success); }
    .pill.pending { background: rgba(245, 158, 11, 0.2); color: var(--warn); }
    .instruction-step {
      margin-bottom: 20px;
    }
    .step-title {
      font-weight: 700;
      color: var(--text);
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .step-number {
      background: var(--accent);
      color: #fff;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.75rem;
    }
    pre {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      font-family: ui-monospace, Menlo, Monaco, monospace;
      font-size: 0.875rem;
      color: var(--primary);
      overflow-x: auto;
      margin-top: 8px;
    }
    .note {
      font-size: 0.8125rem;
      color: var(--text-muted);
      border-left: 3px solid var(--accent);
      padding-left: 12px;
      margin-top: 16px;
    }
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Vercel Edge Deployment</span>
    <h1>Wortklar Ready for Connection</h1>
    <p>Your Wortklar serverless instance is active on Vercel. Because the complete German dictionary database is <strong>3.9 GB</strong> (exceeding Vercel Serverless Function's 250 MB bundle limit), connect your hosted backend below.</p>

    <div class="status-box">
      <div class="status-row">
        <span>Vercel Serverless Python Runtime</span>
        <span class="pill success">Active</span>
      </div>
      <div class="status-row">
        <span>Backend Connection (<code>BACKEND_URL</code>)</span>
        <span class="pill pending">Needs Config</span>
      </div>
      <div class="status-row">
        <span>Gemini AI Provider</span>
        <span class="pill {% if gemini_set %}success{% else %}pending{% endif %}">
          {% if gemini_set %}Configured{% else %}Optional{% endif %}
        </span>
      </div>
    </div>

    <div class="instruction-step">
      <div class="step-title">
        <span class="step-number">1</span>
        <span>Set your Backend URL in Vercel</span>
      </div>
      <p>In your Vercel Project Dashboard &rarr; <strong>Settings</strong> &rarr; <strong>Environment Variables</strong>, add:</p>
      <pre>BACKEND_URL = https://your-wortklar-app.onrender.com</pre>
    </div>

    <div class="instruction-step">
      <div class="step-title">
        <span class="step-number">2</span>
        <span>Redeploy or Trigger Instant Sync</span>
      </div>
      <p>Once saved, Vercel will instantly route all queries, autocomplete suggestions, grammar tables, and Gemini AI lookups through Vercel's global CDN to your hosted backend!</p>
    </div>

    <div class="note">
      <strong>Single-Device / Offline Note:</strong> You can also run Wortklar locally with <code>python3 run.py</code> on your laptop anytime without an internet connection.
    </div>
  </div>
</body>
</html>
"""

def create_vercel_app():
    # Priority 1: Direct local database if available
    if Path(DB_PATH).is_file():
        from wortklar.app import create_app
        return create_app(db_path=DB_PATH)

    # Priority 2: Vercel Edge Proxy / Diagnostic App
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    def vercel_router(path):
        if BACKEND_URL:
            # Proxy to BACKEND_URL
            target_url = f"{BACKEND_URL}/{path}"
            if request.query_string:
                target_url += f"?{request.query_string.decode('utf-8', errors='ignore')}"

            # Filter hop-by-hop headers
            excluded = {"host", "content-length", "transfer-encoding", "connection"}
            forward_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in excluded
            }
            forward_headers["X-Forwarded-For"] = request.remote_addr or ""
            forward_headers["X-Forwarded-Proto"] = request.scheme or "https"

            body_data = request.get_data() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None

            req = urllib.request.Request(
                target_url,
                data=body_data,
                headers=forward_headers,
                method=request.method
            )

            try:
                with urllib.request.urlopen(req, timeout=15) as upstream:
                    resp_headers = []
                    for k, v in upstream.getheaders():
                        if k.lower() not in excluded:
                            resp_headers.append((k, v))
                    return Response(
                        upstream.read(),
                        status=upstream.status,
                        headers=resp_headers
                    )
            except urllib.error.HTTPError as e:
                resp_headers = []
                for k, v in e.headers.items():
                    if k.lower() not in excluded:
                        resp_headers.append((k, v))
                return Response(
                    e.read(),
                    status=e.code,
                    headers=resp_headers
                )
            except Exception as e:
                return Response(
                    f"Wortklar Edge Proxy Error: {str(e)}",
                    status=502,
                    mimetype="text/plain"
                )

        # Priority 3: Diagnostics dashboard
        if path == "healthz":
            return Response('{"status":"pending_backend_url"}', status=503, mimetype="application/json")

        gemini_set = bool(os.environ.get("GEMINI_API_KEY"))
        return render_template_string(DIAGNOSTIC_HTML, gemini_set=gemini_set)

    return app

# WSGI application callable required by Vercel's Python runtime
app = create_vercel_app()

