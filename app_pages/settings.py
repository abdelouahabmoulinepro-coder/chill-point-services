from datetime import datetime

import streamlit as st

from core.database import database_backup_bytes, get_backend_name, get_settings, seed_demo_data, update_settings


settings = get_settings()
st.caption("Personnalisez les informations qui apparaissent sur vos documents et sauvegardez vos données.")

general, backup = st.tabs(["Informations de la société", "Sauvegarde et démonstration"])

with general:
    with st.form("company_settings"):
        left, right = st.columns(2, gap="large")
        with left:
            name = st.text_input("Nom de la société", value=settings["name"])
            slogan = st.text_input("Activité ou slogan", value=settings["slogan"])
            address = st.text_area("Adresse", value=settings["address"], height=90)
            phone = st.text_input("Téléphone", value=settings["phone"])
            email = st.text_input("E-mail", value=settings["email"])
        with right:
            tax_id = st.text_input("ICE", value=settings["tax_id"])
            fiscal_id = st.text_input("Identifiant fiscal (IF)", value=settings["fiscal_id"])
            rc = st.text_input("Registre de commerce (RC)", value=settings["rc"] or settings["registration"])
            patente = st.text_input("Patente", value=settings["patente"])
            cnss = st.text_input("CNSS", value=settings["cnss"])
            currencies = ["EUR", "XOF", "XAF", "USD", "GBP", "MAD", "DZD", "TND", "CDF"]
            currency = st.selectbox("Devise par défaut", currencies, index=currencies.index(settings["currency"]) if settings["currency"] in currencies else 0)
            default_vat = st.number_input("TVA par défaut (%)", min_value=0.0, max_value=100.0, value=float(settings["default_vat"]), step=1.0)
            rib = st.text_input("RIB", value=settings["rib"])
            swift = st.text_input("Code SWIFT", value=settings["swift"])
            show_prices_on_delivery_note = st.checkbox("Afficher les prix sur les bons de livraison", value=bool(settings["show_prices_on_delivery_note"]))
        document_footer = st.text_input("Pied de page des documents", value=settings["document_footer"])
        submitted = st.form_submit_button("Enregistrer les paramètres", type="primary", icon=":material/save:")
    if submitted:
        if not name.strip():
            st.error("Le nom de la société est obligatoire.")
        else:
            bank_details = "\n".join(part for part in [f"RIB : {rib}" if rib else "", f"Code SWIFT : {swift}" if swift else ""] if part)
            update_settings({"name": name.strip(), "slogan": slogan, "address": address, "phone": phone, "email": email, "registration": rc, "tax_id": tax_id, "fiscal_id": fiscal_id, "rc": rc, "patente": patente, "cnss": cnss, "rib": rib, "swift": swift, "currency": currency, "default_vat": default_vat, "bank_details": bank_details, "show_prices_on_delivery_note": int(show_prices_on_delivery_note), "document_footer": document_footer})
            st.success("Paramètres enregistrés. Rechargez la page pour actualiser le nom dans le menu.", icon=":material/check_circle:")

with backup:
    with st.container(border=True):
        st.subheader("Sauvegarder les données")
        if get_backend_name() == "sqlite":
            st.write("Téléchargez une copie complète de la base. Conservez-la dans un emplacement sûr et sauvegardé.")
            backup_data = database_backup_bytes()
            st.download_button(
                "Télécharger la sauvegarde",
                data=backup_data,
                file_name=f"gestion-commerciale-{datetime.now():%Y%m%d-%H%M}.db",
                mime="application/vnd.sqlite3",
                icon=":material/download:",
            )
        else:
            st.info(
                "Les sauvegardes PostgreSQL sont réalisées de manière externe avec pg_dump "
                "et font l'objet de tests de restauration.",
                icon=":material/cloud_done:",
            )

    with st.container(border=True):
        st.subheader("Données de démonstration")
        st.write("Ajoutez un client, deux articles et un devis d'exemple pour découvrir l'application.")
        if st.button("Charger la démonstration", icon=":material/science:"):
            try:
                seed_demo_data()
                st.success("Les données de démonstration ont été ajoutées.", icon=":material/check_circle:")
            except ValueError as error:
                st.warning(str(error))
