"""Apply versioned PostgreSQL migrations without exposing connection secrets."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.database import DatabaseConfigurationError, _postgres_url, get_backend_name
from scripts.config_loader import load_database_config


MIGRATIONS_DIR = ROOT_DIR / "migrations" / "postgres"
MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def migration_files() -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_NAME.match(path.name)
        if not match:
            raise RuntimeError(f"Nom de migration invalide: {path.name}")
        result.append((int(match.group(1)), path))
    versions = [version for version, _ in result]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError("Les migrations PostgreSQL doivent être numérotées sans interruption.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets-file", type=Path)
    args = parser.parse_args()
    if args.secrets_file:
        url = load_database_config(args.secrets_file).url
    else:
        if get_backend_name() != "postgres":
            raise DatabaseConfigurationError(
                "Définissez [database].backend = 'postgres' dans .streamlit/secrets.toml."
            )
        url = _postgres_url()
        if not url:
            raise DatabaseConfigurationError(
                "Renseignez [database].url dans .streamlit/secrets.toml."
            )
    sslmode = "verify-full" if "sslmode=verify-full" in url.lower() else "require"
    with psycopg.connect(
        url,
        autocommit=False,
        connect_timeout=8,
        sslmode=sslmode,
        application_name="chill-point-migrations",
    ) as conn:
        with conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('chill-point-schema-migrations'))"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                int(row[0])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            pending = [(version, path) for version, path in migration_files() if version not in applied]
            for version, path in pending:
                conn.execute(path.read_text(encoding="utf-8"), prepare=False)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (version, path.name),
                )
                print(f"Migration {version:03d} appliquée: {path.name}")
            if not pending:
                print("Schéma PostgreSQL déjà à jour.")


if __name__ == "__main__":
    main()
