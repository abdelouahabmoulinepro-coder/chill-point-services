from datetime import date

import pandas as pd
import streamlit as st

from core.database import get_document, list_documents, list_payments, record_payment
from core.formatting import french_date, money


st.caption("Enregistrez les règlements et suivez automatiquement le solde de chaque facture.")
invoices = [doc for doc in list_documents(doc_type="FACTURE") if doc["balance"] > 0.01 and doc["status"] != "Annulée"]

left, right = st.columns([1, 1.6], gap="large")
with left:
    st.subheader("Nouveau paiement")
    if not invoices:
        st.info("Toutes les factures sont réglées, ou aucune facture n'a encore été créée.", icon=":material/check_circle:")
    else:
        invoice_map = {doc["id"]: f"{doc['number']} · {doc['customer_name']} · solde {money(doc['balance'], doc['currency'])}" for doc in invoices}
        invoice_id = st.selectbox("Facture", invoice_map, format_func=lambda value: invoice_map[value])
        selected = next(doc for doc in invoices if doc["id"] == invoice_id)
        payment_date = st.date_input("Date du paiement", value=date.today())
        amount = st.number_input(f"Montant ({selected['currency']})", min_value=0.01, max_value=float(selected["balance"]), value=float(selected["balance"]), step=1.0, format="%.2f")
        method = st.selectbox("Mode de paiement", ["Virement bancaire", "Carte", "Chèque", "Espèces", "Mobile money", "Autre"])
        reference = st.text_input("Référence", placeholder="N° de transaction ou de chèque")
        notes = st.text_area("Notes", height=80)
        if st.button("Enregistrer le paiement", type="primary", icon=":material/payments:"):
            try:
                record_payment(int(invoice_id), payment_date, amount, method, reference, notes)
                st.toast("Paiement enregistré", icon=":material/check_circle:")
                st.rerun()
            except ValueError as error:
                st.error(str(error))

with right:
    st.subheader("Historique des paiements")
    payments = list_payments()
    if not payments:
        st.info("Aucun paiement enregistré.", icon=":material/receipt_long:")
    else:
        frame = pd.DataFrame(payments)[["payment_date", "document_number", "customer_name", "method", "reference", "amount", "currency"]]
        frame["payment_date"] = frame["payment_date"].map(french_date)
        frame["Montant"] = frame.apply(lambda row: money(row["amount"], row["currency"]), axis=1)
        frame = frame[["payment_date", "document_number", "customer_name", "method", "reference", "Montant"]]
        frame.columns = ["Date", "Facture", "Client", "Mode", "Référence", "Montant"]
        st.dataframe(frame, hide_index=True)

