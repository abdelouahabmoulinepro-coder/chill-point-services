import unittest

from core.auth import LoginAttemptLimiter, hash_password, verify_credentials


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


if __name__ == "__main__":
    unittest.main()
