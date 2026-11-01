"""Check PostgreSQL connectivity and schema without printing credentials."""

import sys
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.database import get_backend_name, init_db
from scripts.config_loader import load_database_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets-file", type=Path)
    args = parser.parse_args()
    if args.secrets_file:
        config = load_database_config(args.secrets_file)
        import psycopg

        sslmode = "verify-full" if "sslmode=verify-full" in config.url.lower() else "require"
        with psycopg.connect(config.url, sslmode=sslmode, connect_timeout=8) as conn:
            marker = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            if int(marker) != 1:
                raise RuntimeError("Version du schéma PostgreSQL incompatible.")
        print("Connexion PostgreSQL et version du schéma validées.")
        return
    if get_backend_name() != "postgres":
        raise RuntimeError("Le moteur configuré n'est pas PostgreSQL.")
    init_db()
    print("Connexion PostgreSQL et version du schéma validées.")


if __name__ == "__main__":
    main()
