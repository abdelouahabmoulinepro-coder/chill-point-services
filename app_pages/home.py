from html import escape
import re

import streamlit as st

from core.database import (
    CLIENT_REQUEST_CONTACT_OPTIONS,
    CLIENT_REQUEST_TYPES,
    add_client_request,
    get_settings,
)


settings = get_settings()
company_name = escape(settings["name"])
slogan = escape(settings.get("slogan") or "Services et vente de biens")
address = escape(settings.get("address") or "Rabat, Maroc")
phone = escape(settings.get("phone") or "Contact sur demande")

st.html(
    """
    <style>
    [data-testid="stMainBlockContainer"] {
        max-width: 1180px;
        padding-top: calc(var(--brand-header-height) + 1.2rem);
        padding-bottom: 0;
    }

    .landing-hero {
        position: relative;
        overflow: hidden;
        padding: clamp(2.4rem, 6vw, 5.4rem);
        border-radius: 28px;
        color: white;
        background:
            radial-gradient(circle at 88% 12%, rgba(220, 38, 38, .42), transparent 30%),
            radial-gradient(circle at 10% 95%, rgba(37, 99, 235, .36), transparent 35%),
            linear-gradient(135deg, #071a3d 0%, #0b3d91 58%, #102a5e 100%);
        box-shadow: 0 28px 70px rgba(7, 26, 61, .24);
        margin-bottom: 3.2rem;
    }

    .landing-hero::after {
        content: "CP";
        position: absolute;
        right: -1.5rem;
        bottom: -4rem;
        font-size: clamp(10rem, 25vw, 22rem);
        font-weight: 800;
        line-height: 1;
        color: rgba(255, 255, 255, .045);
        letter-spacing: -.12em;
        pointer-events: none;
    }

    .landing-eyebrow {
        display: inline-flex;
        padding: .48rem .82rem;
        border: 1px solid rgba(255, 255, 255, .24);
        border-radius: 999px;
        background: rgba(255, 255, 255, .1);
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
    }

    .landing-hero h1 {
        max-width: 850px;
        margin: 1.25rem 0 1rem;
        color: white;
        font-size: clamp(2.35rem, 5.8vw, 5rem);
        line-height: 1.02;
        letter-spacing: -.045em;
    }

    .landing-hero p {
        max-width: 720px;
        margin: 0;
        color: rgba(255, 255, 255, .82);
        font-size: clamp(1rem, 1.6vw, 1.2rem);
        line-height: 1.75;
    }

    .landing-actions {
        display: flex;
        flex-wrap: wrap;
        gap: .8rem;
        margin-top: 1.8rem;
        position: relative;
        z-index: 1;
    }

    .landing-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: .78rem 1.2rem;
        border-radius: 12px;
        font-weight: 700;
        text-decoration: none !important;
    }

    .landing-button-primary { background: white; color: #0b3d91 !important; }
    .landing-button-secondary {
        color: white !important;
        border: 1px solid rgba(255, 255, 255, .34);
        background: rgba(255, 255, 255, .08);
    }

    .landing-trust,
    .landing-grid,
    .landing-process {
        display: grid;
        gap: 1rem;
    }

    .landing-trust { grid-template-columns: repeat(3, 1fr); margin: -4.3rem 1.2rem 4rem; position: relative; z-index: 2; }
    .landing-grid { grid-template-columns: repeat(3, 1fr); margin-bottom: 4.5rem; }
    .landing-process { grid-template-columns: repeat(4, 1fr); margin-bottom: 4.5rem; }

    .landing-trust-card,
    .landing-card,
    .landing-step {
        border: 1px solid #e3eaf4;
        background: rgba(255, 255, 255, .97);
        box-shadow: 0 16px 42px rgba(15, 42, 88, .08);
    }

    .landing-trust-card { padding: 1.2rem 1.35rem; border-radius: 16px; }
    .landing-trust-card strong { display: block; color: #071a3d; margin-bottom: .2rem; }
    .landing-trust-card span { color: #60708a; font-size: .9rem; }

    .landing-section { margin: 0 0 1.5rem; }
    .landing-kicker { color: #c8102e; font-size: .78rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
    .landing-section h2 { color: #071a3d; font-size: clamp(1.8rem, 3vw, 2.8rem); letter-spacing: -.035em; margin: .45rem 0 .7rem; }
    .landing-section p { max-width: 760px; color: #60708a; font-size: 1.05rem; line-height: 1.7; }

    .landing-card { min-height: 190px; padding: 1.55rem; border-radius: 18px; }
    .landing-card-number { color: #c8102e; font-weight: 800; font-size: .78rem; letter-spacing: .08em; }
    .landing-card h3 { color: #0b2d68; margin: .75rem 0 .55rem; font-size: 1.16rem; }
    .landing-card p { color: #687790; line-height: 1.62; margin: 0; font-size: .94rem; }

    .landing-band {
        display: grid;
        grid-template-columns: 1.25fr .75fr;
        gap: 2rem;
        align-items: center;
        padding: clamp(1.8rem, 5vw, 3.5rem);
        border-radius: 24px;
        margin-bottom: 4.5rem;
        background: #f3f7fc;
        border: 1px solid #dfe8f5;
    }
    .landing-band h2 { color: #071a3d; font-size: clamp(1.7rem, 3vw, 2.6rem); margin: 0 0 .8rem; }
    .landing-band p { color: #5f6f88; line-height: 1.72; margin: 0; }
    .landing-band-list { display: grid; gap: .65rem; }
    .landing-band-list div { padding: .8rem 1rem; border-radius: 12px; background: white; color: #17335f; font-weight: 650; box-shadow: 0 8px 24px rgba(15, 42, 88, .06); }

    .landing-step { padding: 1.3rem; border-radius: 16px; }
    .landing-step span { display: grid; place-items: center; width: 2rem; height: 2rem; border-radius: 50%; background: #0b3d91; color: white; font-weight: 800; }
    .landing-step h3 { color: #0b2d68; font-size: 1rem; margin: .85rem 0 .35rem; }
    .landing-step p { color: #687790; font-size: .9rem; line-height: 1.55; margin: 0; }

    .landing-contact-intro { margin-top: 1rem; padding-top: 1rem; }
    .st-key-public_request_form { border-radius: 20px; box-shadow: 0 18px 46px rgba(15, 42, 88, .08); }

    .landing-footer {
        margin-top: 4rem;
        padding: 2rem 0 2.5rem;
        border-top: 1px solid #dfe8f5;
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        color: #66758d;
        font-size: .9rem;
    }

    @media (max-width: 820px) {
        .landing-trust, .landing-grid { grid-template-columns: 1fr; }
        .landing-process { grid-template-columns: repeat(2, 1fr); }
        .landing-trust { margin: -2.4rem .7rem 3rem; }
        .landing-band { grid-template-columns: 1fr; }
    }

    @media (max-width: 520px) {
        .landing-hero { border-radius: 20px; }
        .landing-process { grid-template-columns: 1fr; }
        .landing-footer { flex-direction: column; }
    }
    </style>
    """
)

