"""
Authentication, CSRF protection, and rate limiting for Wortklar hosted mode.
"""

import hmac
import os
import secrets
import time
from typing import Dict, Tuple, Optional
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Request, session, abort


class LoginRateLimiter:
    """
    In-memory bounded rate limiter for login attempts by client IP.
    Blocks brute-force password guessing.
    Default: max 5 failed attempts within 15 minutes (900 seconds).
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # ip -> (failed_count, first_failure_timestamp, lockout_until_timestamp)
        self._records: Dict[str, Tuple[int, float, float]] = {}

    def get_client_ip(self, request: Request) -> str:
        """Extract client IP, inspecting X-Forwarded-For if behind a proxy like Render."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first (original client) IP in the comma-separated chain
            ip = forwarded.split(",")[0].strip()
            if ip:
                return ip
        return request.remote_addr or "127.0.0.1"

    def is_locked_out(self, client_ip: str) -> Tuple[bool, int]:
        """
        Check if IP is currently locked out.
        Returns (is_locked, remaining_lockout_seconds).
        """
        now = time.time()
        record = self._records.get(client_ip)
        if not record:
            return False, 0

        failed_count, first_time, lockout_until = record

        # Check if lockout is active
        if lockout_until > now:
            return True, int(lockout_until - now)

        # Check if window expired
        if now - first_time > self.window_seconds:
            # Window expired, reset
            self._records.pop(client_ip, None)
            return False, 0

        if failed_count >= self.max_attempts:
            # Still in window and exceeded attempts
            remaining = int(self.window_seconds - (now - first_time))
            return True, max(remaining, 1)

        return False, 0

    def record_failure(self, client_ip: str) -> int:
        """
        Record a failed attempt.
        Returns the number of remaining attempts before lockout.
        """
        now = time.time()
        record = self._records.get(client_ip)

        if not record:
            self._records[client_ip] = (1, now, 0.0)
            return self.max_attempts - 1

        failed_count, first_time, lockout_until = record

        if now - first_time > self.window_seconds:
            # Previous window expired
            self._records[client_ip] = (1, now, 0.0)
            return self.max_attempts - 1

        new_count = failed_count + 1
        new_lockout = 0.0
        if new_count >= self.max_attempts:
            new_lockout = now + self.window_seconds

        self._records[client_ip] = (new_count, first_time, new_lockout)
        return max(0, self.max_attempts - new_count)

    def record_success(self, client_ip: str) -> None:
        """Reset failed attempt counters upon successful login."""
        self._records.pop(client_ip, None)

    def prune(self) -> None:
        """Prune expired records to prevent unbounded memory growth."""
        now = time.time()
        expired = [
            ip for ip, (count, first_time, lockout) in self._records.items()
            if now - first_time > self.window_seconds and lockout <= now
        ]
        for ip in expired:
            self._records.pop(ip, None)


# Global login rate limiter instance
login_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)


def hash_password(password: str) -> str:
    """Generate a secure password hash (scrypt if supported, otherwise pbkdf2:sha256)."""
    try:
        return generate_password_hash(password, method="scrypt")
    except (AttributeError, ValueError):
        return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(provided_password: str, stored_hash_or_secret: str) -> bool:
    """
    Verify provided password against a hash or exact secret using constant-time comparison.
    Supports Werkzeug hashes (scrypt / pbkdf2) and plaintext secret comparison.
    """
    if not provided_password or not stored_hash_or_secret:
        return False

    # Check if stored value looks like a Werkzeug hash (e.g. scrypt:..., pbkdf2:...)
    if stored_hash_or_secret.startswith(("scrypt:", "pbkdf2:", "argon2:")):
        try:
            return check_password_hash(stored_hash_or_secret, provided_password)
        except Exception:
            return False

    # Constant time comparison for raw secret string fallback
    return hmac.compare_digest(stored_hash_or_secret.encode("utf-8"), provided_password.encode("utf-8"))


def get_or_create_csrf_token() -> str:
    """Ensure a cryptographically secure CSRF token exists in the current session."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token(request: Request) -> bool:
    """
    Validate CSRF token for state-changing requests (POST, PUT, DELETE, PATCH).
    Checks header 'X-CSRF-Token', form data 'csrf_token', or JSON payload 'csrf_token'.
    """
    expected = session.get("csrf_token")
    if not expected:
        return False

    # 1. Check header
    token = request.headers.get("X-CSRF-Token")
    if token and hmac.compare_digest(token, expected):
        return True

    # 2. Check form data
    token = request.form.get("csrf_token")
    if token and hmac.compare_digest(token, expected):
        return True

    # 3. Check JSON payload
    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            token = data.get("csrf_token")
            if token and hmac.compare_digest(str(token), expected):
                return True

    return False


def is_authenticated() -> bool:
    """Check if the current session has been authenticated."""
    return bool(session.get("authenticated") is True)


def login_user() -> None:
    """Mark the current session as authenticated and rotate CSRF token."""
    session["authenticated"] = True
    session["csrf_token"] = secrets.token_hex(32)


def logout_user() -> None:
    """Clear session authentication state and rotate CSRF token."""
    session.pop("authenticated", None)
    session["csrf_token"] = secrets.token_hex(32)


def check_hosted_mode_configured() -> Tuple[bool, Optional[str]]:
    """
    Verify whether hosted mode is requested and whether all required secrets exist.
    Fails closed if hosted mode is enabled but secrets are missing.
    Returns (is_hosted, error_message).
    """
    is_hosted = (
        os.environ.get("HOSTED_MODE", "").lower() in ("true", "1", "yes")
        or bool(os.environ.get("RENDER"))
    )

    if not is_hosted:
        return False, None

    # Hosted mode requires SECRET_KEY and password configuration
    secret_key = os.environ.get("SECRET_KEY") or os.environ.get("WORTKLAR_SECRET_KEY")
    password_hash = os.environ.get("WORTKLAR_PASSWORD_HASH") or os.environ.get("WORTKLAR_PASSWORD")

    if not secret_key:
        return True, "HOSTED_MODE is active but SECRET_KEY (or WORTKLAR_SECRET_KEY) environment variable is missing."

    if not password_hash:
        return True, "HOSTED_MODE is active but WORTKLAR_PASSWORD_HASH (or WORTKLAR_PASSWORD) environment variable is missing."

    return True, None
