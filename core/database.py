from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from core.formatting import DOCUMENT_PATTERNS, STATUS_OPTIONS


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "gestion.db"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _round(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


@contextmanager
def connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
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
    recent_limit = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    with connection() as conn:
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
        cursor = conn.execute(
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
        return int(cursor.lastrowid)


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
        cursor = conn.execute(
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
        customer_id = int(cursor.lastrowid)
        if not values.get("code"):
            conn.execute(
                "UPDATE customers SET code = ? WHERE id = ?",
                (f"CLI-{customer_id:04d}", customer_id),
            )
        return customer_id


def list_customers(search: str = "", active_only: bool = True) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if active_only:
        clauses.append("active = 1")
    if search.strip():
        clauses.append("(name LIKE ? OR code LIKE ? OR email LIKE ? OR phone LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _rows(
        f"SELECT * FROM customers {where} ORDER BY name COLLATE NOCASE", params
    )


def add_item(values: dict[str, Any]) -> int:
    with connection() as conn:
        cursor = conn.execute(
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
                float(values.get("unit_price", 0)),
                float(values.get("vat_rate", 0)),
                float(values.get("stock_quantity", 0)),
                int(bool(values.get("track_stock", False))),
                _now(),
            ),
        )
        item_id = int(cursor.lastrowid)
        if not values.get("sku"):
            prefix = "SRV" if values.get("kind") == "Service" else "ART"
            conn.execute(
                "UPDATE items SET sku = ? WHERE id = ?", (f"{prefix}-{item_id:04d}", item_id)
            )
        return item_id


def list_items(search: str = "", active_only: bool = True) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if active_only:
        clauses.append("active = 1")
    if search.strip():
        clauses.append("(name LIKE ? OR sku LIKE ? OR description LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _rows(f"SELECT * FROM items {where} ORDER BY name COLLATE NOCASE", params)


def _next_number(conn: sqlite3.Connection, doc_type: str, year: int) -> str:
    pattern = DOCUMENT_PATTERNS[doc_type]
    sequence_year = year if "{year}" in pattern else 0
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


def calculate_lines(lines: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float, float]:
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
        base = quantity * unit_price * (Decimal("1") - discount / Decimal("100"))
        tax = base * vat / Decimal("100")
        total = base + tax
        calculated.append(
            {
                "item_id": line.get("item_id") or None,
                "description": description,
                "quantity": float(quantity),
                "unit": str(line.get("unit") or "unité"),
                "unit_price": float(unit_price),
                "discount_rate": float(discount),
                "vat_rate": float(vat),
                "line_subtotal": _round(base),
                "line_tax": _round(tax),
                "line_total": _round(total),
            }
        )
        subtotal += base
        tax_total += tax
    return calculated, _round(subtotal), _round(tax_total), _round(subtotal + tax_total)


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
        cursor = conn.execute(
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
        document_id = int(cursor.lastrowid)
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
    clauses: list[str] = []
    params: list[Any] = []
    if search.strip():
        clauses.append("(d.number LIKE ? OR c.name LIKE ?)")
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
    document = get_document(document_id)
    if status not in STATUS_OPTIONS[document["doc_type"]]:
        raise ValueError("Statut invalide.")
    with connection() as conn:
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
    document = get_document(document_id)
    if document["doc_type"] != "FACTURE":
        raise ValueError("Un paiement doit être rattaché à une facture.")
    remaining = _decimal(document["total"]) - _decimal(document["paid_amount"])
    amount_decimal = _decimal(amount)
    if amount_decimal <= 0:
        raise ValueError("Le montant doit être supérieur à zéro.")
    if amount_decimal > remaining + Decimal("0.01"):
        raise ValueError("Le paiement dépasse le solde de la facture.")
    payment_iso = payment_date.isoformat() if isinstance(payment_date, date) else str(payment_date)
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO payments
                (document_id, payment_date, amount, method, reference, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, payment_iso, float(amount_decimal), method, reference.strip(), notes.strip(), _now()),
        )
        paid = _decimal(document["paid_amount"]) + amount_decimal
        status = "Payée" if paid >= _decimal(document["total"]) - Decimal("0.01") else "Partiellement payée"
        conn.execute(
            "UPDATE documents SET paid_amount = ?, status = ? WHERE id = ?",
            (_round(paid), status, document_id),
        )
        return int(cursor.lastrowid)


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
        monthly = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT substr(d.issue_date, 1, 7) AS month,
                       ROUND(SUM(d.total), 2) AS invoiced,
                       ROUND(SUM(d.paid_amount), 2) AS collected
                FROM documents d
                WHERE {where}
                GROUP BY substr(d.issue_date, 1, 7)
                ORDER BY month
                """,
                tuple(params),
            ).fetchall()
        ]
    return {**dict(invoice), **dict(quote), "monthly": monthly}


def database_backup_bytes() -> bytes:
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
        for doc_type, sequence_year, floor in [
            ("DEVIS", 0, 6),
            ("FACTURE", 2026, 5),
            ("BL", 2026, 3),
        ]:
            conn.execute(
                """
                INSERT INTO sequences (doc_type, year, last_value) VALUES (?, ?, ?)
                ON CONFLICT(doc_type, year) DO UPDATE SET
                    last_value = MAX(last_value, excluded.last_value)
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
