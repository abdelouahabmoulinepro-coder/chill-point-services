from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import streamlit as st
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from streamlit.errors import StreamlitSecretNotFoundError


MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60
PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


@dataclass
class _AttemptState:
    failures: int = 0
    locked_until: float = 0.0


class LoginAttemptLimiter:
    """Process-wide limiter for the application's single director account."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _AttemptState()

    def seconds_remaining(self) -> int:
        with self._lock:
            remaining = max(0, int(self._state.locked_until - time.time()) + 1)
            if remaining == 0 and self._state.locked_until:
                self._state = _AttemptState()
            return remaining

    def record_failure(self) -> int:
        with self._lock:
            self._state.failures += 1
            if self._state.failures >= MAX_FAILED_ATTEMPTS:
                self._state.locked_until = time.time() + LOCKOUT_SECONDS
                return 0
            return MAX_FAILED_ATTEMPTS - self._state.failures

    def record_success(self) -> None:
        with self._lock:
            self._state = _AttemptState()


@st.cache_resource
def _attempt_limiter() -> LoginAttemptLimiter:
    return LoginAttemptLimiter()


def hash_password(password: str) -> str:
    """Create a salted Argon2id hash suitable for the secrets configuration."""
    return PASSWORD_HASHER.hash(password)


def verify_credentials(
    supplied_login_id: str,
    supplied_password: str,
    configured_login_id: str,
    configured_password_hash: str,
) -> bool:
    """Verify both fields without revealing which one is incorrect."""
    login_matches = hmac.compare_digest(
        supplied_login_id.strip().casefold(),
        configured_login_id.strip().casefold(),
    )
    try:
        password_matches = PASSWORD_HASHER.verify(
            configured_password_hash,
            supplied_password,
        )
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        password_matches = False
    return login_matches and password_matches


def _secret_section(name: str) -> Mapping[str, Any]:
    try:
        section = st.secrets.get(name, {})
    except (StreamlitSecretNotFoundError, FileNotFoundError):
        return {}
    return section if isinstance(section, Mapping) else {}


def _show_auth_logo(logo_path: str | None) -> None:
    if logo_path:
        st.image(logo_path, width=180)


def _show_missing_configuration(logo_path: str | None) -> None:
    _show_auth_logo(logo_path)
    st.title(":material/lock: Connexion")
    st.write("Cette application de gestion est réservée au dirigeant de l’entreprise.")
    with st.container(border=True):
        st.subheader("Accès dirigeant")
        st.text_input("Identifiant", disabled=True)
        st.text_input("Mot de passe", type="password", disabled=True)
        st.button(
            "Se connecter",
            type="primary",
            icon=":material/login:",
            disabled=True,
        )
    st.warning(
        "L’identifiant et le mot de passe du dirigeant ne sont pas encore configurés. "
        "Les données commerciales restent verrouillées.",
        icon=":material/lock:",
    )
    st.caption(
        "Créez la configuration locale avec `python scripts/configurer_acces.py`, "
        "puis redémarrez l’application."
    )


def logout_director() -> None:
    st.session_state.pop("director_authenticated", None)
    st.session_state.pop("director_display_name", None)


def require_director_auth(logo_path: str | None = None) -> Mapping[str, str]:
    """Stop before business data is loaded unless the director is authenticated."""
    access = _secret_section("access")
    configured_login_id = str(access.get("login_id", "")).strip()
    configured_password_hash = str(access.get("password_hash", "")).strip()
    display_name = str(access.get("display_name", "Dirigeant")).strip() or "Dirigeant"

    if not configured_login_id or not configured_password_hash.startswith("$argon2id$"):
        _show_missing_configuration(logo_path)
        st.stop()

    st.session_state.setdefault("director_authenticated", False)
    if st.session_state.director_authenticated:
        return {"name": st.session_state.get("director_display_name", display_name)}

    _show_auth_logo(logo_path)
    st.title(":material/lock: Connexion")
    st.write("Cette application de gestion est réservée au dirigeant de l’entreprise.")

    limiter = _attempt_limiter()
    locked_for = limiter.seconds_remaining()
    with st.container(border=True):
        st.subheader("Accès dirigeant")
        with st.form("director_login", clear_on_submit=False):
            login_id = st.text_input(
                "Identifiant",
                autocomplete="username",
                disabled=locked_for > 0,
            )
            password = st.text_input(
                "Mot de passe",
                type="password",
                autocomplete="current-password",
                disabled=locked_for > 0,
            )
            submitted = st.form_submit_button(
                "Se connecter",
                type="primary",
                icon=":material/login:",
                disabled=locked_for > 0,
            )

        if locked_for > 0:
            minutes, seconds = divmod(locked_for, 60)
            st.error(
                f"Trop de tentatives. Réessayez dans {minutes:02d}:{seconds:02d}.",
                icon=":material/lock_clock:",
            )
        elif submitted:
            if verify_credentials(
                login_id,
                password,
                configured_login_id,
                configured_password_hash,
            ):
                limiter.record_success()
                st.session_state.director_authenticated = True
                st.session_state.director_display_name = display_name
                st.rerun()
            attempts_left = limiter.record_failure()
            if attempts_left:
                st.error(
                    f"Identifiant ou mot de passe incorrect. {attempts_left} tentative(s) restante(s).",
                    icon=":material/error:",
                )
            else:
                st.error(
                    "Trop de tentatives. L’accès est bloqué pendant cinq minutes.",
                    icon=":material/lock_clock:",
                )

    st.stop()
