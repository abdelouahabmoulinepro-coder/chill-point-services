"""Check PostgreSQL connectivity and schema without printing credentials."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.database import get_backend_name, init_db


def main() -> None:
    if get_backend_name() != "postgres":
        raise RuntimeError("Le moteur configuré n'est pas PostgreSQL.")
    init_db()
    print("Connexion PostgreSQL et version du schéma validées.")


if __name__ == "__main__":
    main()
