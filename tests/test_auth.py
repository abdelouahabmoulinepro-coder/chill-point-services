import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import auth
from core.auth import (
    LoginAttemptLimiter,
    SESSION_TTL_SECONDS,
    create_persistent_session,
    hash_password,
    issue_session_token,
    revoke_persistent_session,
    validate_persistent_session,
    validate_session_token,
    verify_credentials,
)


class AuthTest(unittest.TestCase):
    def test_hash_is_argon2id_and_never_contains_password(self):
        password = "une phrase secrete tres longue"
        password_hash = hash_password(password)
        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertNotIn(password, password_hash)

    def test_verifies_both_identifier_and_password(self):
        password_hash = hash_password("une phrase secrete tres longue")
        self.assertTrue(
            verify_credentials(
                " Direction ",
                "une phrase secrete tres longue",
                "direction",
                password_hash,
            )
        )
        self.assertFalse(
            verify_credentials(
                "autre",
                "une phrase secrete tres longue",
                "direction",
                password_hash,
            )
        )
        self.assertFalse(
            verify_credentials("direction", "mot de passe faux", "direction", password_hash)
        )

    def test_limiter_locks_after_five_failures(self):
        limiter = LoginAttemptLimiter()
        for expected_remaining in [4, 3, 2, 1, 0]:
            self.assertEqual(limiter.record_failure(), expected_remaining)
        self.assertGreater(limiter.seconds_remaining(), 0)
        limiter.record_success()
        self.assertEqual(limiter.seconds_remaining(), 0)

    def test_signed_session_survives_fresh_streamlit_sessions_without_credentials(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        session_secret = "server-secret-" + "x" * 48
        password_hash = "$argon2id$private-password-hash"
        password = "phrase confidentielle jamais stockee"

        token, claims = issue_session_token(session_secret, password_hash, now=now)
        self.assertIsNotNone(
            validate_session_token(token, session_secret, password_hash, now=now)
        )
        # F5, new tab, and browser restart all validate the same cookie in a fresh state.
        for _fresh_session in range(3):
            self.assertEqual(
                validate_session_token(token, session_secret, password_hash, now=now),
                claims,
            )
        for forbidden in (password, password_hash, session_secret):
            self.assertNotIn(forbidden, token)
        encoded_payload = token.split(".", 1)[0]
        payload = json.loads(
            base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        )
        self.assertEqual(set(payload), {"v", "sid", "iat", "exp"})

    def test_tampering_rotation_and_expiry_are_rejected(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        token, _ = issue_session_token("s" * 48, "$argon2id$hash", now=now)
        replacement = "A" if token[-1] != "A" else "B"
        tampered = token[:-1] + replacement
        self.assertIsNone(validate_session_token(tampered, "s" * 48, "$argon2id$hash", now=now))
        self.assertIsNone(validate_session_token(token, "t" * 48, "$argon2id$hash", now=now))
        self.assertIsNone(validate_session_token(token, "s" * 48, "$argon2id$new", now=now))
        self.assertIsNone(
            validate_session_token(
                token,
                "s" * 48,
                "$argon2id$hash",
                now=now + timedelta(seconds=SESSION_TTL_SECONDS),
            )
        )

    @patch("core.auth.is_auth_session_active", return_value=True)
    @patch("core.auth.create_auth_session")
    def test_registry_allows_authenticated_access_after_refresh(self, register, is_active):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        token, claims = create_persistent_session("s" * 48, "$argon2id$hash", now=now)
        register.assert_called_once()
        self.assertEqual(
            validate_persistent_session(token, "s" * 48, "$argon2id$hash", now=now),
            claims,
        )
        is_active.assert_called_once()

    @patch("core.auth.revoke_auth_session")
    def test_logout_revokes_server_side_session(self, revoke):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        token, _ = issue_session_token("s" * 48, "$argon2id$hash", now=now)
        with patch("core.auth.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = now
            mocked_datetime.fromtimestamp = datetime.fromtimestamp
            revoke_persistent_session(token, "s" * 48, "$argon2id$hash")
        revoke.assert_called_once()

    def test_missing_token_cannot_authenticate(self):
        self.assertIsNone(validate_session_token("", "s" * 48, "$argon2id$hash"))

    def test_production_cookie_is_secure_strict_and_expiring(self):
        manager = Mock()
        expires_at = int(datetime.now(timezone.utc).timestamp()) + SESSION_TTL_SECONDS
        with (
            patch.object(auth.st, "context", SimpleNamespace(url="https://app.example.test/admin")),
            patch("core.auth._cookie_manager", return_value=manager),
        ):
            auth._set_browser_cookie("signed-token", expires_at)
        _, kwargs = manager.set.call_args
        self.assertTrue(kwargs["secure"])
        self.assertEqual(kwargs["same_site"], "strict")
        self.assertEqual(kwargs["path"], "/")
        self.assertEqual(kwargs["max_age"], SESSION_TTL_SECONDS)


if __name__ == "__main__":
    unittest.main()
