from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.database import dashboard_data, get_settings, list_documents
from core.formatting import DOCUMENT_LABELS, french_date, money


settings = get_settings()
currency = settings["currency"]

with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.caption("Pilotez votre activité commerciale en un coup d'œil.")
    period = st.segmented_control(
        "Période",
        ["30 jours", "Cette année", "Tout"],
        default="Cette année",
        required=True,
        key="dashboard_period",
        persist_state="session",
    )

today = date.today()
if period == "30 jours":
    start = today - timedelta(days=30)
elif period == "Cette année":
    start = date(today.year, 1, 1)
else:
    start = None

metrics = dashboard_data(start, today)

with st.container(horizontal=True):
    st.metric("Chiffre d'affaires facturé", money(metrics["invoiced"], currency), border=True)
    st.metric("Montant encaissé", money(metrics["collected"], currency), border=True)
    st.metric("Reste à encaisser", money(metrics["outstanding"], currency), border=True)
    st.metric("Devis en cours", money(metrics["pipeline"], currency), f"{metrics['quote_count']} document(s)", border=True)

left, right = st.columns([1.5, 1], gap="medium")
with left:
    with st.container(border=True, height="stretch"):
        st.subheader("Évolution des ventes")
        monthly = pd.DataFrame(metrics["monthly"])
        if monthly.empty:
            st.info("Les ventes apparaîtront ici dès qu'une facture sera créée.", icon=":material/monitoring:")
        else:
            monthly = monthly.rename(columns={"month": "Mois", "invoiced": "Facturé", "collected": "Encaissé"})
            monthly[["Facturé", "Encaissé"]] = monthly[["Facturé", "Encaissé"]].astype(float)
            st.bar_chart(monthly, x="Mois", y=["Facturé", "Encaissé"], y_label=f"Montant ({currency})")

with right:
    with st.container(border=True, height="stretch"):
        st.subheader("Activité")
        st.metric("Factures", int(metrics["invoice_count"]))
        if metrics["invoiced"]:
            rate = float(metrics["collected"] / metrics["invoiced"] * 100)
            st.metric("Taux d'encaissement", f"{rate:.1f} %")
            st.progress(min(rate / 100, 1), text="Part des factures encaissée")
        else:
            st.caption("Aucune facture sur cette période.")

with st.container(border=True):
    st.subheader("Documents récents")
    recent = list_documents()[:8]
    if not recent:
        st.info("Commencez par ajouter un client, puis créez votre premier devis ou votre première facture.", icon=":material/lightbulb:")
    else:
        frame = pd.DataFrame(recent)[["number", "doc_type", "customer_name", "issue_date", "status", "total", "balance"]]
        frame[["total", "balance"]] = frame[["total", "balance"]].astype(float)
        frame["doc_type"] = frame["doc_type"].map(DOCUMENT_LABELS)
        frame["issue_date"] = frame["issue_date"].map(french_date)
        frame.columns = ["Numéro", "Type", "Client", "Date", "Statut", "Total", "Solde"]
        st.dataframe(
            frame,
            hide_index=True,
            column_config={
                "Total": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "Solde": st.column_config.NumberColumn(format=f"%.2f {currency}"),
            },
        )

