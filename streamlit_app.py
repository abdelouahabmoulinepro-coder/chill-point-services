import streamlit as st

from core.auth import logout_director, require_director_auth
from core.database import DatabaseError, get_settings, init_db


DEFAULT_LOGO_PATH = "assets/logo-moderne-final.png"

st.set_page_config(
    page_title="Chill Point Services",
    page_icon=DEFAULT_LOGO_PATH,
    layout="wide",
)

st.logo(DEFAULT_LOGO_PATH, size="large")
st.html(
    """
    <style>
    :root {
        --brand-header-height: 9rem;
    }

    [data-testid="stHeader"] {
        height: var(--brand-header-height);
        background: rgba(255, 255, 255, 0.98);
        border-bottom: 1px solid rgba(11, 61, 145, 0.08);
        box-shadow: 0 8px 30px rgba(7, 26, 61, 0.05);
    }

    [data-testid="stToolbar"] {
        width: 100%;
        height: var(--brand-header-height);
        align-items: center;
        justify-content: center;
    }

    [data-testid="stToolbar"] img.stLogo {
        position: fixed;
        top: 0.5rem;
        left: 50%;
        z-index: 1000;
        width: 12rem !important;
        height: 8rem !important;
        max-width: none !important;
        max-height: none !important;
        transform: translateX(-50%);
        object-fit: contain;
        object-position: center;
    }

    [data-testid="stMainBlockContainer"] {
        padding-top: calc(var(--brand-header-height) + 1.2rem);
    }

    @media (max-width: 640px) {
        :root { --brand-header-height: 7.5rem; }

        [data-testid="stToolbar"] img.stLogo {
            width: 10rem !important;
            height: 6.5rem !important;
        }
    }
    </style>
    """
)

try:
    init_db()
except DatabaseError:
    st.error(
        "Le service de données est indisponible ou nécessite une migration. "
        "Aucune base locale de remplacement n'a été utilisée.",
        icon=":material/database_off:",
    )
    st.stop()

home_page = st.Page(
    "app_pages/home.py",
    title="Accueil",
    icon=":material/home:",
    default=True,
)
dashboard_page = st.Page(
    "app_pages/dashboard.py",
    title="Vue d'ensemble",
    icon=":material/dashboard:",
    url_path="admin",
)
requests_page = st.Page(
    "app_pages/requests.py",
    title="Demandes clients",
    icon=":material/contact_mail:",
    url_path="demandes-clients",
)
documents_page = st.Page(
    "app_pages/documents.py",
    title="Documents",
    icon=":material/description:",
    url_path="documents",
)
payments_page = st.Page(
    "app_pages/payments.py",
    title="Paiements",
    icon=":material/payments:",
    url_path="payments",
)
customers_page = st.Page(
    "app_pages/customers.py",
    title="Clients",
    icon=":material/groups:",
    url_path="customers",
)
catalog_page = st.Page(
    "app_pages/catalog.py",
    title="Catalogue",
    icon=":material/inventory_2:",
    url_path="catalog",
)
settings_page = st.Page(
    "app_pages/settings.py",
    title="Paramètres",
    icon=":material/settings:",
    url_path="settings",
)

navigation = st.navigation(
    [
        home_page,
        dashboard_page,
        requests_page,
        documents_page,
        payments_page,
        customers_page,
        catalog_page,
        settings_page,
    ],
    position="hidden",
)

if navigation.url_path == "":
    navigation.run()
else:
    # Toutes les routes autres que l'accueil public restent privées.
    director = require_director_auth(DEFAULT_LOGO_PATH)
    settings = get_settings()
    logo_path = settings.get("logo_path") or DEFAULT_LOGO_PATH
    st.logo(logo_path, size="large")

    with st.sidebar:
        st.markdown(f"### {settings['name']}")
        if settings.get("slogan"):
            st.caption(settings["slogan"])

        st.page_link(home_page, label="Voir le site public", icon=":material/open_in_new:")
        st.caption("PILOTAGE")
        st.page_link(dashboard_page, label="Vue d'ensemble", icon=":material/dashboard:")
        st.page_link(requests_page, label="Demandes clients", icon=":material/contact_mail:")
        st.caption("VENTES")
        st.page_link(documents_page, label="Documents", icon=":material/description:")
        st.page_link(payments_page, label="Paiements", icon=":material/payments:")
        st.caption("DONNÉES")
        st.page_link(customers_page, label="Clients", icon=":material/groups:")
        st.page_link(catalog_page, label="Catalogue", icon=":material/inventory_2:")
        st.caption("ADMINISTRATION")
        st.page_link(settings_page, label="Paramètres", icon=":material/settings:")

        st.caption(f"Connecté : {director['name']}")
        if st.button("Se déconnecter", icon=":material/logout:"):
            try:
                logout_director()
                st.info("Session fermée sur cet appareil.", icon=":material/logout:")
            except DatabaseError:
                st.warning(
                    "La session locale est fermée, mais sa révocation serveur n’a pas pu être confirmée. "
                    "Le jeton expirera automatiquement.",
                    icon=":material/warning:",
                )
            # Let the cookie component finish deletion before the next automatic rerun.
            st.stop()
        st.caption(f"Devise : {settings['currency']} · Version 1.2")

    st.title(f"{navigation.icon} {navigation.title}")
    navigation.run()
