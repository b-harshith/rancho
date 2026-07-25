"""Password exchange and session-status endpoint for the research portal."""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler

try:
    from portal_auth import (
        clear_session_cookie,
        is_authorized,
        is_configured,
        issue_session,
        password_matches,
        session_cookie,
    )
except ImportError:  # pragma: no cover - package import in tests/tooling
    from src.portal_auth import (
        clear_session_cookie,
        is_authorized,
        is_configured,
        issue_session,
        password_matches,
        session_cookie,
    )


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_configured():
            self._send_json(
                {"authenticated": False, "error": "Portal access is not configured"},
                503,
            )
            return
        self._send_json({"authenticated": is_authorized(self.headers)})

    def do_POST(self):
        if not is_configured():
            self._send_json(
                {"authenticated": False, "error": "Portal access is not configured"},
                503,
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._send_json({"authenticated": False, "error": "Invalid request"}, 400)
            return

        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        try:
            if content_type == "application/json":
                payload = json.loads(raw.decode("utf-8"))
            else:
                form = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                payload = {key: values[-1] for key, values in form.items()}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"authenticated": False, "error": "Invalid request"}, 400)
            return

        action = str(payload.get("action", "login")) if isinstance(payload, dict) else "login"
        if action == "logout":
            self._send_json(
                {"authenticated": False},
                cookie=clear_session_cookie(self.headers),
            )
            return

        password = payload.get("password") if isinstance(payload, dict) else None
        if not password_matches(password):
            self._send_json(
                {"authenticated": False, "error": "The password was not accepted"},
                401,
            )
            return

        token, expires_at = issue_session()
        self._send_json(
            {"authenticated": True, "expires_at": expires_at},
            cookie=session_cookie(self.headers, token, expires_at),
        )

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, payload, status=200, cookie=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
