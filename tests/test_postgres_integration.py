"""Opt-in tests for the dedicated chill-point-dev PostgreSQL database.

Run only after configuring .streamlit/secrets.toml:
    $env:RUN_POSTGRES_TESTS = "1"
    python -m unittest tests.test_postgres_integration -v

All inserted records are explicitly marked as fictitious test data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from core import database


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "PostgreSQL tests not enabled")
class PostgresIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if database.get_backend_name() != "postgres":
            raise RuntimeError("RUN_POSTGRES_TESTS exige [database].backend = 'postgres'.")
        database.init_db()

    def fake_customer(self) -> tuple[int, str]:
        token = uuid.uuid4().hex[:12].upper()
        code = f"TEST-{token}"
        customer_id = database.add_customer(
            {
                "code": code,
                "name": f"Client fictif intégration {token}",
                "email": f"test-{token.lower()}@example.test",
            }
        )
        return customer_id, code

    def test_auth_session_revocation(self):
        fingerprint = uuid.uuid4().hex + uuid.uuid4().hex
        now = datetime.now(timezone.utc).replace(microsecond=0)
        database.create_auth_session(fingerprint, now + timedelta(minutes=10))
        self.assertTrue(database.is_auth_session_active(fingerprint, now))
        database.revoke_auth_session(fingerprint)
        self.assertFalse(database.is_auth_session_active(fingerprint, now))

    def test_workflow_and_new_process_persistence(self):
        customer_id, code = self.fake_customer()
        document_id, _ = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2098, 1, 10),
            due_date=date(2098, 2, 10),
            status="Envoyée",
            currency="MAD",
            lines=[
                {
                    "description": "Prestation fictive",
                    "quantity": Decimal("1.25"),
                    "unit_price": Decimal("99.99"),
                    "discount_rate": Decimal("5"),
                    "vat_rate": Decimal("20"),
                }
            ],
        )
        database.record_payment(document_id, date(2098, 1, 11), Decimal("20.00"), "Test")
        document = database.get_document(document_id)
        self.assertEqual(document["paid_amount"], Decimal("20.00"))

        code_literal = repr(code)
        program = (
            "from core.database import list_customers; "
            f"rows=list_customers({code_literal}); "
            "raise SystemExit(0 if len(rows)==1 else 2)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_concurrent_numbering_is_unique(self):
        customer_id, _ = self.fake_customer()
        barrier = threading.Barrier(8)

        def create_one(index: int) -> str:
            barrier.wait()
            return database.create_document(
                doc_type="FACTURE",
                customer_id=customer_id,
                issue_date=date(2099, 1, index + 1),
                due_date=None,
                status="Brouillon",
                currency="MAD",
                lines=[{"description": "Test fictif", "quantity": 1, "unit_price": 10}],
            )[1]

        with ThreadPoolExecutor(max_workers=8) as executor:
            numbers = list(executor.map(create_one, range(8)))
        self.assertEqual(len(numbers), len(set(numbers)))
        sequences = sorted(int(number.rsplit("/", 1)[1]) for number in numbers)
        self.assertEqual(sequences, list(range(sequences[0], sequences[0] + 8)))

    def test_concurrent_conversion_creates_one_target(self):
        customer_id, _ = self.fake_customer()
        source_id, _ = database.create_document(
            doc_type="DEVIS",
            customer_id=customer_id,
            issue_date=date(2097, 1, 1),
            due_date=None,
            status="Accepté",
            currency="MAD",
            lines=[{"description": "Test fictif", "quantity": 1, "unit_price": 100}],
        )
        barrier = threading.Barrier(6)

        def convert(_: int) -> tuple[int, str]:
            barrier.wait()
            return database.convert_document(source_id, "FACTURE")

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(convert, range(6)))
        self.assertEqual(len({result[0] for result in results}), 1)
        self.assertEqual(len({result[1] for result in results}), 1)

    def test_concurrent_payments_cannot_overpay(self):
        customer_id, _ = self.fake_customer()
        document_id, _ = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2096, 1, 1),
            due_date=None,
            status="Envoyée",
            currency="MAD",
            lines=[
                {
                    "description": "Test fictif",
                    "quantity": 1,
                    "unit_price": 100,
                    "vat_rate": 20,
                }
            ],
        )
        barrier = threading.Barrier(2)

        def pay(_: int) -> str:
            barrier.wait()
            try:
                database.record_payment(document_id, date(2096, 1, 2), Decimal("80"), "Test")
                return "accepted"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(pay, range(2)))
        self.assertEqual(sorted(outcomes), ["accepted", "rejected"])
        self.assertEqual(database.get_document(document_id)["paid_amount"], Decimal("80.00"))


if __name__ == "__main__":
    unittest.main()
