import sqlite3

import pandas as pd
import streamlit as st

from core.database import add_customer, list_customers


st.caption("Centralisez les coordonnées de vos clients professionnels et particuliers.")

left, right = st.columns([1, 1.7], gap="large")

with left:
    with st.form("new_customer"):
        st.subheader("Nouveau client")
        name = st.text_input("Nom ou raison sociale", placeholder="Ex. Société Horizon")
        kind = st.segmented_control("Type", ["Entreprise", "Particulier"], default="Entreprise", required=True)
        contact_name = st.text_input("Personne à contacter")
        email = st.text_input("E-mail")
        phone = st.text_input("Téléphone")
        address = st.text_area("Adresse", height=90)
        tax_id = st.text_input("ICE / identifiant fiscal")
        code = st.text_input("Code client", placeholder="Automatique si vide")
        submitted = st.form_submit_button("Enregistrer le client", type="primary", icon=":material/save:")

    if submitted:
        if not name.strip():
            st.error("Le nom du client est obligatoire.")
        else:
            try:
                add_customer({"name": name, "kind": kind, "contact_name": contact_name, "email": email, "phone": phone, "address": address, "tax_id": tax_id, "code": code.strip()})
                st.toast("Client enregistré", icon=":material/check_circle:")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Ce code client est déjà utilisé.")

with right:
    st.subheader("Répertoire clients")
    search = st.text_input("Rechercher un client", placeholder="Nom, code, e-mail ou téléphone", icon=":material/search:")
    customers = list_customers(search)
    if not customers:
        st.info("Aucun client trouvé.", icon=":material/person_search:")
    else:
        frame = pd.DataFrame(customers)[["code", "name", "kind", "contact_name", "email", "phone", "tax_id"]]
        frame.columns = ["Code", "Client", "Type", "Contact", "E-mail", "Téléphone", "ICE / identifiant fiscal"]
        st.dataframe(frame, hide_index=True)
        st.caption(f"{len(frame)} client(s)")
