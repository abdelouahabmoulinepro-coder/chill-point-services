import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.backup_postgres import encrypt_dump, write_checksum
from scripts.decrypt_backup import decrypt_backup


class BackupEncryptionTest(unittest.TestCase):
    def test_encrypted_backup_round_trip_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dump"
            restored = root / "restored.dump"
            payload = os.urandom(4096)
            source.write_bytes(payload)
            passphrase = "phrase-de-sauvegarde-test-assez-longue"
            encrypted = encrypt_dump(source, passphrase)
            checksum = write_checksum(encrypted)
            self.assertFalse(source.exists())
            decrypt_backup(encrypted, restored, passphrase, checksum)
            self.assertEqual(restored.read_bytes(), payload)

    def test_wrong_passphrase_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dump"
            source.write_bytes(b"contenu fictif")
            encrypted = encrypt_dump(source, "phrase-correcte-suffisamment-longue")
            with self.assertRaises(Exception):
                decrypt_backup(
                    encrypted,
                    root / "restored.dump",
                    "phrase-incorrecte-suffisamment-longue",
                )


if __name__ == "__main__":
    unittest.main()
