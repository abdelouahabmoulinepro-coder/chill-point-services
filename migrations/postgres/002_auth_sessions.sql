-- Server-side registry for revocable persistent director sessions.
-- Only the SHA-256 fingerprint of a random session identifier is stored.
CREATE TABLE auth_sessions (
    session_id_hash CHAR(64) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_auth_sessions_hash_length
        CHECK (char_length(session_id_hash) = 64),
    CONSTRAINT ck_auth_sessions_expiry
        CHECK (expires_at > created_at)
);

CREATE INDEX idx_auth_sessions_expiry ON auth_sessions(expires_at);

COMMENT ON TABLE auth_sessions IS
    'Revocable director sessions; contains no password, password hash, token, or business data.';