st.html(
    f"""
    <section class="landing-hero">
        <span class="landing-eyebrow">{company_name} · Maroc</span>
        <h1>Un seul partenaire pour concrétiser tous vos besoins.</h1>
        <p>
            Nous accompagnons entreprises, institutions et particuliers avec des
            prestations sur mesure, l’approvisionnement, la vente de produits divers
            et un suivi rigoureux de la demande jusqu’à la livraison.
        </p>
        <div class="landing-actions">
            <a class="landing-button landing-button-primary" href="#demande">Décrivez votre besoin</a>
            <a class="landing-button landing-button-secondary" href="admin">Espace dirigeant</a>
        </div>
    </section>

    <section class="landing-trust">
        <div class="landing-trust-card"><strong>Une offre multiservices</strong><span>Des réponses adaptées, même pour les demandes atypiques.</span></div>
        <div class="landing-trust-card"><strong>Un interlocuteur unique</strong><span>Une coordination simple, claire et professionnelle.</span></div>
        <div class="landing-trust-card"><strong>Un suivi de bout en bout</strong><span>De l’étude du besoin à la livraison finale.</span></div>
    </section>

    <section class="landing-section">
        <span class="landing-kicker">Notre savoir-faire</span>
        <h2>Des solutions utiles, flexibles et bien exécutées.</h2>
        <p>
            {company_name} intervient comme partenaire opérationnel pour simplifier
            vos projets, vos achats et vos besoins du quotidien. Notre approche repose
            sur l’écoute, la réactivité et une proposition adaptée à chaque situation.
        </p>
    </section>

    <section class="landing-grid">
        <article class="landing-card"><span class="landing-card-number">01 · SERVICES</span><h3>Prestations professionnelles</h3><p>Assistance, coordination, accompagnement et réalisation de missions ponctuelles ou récurrentes selon votre cahier des charges.</p></article>
        <article class="landing-card"><span class="landing-card-number">02 · FOURNITURES</span><h3>Approvisionnement sur demande</h3><p>Recherche, sélection et fourniture de biens adaptés à vos contraintes de qualité, de quantité, de délai et de budget.</p></article>
        <article class="landing-card"><span class="landing-card-number">03 · COMMERCE</span><h3>Vente de produits divers</h3><p>Une offre ouverte pour répondre aux besoins des professionnels et particuliers dans différentes catégories de produits.</p></article>
        <article class="landing-card"><span class="landing-card-number">04 · LOGISTIQUE</span><h3>Livraison et coordination</h3><p>Organisation du traitement de la commande et suivi jusqu’à la remise des produits ou l’achèvement de la prestation.</p></article>
        <article class="landing-card"><span class="landing-card-number">05 · SUR MESURE</span><h3>Demandes spécifiques</h3><p>Vous avez un besoin qui sort des offres habituelles ? Nous l’étudions et construisons une réponse réaliste et personnalisée.</p></article>
        <article class="landing-card"><span class="landing-card-number">06 · ENTREPRISES</span><h3>Solutions pour professionnels</h3><p>Devis clairs, facturation structurée, documents de livraison et suivi administratif pour faciliter vos opérations.</p></article>
    </section>

    <section class="landing-band">
        <div><h2>Notre métier : trouver la bonne solution.</h2><p>Plutôt qu’une offre limitée, nous partons de votre objectif. Nous analysons la demande, identifions les moyens nécessaires et vous proposons une réponse compréhensible, chiffrée et réalisable.</p></div>
        <div class="landing-band-list"><div>Prestations ponctuelles ou récurrentes</div><div>Achats et fournitures diversifiés</div><div>Devis et suivi transparents</div><div>Solutions adaptées au contexte</div></div>
    </section>

    <section class="landing-section">
        <span class="landing-kicker">Une méthode simple</span>
        <h2>Votre demande avance en quatre étapes.</h2>
    </section>
    <section class="landing-process">
        <article class="landing-step"><span>1</span><h3>Comprendre</h3><p>Nous recueillons votre besoin, vos priorités et vos contraintes.</p></article>
        <article class="landing-step"><span>2</span><h3>Proposer</h3><p>Nous préparons une solution et un devis adaptés à votre demande.</p></article>
        <article class="landing-step"><span>3</span><h3>Réaliser</h3><p>Nous coordonnons la prestation ou l’approvisionnement convenu.</p></article>
        <article class="landing-step"><span>4</span><h3>Suivre</h3><p>Nous restons présents jusqu’à la livraison et la clôture.</p></article>
    </section>

    <div id="demande" class="landing-contact-intro landing-section">
        <span class="landing-kicker">Parlons de votre projet</span>
        <h2>Décrivez-nous ce dont vous avez besoin.</h2>
        <p>Quelques informations suffisent pour lancer l’étude de votre demande. Nous utiliserons vos coordonnées uniquement pour vous répondre.</p>
    </div>
    """
)

