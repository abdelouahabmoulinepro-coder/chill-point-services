from __future__ import annotations

import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool, PoolTimeout
except ImportError:  # SQLite remains usable without the optional PostgreSQL driver.
    psycopg = None
    dict_row = None
    ConnectionPool = None
    PoolTimeout = Exception

from core.formatting import DOCUMENT_PATTERNS, STATUS_OPTIONS


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "gestion.db"
POSTGRES_SCHEMA_VERSION = 1
LOGGER = logging.getLogger(__name__)
_ACTIVE_POOLS: set[Any] = set()


class DatabaseError(RuntimeError):
    """Base class for sanitized persistence errors exposed to the application."""


class DatabaseConfigurationError(DatabaseError):
    pass


class DatabaseUnavailableError(DatabaseError):
    pass


class DatabaseSchemaError(DatabaseError):
    pass


class DatabaseIntegrityError(DatabaseError):
    pass


class DuplicateValueError(DatabaseIntegrityError):
    pass


def _secret_database_section() -> Mapping[str, Any]:
    try:
        section = st.secrets.get("database", {})
    except (StreamlitSecretNotFoundError, FileNotFoundError):
        return {}
    return section if isinstance(section, Mapping) else {}


def get_backend_name() -> str:
    section = _secret_database_section()
    backend = os.environ.get("DB_BACKEND", str(section.get("backend", "sqlite"))).strip().lower()
    if backend not in {"sqlite", "postgres"}:
        raise DatabaseConfigurationError("DB_BACKEND doit valoir 'sqlite' ou 'postgres'.")
    return backend


def _postgres_url() -> str:
    section = _secret_database_section()
    url = os.environ.get("DATABASE_URL", str(section.get("url", ""))).strip()
    expected_project_ref = os.environ.get(
        "DB_PROJECT_REF", str(section.get("project_ref", ""))
    ).strip()
    if url:
        if "://" not in url:
            raise DatabaseConfigurationError("L'URI PostgreSQL est invalide.")
        authority = url.split("://", 1)[1].split("/", 1)[0]
        if authority.count("@") != 1:
            raise DatabaseConfigurationError(
                "L'URI PostgreSQL contient un caractère réservé non encodé dans les identifiants."
            )
        if expected_project_ref:
            parsed = urlsplit(url)
            username = unquote(parsed.username or "")
            host = parsed.hostname or ""
            if not (
                username.endswith(f".{expected_project_ref}")
                or f".{expected_project_ref}." in host
            ):
                raise DatabaseConfigurationError(
                    "L'URI PostgreSQL ne correspond pas au Project ref configuré."
                )
    return url


@lru_cache(maxsize=2)
def _postgres_pool(url: str):
    if psycopg is None or ConnectionPool is None:
        raise DatabaseConfigurationError(
            "Le pilote PostgreSQL n'est pas installé. Installez les dépendances du projet."
        )
    sslmode = "verify-full" if "sslmode=verify-full" in url.lower() else "require"
    pool = ConnectionPool(
        conninfo=url,
        min_size=0,
        max_size=3,
        open=True,
        timeout=8,
        max_lifetime=300,
        kwargs={
            "autocommit": False,
            "connect_timeout": 8,
            "row_factory": dict_row,
            "application_name": "chill-point-services",
            "sslmode": sslmode,
        },
    )
    _ACTIVE_POOLS.add(pool)
    return pool


def reset_database_runtime() -> None:
    """Close cached PostgreSQL pools; primarily useful for isolated tests."""
    for pool in list(_ACTIVE_POOLS):
        pool.close()
    _ACTIVE_POOLS.clear()
    _postgres_pool.cache_clear()


def _postgres_query(query: str) -> str:
    # All SQL in this module uses question marks exclusively as DB-API placeholders.
    return query.replace("?", "%s")


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    return value


