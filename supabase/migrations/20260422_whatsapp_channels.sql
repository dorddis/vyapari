-- Phase 3 schema: per-business WhatsApp Cloud API channel config.
--
-- Additive migration over Phase 2's 20260422_templates_and_last_inbound.sql.
-- Idempotent — safe to re-run. Local SQLite dev uses SQLAlchemy
-- create_all(); this file exists for the Supabase Postgres instance
-- at mhxpcsylxicnzujgtepa.

CREATE TABLE IF NOT EXISTS whatsapp_channels (
    id               VARCHAR(36) PRIMARY KEY,
    business_id      VARCHAR(64) NOT NULL
                        REFERENCES businesses(id) ON DELETE CASCADE,
    phone_number     VARCHAR(32) NOT NULL,
    phone_number_id  VARCHAR(64) NOT NULL UNIQUE,
    waba_id          VARCHAR(64) NOT NULL,
    -- Encrypted by services/secrets.encrypt_secrets; shape:
    --   {"key_id": "primary", "ct": "<Fernet token>"}
    -- Decryption yields {access_token, app_secret,
    --                    webhook_verify_token, verification_pin}.
    provider_config  JSONB DEFAULT '{}'::jsonb,
    source           VARCHAR(32) DEFAULT 'manual',
    health_status    VARCHAR(32) DEFAULT 'pending',
    last_verified_at TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at       TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_channel_business_phone UNIQUE (business_id, phone_number)
);

-- phone_number_id is how inbound webhooks identify the tenant; it
-- already has an implicit index via UNIQUE, but mirror the model's
-- explicit index to keep DDL and ORM in sync.
CREATE INDEX IF NOT EXISTS ix_whatsapp_channels_phone_number_id
    ON whatsapp_channels (phone_number_id);

CREATE INDEX IF NOT EXISTS ix_whatsapp_channels_business
    ON whatsapp_channels (business_id);
