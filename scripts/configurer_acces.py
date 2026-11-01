from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path
import sys
import tomllib

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_PATH = ROOT_DIR / ".streamlit" / "secrets.toml"
sys.path.insert(0, str(ROOT_DIR))

from core.auth import hash_password  # noqa: E402


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET_PATH)
    args = parser.parse_args()
    target_path = args.output.resolve()
    print("Configuration de l’accès privé Chill Point Services")
    login_id = input("Identifiant du dirigeant [dirigeant] : ").strip() or "dirigeant"
    display_name = input("Nom affiché [Dirigeant] : ").strip() or "Dirigeant"
    password = getpass("Mot de passe (15 caractères minimum) : ")
    confirmation = getpass("Confirmez le mot de passe : ")

    if password != confirmation:
        raise SystemExit("Les deux mots de passe ne correspondent pas.")
    if len(password) < 15:
        raise SystemExit("Le mot de passe doit contenir au moins 15 caractères.")
    if len(password) > 128:
        raise SystemExit("Le mot de passe ne doit pas dépasser 128 caractères.")

    password_hash = hash_password(password)
    lines = [
        "# Fichier privé : ne jamais publier dans Git.",
        "",
        "[access]",
        f"login_id = {_toml_string(login_id)}",
        f"display_name = {_toml_string(display_name)}",
        f"password_hash = {_toml_string(password_hash)}",
        "",
    ]
    if target_path.is_file():
        existing = tomllib.loads(target_path.read_text(encoding="utf-8"))
        database = existing.get("database")
        if isinstance(database, dict):
            lines.extend(["[database]"])
            for key in ("backend", "project_ref", "url"):
                if key in database:
                    lines.append(f"{key} = {_toml_string(str(database[key]))}")
            lines.append("")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Accès configuré dans {target_path}")
    print("Redémarrez maintenant l’application.")


if __name__ == "__main__":
    main()
