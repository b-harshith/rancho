import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
os.sys.path.insert(0, str(ROOT / "src"))

import portal_auth  # noqa: E402


class PortalAuthTests(unittest.TestCase):
    def configured_environment(self):
        return patch.dict(
            os.environ,
            {
                "PORTAL_PASSWORD": "test-password",
                "PORTAL_SESSION_SECRET": "test-secret-that-is-not-for-production",
                "PORTAL_SESSION_TTL_SECONDS": "3600",
            },
            clear=False,
        )

    def test_password_and_signed_session_are_server_side(self):
        with self.configured_environment():
            self.assertTrue(portal_auth.password_matches("test-password"))
            self.assertFalse(portal_auth.password_matches("wrong"))
            token, expires_at = portal_auth.issue_session(now=1_000)
            headers = {"Cookie": f"{portal_auth.COOKIE_NAME}={token}"}
            self.assertTrue(portal_auth.is_authorized(headers, now=1_001))
            self.assertFalse(portal_auth.is_authorized(headers, now=expires_at))

    def test_session_cookie_security_attributes(self):
        with self.configured_environment():
            token, expires_at = portal_auth.issue_session()
            production = portal_auth.session_cookie(
                {"Host": "client.example"}, token, expires_at
            )
            local = portal_auth.session_cookie(
                {"Host": "localhost:8050"}, token, expires_at
            )
            self.assertIn("HttpOnly", production)
            self.assertIn("SameSite=Lax", production)
            self.assertIn("Secure", production)
            self.assertNotIn("Secure", local)

    def test_public_bundle_has_no_embedded_password_or_backup_files(self):
        public = ROOT / "src" / "public"
        self.assertEqual(list(public.glob("*.bak")), [])
        for path in (
            public / "auth.js",
            public / "index.html",
            public / "index.js",
            public / "multicity.html",
            public / "multicity.js",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("04012007", source)
            self.assertNotIn("RANCHO_PASSCODE", source)
            self.assertNotIn("RANCHO_UNLOCKED", source)

if __name__ == "__main__":
    unittest.main()
