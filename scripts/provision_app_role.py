"""Create/rotate a least-privilege application role without printing secrets."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import tomllib
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.config_loader import load_database_config


ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


def write_runtime_secrets(path: Path, url: str, project_ref: str) -> None:
    existing = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    access = existing.get("access", {})
    login_id = str(access.get("login_id", ""))
    display_name = str(access.get("display_name", "Dirigeant"))
    password_hash = str(access.get("password_hash", ""))
    content = (
        "# Secret de production généré localement et ignoré par Git.\n\n"
        "[access]\n"
        f"login_id = {json.dumps(login_id)}\n"
        f"display_name = {json.dumps(display_name)}\n"
        f"password_hash = {json.dumps(password_hash)}\n\n"
        "[database]\n"
        'backend = "postgres"\n'
        f"project_ref = {json.dumps(project_ref)}\n"
        f"url = {json.dumps(url)}\n"
    )
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-secrets", required=True, type=Path)
    parser.add_argument("--runtime-secrets", required=True, type=Path)
    parser.add_argument("--role", default="chill_point_app")
    args = parser.parse_args()
    if not ROLE_PATTERN.fullmatch(args.role):
        raise RuntimeError("Nom de rôle applicatif invalide.")
    config = load_database_config(args.admin_secrets)
    password = secrets.token_urlsafe(36)
    sslmode = "verify-full" if "sslmode=verify-full" in config.url.lower() else "require"
    with psycopg.connect(config.url, autocommit=False, sslmode=sslmode, connect_timeout=8) as conn:
        database_name = conn.info.dbname
        with conn.transaction():
            exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (args.role,)
            ).fetchone()
            role_identifier = sql.Identifier(args.role)
            password_literal = sql.Literal(password)
            if exists:
                conn.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                    ).format(role_identifier, password_literal),
                )
            else:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                    ).format(role_identifier, password_literal),
                )
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database_name), role_identifier
            ))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role_identifier))
            conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role_identifier))
            conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {}").format(role_identifier))
            conn.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role_identifier))
            conn.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO {}"
            ).format(role_identifier))
            conn.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(role_identifier))

    parsed = urlsplit(config.url)
    runtime_username = f"{args.role}.{config.project_ref}"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{quote(runtime_username, safe='.') }:{quote(password, safe='')}@{host}{port}"
    runtime_url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    write_runtime_secrets(args.runtime_secrets, runtime_url, config.project_ref)
    print("Rôle applicatif limité configuré; secret runtime écrit sans affichage des identifiants.")


if __name__ == "__main__":
    main()
