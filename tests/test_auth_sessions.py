import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import database


class AuthSessionRegistryTest(unittest.TestCase):
    def setUp(self):
        self.backend_patch = patch.dict(os.environ, {"DB_BACKEND": "sqlite"})
        self.backend_patch.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir, self.old_db_path = database.DATA_DIR, database.DB_PATH
        database.DATA_DIR = Path(self.temp_dir.name)
        database.DB_PATH = database.DATA_DIR / "auth-sessions.db"
        database.init_db()

    def tearDown(self):
        database.DATA_DIR, database.DB_PATH = self.old_data_dir, self.old_db_path
        self.temp_dir.cleanup()
        self.backend_patch.stop()

    def test_active_session_is_revoked_and_cannot_be_replayed(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fingerprint = "a" * 64
        database.create_auth_session(fingerprint, now + timedelta(hours=1))
        self.assertTrue(database.is_auth_session_active(fingerprint, now))
        database.revoke_auth_session(fingerprint)
        self.assertFalse(database.is_auth_session_active(fingerprint, now))

    def test_expired_and_unknown_sessions_are_denied(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fingerprint = "b" * 64
        database.create_auth_session(fingerprint, now + timedelta(minutes=1))
        self.assertFalse(
            database.is_auth_session_active(fingerprint, now + timedelta(minutes=2))
        )
        self.assertFalse(database.is_auth_session_active("c" * 64, now))


if __name__ == "__main__":
    unittest.main()
