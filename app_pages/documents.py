from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.database import (
    calculate_lines,
    convert_document,
    create_document,
    find_conversion,
    get_document,
    get_settings,
    list_customers,
    list_documents,
    list_items,
    update_document_status,
)
from core.formatting import DOCUMENT_LABELS, STATUS_OPTIONS, document_label, french_date, money
from core.pdf_export import build_document_pdf


def blank_lines(default_vat: float = 20.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "item_id": pd.Series([None], dtype="object"),
            "description": pd.Series([""], dtype="string"),
            "quantity": pd.Series([1.0], dtype="float"),
            "unit": pd.Series(["unité"], dtype="string"),
            "unit_price": pd.Series([0.0], dtype="float"),
            "discount_rate": pd.Series([0.0], dtype="float"),
            "vat_rate": pd.Series([float(default_vat)], dtype="float"),
        }
    )


settings = get_settings()
st.caption("Créez, consultez, exportez et convertissez vos documents commerciaux.")
mode = st.segmented_control("Action", ["Créer un document", "Consulter les documents"], default="Créer un document", required=True)

if mode == "Créer un document":
    customers = list_customers()
    if not customers:
        st.warning("Ajoutez au moins un client avant de créer un document.", icon=":material/person_add:")
        st.stop()

    st.session_state.setdefault("draft_lines", blank_lines(float(settings["default_vat"])))
    header_left, header_right = st.columns(2, gap="large")
    with header_left:
        doc_type = st.segmented_control("Type de document", list(DOCUMENT_LABELS), default="DEVIS", format_func=lambda value: DOCUMENT_LABELS[value], required=True)
        customer_map = {customer["id"]: f"{customer['name']} · {customer['code']}" for customer in customers}
        customer_id = st.selectbox("Client", customer_map, format_func=lambda value: customer_map[value])
        status = st.selectbox("Statut initial", STATUS_OPTIONS[doc_type])
    with header_right:
        issue_date = st.date_input("Date d'émission", value=date.today())
        default_due = date.today() + timedelta(days=30 if doc_type == "FACTURE" else 15)
        due_date = st.date_input("Échéance ou validité", value=default_due, disabled=doc_type == "BL")
        currency = st.selectbox("Devise", ["EUR", "XOF", "XAF", "USD", "GBP", "MAD", "DZD", "TND", "CDF"], index=["EUR", "XOF", "XAF", "USD", "GBP", "MAD", "DZD", "TND", "CDF"].index(settings["currency"]) if settings["currency"] in ["EUR", "XOF", "XAF", "USD", "GBP", "MAD", "DZD", "TND", "CDF"] else 0)

    st.subheader("Lignes du document")
    edited_lines = st.data_editor(
        st.session_state.draft_lines,
        key="document_lines_editor",
        num_rows="dynamic",
        hide_index=True,
        column_order=["description", "quantity", "unit", "unit_price", "discount_rate", "vat_rate"],
        column_config={
            "item_id": None,
            "description": st.column_config.TextColumn("Description", required=True, width="large"),
            "quantity": st.column_config.NumberColumn("Quantité", min_value=0.01, step=1.0, format="%.2f"),
            "unit": st.column_config.SelectboxColumn("Unité", options=["unité", "heure", "jour", "forfait", "kg", "m", "m²", "lot"]),
            "unit_price": st.column_config.NumberColumn(f"Prix HT ({currency})", min_value=0.0, step=1.0, format="%.2f"),
            "discount_rate": st.column_config.NumberColumn("Remise %", min_value=0.0, max_value=100.0, format="%.1f"),
            "vat_rate": st.column_config.NumberColumn("TVA %", min_value=0.0, max_value=100.0, format="%.1f"),
        },
    )

    items = list_items()
    if items:
        item_map = {item["id"]: f"{item['sku']} · {item['name']}" for item in items}
        with st.container(horizontal=True, vertical_alignment="bottom"):
            selected_item = st.selectbox("Ajouter depuis le catalogue", item_map, format_func=lambda value: item_map[value], key="catalog_item")
            if st.button("Ajouter", icon=":material/add:"):
                item = next(entry for entry in items if entry["id"] == selected_item)
                description = item["name"]
                if item.get("description"):
                    description += "\n" + item["description"]
                new_row = pd.DataFrame([{"item_id": item["id"], "description": description, "quantity": 1.0, "unit": item["unit"], "unit_price": item["unit_price"], "discount_rate": 0.0, "vat_rate": item["vat_rate"]}])
                current = edited_lines[edited_lines["description"].astype(str).str.strip() != ""]
                st.session_state.draft_lines = pd.concat([current, new_row], ignore_index=True)
                st.session_state.pop("document_lines_editor", None)
                st.rerun()

    _, subtotal, tax_total, total = calculate_lines(edited_lines.to_dict("records"))
    with st.container(horizontal=True, horizontal_alignment="right"):
        st.metric("Sous-total HT", money(subtotal, currency), border=True)
        st.metric("TVA", money(tax_total, currency), border=True)
        st.metric("Total TTC", money(total, currency), border=True)

    notes = st.text_area("Notes", placeholder="Informations utiles pour le client")
    terms = st.text_area("Conditions", placeholder="Délai de paiement, validité de l'offre, conditions de livraison…")
    if st.button("Créer le document", type="primary", icon=":material/save:"):
        try:
            _, number = create_document(
                doc_type=doc_type,
                customer_id=int(customer_id),
                issue_date=issue_date,
                due_date=None if doc_type == "BL" else due_date,
                status=status,
                currency=currency,
                lines=edited_lines.to_dict("records"),
                notes=notes,
                terms=terms,
            )
            st.session_state.draft_lines = blank_lines(float(settings["default_vat"]))
            st.session_state.pop("document_lines_editor", None)
            st.success(f"Le document {number} a été créé.", icon=":material/check_circle:")
        except ValueError as error:
            st.error(str(error))

