from __future__ import annotations

from getpass import getpass
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
TARGET_PATH = ROOT_DIR / ".streamlit" / "secrets.toml"
sys.path.insert(0, str(ROOT_DIR))

from core.auth import hash_password  # noqa: E402


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
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
    content = "\n".join(
        [
            "# Fichier privé : ne jamais publier dans Git.",
            "",
            "[access]",
            f"login_id = {_toml_string(login_id)}",
            f"display_name = {_toml_string(display_name)}",
            f"password_hash = {_toml_string(password_hash)}",
            "",
        ]
    )
    TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PATH.write_text(content, encoding="utf-8")
    print(f"Accès configuré dans {TARGET_PATH}")
    print("Redémarrez maintenant l’application.")


if __name__ == "__main__":
    main()