class _ConnectionAdapter:
    def __init__(self, raw: Any, backend: str) -> None:
        self.raw = raw
        self.backend = backend

    def execute(self, query: str, params: Iterable[Any] = ()):
        sql = _postgres_query(query) if self.backend == "postgres" else query
        values = tuple(params)
        if self.backend == "sqlite":
            values = tuple(_sqlite_value(value) for value in values)
        try:
            return self.raw.execute(sql, values)
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateValueError("Une valeur unique existe déjà.") from error
            raise DatabaseIntegrityError("La contrainte de données SQLite a été refusée.") from error
        except Exception as error:
            if psycopg is not None and isinstance(error, psycopg.errors.UniqueViolation):
                raise DuplicateValueError("Une valeur unique existe déjà.") from error
            if psycopg is not None and isinstance(error, psycopg.IntegrityError):
                raise DatabaseIntegrityError("La contrainte de données PostgreSQL a été refusée.") from error
            raise

    def executemany(self, query: str, params: Iterable[Iterable[Any]]):
        sql = _postgres_query(query) if self.backend == "postgres" else query
        values = [tuple(row) for row in params]
        if self.backend == "sqlite":
            values = [tuple(_sqlite_value(value) for value in row) for row in values]
            return self.raw.executemany(sql, values)
        with self.raw.cursor() as cursor:
            cursor.executemany(sql, values)

    def executescript(self, script: str):
        if self.backend != "sqlite":
            raise DatabaseSchemaError("Les scripts SQLite ne peuvent pas être exécutés sur PostgreSQL.")
        return self.raw.executescript(script)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ensure_column(conn: _ConnectionAdapter, table: str, name: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


@contextmanager
def connection():
    backend = get_backend_name()
    if backend == "sqlite":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(DB_PATH, timeout=15)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        adapter = _ConnectionAdapter(raw, backend)
        try:
            yield adapter
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        return

    url = _postgres_url()
    if not url:
        raise DatabaseConfigurationError(
            "La connexion PostgreSQL est sélectionnée, mais aucune URI n'est configurée."
        )
    try:
        pool = _postgres_pool(url)
        with pool.connection() as raw:
            with raw.transaction():
                yield _ConnectionAdapter(raw, backend)
    except DatabaseError:
        raise
    except (PoolTimeout, psycopg.OperationalError) as error:
        LOGGER.error("PostgreSQL indisponible (%s).", type(error).__name__)
        raise DatabaseUnavailableError(
            "La base PostgreSQL est momentanément indisponible. Aucun enregistrement n'a été effectué."
        ) from error


def init_db() -> None:
    if get_backend_name() == "postgres":
        with connection() as conn:
            marker = conn.execute(
                "SELECT to_regclass('public.schema_migrations') AS relation_name"
            ).fetchone()
            if not marker or marker["relation_name"] is None:
                raise DatabaseSchemaError(
                    "Le schéma PostgreSQL n'est pas initialisé. Exécutez scripts/migrate_postgres.py."
                )
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()["version"]
            if int(version) != POSTGRES_SCHEMA_VERSION:
                raise DatabaseSchemaError(
                    f"Version du schéma PostgreSQL incompatible: {version}; "
                    f"version attendue: {POSTGRES_SCHEMA_VERSION}."
                )
        return

    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS company_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL,
                slogan TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                tax_id TEXT NOT NULL DEFAULT '',
                registration TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'EUR',
                default_vat REAL NOT NULL DEFAULT 20,
                bank_details TEXT NOT NULL DEFAULT '',
                document_footer TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'Entreprise',
                contact_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                tax_id TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'Service',
                description TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'unité',
                unit_price REAL NOT NULL DEFAULT 0,
                vat_rate REAL NOT NULL DEFAULT 0,
                stock_quantity REAL NOT NULL DEFAULT 0,
                track_stock INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sequences (
                doc_type TEXT NOT NULL,
                year INTEGER NOT NULL,
                last_value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (doc_type, year)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_type TEXT NOT NULL,
                number TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                issue_date TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                terms TEXT NOT NULL DEFAULT '',
                subtotal REAL NOT NULL DEFAULT 0,
                tax_total REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                paid_amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL,
                source_document_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (source_document_id) REFERENCES documents(id)
            );

            CREATE TABLE IF NOT EXISTS document_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                item_id INTEGER,
                description TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT 'unité',
                unit_price REAL NOT NULL,
                discount_rate REAL NOT NULL DEFAULT 0,
                vat_rate REAL NOT NULL DEFAULT 0,
                line_subtotal REAL NOT NULL,
                line_tax REAL NOT NULL,
                line_total REAL NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES items(id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                method TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS client_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                company_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                request_type TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                preferred_contact TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Nouvelle',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_documents_type_date
                ON documents(doc_type, issue_date);
            CREATE INDEX IF NOT EXISTS idx_documents_customer
                ON documents(customer_id);
            CREATE INDEX IF NOT EXISTS idx_payments_document
                ON payments(document_id);
            CREATE INDEX IF NOT EXISTS idx_client_requests_status_date
                ON client_requests(status, created_at);
            """
        )
        for name, definition in {
            "fiscal_id": "TEXT NOT NULL DEFAULT ''",
            "rc": "TEXT NOT NULL DEFAULT ''",
            "patente": "TEXT NOT NULL DEFAULT ''",
            "cnss": "TEXT NOT NULL DEFAULT ''",
            "rib": "TEXT NOT NULL DEFAULT ''",
            "swift": "TEXT NOT NULL DEFAULT ''",
            "logo_path": "TEXT NOT NULL DEFAULT 'assets/logo-moderne-final.png'",
            "show_prices_on_delivery_note": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            _ensure_column(conn, "company_settings", name, definition)
        conn.execute(
            """
            INSERT OR IGNORE INTO company_settings
                (id, name, slogan, currency, default_vat, document_footer)
            VALUES
                (1, 'CHILL POINT SERVICES', 'Services et vente de biens', 'MAD', 20,
                 'Merci pour votre confiance.')
            """
        )


def _rows(query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def _insert_id(conn: _ConnectionAdapter, query: str, params: Iterable[Any]) -> int:
    if conn.backend == "postgres":
        row = conn.execute(f"{query.rstrip()} RETURNING id", tuple(params)).fetchone()
        return int(row["id"])
    cursor = conn.execute(query, tuple(params))
    return int(cursor.lastrowid)


def get_settings() -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM company_settings WHERE id = 1").fetchone()
        return dict(row)


def update_settings(values: dict[str, Any]) -> None:
    allowed = {
        "name",
        "slogan",
        "address",
        "phone",
        "email",
        "tax_id",
        "registration",
        "fiscal_id",
        "rc",
        "patente",
        "cnss",
        "rib",
        "swift",
        "logo_path",
        "show_prices_on_delivery_note",
        "currency",
        "default_vat",
        "bank_details",
        "document_footer",
    }
    clean = {key: values[key] for key in allowed if key in values}
    if not clean:
        return
    assignments = ", ".join(f"{key} = ?" for key in clean)
    with connection() as conn:
        conn.execute(
            f"UPDATE company_settings SET {assignments} WHERE id = 1",
            tuple(clean.values()),
        )


CLIENT_REQUEST_TYPES = [
    "Prestation de services",
    "Achat ou fourniture de produits",
    "Livraison ou logistique",
    "Demande sur mesure",
    "Autre besoin",
]
CLIENT_REQUEST_CONTACT_OPTIONS = ["E-mail", "Téléphone", "WhatsApp"]
CLIENT_REQUEST_STATUSES = ["Nouvelle", "Contactée", "En cours", "Traitée", "Archivée"]


def add_client_request(values: dict[str, Any]) -> int:
    full_name = str(values.get("full_name", "")).strip()
    email = str(values.get("email", "")).strip().casefold()
    phone = str(values.get("phone", "")).strip()
    request_type = str(values.get("request_type", "")).strip()
    company_name = str(values.get("company_name", "")).strip()
    subject = str(values.get("subject", "")).strip()
    message = str(values.get("message", "")).strip()
    preferred_contact = str(values.get("preferred_contact", "")).strip()

    if not full_name or request_type not in CLIENT_REQUEST_TYPES or len(message) < 20:
        raise ValueError("La demande est incomplète.")
    if not email and not phone:
        raise ValueError("Une adresse e-mail ou un téléphone est obligatoire.")
    if preferred_contact and preferred_contact not in CLIENT_REQUEST_CONTACT_OPTIONS:
        raise ValueError("Le moyen de contact est invalide.")
    if (
        len(full_name) > 160
        or len(company_name) > 180
        or len(email) > 180
        or len(phone) > 40
        or len(subject) > 200
    ):
        raise ValueError("Certaines coordonnées sont trop longues.")
    if len(message) > 5000:
        raise ValueError("La description de la demande est trop longue.")

    now = _now()
    recent_limit = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    with connection() as conn:
        if conn.backend == "postgres":
            contact_key = f"{email}|{phone}"
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(?))",
                (contact_key,),
            )
        recent = conn.execute(
            """
            SELECT id FROM client_requests
            WHERE created_at >= ?
              AND ((? <> '' AND lower(email) = ?) OR (? <> '' AND phone = ?))
            LIMIT 1
            """,
            (recent_limit, email, email, phone, phone),
        ).fetchone()
        if recent:
            raise ValueError(
                "Une demande avec ces coordonnées vient déjà d’être envoyée. "
                "Veuillez patienter quelques minutes."
            )
        request_id = _insert_id(
            conn,
            """
            INSERT INTO client_requests
                (full_name, company_name, email, phone, request_type, subject,
                 message, preferred_contact, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Nouvelle', ?, ?)
            """,
            (
                full_name,
                company_name,
                email,
                phone,
                request_type,
                subject,
                message,
                preferred_contact,
                now,
                now,
            ),
        )
        return request_id


def list_client_requests(status: str | None = None) -> list[dict[str, Any]]:
    if status and status in CLIENT_REQUEST_STATUSES:
        return _rows(
            "SELECT * FROM client_requests WHERE status = ? ORDER BY created_at DESC",
            (status,),
        )
    return _rows("SELECT * FROM client_requests ORDER BY created_at DESC")


def get_client_request(request_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM client_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        return dict(row) if row else None


def update_client_request_status(request_id: int, status: str) -> None:
    if status not in CLIENT_REQUEST_STATUSES:
        raise ValueError("Statut de demande invalide.")
    with connection() as conn:
        conn.execute(
            "UPDATE client_requests SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), request_id),
        )


def add_customer(values: dict[str, Any]) -> int:
    with connection() as conn:
        customer_id = _insert_id(
            conn,
            """
            INSERT INTO customers
                (code, name, kind, contact_name, email, phone, address, tax_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values.get("code") or None,
                values["name"].strip(),
                values.get("kind", "Entreprise"),
                values.get("contact_name", "").strip(),
                values.get("email", "").strip(),
                values.get("phone", "").strip(),
                values.get("address", "").strip(),
                values.get("tax_id", "").strip(),
                _now(),
            ),
        )
        if not values.get("code"):
            conn.execute(
                "UPDATE customers SET code = ? WHERE id = ?",
                (f"CLI-{customer_id:04d}", customer_id),
            )
        return customer_id


def list_customers(search: str = "", active_only: bool = True) -> list[dict[str, Any]]:
    postgres = get_backend_name() == "postgres"
    clauses = []
    params: list[Any] = []
    if active_only:
        clauses.append("active = TRUE" if postgres else "active = 1")
    if search.strip():
        operator = "ILIKE" if postgres else "LIKE"
        clauses.append(
            f"(name {operator} ? OR code {operator} ? OR email {operator} ? OR phone {operator} ?)"
        )
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "lower(name), name" if postgres else "name COLLATE NOCASE"
    return _rows(f"SELECT * FROM customers {where} ORDER BY {order}", params)


def add_item(values: dict[str, Any]) -> int:
    with connection() as conn:
        item_id = _insert_id(
            conn,
            """
            INSERT INTO items
                (sku, name, kind, description, unit, unit_price, vat_rate,
                 stock_quantity, track_stock, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values.get("sku") or None,
                values["name"].strip(),
                values.get("kind", "Service"),
                values.get("description", "").strip(),
                values.get("unit", "unité"),
                _decimal(values.get("unit_price", 0)),
                _decimal(values.get("vat_rate", 0)),
                _decimal(values.get("stock_quantity", 0)),
                bool(values.get("track_stock", False)),
                _now(),
            ),
        )
        if not values.get("sku"):
            prefix = "SRV" if values.get("kind") == "Service" else "ART"
            conn.execute(
                "UPDATE items SET sku = ? WHERE id = ?", (f"{prefix}-{item_id:04d}", item_id)
            )
        return item_id


def list_items(search: str = "", active_only: bool = True) -> list[dict[str, Any]]:
    postgres = get_backend_name() == "postgres"
    clauses = []
    params: list[Any] = []
    if active_only:
        clauses.append("active = TRUE" if postgres else "active = 1")
    if search.strip():
        operator = "ILIKE" if postgres else "LIKE"
        clauses.append(f"(name {operator} ? OR sku {operator} ? OR description {operator} ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "lower(name), name" if postgres else "name COLLATE NOCASE"
    return _rows(f"SELECT * FROM items {where} ORDER BY {order}", params)


def _next_number(conn: _ConnectionAdapter, doc_type: str, year: int) -> str:
    pattern = DOCUMENT_PATTERNS[doc_type]
    sequence_year = year if "{year}" in pattern else 0
    if conn.backend == "postgres":
        row = conn.execute(
            """
            INSERT INTO sequences (doc_type, year, last_value)
            VALUES (?, ?, 1)
            ON CONFLICT (doc_type, year) DO UPDATE
            SET last_value = sequences.last_value + 1
            RETURNING last_value
            """,
            (doc_type, sequence_year),
        ).fetchone()
        return pattern.format(year=year, seq=int(row["last_value"]))

    conn.execute(
        "INSERT OR IGNORE INTO sequences (doc_type, year, last_value) VALUES (?, ?, 0)",
        (doc_type, sequence_year),
    )
    conn.execute(
        "UPDATE sequences SET last_value = last_value + 1 WHERE doc_type = ? AND year = ?",
        (doc_type, sequence_year),
    )
    sequence = conn.execute(
        "SELECT last_value FROM sequences WHERE doc_type = ? AND year = ?",
        (doc_type, sequence_year),
    ).fetchone()[0]
    return pattern.format(year=year, seq=sequence)


def calculate_lines(
    lines: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Decimal, Decimal, Decimal]:
    calculated: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in lines:
        description = str(line.get("description", "")).strip()
        quantity = _decimal(line.get("quantity"))
        unit_price = _decimal(line.get("unit_price"))
        discount = _decimal(line.get("discount_rate"))
        vat = _decimal(line.get("vat_rate"))
        if not description or quantity <= 0:
            continue
        if unit_price < 0:
            raise ValueError("Le prix unitaire ne peut pas être négatif.")
        if discount < 0 or discount > 100:
            raise ValueError("La remise doit être comprise entre 0 et 100 %.")
        if vat < 0 or vat > 100:
            raise ValueError("Le taux de TVA doit être compris entre 0 et 100 %.")
        base = quantity * unit_price * (Decimal("1") - discount / Decimal("100"))
        tax = base * vat / Decimal("100")
        line_subtotal = _round(base)
        line_tax = _round(tax)
        line_total = line_subtotal + line_tax
        calculated.append(
            {
                "item_id": line.get("item_id") or None,
                "description": description,
                "quantity": quantity,
                "unit": str(line.get("unit") or "unité"),
                "unit_price": unit_price,
                "discount_rate": discount,
                "vat_rate": vat,
                "line_subtotal": line_subtotal,
                "line_tax": line_tax,
                "line_total": line_total,
            }
        )
        subtotal += line_subtotal
        tax_total += line_tax
    return calculated, subtotal, tax_total, subtotal + tax_total


def create_document(
    *,
    doc_type: str,
    customer_id: int,
    issue_date: date | str,
    due_date: date | str | None,
    status: str,
    currency: str,
    lines: Iterable[dict[str, Any]],
    notes: str = "",
    terms: str = "",
    source_document_id: int | None = None,
) -> tuple[int, str]:
    if doc_type not in DOCUMENT_PATTERNS:
        raise ValueError("Type de document inconnu.")
    if status not in STATUS_OPTIONS[doc_type]:
        raise ValueError("Statut de document invalide.")
    issue_iso = issue_date.isoformat() if isinstance(issue_date, date) else str(issue_date)
    due_iso = due_date.isoformat() if isinstance(due_date, date) else (str(due_date) if due_date else None)
    calculated, subtotal, tax_total, total = calculate_lines(lines)
    if not calculated:
        raise ValueError("Ajoutez au moins une ligne valide au document.")

    with connection() as conn:
        number = _next_number(conn, doc_type, int(issue_iso[:4]))
        document_id = _insert_id(
            conn,
            """
            INSERT INTO documents
                (doc_type, number, customer_id, issue_date, due_date, status, notes,
                 terms, subtotal, tax_total, total, currency, source_document_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_type,
                number,
                customer_id,
                issue_iso,
                due_iso,
                status,
                notes.strip(),
                terms.strip(),
                subtotal,
                tax_total,
                total,
                currency,
                source_document_id,
                _now(),
            ),
        )
        conn.executemany(
            """
            INSERT INTO document_lines
                (document_id, item_id, description, quantity, unit, unit_price,
                 discount_rate, vat_rate, line_subtotal, line_tax, line_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    document_id,
                    line["item_id"],
                    line["description"],
                    line["quantity"],
                    line["unit"],
                    line["unit_price"],
                    line["discount_rate"],
                    line["vat_rate"],
                    line["line_subtotal"],
                    line["line_tax"],
                    line["line_total"],
                )
                for line in calculated
            ],
        )
        return document_id, number


def list_documents(
    search: str = "", doc_type: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    postgres = get_backend_name() == "postgres"
    clauses: list[str] = []
    params: list[Any] = []
    if search.strip():
        operator = "ILIKE" if postgres else "LIKE"
        clauses.append(f"(d.number {operator} ? OR c.name {operator} ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term])
    if doc_type:
        clauses.append("d.doc_type = ?")
        params.append(doc_type)
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _rows(
        f"""
        SELECT d.*, c.name AS customer_name,
               ROUND(d.total - d.paid_amount, 2) AS balance
        FROM documents d
        JOIN customers c ON c.id = d.customer_id
        {where}
        ORDER BY d.issue_date DESC, d.id DESC
        """,
        params,
    )


def get_document(document_id: int) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT d.*, c.name AS customer_name, c.contact_name, c.email AS customer_email,
                   c.phone AS customer_phone, c.address AS customer_address,
                   c.tax_id AS customer_tax_id,
                   ROUND(d.total - d.paid_amount, 2) AS balance
            FROM documents d
            JOIN customers c ON c.id = d.customer_id
            WHERE d.id = ?
            """,
            (document_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Document introuvable.")
        document = dict(row)
        document["lines"] = [
            dict(line)
            for line in conn.execute(
                "SELECT * FROM document_lines WHERE document_id = ? ORDER BY id",
                (document_id,),
            ).fetchall()
        ]
        document["payments"] = [
            dict(payment)
            for payment in conn.execute(
                "SELECT * FROM payments WHERE document_id = ? ORDER BY payment_date DESC, id DESC",
                (document_id,),
            ).fetchall()
        ]
        return document


def update_document_status(document_id: int, status: str) -> None:
    with connection() as conn:
        lock = " FOR UPDATE" if conn.backend == "postgres" else ""
        document = conn.execute(
            f"SELECT doc_type FROM documents WHERE id = ?{lock}",
            (document_id,),
        ).fetchone()
        if document is None:
            raise ValueError("Document introuvable.")
        doc_type = document["doc_type"] if conn.backend == "postgres" else document[0]
        if status not in STATUS_OPTIONS[doc_type]:
            raise ValueError("Statut invalide.")
        conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, document_id))


def convert_document(source_id: int, target_type: str) -> tuple[int, str]:
    source = get_document(source_id)
    allowed = {"DEVIS": "FACTURE", "PROFORMA": "FACTURE", "FACTURE": "BL"}
    if allowed.get(source["doc_type"]) != target_type:
        raise ValueError("Cette conversion n'est pas autorisée.")
    if existing := find_conversion(source_id, target_type):
        return int(existing["id"]), str(existing["number"])
    today = date.today()
    due = today + timedelta(days=30) if target_type == "FACTURE" else None
    status = "Brouillon"
    try:
        return create_document(
            doc_type=target_type,
            customer_id=int(source["customer_id"]),
            issue_date=today,
            due_date=due,
            status=status,
            currency=source["currency"],
            lines=source["lines"],
            notes=source["notes"],
            terms=source["terms"],
            source_document_id=source_id,
        )
    except DuplicateValueError:
        existing = find_conversion(source_id, target_type)
        if existing:
            return int(existing["id"]), str(existing["number"])
        raise


def find_conversion(source_id: int, target_type: str) -> dict[str, Any] | None:
    results = _rows(
        "SELECT id, number FROM documents WHERE source_document_id = ? AND doc_type = ? LIMIT 1",
        (source_id, target_type),
    )
    return results[0] if results else None


def record_payment(
    document_id: int,
    payment_date: date | str,
    amount: float,
    method: str,
    reference: str = "",
    notes: str = "",
) -> int:
    amount_decimal = _round(_decimal(amount))
    if amount_decimal <= 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    payment_iso = payment_date.isoformat() if isinstance(payment_date, date) else str(payment_date)
    with connection() as conn:
        lock = " FOR UPDATE" if conn.backend == "postgres" else ""
        row = conn.execute(
            f"SELECT doc_type, total FROM documents WHERE id = ?{lock}",
            (document_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Document introuvable.")
        document = dict(row)
        if document["doc_type"] != "FACTURE":
            raise ValueError("Un paiement doit être rattaché à une facture.")
        paid_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS paid FROM payments WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        paid_before = _decimal(dict(paid_row)["paid"])
        remaining = _round(_decimal(document["total"]) - paid_before)
        if amount_decimal > remaining:
            raise ValueError("Le paiement dépasse le solde de la facture.")

        payment_id = _insert_id(
            conn,
            """
            INSERT INTO payments
                (document_id, payment_date, amount, method, reference, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, payment_iso, amount_decimal, method, reference.strip(), notes.strip(), _now()),
        )
        paid = paid_before + amount_decimal
        status = "Payée" if paid == _round(_decimal(document["total"])) else "Partiellement payée"
        conn.execute(
            "UPDATE documents SET paid_amount = ?, status = ? WHERE id = ?",
            (_round(paid), status, document_id),
        )
        return payment_id


def list_payments() -> list[dict[str, Any]]:
    return _rows(
        """
        SELECT p.*, d.number AS document_number, d.currency, c.name AS customer_name
        FROM payments p
        JOIN documents d ON d.id = p.document_id
        JOIN customers c ON c.id = d.customer_id
        ORDER BY p.payment_date DESC, p.id DESC
        """
    )


def dashboard_data(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    clauses = ["d.doc_type = 'FACTURE'", "d.status != 'Annulée'"]
    params: list[Any] = []
    if start_date:
        clauses.append("d.issue_date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        clauses.append("d.issue_date <= ?")
        params.append(end_date.isoformat())
    where = " AND ".join(clauses)
    with connection() as conn:
        invoice = conn.execute(
            f"""
            SELECT COALESCE(SUM(d.total), 0) AS invoiced,
                   COALESCE(SUM(d.paid_amount), 0) AS collected,
                   COALESCE(SUM(d.total - d.paid_amount), 0) AS outstanding,
                   COUNT(*) AS invoice_count
            FROM documents d WHERE {where}
            """,
            tuple(params),
        ).fetchone()
        quote_clauses = ["doc_type = 'DEVIS'", "status IN ('Brouillon', 'Envoyé')"]
        quote_params: list[Any] = []
        if start_date:
            quote_clauses.append("issue_date >= ?")
            quote_params.append(start_date.isoformat())
        if end_date:
            quote_clauses.append("issue_date <= ?")
            quote_params.append(end_date.isoformat())
        quote = conn.execute(
            f"SELECT COALESCE(SUM(total), 0) AS pipeline, COUNT(*) AS quote_count FROM documents WHERE {' AND '.join(quote_clauses)}",
            tuple(quote_params),
        ).fetchone()
        month_expression = (
            "to_char(d.issue_date, 'YYYY-MM')"
            if conn.backend == "postgres"
            else "substr(d.issue_date, 1, 7)"
        )
        monthly = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT {month_expression} AS month,
                       ROUND(SUM(d.total), 2) AS invoiced,
                       ROUND(SUM(d.paid_amount), 2) AS collected
                FROM documents d
                WHERE {where}
                GROUP BY {month_expression}
                ORDER BY month
                """,
                tuple(params),
            ).fetchall()
        ]
    return {**dict(invoice), **dict(quote), "monthly": monthly}


def database_backup_bytes() -> bytes:
    if get_backend_name() == "postgres":
        raise ValueError(
            "Les sauvegardes PostgreSQL sont réalisées hors de l'application avec pg_dump."
        )
    if not DB_PATH.exists():
        init_db()
    backup_path = DATA_DIR / "gestion.backup.db"
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    data = backup_path.read_bytes()
    backup_path.unlink(missing_ok=True)
    return data


def seed_demo_data() -> None:
    if list_customers(active_only=False):
        raise ValueError("Des clients existent déjà. Les données de démonstration n'ont pas été ajoutées.")
    client_id = add_customer(
        {
            "name": "Entreprise Démo",
            "kind": "Entreprise",
            "contact_name": "Marie Martin",
            "email": "contact@exemple.test",
            "phone": "+33 1 00 00 00 00",
            "address": "10 avenue des Entreprises, 75000 Paris",
        }
    )
    service_id = add_item(
        {
            "name": "Prestation de conseil",
            "kind": "Service",
            "unit": "heure",
            "unit_price": 85,
            "vat_rate": 20,
        }
    )
    product_id = add_item(
        {
            "name": "Équipement standard",
            "kind": "Bien",
            "unit": "unité",
            "unit_price": 250,
            "vat_rate": 20,
            "track_stock": True,
            "stock_quantity": 12,
        }
    )
    today = date.today()
    create_document(
        doc_type="DEVIS",
        customer_id=client_id,
        issue_date=today,
        due_date=today + timedelta(days=15),
        status="Envoyé",
        currency=get_settings()["currency"],
        lines=[
            {"item_id": service_id, "description": "Prestation de conseil", "quantity": 5, "unit": "heure", "unit_price": 85, "discount_rate": 0, "vat_rate": 20},
            {"item_id": product_id, "description": "Équipement standard", "quantity": 2, "unit": "unité", "unit_price": 250, "discount_rate": 5, "vat_rate": 20},
        ],
        notes="Exemple modifiable depuis l'application.",
    )


def apply_reference_data() -> dict[str, int]:
    """Apply verified company details and reusable master data from prior documents."""
    update_settings(
        {
            "name": "CHILL POINT SERVICES",
            "slogan": "Services et vente de biens",
            "address": "IMM 43 APPT 26 RUE AGUELMANE SIDI AALI AGDAL, Rabat 20200, Maroc",
            "phone": "0662246682",
            "tax_id": "003503240000033",
            "registration": "177073",
            "fiscal_id": "65945289",
            "rc": "177073",
            "patente": "25715416",
            "cnss": "5669163",
            "rib": "007 825 0008567000000419 78",
            "swift": "BCMAMAMC",
            "bank_details": "RIB : 007 825 0008567000000419 78\nCode SWIFT : BCMAMAMC",
            "currency": "MAD",
            "default_vat": 20,
            "logo_path": "assets/logo-moderne-final.png",
            "show_prices_on_delivery_note": 1,
            "document_footer": "Merci pour votre confiance.",
        }
    )
    with connection() as conn:
        floor_function = "GREATEST" if conn.backend == "postgres" else "MAX"
        for doc_type, sequence_year, floor in [
            ("DEVIS", 0, 6),
            ("FACTURE", 2026, 5),
            ("BL", 2026, 3),
        ]:
            conn.execute(
                f"""
                INSERT INTO sequences (doc_type, year, last_value) VALUES (?, ?, ?)
                ON CONFLICT(doc_type, year) DO UPDATE SET
                    last_value = {floor_function}(sequences.last_value, excluded.last_value)
                """,
                (doc_type, sequence_year, floor),
            )

    existing_customers = {row["name"].strip().upper() for row in list_customers(active_only=False)}
    added_customers = 0
    for customer in [
        {"name": "CAPLM", "kind": "Entreprise"},
        {"name": "LALLA SOUMIA", "kind": "Particulier", "address": "Rabat"},
        {"name": "FROMADEL", "kind": "Entreprise"},
    ]:
        if customer["name"].upper() not in existing_customers:
            add_customer(customer)
            added_customers += 1

    existing_items = {row["name"].strip().upper() for row in list_items(active_only=False)}
    added_items = 0
    reference_items = [
        {
            "name": "Climatiseur CIAT 9000 BTU",
            "kind": "Bien",
            "description": "Fourniture d'un climatiseur système type mural marque CIAT 9000 BTU",
            "unit": "unité",
            "unit_price": 3416.67,
            "vat_rate": 20,
        },
        {
            "name": "Climatiseur 12000 BTU",
            "kind": "Bien",
            "unit": "unité",
            "unit_price": 3833.33,
            "vat_rate": 20,
        },
        {
            "name": "Travaux de peinture",
            "kind": "Service",
            "description": "Salle de bain + 2 chambres + cheminée",
            "unit": "forfait",
            "unit_price": 14200,
            "vat_rate": 20,
        },
        {
            "name": "Maintenance d'équipements frigorifiques",
            "kind": "Service",
            "description": "Déplacement, liaison frigorifique, charge de gaz, câblage, support, réparations et contrôle de bon fonctionnement.",
            "unit": "forfait",
            "unit_price": 3000,
            "vat_rate": 20,
        },
    ]
    for item in reference_items:
        if item["name"].upper() not in existing_items:
            add_item(item)
            added_items += 1
    return {"customers": added_customers, "items": added_items}
