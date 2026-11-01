from datetime import datetime

import pandas as pd
import streamlit as st

from core.database import (
    CLIENT_REQUEST_STATUSES,
    get_client_request,
    list_client_requests,
    update_client_request_status,
)


st.caption("Consultez, qualifiez et suivez les demandes envoyées depuis le site public.")

all_requests = list_client_requests()
new_count = sum(request["status"] == "Nouvelle" for request in all_requests)
active_count = sum(request["status"] in {"Contactée", "En cours"} for request in all_requests)

with st.container(horizontal=True):
    st.metric("Nouvelles demandes", new_count, border=True)
    st.metric("À suivre", active_count, border=True)
    st.metric("Total reçu", len(all_requests), border=True)

status_filter = st.selectbox(
    "Filtrer par statut",
    ["Tous", *CLIENT_REQUEST_STATUSES],
    key="request_status_filter",
)
requests = all_requests if status_filter == "Tous" else list_client_requests(status_filter)

with st.container(border=True):
    st.subheader("Boîte de réception")
    if not requests:
        st.info("Aucune demande ne correspond à ce filtre.", icon=":material/inbox:")
    else:
        frame = pd.DataFrame(requests)[
            ["id", "created_at", "full_name", "company_name", "request_type", "status"]
        ]
        frame["created_at"] = frame["created_at"].map(
            lambda value: datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
        )
        frame.columns = ["N°", "Reçue le", "Contact", "Entreprise", "Besoin", "Statut"]
        st.dataframe(frame, hide_index=True)

if requests:
    request_ids = [request["id"] for request in requests]
    labels = {
        request["id"]: f"#{request['id']} · {request['full_name']} · {request['request_type']}"
        for request in requests
    }
    selected_id = st.selectbox(
        "Ouvrir une demande",
        request_ids,
        format_func=lambda request_id: labels[request_id],
    )
    selected = get_client_request(selected_id)

    if selected:
        with st.container(border=True):
            st.subheader(selected["subject"] or selected["request_type"])
            contact_left, contact_right = st.columns(2, gap="large")
            with contact_left:
                st.markdown(f"**Contact :** {selected['full_name']}")
                st.markdown(f"**Entreprise :** {selected['company_name'] or '—'}")
                st.markdown(f"**E-mail :** {selected['email'] or '—'}")
            with contact_right:
                st.markdown(f"**Téléphone :** {selected['phone'] or '—'}")
                st.markdown(f"**Contact préféré :** {selected['preferred_contact'] or '—'}")
                created_at = selected["created_at"]
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                received_at = created_at.strftime("%d/%m/%Y à %H:%M")
                st.markdown(f"**Reçue le :** {received_at}")
            st.markdown("**Message du client**")
            st.write(selected["message"])

            current_index = CLIENT_REQUEST_STATUSES.index(selected["status"])
            new_status = st.selectbox(
                "Statut de suivi",
                CLIENT_REQUEST_STATUSES,
                index=current_index,
                key=f"request_status_{selected_id}",
            )
            if st.button(
                "Mettre à jour le statut",
                type="primary",
                icon=":material/save:",
            ):
                update_client_request_status(selected_id, new_status)
                st.success("Statut mis à jour.", icon=":material/check_circle:")
                st.rerun()
