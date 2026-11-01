"""Decrypt an AES-GCM PostgreSQL backup created by backup_postgres.py."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


MAGIC = b"CPSBACKUP1"


def decrypt_backup(
    encrypted: Path,
    output: Path,
    passphrase: str,
    checksum: Path | None = None,
) -> None:
    if len(passphrase) < 20:
        raise RuntimeError("BACKUP_ENCRYPTION_PASSPHRASE doit contenir au moins 20 caractères.")
    payload = encrypted.read_bytes()
    if checksum:
        expected = checksum.read_text(encoding="ascii").split()[0]
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise RuntimeError("L'empreinte SHA-256 de la sauvegarde est invalide.")
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 28:
        raise RuntimeError("Format de sauvegarde chiffrée invalide.")
    offset = len(MAGIC)
    salt = payload[offset : offset + 16]
    nonce = payload[offset + 16 : offset + 28]
    ciphertext = payload[offset + 28 :]
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC)
    output.write_bytes(plaintext)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("encrypted", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--checksum", type=Path)
    args = parser.parse_args()
    passphrase = os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE", "")
    decrypt_backup(args.encrypted, args.output, passphrase, args.checksum)
    print("Sauvegarde déchiffrée et authentifiée.")


if __name__ == "__main__":
    main()