if st.session_state.pop("public_request_sent", False):
    st.success(
        "Votre demande a bien été enregistrée. Chill Point Services pourra maintenant l’étudier et vous recontacter.",
        icon=":material/check_circle:",
    )

with st.form("public_request_form", border=True):
    identity_left, identity_right = st.columns(2, gap="medium")
    with identity_left:
        full_name = st.text_input("Nom et prénom *", key="public_full_name", max_chars=160)
        company = st.text_input("Entreprise ou organisation", key="public_company", max_chars=180)
        email = st.text_input("E-mail", key="public_email", max_chars=180)
    with identity_right:
        phone_input = st.text_input("Téléphone", key="public_phone", max_chars=40)
        request_type = st.selectbox(
            "Type de demande *",
            CLIENT_REQUEST_TYPES,
            key="public_request_type",
        )
        preferred_contact = st.selectbox(
            "Moyen de contact préféré",
            CLIENT_REQUEST_CONTACT_OPTIONS,
            key="public_preferred_contact",
        )
    subject = st.text_input("Objet de la demande", key="public_subject", max_chars=200)
    message = st.text_area(
        "Décrivez votre besoin *",
        key="public_message",
        height=170,
        max_chars=5000,
        placeholder="Type de prestation ou de produit, quantité, délai souhaité, lieu de livraison et toute précision utile…",
    )
    consent = st.checkbox(
        "J’accepte que mes coordonnées soient utilisées pour répondre à cette demande.",
        key="public_consent",
    )
    submitted = st.form_submit_button(
        "Envoyer ma demande",
        type="primary",
        icon=":material/send:",
    )

if submitted:
    errors = []
    if not full_name.strip():
        errors.append("Indiquez votre nom et prénom.")
    if not email.strip() and not phone_input.strip():
        errors.append("Indiquez au moins un e-mail ou un téléphone.")
    if email.strip() and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
        errors.append("L’adresse e-mail n’est pas valide.")
    if len(message.strip()) < 20:
        errors.append("Décrivez votre besoin en au moins 20 caractères.")
    if not consent:
        errors.append("Votre accord est nécessaire pour traiter la demande.")

    if errors:
        st.error(" ".join(errors), icon=":material/error:")
    else:
        try:
            add_client_request(
                {
                    "full_name": full_name,
                    "company_name": company,
                    "email": email,
                    "phone": phone_input,
                    "request_type": request_type,
                    "subject": subject,
                    "message": message,
                    "preferred_contact": preferred_contact,
                }
            )
        except ValueError as error:
            st.warning(str(error), icon=":material/schedule:")
        else:
            for key in [
                "public_full_name", "public_company", "public_email", "public_phone",
                "public_request_type", "public_preferred_contact", "public_subject",
                "public_message", "public_consent",
            ]:
                st.session_state.pop(key, None)
            st.session_state.public_request_sent = True
            st.rerun()

st.html(
    f"""
    <footer class="landing-footer">
        <div><strong>{company_name}</strong><br>{slogan}</div>
        <div>{address}<br>{phone}</div>
    </footer>
    """
)
