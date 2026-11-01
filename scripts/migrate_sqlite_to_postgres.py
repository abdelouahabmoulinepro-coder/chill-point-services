"""Validate and import a verified SQLite backup into an empty PostgreSQL schema.

The default mode is read-only and reports table counts. Passing --execute writes
inside one PostgreSQL transaction. It never deletes or truncates destination data.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.database import _postgres_url, get_backend_name, init_db


TABLES = (
    "company_settings",
    "customers",
    "items",
    "sequences",
    "documents",
    "document_lines",
    "payments",
    "client_requests",
)

BUSINESS_TABLES = tuple(table for table in TABLES if table != "company_settings")

IDENTITY_TABLES = (
    "customers",
    "items",
    "documents",
    "document_lines",
    "payments",
    "client_requests",
)

BOOLEAN_COLUMNS = {
    "company_settings": {"show_prices_on_delivery_note"},
    "customers": {"active"},
    "items": {"track_stock", "active"},
}

TIMESTAMP_COLUMNS = {
    "customers": {"created_at"},
    "items": {"created_at"},
    "documents": {"created_at"},
    "payments": {"created_at"},
    "client_requests": {"created_at", "updated_at"},
}

SOURCE_TIMEZONE = ZoneInfo("Africa/Casablanca")


def source_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]


def validate_source(conn: sqlite3.Connection) -> dict[str, int]:
    available = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    missing = set(TABLES) - available
    if missing:
        raise RuntimeError(f"Tables SQLite manquantes: {', '.join(sorted(missing))}")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError("La vérification d'intégrité SQLite a échoué.")
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"La sauvegarde SQLite contient {len(foreign_keys)} violation(s) de clé étrangère.")
    return {table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in TABLES}


def normalized_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for column in BOOLEAN_COLUMNS.get(table, set()):
        if column in result:
            result[column] = bool(result[column])
    for column in TIMESTAMP_COLUMNS.get(table, set()):
        if result.get(column):
            parsed = datetime.fromisoformat(str(result[column]))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SOURCE_TIMEZONE)
            result[column] = parsed.astimezone(timezone.utc)
    return result


def insert_rows(target: psycopg.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    target_columns = {
        row[0]
        for row in target.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            (table,),
        ).fetchall()
    }
    columns = [column for column in rows[0] if column in target_columns]
    if not columns:
        raise RuntimeError(f"Aucune colonne compatible pour {table}.")
    quoted = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    query = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})'
    if table == "company_settings":
        updates = ", ".join(
            f'"{column}" = EXCLUDED."{column}"' for column in columns if column != "id"
        )
        query += f' ON CONFLICT ("id") DO UPDATE SET {updates}'
    with target.cursor() as cursor:
        cursor.executemany(
            query,
            [tuple(normalized_row(table, row).get(column) for column in columns) for row in rows],
        )


def compare_counts(target: psycopg.Connection, expected: dict[str, int]) -> None:
    for table, source_count in expected.items():
        target_count = int(target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        if target_count != source_count:
            raise RuntimeError(
                f"Comptage différent pour {table}: source={source_count}, destination={target_count}."
            )


def compare_financial_totals(source: sqlite3.Connection, target: psycopg.Connection) -> None:
    checks = (("documents", "total"), ("documents", "paid_amount"), ("payments", "amount"))
    for table, column in checks:
        source_value = source.execute(
            f'SELECT COALESCE(SUM("{column}"), 0) FROM "{table}"'
        ).fetchone()[0]
        target_value = target.execute(
            f'SELECT COALESCE(SUM("{column}"), 0) FROM "{table}"'
        ).fetchone()[0]
        source_decimal = Decimal(str(source_value)).quantize(Decimal("0.01"))
        target_decimal = Decimal(str(target_value)).quantize(Decimal("0.01"))
        if source_decimal != target_decimal:
            raise RuntimeError(
                f"Total financier différent pour {table}.{column}: "
                f"source={source_decimal}, destination={target_decimal}."
            )


def migrate(source_path: Path, execute: bool) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(f"Sauvegarde SQLite introuvable: {source_path}")
    uri = source_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as source:
        source.row_factory = sqlite3.Row
        counts = validate_source(source)
        print("Sauvegarde SQLite validée (données non affichées).")
        for table in TABLES:
            print(f"- {table}: {counts[table]} ligne(s)")
        if not execute:
            print("Mode analyse uniquement. Relancez avec --execute après validation de la sauvegarde.")
            return

        if get_backend_name() != "postgres" or not _postgres_url():
            raise RuntimeError("La destination PostgreSQL n'est pas configurée.")
        init_db()
        url = _postgres_url()
        sslmode = "verify-full" if "sslmode=verify-full" in url.lower() else "require"
        with psycopg.connect(url, autocommit=False, sslmode=sslmode, connect_timeout=8) as target:
            with target.transaction():
                target.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('chill-point-data-import'))"
                )
                occupied = {
                    table: int(target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                    for table in BUSINESS_TABLES
                }
                if any(occupied.values()):
                    raise RuntimeError(
                        "La destination contient déjà des données métier; import refusé sans suppression."
                    )
                for table in TABLES:
                    insert_rows(target, table, source_rows(source, table))
                for table in IDENTITY_TABLES:
                    target.execute(
                        f"""
                        SELECT setval(
                            pg_get_serial_sequence('{table}', 'id'),
                            COALESCE(MAX(id), 1),
                            COUNT(*) > 0
                        ) FROM "{table}"
                        """
                    )
                compare_counts(target, counts)
                compare_financial_totals(source, target)
        print("Import terminé et validé dans une transaction unique.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/gestion.db"),
        help="Copie de sauvegarde SQLite cohérente à analyser/importer.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Autorise l'écriture vers PostgreSQL; sans cette option, aucune écriture.",
    )
    args = parser.parse_args()
    migrate(args.source, args.execute)


if __name__ == "__main__":
    main()
