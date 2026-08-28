import tempfile
import unittest
from datetime import date
from pathlib import Path

from core import database
from core.formatting import amount_in_words
from core.pdf_export import build_document_pdf


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.temp_dir.name)
        database.DB_PATH = database.DATA_DIR / "test.db"
        database.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

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


if __name__ == "__main__":
    unittest.main()
