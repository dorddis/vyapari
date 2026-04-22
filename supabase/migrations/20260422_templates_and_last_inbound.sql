-- Phase 2 schema: 24-hour window tracking + message template catalog.
--
-- Additive migration over 20260416000000_full_schema.sql. Idempotent —
-- safe to re-run. For local SQLite dev the models alone drive schema via
-- SQLAlchemy `create_all()`; this file exists for the Supabase Postgres
-- instance at mhxpcsylxicnzujgtepa.

-- -------------------------------------------------------------------------
-- 1. Per-customer 24-hour window source of truth.
--
-- Populated by the webhook on every inbound message (NOT on our own
-- outbound). The outbound dispatcher reads it to decide free-form reply
-- vs. template-only. Nullable for backfill; rows pre-existing at
-- migration time may not have seen an inbound since this landed.
-- -------------------------------------------------------------------------

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS ix_customers_last_inbound
    ON customers (last_inbound_at);


-- -------------------------------------------------------------------------
-- 2. Message template catalog.
--
-- One row per (business_id, name, language). Status tracks Meta's
-- approval lifecycle. `components` mirrors the exact shape the Graph
-- API /messages template payload expects (header/body/footer/button
-- components), so the dispatcher can hand the JSON to send_template
-- without reshaping.
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS message_templates (
    id                VARCHAR(36) PRIMARY KEY,
    business_id       VARCHAR(64) NOT NULL
                         REFERENCES businesses(id) ON DELETE CASCADE,
    name              VARCHAR(128) NOT NULL,
    language          VARCHAR(16) NOT NULL DEFAULT 'en',
    category          VARCHAR(32) DEFAULT 'UTILITY',
    components        JSONB DEFAULT '[]'::jsonb,
    status            VARCHAR(16) DEFAULT 'pending',
    rejected_reason   TEXT,
    meta_template_id  VARCHAR(128),
    last_synced_at    TIMESTAMP WITH TIME ZONE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at        TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT uq_template_business_name_lang UNIQUE (business_id, name, language)
);

CREATE INDEX IF NOT EXISTS ix_templates_business_status
    ON message_templates (business_id, status);
