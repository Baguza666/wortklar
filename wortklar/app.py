"""
Flask application factory and routes for Wortklar.
Supports offline local mode and single-owner password-protected hosted mode (Render).
"""

import os
import sqlite3
import unicodedata
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.middleware.proxy_fix import ProxyFix

from wortklar.db import get_db_connection, get_metadata, check_integrity, DEFAULT_DB_PATH
from wortklar.search import get_suggestions, lookup_word, count_letters, normalize_input
from wortklar.auth import (
    check_hosted_mode_configured,
    verify_password,
    login_limiter,
    get_or_create_csrf_token,
    validate_csrf_token,
    is_authenticated,
    login_user,
    logout_user
)


def create_app(db_path: str = DEFAULT_DB_PATH) -> Flask:
    """Create and configure the Wortklar Flask application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["DB_PATH"] = db_path
    app.config["JSON_AS_ASCII"] = False

    # Check hosted mode configuration
    is_hosted, config_err = check_hosted_mode_configured()
    if is_hosted and config_err:
        # Fail closed: Hosted mode is enabled but required secrets are missing
        raise RuntimeError(f"Wortklar Hosted Mode Configuration Error: {config_err}")

    app.config["HOSTED_MODE"] = is_hosted

    if is_hosted:
        secret_key = os.environ.get("SECRET_KEY") or os.environ.get("WORTKLAR_SECRET_KEY")
        app.secret_key = secret_key
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        # Secure cookie by default; can be disabled explicitly for local testing of hosted mode
        cookie_secure = os.environ.get("WORTKLAR_COOKIE_SECURE", "true").lower() == "true"
        app.config["SESSION_COOKIE_SECURE"] = cookie_secure
        # Terminate proxy headers safely for Render HTTPS
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    else:
        app.secret_key = os.environ.get("SECRET_KEY", "wortklar-local-mode-secret-key-32bytes")

    def get_conn() -> sqlite3.Connection:
        path = app.config["DB_PATH"]
        if not os.path.exists(path):
            raise FileNotFoundError(f"Database not initialized at: {path}")
        return get_db_connection(path, read_only=True)

    @app.before_request
    def access_control():
        """Enforce authentication and CSRF protections in hosted mode."""
        login_limiter.prune()

        if not app.config.get("HOSTED_MODE"):
            return None

        path = request.path

        # Minimal public endpoints: /healthz, /login, static files
        if path in ("/healthz", "/login") or path.startswith("/static/"):
            return None

        # Allow test login endpoint only when test flag is explicitly set
        if os.environ.get("WORTKLAR_TEST_AUTH") == "true" and path == "/_test_login":
            return None

        # Guarded endpoints: check authentication
        if is_authenticated():
            # In hosted mode, state-changing requests require valid CSRF
            if request.method in ("POST", "PUT", "DELETE", "PATCH") and path != "/logout":
                if not validate_csrf_token(request):
                    return jsonify({"error": "csrf_invalid", "message": "Invalid or missing CSRF token."}), 403
            return None

        # Unauthenticated access to protected endpoints:
        if path.startswith("/api/") or request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({
                "error": "unauthorized",
                "message": "Authentication required. Please log in."
            }), 401

        # Browser navigation: redirect to login
        next_target = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_target))

    @app.route("/healthz")
    def healthz():
        """
        Minimal public readiness endpoint for Render health checks.
        Verifies that the packaged SQLite database exists and is readable
        without exposing schema, metadata, counts, or secrets.
        """
        db_path = app.config["DB_PATH"]
        if not os.path.exists(db_path):
            return jsonify({"status": "unhealthy", "reason": "database_missing"}), 503

        try:
            conn = get_conn()
            cur = conn.execute("SELECT 1")
            cur.fetchone()
            conn.close()
            return jsonify({"status": "ok"}), 200
        except Exception:
            return jsonify({"status": "unhealthy", "reason": "db_error"}), 503

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Single-owner password login gate in hosted mode."""
        if not app.config.get("HOSTED_MODE"):
            return redirect(url_for("index"))

        csrf_token = get_or_create_csrf_token()
        client_ip = login_limiter.get_client_ip(request)
        next_url = request.args.get("next") or request.form.get("next") or "/"
        # Prevent open redirects
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"

        if request.method == "GET":
            if is_authenticated():
                return redirect(next_url)
            return render_template(
                "login.html",
                csrf_token=csrf_token,
                next_url=next_url,
                error_message=None,
                lockout_seconds=None,
                remaining_attempts=None
            )

        # POST: Check CSRF
        if not validate_csrf_token(request):
            return render_template(
                "login.html",
                csrf_token=get_or_create_csrf_token(),
                next_url=next_url,
                error_message="Invalid session or CSRF token. Please try again.",
                lockout_seconds=None,
                remaining_attempts=None
            ), 403

        # Check rate limiter
        locked, remaining_secs = login_limiter.is_locked_out(client_ip)
        if locked:
            return render_template(
                "login.html",
                csrf_token=csrf_token,
                next_url=next_url,
                error_message="Too many failed login attempts. Temporary lockout active.",
                lockout_seconds=remaining_secs,
                remaining_attempts=0
            ), 429

        password = request.form.get("password", "")
        expected_hash_or_secret = os.environ.get("WORTKLAR_PASSWORD_HASH") or os.environ.get("WORTKLAR_PASSWORD")

        if verify_password(password, expected_hash_or_secret):
            login_limiter.record_success(client_ip)
            login_user()
            return redirect(next_url)
        else:
            remaining_attempts = login_limiter.record_failure(client_ip)
            locked_now, remaining_secs = login_limiter.is_locked_out(client_ip)
            status_code = 429 if locked_now else 401
            err_msg = "Too many failed attempts. Temporary lockout active." if locked_now else "Incorrect owner password."
            return render_template(
                "login.html",
                csrf_token=csrf_token,
                next_url=next_url,
                error_message=err_msg,
                lockout_seconds=remaining_secs if locked_now else None,
                remaining_attempts=remaining_attempts if not locked_now else 0
            ), status_code

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        """End the current private owner session."""
        if request.method == "POST" and app.config.get("HOSTED_MODE"):
            if not validate_csrf_token(request):
                return jsonify({"error": "csrf_invalid", "message": "Invalid CSRF token."}), 403

        logout_user()
        if app.config.get("HOSTED_MODE"):
            return redirect(url_for("login"))
        return redirect(url_for("index"))

    if os.environ.get("WORTKLAR_TEST_AUTH") == "true":
        @app.route("/_test_login")
        def _test_login():
            """Harness endpoint for headless browser testing."""
            login_user()
            target = request.args.get("next", "/")
            return redirect(target)

    @app.route("/")
    def index():
        """Render the single-page interface."""
        db_exists = os.path.exists(app.config["DB_PATH"])
        metadata = {}
        if db_exists:
            try:
                conn = get_conn()
                metadata = get_metadata(conn)
                conn.close()
            except Exception:
                db_exists = False

        csrf_token = get_or_create_csrf_token()
        return render_template(
            "index.html",
            db_exists=db_exists,
            metadata=metadata,
            hosted_mode=app.config.get("HOSTED_MODE", False),
            csrf_token=csrf_token
        )

    @app.route("/api/status")
    def api_status():
        """Check database status, record counts, and metadata."""
        db_path = app.config["DB_PATH"]
        if not os.path.exists(db_path):
            return jsonify({
                "status": "missing_index",
                "message": "Database not initialized. Please run bootstrap.py.",
                "db_path": db_path
            }), 200

        try:
            conn = get_conn()
            meta = get_metadata(conn)
            lemma_count = meta.get("lemma_count", 0)
            form_count = meta.get("form_count", 0)
            search_count = meta.get("search_index_count", 0)

            # Only run heavy full disk scan if explicitly requested
            integrity_ok = True
            if request.args.get("full_check") == "true":
                integrity_ok = check_integrity(conn)

            conn.close()

            return jsonify({
                "status": "ready",
                "lemma_count": lemma_count,
                "form_count": form_count,
                "search_index_count": search_count,
                "integrity_ok": integrity_ok,
                "metadata": meta
            })
        except Exception as ex:
            return jsonify({
                "status": "error",
                "message": str(ex)
            }), 500

    @app.route("/api/suggest")
    def api_suggest():
        """
        Keyboard suggestion endpoint:
        - 4-letter threshold rule: if trimmed Unicode NFC input has < 4 letters, returns empty list.
        - Returns up to 8 selectable results ranked by exactness, case, literal prefix, and forms.
        """
        raw_query = request.args.get("q", "").strip()
        # Bounded query length check
        if len(raw_query) > 100:
            raw_query = raw_query[:100]

        q = normalize_input(raw_query)
        if count_letters(q) < 4:
            return jsonify({
                "query": q,
                "letter_count": count_letters(q),
                "threshold_met": False,
                "suggestions": []
            })

        try:
            conn = get_conn()
            suggestions = get_suggestions(conn, q, limit=8)
            conn.close()
            return jsonify({
                "query": q,
                "letter_count": count_letters(q),
                "threshold_met": True,
                "suggestions": suggestions
            })
        except FileNotFoundError:
            return jsonify({
                "error": "database_missing",
                "message": "Database index is missing. Please run bootstrap."
            }), 503
        except Exception as ex:
            return jsonify({"error": "server_error", "message": str(ex)}), 500

    @app.route("/api/lookup")
    def api_lookup():
        """
        Complete word lookup endpoint for words of any length (e.g. 'in', 'Ei', 'bin').
        Returns exact entries, inflected form matches, lookalikes, and typo suggestions.
        """
        raw_query = request.args.get("q", "").strip()
        if len(raw_query) > 100:
            raw_query = raw_query[:100]

        q = normalize_input(raw_query)
        if not q:
            return jsonify({"error": "empty_query", "message": "Please enter a word."}), 400

        try:
            conn = get_conn()
            result = lookup_word(conn, q)
            conn.close()
            return jsonify(result)
        except FileNotFoundError:
            return jsonify({
                "error": "database_missing",
                "message": "Database index is missing. Please run bootstrap."
            }), 503
        except Exception as ex:
            return jsonify({"error": "server_error", "message": str(ex)}), 500

    @app.route("/api/check_online", methods=["POST"])
    def api_check_online():
        """
        Explicit Check Wiktionary Online action (R5).
        Manual external call, timeout-bounded, restricted to known hosts,
        deduplicated, with optional server-side Gemini explanation stage.
        """
        # Cross-origin protection
        sec_fetch = request.headers.get("Sec-Fetch-Site")
        if sec_fetch and sec_fetch not in ("same-origin", "same-site", "none"):
            return jsonify({"error": "forbidden", "message": "Cross-origin requests blocked."}), 403

        data = request.get_json(silent=True) or request.form
        raw_word = data.get("word", "").strip() if data else ""
        if len(raw_word) > 100:
            raw_word = raw_word[:100]

        word = normalize_input(raw_word)
        if not word:
            return jsonify({"error": "empty_word", "message": "No word specified."}), 400

        try:
            from wortklar.online import check_word_online
            res = check_word_online(word)
            return jsonify(res)
        except Exception as ex:
            return jsonify({
                "error": "online_check_failed",
                "message": f"Online research failed: {str(ex)}"
            }), 500

    return app
