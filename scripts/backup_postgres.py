"""Create, restore-test, and optionally encrypt a PostgreSQL custom-format dump."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.config_loader import load_database_config
from core.database import POSTGRES_SCHEMA_VERSION


POSTGRES_IMAGE = "postgres:17-alpine"
MAGIC = b"CPSBACKUP1"


def run(command: list[str], *, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "erreur sans détail").strip()[-1200:]
        raise RuntimeError(
            f"Commande de sauvegarde en échec ({command[1] if len(command) > 1 else command[0]}): {detail}"
        )
    return result


def connection_parts(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    return {
        "host": parsed.hostname or "",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") or "postgres",
    }


def create_dump(url: str, output: Path) -> None:
    parts = connection_parts(url)
    output.parent.mkdir(parents=True, exist_ok=True)
    mount = f"{output.parent.resolve()}:/backup"
    run(
        [
            "docker", "run", "--rm",
            "-e", "PGPASSWORD", "-e", "PGSSLMODE=require",
            "-v", mount,
            POSTGRES_IMAGE,
            "pg_dump",
            "--host", parts["host"],
            "--port", parts["port"],
            "--username", parts["user"],
            "--dbname", parts["database"],
            "--format=custom",
            "--schema=public",
            "--no-owner",
            "--no-acl",
            "--file", f"/backup/{output.name}",
        ],
        environment={**os.environ, "PGPASSWORD": parts["password"]},
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Le dump PostgreSQL n'a pas été produit.")


def verify_restore(dump_path: Path) -> None:
    container = f"cps-restore-{uuid.uuid4().hex[:10]}"
    password = secrets.token_urlsafe(24)
    mount = f"{dump_path.parent.resolve()}:/backup:ro"
    try:
        run([
            "docker", "run", "--detach", "--rm", "--name", container,
            "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_DB=restore_test",
            "-v", mount,
            POSTGRES_IMAGE,
        ])
        ready = False
        for _ in range(30):
            result = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "restore_test"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise RuntimeError("La base de restauration isolée n'est pas devenue disponible.")
        run([
            "docker", "exec", "-e", f"PGPASSWORD={password}", container,
            "psql", "-U", "postgres", "-d", "restore_test", "-v", "ON_ERROR_STOP=1",
            "-c", "DROP SCHEMA public CASCADE;",
        ])
        run([
            "docker", "exec", "-e", f"PGPASSWORD={password}", container,
            "pg_restore", "-U", "postgres", "-d", "restore_test",
            "--no-owner", "--no-acl", f"/backup/{dump_path.name}",
        ])
        result = run([
            "docker", "exec", "-e", f"PGPASSWORD={password}", container,
            "psql", "-U", "postgres", "-d", "restore_test", "-Atc",
            "SELECT COALESCE(MAX(version),0) FROM schema_migrations;",
        ])
        if result.stdout.strip() != str(POSTGRES_SCHEMA_VERSION):
            raise RuntimeError("La restauration ne contient pas la version de schéma attendue.")
    finally:
        subprocess.run(
            ["docker", "stop", container], capture_output=True, text=True, timeout=30, check=False
        )


def encrypt_dump(dump_path: Path, passphrase: str) -> Path:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as error:
        raise RuntimeError("Installez requirements-backup.txt pour chiffrer les sauvegardes.") from error
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))
    encrypted = AESGCM(key).encrypt(nonce, dump_path.read_bytes(), MAGIC)
    output = dump_path.with_suffix(dump_path.suffix + ".enc")
    output.write_bytes(MAGIC + salt + nonce + encrypted)
    dump_path.unlink()
    return output


def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets-file", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "backups")
    parser.add_argument("--verify-restore", action="store_true")
    parser.add_argument("--encrypt", action="store_true")
    parser.add_argument("--passphrase-file", type=Path)
    args = parser.parse_args()
    config = load_database_config(args.secrets_file)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = args.output_dir / f"chill-point-postgres-{timestamp}.dump"
    create_dump(config.url, dump_path)
    if args.verify_restore:
        verify_restore(dump_path)
    final_path = dump_path
    if args.encrypt:
        passphrase = (
            args.passphrase_file.read_text(encoding="utf-8").strip()
            if args.passphrase_file
            else os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE", "")
        )
        if len(passphrase) < 20:
            raise RuntimeError("BACKUP_ENCRYPTION_PASSPHRASE doit contenir au moins 20 caractères.")
        final_path = encrypt_dump(dump_path, passphrase)
    checksum = write_checksum(final_path)
    print(f"Sauvegarde créée: {final_path.name}")
    print(f"Empreinte créée: {checksum.name}")
    if args.verify_restore:
        print("Restauration isolée validée.")


if __name__ == "__main__":
    main()
