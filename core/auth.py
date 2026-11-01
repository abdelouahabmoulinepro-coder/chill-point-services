from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from streamlit.errors import StreamlitSecretNotFoundError

from core.database import (
    DatabaseError,
    create_auth_session,
    is_auth_session_active,
    revoke_auth_session,
)


MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60
SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_COOKIE_NAME = "chill_point_director_session"
SESSION_TOKEN_STATE_KEY = "director_session_token"
SESSION_TOKEN_VERSION = 1
MAX_SESSION_TOKEN_LENGTH = 1024
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
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


@dataclass(frozen=True)
class SessionClaims:
    session_id: str
    issued_at: int
    expires_at: int


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


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Encodage base64url invalide.")
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _session_signing_key(session_secret: str, password_hash: str) -> bytes:
    return hmac.new(
        session_secret.encode("utf-8"),
        b"chill-point/director-session/v1\0" + password_hash.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _session_id_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def issue_session_token(
    session_secret: str,
    password_hash: str,
    *,
    now: datetime | None = None,
) -> tuple[str, SessionClaims]:
    """Create a signed opaque session token containing no account credentials."""
    issued_at = int((now or datetime.now(timezone.utc)).timestamp())
    claims = SessionClaims(
        session_id=secrets.token_urlsafe(32),
        issued_at=issued_at,
        expires_at=issued_at + SESSION_TTL_SECONDS,
    )
    payload = json.dumps(
        {
            "exp": claims.expires_at,
            "iat": claims.issued_at,
            "sid": claims.session_id,
            "v": SESSION_TOKEN_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = _base64url_encode(payload)
    signature = hmac.new(
        _session_signing_key(session_secret, password_hash),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}", claims


def validate_session_token(
    token: str,
    session_secret: str,
    password_hash: str,
    *,
    now: datetime | None = None,
) -> SessionClaims | None:
    """Validate signature, structure, issue time, maximum lifetime, and expiry."""
    if not token or len(token) > MAX_SESSION_TOKEN_LENGTH or token.count(".") != 1:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            _session_signing_key(session_secret, password_hash),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        raw_claims = json.loads(_base64url_decode(encoded_payload))
        if not isinstance(raw_claims, dict) or set(raw_claims) != {"v", "sid", "iat", "exp"}:
            return None
        if raw_claims["v"] != SESSION_TOKEN_VERSION:
            return None
        if type(raw_claims["iat"]) is not int or type(raw_claims["exp"]) is not int:
            return None
        session_id = raw_claims["sid"]
        if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            return None
        checked_at = int((now or datetime.now(timezone.utc)).timestamp())
        issued_at = raw_claims["iat"]
        expires_at = raw_claims["exp"]
        if issued_at > checked_at + 60:
            return None
        if expires_at <= checked_at or expires_at <= issued_at:
            return None
        if expires_at - issued_at > SESSION_TTL_SECONDS:
            return None
        return SessionClaims(session_id, issued_at, expires_at)
    except (TypeError, ValueError, UnicodeError, binascii.Error, json.JSONDecodeError):
        return None


def create_persistent_session(
    session_secret: str,
    password_hash: str,
    *,
    now: datetime | None = None,
) -> tuple[str, SessionClaims]:
    token, claims = issue_session_token(
        session_secret,
        password_hash,
        now=now,
    )
    create_auth_session(
        _session_id_hash(claims.session_id),
        datetime.fromtimestamp(claims.expires_at, tz=timezone.utc),
    )
    return token, claims


def validate_persistent_session(
    token: str,
    session_secret: str,
    password_hash: str,
    *,
    now: datetime | None = None,
) -> SessionClaims | None:
    claims = validate_session_token(token, session_secret, password_hash, now=now)
    if claims is None:
        return None
    checked_at = now or datetime.now(timezone.utc)
    if not is_auth_session_active(_session_id_hash(claims.session_id), checked_at):
        return None
    return claims


def revoke_persistent_session(
    token: str,
    session_secret: str,
    password_hash: str,
) -> None:
    claims = validate_session_token(token, session_secret, password_hash)
    if claims is not None:
        revoke_auth_session(_session_id_hash(claims.session_id))


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
        "L’identifiant, le mot de passe ou le secret de session ne sont pas encore configurés. "
        "Les données commerciales restent verrouillées.",
        icon=":material/lock:",
    )
    st.caption(
        "Créez la configuration locale avec `python scripts/configurer_acces.py`, "
        "puis redémarrez l’application."
    )


def _cookie_manager():
    import extra_streamlit_components as stx

    state_key = "_director_cookie_manager"
    if state_key not in st.session_state:
        st.session_state[state_key] = stx.CookieManager(key="director_cookie_manager")
    return st.session_state[state_key]


def _browser_cookie() -> str:
    try:
        return str(st.context.cookies.get(SESSION_COOKIE_NAME, ""))
    except (AttributeError, KeyError, TypeError):
        return ""


def _set_browser_cookie(token: str, expires_at: int) -> None:
    try:
        current_url = str(st.context.url)
    except (AttributeError, RuntimeError):
        current_url = ""
    _cookie_manager().set(
        SESSION_COOKIE_NAME,
        token,
        key="director_cookie_set",
        path="/",
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        max_age=SESSION_TTL_SECONDS,
        secure=current_url.lower().startswith("https://"),
        same_site="strict",
    )


def _delete_browser_cookie() -> None:
    try:
        _cookie_manager().delete(SESSION_COOKIE_NAME, key="director_cookie_delete")
    except KeyError:
        # The browser cookie may exist even when the component's first snapshot is empty.
        pass


def _clear_auth_state() -> None:
    st.session_state.pop("director_authenticated", None)
    st.session_state.pop("director_display_name", None)
    st.session_state.pop(SESSION_TOKEN_STATE_KEY, None)


def logout_director() -> None:
    access = _secret_section("access")
    session_secret = str(access.get("session_secret", "")).strip()
    password_hash = str(access.get("password_hash", "")).strip()
    token = str(st.session_state.get(SESSION_TOKEN_STATE_KEY, "")) or _browser_cookie()
    try:
        if token and session_secret and password_hash:
            revoke_persistent_session(token, session_secret, password_hash)
    finally:
        _clear_auth_state()
        _delete_browser_cookie()


def require_director_auth(logo_path: str | None = None) -> Mapping[str, str]:
    """Stop before business data is loaded unless the director is authenticated."""
    access = _secret_section("access")
    configured_login_id = str(access.get("login_id", "")).strip()
    configured_password_hash = str(access.get("password_hash", "")).strip()
    session_secret = str(access.get("session_secret", "")).strip()
    display_name = str(access.get("display_name", "Dirigeant")).strip() or "Dirigeant"

    if (
        not configured_login_id
        or not configured_password_hash.startswith("$argon2id$")
        or len(session_secret) < 32
    ):
        _show_missing_configuration(logo_path)
        st.stop()

    state_token = str(st.session_state.get(SESSION_TOKEN_STATE_KEY, ""))
    if state_token and validate_persistent_session(
        state_token,
        session_secret,
        configured_password_hash,
    ):
        st.session_state.director_authenticated = True
        return {"name": st.session_state.get("director_display_name", display_name)}

    _clear_auth_state()
    cookie_token = _browser_cookie()
    if cookie_token and validate_persistent_session(
        cookie_token,
        session_secret,
        configured_password_hash,
    ):
        st.session_state.director_authenticated = True
        st.session_state.director_display_name = display_name
        st.session_state[SESSION_TOKEN_STATE_KEY] = cookie_token
        return {"name": display_name}
    if cookie_token:
        _delete_browser_cookie()

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
                try:
                    token, claims = create_persistent_session(
                        session_secret,
                        configured_password_hash,
                    )
                except DatabaseError:
                    st.error(
                        "La session sécurisée n’a pas pu être créée. Réessayez dans un instant.",
                        icon=":material/database_off:",
                    )
                    st.stop()
                limiter.record_success()
                st.session_state.director_authenticated = True
                st.session_state.director_display_name = display_name
                st.session_state[SESSION_TOKEN_STATE_KEY] = token
                _set_browser_cookie(token, claims.expires_at)
                st.success("Connexion sécurisée établie.", icon=":material/verified_user:")
                # The cookie component completes client-side and triggers the next rerun.
                st.stop()
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
