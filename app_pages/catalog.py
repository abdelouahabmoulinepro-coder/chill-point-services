import pandas as pd
import streamlit as st

from core.database import DuplicateValueError, add_item, get_settings, list_items


settings = get_settings()
currency = settings["currency"]
st.caption("Enregistrez vos services et vos biens pour accélérer la création des documents.")

left, right = st.columns([1, 1.7], gap="large")
with left:
    with st.form("new_item"):
        st.subheader("Nouvel article")
        name = st.text_input("Désignation", placeholder="Ex. Installation sur site")
        kind = st.segmented_control("Nature", ["Service", "Bien"], default="Service", required=True)
        sku = st.text_input("Référence", placeholder="Automatique si vide")
        description = st.text_area("Description", height=80)
        unit = st.selectbox("Unité", ["unité", "heure", "jour", "forfait", "kg", "m", "m²", "lot"], accept_new_options=True)
        unit_price = st.number_input(f"Prix unitaire HT ({currency})", min_value=0.0, step=1.0, format="%.2f")
        vat_rate = st.number_input("TVA (%)", min_value=0.0, max_value=100.0, value=float(settings["default_vat"]), step=1.0)
        track_stock = st.checkbox("Suivre le stock", disabled=kind == "Service")
        stock_quantity = st.number_input("Stock initial", min_value=0.0, step=1.0, disabled=not track_stock)
        submitted = st.form_submit_button("Enregistrer l'article", type="primary", icon=":material/save:")
    if submitted:
        if not name.strip():
            st.error("La désignation est obligatoire.")
        else:
            try:
                add_item({"name": name, "kind": kind, "sku": sku.strip(), "description": description, "unit": unit, "unit_price": unit_price, "vat_rate": vat_rate, "track_stock": track_stock and kind == "Bien", "stock_quantity": stock_quantity})
                st.toast("Article enregistré", icon=":material/check_circle:")
                st.rerun()
            except DuplicateValueError:
                st.error("Cette référence est déjà utilisée.")

with right:
    st.subheader("Catalogue")
    search = st.text_input("Rechercher dans le catalogue", placeholder="Désignation, référence ou description", icon=":material/search:")
    items = list_items(search)
    if not items:
        st.info("Aucun article trouvé.", icon=":material/inventory_2:")
    else:
        frame = pd.DataFrame(items)[["sku", "name", "kind", "unit", "unit_price", "vat_rate", "stock_quantity", "track_stock"]]
        frame[["unit_price", "vat_rate", "stock_quantity"]] = frame[
            ["unit_price", "vat_rate", "stock_quantity"]
        ].astype(float)
        frame.columns = ["Référence", "Désignation", "Nature", "Unité", "Prix HT", "TVA", "Stock", "Suivi du stock"]
        st.dataframe(
            frame,
            hide_index=True,
            column_config={
                "Prix HT": st.column_config.NumberColumn(format=f"%.2f {currency}"),
                "TVA": st.column_config.NumberColumn(format="%.1f %%"),
                "Suivi du stock": st.column_config.CheckboxColumn(),
            },
        )

