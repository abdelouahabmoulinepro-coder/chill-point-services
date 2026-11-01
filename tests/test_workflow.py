import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from pathlib import Path

from core import database
from core.formatting import amount_in_words
from core.pdf_export import build_document_pdf


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.backend_patch = patch.dict("os.environ", {"DB_BACKEND": "sqlite"})
        self.backend_patch.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir, self.old_db_path = database.DATA_DIR, database.DB_PATH
        database.DATA_DIR = Path(self.temp_dir.name)
        database.DB_PATH = database.DATA_DIR / "test.db"
        database.init_db()

    def tearDown(self):
        database.DATA_DIR, database.DB_PATH = self.old_data_dir, self.old_db_path
        self.temp_dir.cleanup()
        self.backend_patch.stop()

    def test_complete_sales_workflow(self):
        customer_id = database.add_customer({"name": "Client Test"})
        item_id = database.add_item({"name": "Conseil", "kind": "Service", "unit": "heure", "unit_price": 100, "vat_rate": 20})
        document_id, number = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2026, 8, 28),
            due_date=date(2026, 9, 28),
            status="Envoyée",
            currency="EUR",
            lines=[{"item_id": item_id, "description": "Conseil", "quantity": 2, "unit": "heure", "unit_price": 100, "discount_rate": 0, "vat_rate": 20}],
        )
        self.assertEqual(number, "FA-2026/000001")
        document = database.get_document(document_id)
        self.assertEqual(document["total"], 240.0)
        database.record_payment(document_id, date(2026, 8, 28), 100, "Virement bancaire")
        document = database.get_document(document_id)
        self.assertEqual(document["paid_amount"], 100.0)
        self.assertEqual(document["status"], "Partiellement payée")
        pdf = build_document_pdf(document, database.get_settings())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_document_conversion_reuses_existing_conversion(self):
        customer_id = database.add_customer({"name": "Client Test"})
        quote_id, _ = database.create_document(
            doc_type="DEVIS",
            customer_id=customer_id,
            issue_date=date(2026, 8, 28),
            due_date=date(2026, 9, 12),
            status="Accepté",
            currency="EUR",
            lines=[{"description": "Forfait", "quantity": 1, "unit": "forfait", "unit_price": 500, "discount_rate": 0, "vat_rate": 20}],
        )
        first_id, first_number = database.convert_document(quote_id, "FACTURE")
        second_id, second_number = database.convert_document(quote_id, "FACTURE")
        self.assertEqual((first_id, first_number), (second_id, second_number))

    def test_reference_profile_preserves_historical_numbering(self):
        imported = database.apply_reference_data()
        self.assertEqual(imported, {"customers": 3, "items": 4})
        customer_id = database.list_customers()[0]["id"]
        _, number = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2026, 8, 28),
            due_date=date(2026, 9, 28),
            status="Brouillon",
            currency="MAD",
            lines=[{"description": "Test", "quantity": 1, "unit": "unité", "unit_price": 100, "discount_rate": 0, "vat_rate": 20}],
        )
        self.assertEqual(number, "FA-2026/000006")
        self.assertEqual(
            amount_in_words(16900.80, "MAD"),
            "SEIZE MILLE NEUF CENTS DIRHAMS ET QUATRE-VINGTS CENTIMES",
        )

    def test_public_client_request_workflow(self):
        request_id = database.add_client_request(
            {
                "full_name": "Client Public",
                "company_name": "Entreprise Exemple",
                "email": "client@example.com",
                "phone": "",
                "request_type": "Prestation de services",
                "subject": "Besoin d'accompagnement",
                "message": "Nous souhaitons recevoir une proposition détaillée pour notre projet.",
                "preferred_contact": "E-mail",
            }
        )
        request = database.get_client_request(request_id)
        self.assertEqual(request["status"], "Nouvelle")
        self.assertEqual(database.list_client_requests()[0]["full_name"], "Client Public")

        database.update_client_request_status(request_id, "En cours")
        self.assertEqual(database.get_client_request(request_id)["status"], "En cours")

        with self.assertRaises(ValueError):
            database.add_client_request(
                {
                    "full_name": "Client Public",
                    "email": "client@example.com",
                    "request_type": "Autre besoin",
                    "message": "Deuxième demande envoyée beaucoup trop rapidement pour être acceptée.",
                }
            )

    def test_financial_rounding_is_decimal_and_lines_reconcile(self):
        lines, subtotal, tax_total, total = database.calculate_lines(
            [
                {
                    "description": f"Ligne {index}",
                    "quantity": 1,
                    "unit_price": Decimal("0.005"),
                    "discount_rate": 0,
                    "vat_rate": 0,
                }
                for index in range(3)
            ]
        )
        self.assertEqual(subtotal, Decimal("0.03"))
        self.assertEqual(tax_total, Decimal("0.00"))
        self.assertEqual(total, Decimal("0.03"))
        self.assertEqual(sum(line["line_total"] for line in lines), total)

    def test_failed_document_rolls_back_number(self):
        with self.assertRaises(database.DatabaseIntegrityError):
            database.create_document(
                doc_type="FACTURE",
                customer_id=999999,
                issue_date=date(2026, 8, 28),
                due_date=None,
                status="Brouillon",
                currency="MAD",
                lines=[{"description": "Test", "quantity": 1, "unit_price": 100}],
            )
        customer_id = database.add_customer({"name": "Client valide"})
        _, number = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2026, 8, 28),
            due_date=None,
            status="Brouillon",
            currency="MAD",
            lines=[{"description": "Test", "quantity": 1, "unit_price": 100}],
        )
        self.assertEqual(number, "FA-2026/000001")

    def test_concurrent_document_numbers_are_unique(self):
        customer_id = database.add_customer({"name": "Client concurrence"})

        def create_one(_: int) -> str:
            return database.create_document(
                doc_type="FACTURE",
                customer_id=customer_id,
                issue_date=date(2026, 8, 28),
                due_date=None,
                status="Brouillon",
                currency="MAD",
                lines=[{"description": "Test", "quantity": 1, "unit_price": 10}],
            )[1]

        with ThreadPoolExecutor(max_workers=6) as executor:
            numbers = list(executor.map(create_one, range(12)))
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(sorted(numbers), [f"FA-2026/{index:06d}" for index in range(1, 13)])

    def test_payment_cannot_exceed_remaining_balance(self):
        customer_id = database.add_customer({"name": "Client paiement"})
        document_id, _ = database.create_document(
            doc_type="FACTURE",
            customer_id=customer_id,
            issue_date=date(2026, 8, 28),
            due_date=None,
            status="Envoyée",
            currency="MAD",
            lines=[{"description": "Test", "quantity": 1, "unit_price": 100}],
        )
        database.record_payment(document_id, date(2026, 8, 28), Decimal("60.00"), "Virement")
        with self.assertRaises(ValueError):
            database.record_payment(document_id, date(2026, 8, 28), Decimal("60.01"), "Virement")


class BackendSelectionTest(unittest.TestCase):
    def test_postgres_uri_rejects_unescaped_reserved_characters(self):
        malformed = "postgresql://role:password@part@pooler.example.test:5432/postgres"
        with patch.dict(
            "os.environ",
            {"DB_BACKEND": "postgres", "DATABASE_URL": malformed},
            clear=False,
        ):
            with self.assertRaises(database.DatabaseConfigurationError):
                database.init_db()

    def test_postgres_configuration_never_falls_back_to_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            old_data_dir, old_db_path = database.DATA_DIR, database.DB_PATH
            database.DATA_DIR = Path(directory)
            database.DB_PATH = database.DATA_DIR / "must-not-exist.db"
            try:
                with patch.dict(
                    "os.environ",
                    {"DB_BACKEND": "postgres", "DATABASE_URL": ""},
                    clear=False,
                ):
                    with self.assertRaises(database.DatabaseConfigurationError):
                        database.init_db()
                self.assertFalse(database.DB_PATH.exists())
            finally:
                database.DATA_DIR, database.DB_PATH = old_data_dir, old_db_path


if __name__ == "__main__":
    unittest.main()
