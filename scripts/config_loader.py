"""Load local TOML secrets without logging their contents."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    project_ref: str


def load_database_config(path: Path) -> DatabaseConfig:
    if not path.is_file():
        raise RuntimeError(f"Fichier de secrets introuvable: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    database = data.get("database", {})
    if str(database.get("backend", "")).strip().lower() != "postgres":
        raise RuntimeError("Le fichier de secrets ne sélectionne pas PostgreSQL.")
    url = str(database.get("url", "")).strip()
    project_ref = str(database.get("project_ref", "")).strip()
    if not url or not project_ref:
        raise RuntimeError("L'URI PostgreSQL et le Project ref sont obligatoires.")
    if "://" not in url:
        raise RuntimeError("L'URI PostgreSQL est invalide.")
    authority = url.split("://", 1)[1].split("/", 1)[0]
    if authority.count("@") != 1:
        raise RuntimeError("L'URI contient un caractère réservé non encodé.")
    parsed = urlsplit(url)
    username = unquote(parsed.username or "")
    host = parsed.hostname or ""
    if not (username.endswith(f".{project_ref}") or f".{project_ref}." in host):
        raise RuntimeError("L'URI ne correspond pas au Project ref attendu.")
    if not host.endswith("supabase.com"):
        raise RuntimeError("L'hôte PostgreSQL n'est pas un hôte Supabase attendu.")
    return DatabaseConfig(url=url, project_ref=project_ref)
