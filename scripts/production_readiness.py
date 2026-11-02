"""Read-only production database readiness checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.database import POSTGRES_SCHEMA_VERSION
from scripts.config_loader import load_database_config


BUSINESS_TABLES = (
    "customers",
    "items",
    "documents",
    "document_lines",
    "payments",
    "client_requests",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets-file", required=True, type=Path)
    parser.add_argument(
        "--require-empty-business-data",
        action="store_true",
        help="Réservé au premier déploiement d'une production encore vide.",
    )
    args = parser.parse_args()
    config = load_database_config(args.secrets_file)
    sslmode = "verify-full" if "sslmode=verify-full" in config.url.lower() else "require"
    with psycopg.connect(config.url, sslmode=sslmode, connect_timeout=8) as conn:
        role = conn.execute(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if not role or any(role[1:]):
            raise RuntimeError("Le rôle runtime possède des privilèges administratifs interdits.")
        if role[0] == "postgres":
            raise RuntimeError("Le rôle administrateur postgres ne peut pas servir au runtime.")
        version = int(conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])
        if version != POSTGRES_SCHEMA_VERSION:
            raise RuntimeError(
                f"Version du schéma incorrecte: {version}; "
                f"version attendue: {POSTGRES_SCHEMA_VERSION}."
            )
        counts = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in BUSINESS_TABLES
        }
        if args.require_empty_business_data and any(counts.values()):
            raise RuntimeError("La production contient déjà des données métier.")
        sequence_rows = int(conn.execute("SELECT COUNT(*) FROM sequences").fetchone()[0])
        if args.require_empty_business_data and sequence_rows:
            raise RuntimeError("Les séquences métier de production ne sont pas vides.")
        if conn.execute(
            "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
        ).fetchone()[0]:
            raise RuntimeError("Le rôle runtime peut créer des objets dans le schéma public.")
        for table in BUSINESS_TABLES + (
            "company_settings",
            "sequences",
            "schema_migrations",
            "auth_sessions",
        ):
            allowed = conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT')",
                (f"public.{table}",),
            ).fetchone()[0]
            if not allowed:
                raise RuntimeError(f"Privilège SELECT absent pour {table}.")
        for privilege in ("INSERT", "UPDATE"):
            allowed = conn.execute(
                "SELECT has_table_privilege(current_user, 'public.auth_sessions', %s)",
                (privilege,),
            ).fetchone()[0]
            if not allowed:
                raise RuntimeError(
                    f"Privilège {privilege} absent pour auth_sessions."
                )
        index_exists = conn.execute(
            "SELECT to_regclass('public.uq_documents_source_type') IS NOT NULL"
        ).fetchone()[0]
        if not index_exists:
            raise RuntimeError("Index d'unicité des conversions absent.")
        foreign_keys = int(conn.execute(
            """
            SELECT COUNT(*) FROM pg_constraint
            WHERE contype = 'f' AND connamespace = 'public'::regnamespace
            """
        ).fetchone()[0])
        if foreign_keys < 5:
            raise RuntimeError("Certaines clés étrangères attendues sont absentes.")
    print("Production PostgreSQL prête: schéma valide et rôle limité.")


if __name__ == "__main__":
    main()