else:
    with st.container(horizontal=True, vertical_alignment="bottom"):
        search = st.text_input("Rechercher", placeholder="Numéro ou client", icon=":material/search:")
        type_filter = st.selectbox("Type", [None, *DOCUMENT_LABELS], format_func=lambda value: "Tous les types" if value is None else DOCUMENT_LABELS[value])
        statuses = sorted({status for options in STATUS_OPTIONS.values() for status in options})
        status_filter = st.selectbox("Statut", [None, *statuses], format_func=lambda value: value or "Tous les statuts")
    documents = list_documents(search, type_filter, status_filter)
    if not documents:
        st.info("Aucun document ne correspond à ces critères.", icon=":material/search_off:")
        st.stop()

    frame = pd.DataFrame(documents)[["number", "doc_type", "customer_name", "issue_date", "status", "total", "paid_amount", "balance"]]
    frame["doc_type"] = frame["doc_type"].map(DOCUMENT_LABELS)
    frame["issue_date"] = frame["issue_date"].map(french_date)
    frame.columns = ["Numéro", "Type", "Client", "Date", "Statut", "Total", "Payé", "Solde"]
    st.dataframe(
        frame,
        hide_index=True,
        column_config={
            "Total": st.column_config.NumberColumn(format="%.2f"),
            "Payé": st.column_config.NumberColumn(format="%.2f"),
            "Solde": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    selected_id = st.selectbox("Afficher le document", [doc["id"] for doc in documents], format_func=lambda value: next(doc["number"] + " · " + doc["customer_name"] for doc in documents if doc["id"] == value))
    document = get_document(int(selected_id))
    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.subheader(f"{document_label(document['doc_type'])} {document['number']}")
            st.badge(document["status"], icon=":material/info:", color="blue")
        st.caption(f"Client : {document['customer_name']} · Émis le {french_date(document['issue_date'])} · Devise : {document['currency']}")
        line_frame = pd.DataFrame(document["lines"])[["description", "quantity", "unit", "unit_price", "discount_rate", "vat_rate", "line_total"]]
        line_frame.columns = ["Description", "Quantité", "Unité", "Prix HT", "Remise %", "TVA %", "Total TTC"]
        st.dataframe(line_frame, hide_index=True)
        if document["doc_type"] != "BL" or settings.get("show_prices_on_delivery_note"):
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.metric("Total TTC", money(document["total"], document["currency"]), border=True)
                if document["doc_type"] == "FACTURE":
                    st.metric("Solde", money(document["balance"], document["currency"]), border=True)

        pdf_bytes = build_document_pdf(document, settings)
        status_index = STATUS_OPTIONS[document["doc_type"]].index(document["status"])
        new_status = st.selectbox("Mettre à jour le statut", STATUS_OPTIONS[document["doc_type"]], index=status_index, key=f"status_{document['id']}")
        with st.container(horizontal=True):
            if st.button("Enregistrer le statut", icon=":material/save:"):
                update_document_status(document["id"], new_status)
                st.toast("Statut mis à jour", icon=":material/check_circle:")
                st.rerun()
            st.download_button("Télécharger le PDF", data=pdf_bytes, file_name=f"{document['number']}.pdf", mime="application/pdf", icon=":material/download:")

            target = {"DEVIS": "FACTURE", "PROFORMA": "FACTURE", "FACTURE": "BL"}.get(document["doc_type"])
            if target:
                existing = find_conversion(document["id"], target)
                label = f"Déjà converti : {existing['number']}" if existing else f"Convertir en {document_label(target).lower()}"
                if st.button(label, icon=":material/swap_horiz:", disabled=existing is not None):
                    _, number = convert_document(document["id"], target)
                    st.success(f"Le document {number} a été créé.")
                    st.rerun()
