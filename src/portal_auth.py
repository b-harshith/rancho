"""Small, server-side session helper for the client research portal.

The password and signing key are deployment secrets.  Browser code never sees
either value; it only receives an HttpOnly, signed, expiring session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from http.cookies import SimpleCookie


COOKIE_NAME = "rancho_portal_session"
DEFAULT_TTL_SECONDS = 12 * 60 * 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60


def _portal_password() -> str:
    return os.environ.get("PORTAL_PASSWORD", "")


def _session_secret() -> str:
    return os.environ.get("PORTAL_SESSION_SECRET", "")


def is_configured() -> bool:
    return bool(_portal_password() and _session_secret())


def _ttl_seconds() -> int:
    try:
        configured = int(os.environ.get("PORTAL_SESSION_TTL_SECONDS", DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        configured = DEFAULT_TTL_SECONDS
    return max(15 * 60, min(configured, MAX_TTL_SECONDS))


def password_matches(candidate: object) -> bool:
    expected = _portal_password()
    if not expected or not isinstance(candidate, str):
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def _signature(expires_at: int) -> str:
    secret = _session_secret().encode("utf-8")
    return hmac.new(secret, str(expires_at).encode("ascii"), hashlib.sha256).hexdigest()


def issue_session(now: int | None = None) -> tuple[str, int]:
    if not is_configured():
        raise RuntimeError("Portal authentication is not configured")
    expires_at = int(now or time.time()) + _ttl_seconds()
    return f"{expires_at}.{_signature(expires_at)}", expires_at


def _cookie_value(headers) -> str:
    cookie_header = headers.get("Cookie", "") if headers else ""
    if not cookie_header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return ""
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else ""


def is_authorized(headers, now: int | None = None) -> bool:
    if not is_configured():
        return False
    value = _cookie_value(headers)
    try:
        expires_raw, supplied = value.split(".", 1)
        expires_at = int(expires_raw)
    except (AttributeError, TypeError, ValueError):
        return False
    if expires_at <= int(now or time.time()):
        return False
    return hmac.compare_digest(supplied, _signature(expires_at))


def _is_local_request(headers) -> bool:
    host = (headers.get("Host", "") if headers else "").split(":", 1)[0].lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def session_cookie(headers, token: str, expires_at: int) -> str:
    parts = [
        f"{COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max(0, expires_at - int(time.time()))}",
    ]
    if not _is_local_request(headers):
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie(headers) -> str:
    parts = [
        f"{COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if not _is_local_request(headers):
        parts.append("Secure")
    return "; ".join(parts)
