-- Phase 3.7: per-business REST API keys.
--
-- Replaces the single shared `API_AUTH_TOKEN` env var with
-- tenant-bound credentials. See src/services/api_keys.py for the
-- mint / verify / revoke surface.

CREATE TABLE IF NOT EXISTS api_keys (
    id           VARCHAR(36) PRIMARY KEY,
    business_id  VARCHAR(64) NOT NULL
                    REFERENCES businesses(id) ON DELETE CASCADE,
    -- SHA-256 hex of the plaintext key. The plaintext is shown ONCE
    -- at mint time and never persisted.
    key_hash     VARCHAR(64) NOT NULL UNIQUE,
    -- First 8 chars of the plaintext. Safe to show in admin UIs.
    key_prefix   VARCHAR(16) DEFAULT '',
    description  VARCHAR(256) DEFAULT '',
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    revoked_at   TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_api_keys_business
    ON api_keys (business_id);
CREATE INDEX IF NOT EXISTS ix_api_keys_hash
    ON api_keys (key_hash);
