-- Vyapari full schema migration
-- Matches DESIGN_DOC.md Section 4 and SQLAlchemy models in src/db_models.py
--
-- Run against Supabase project via:
--   supabase db push
-- Or manually in the SQL Editor on dashboard.supabase.com

-- ===========================================================================
-- 1. businesses (multi-tenant root)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS businesses (
    id              VARCHAR(64)     PRIMARY KEY,
    name            VARCHAR(256)    NOT NULL,
    type            VARCHAR(64)     DEFAULT '',
    vertical        VARCHAR(64)     DEFAULT '',
    owner_phone     VARCHAR(32)     NOT NULL,
    wa_catalog_id   VARCHAR(128),
    greeting        TEXT            DEFAULT '',
    hours           JSONB           DEFAULT '{}'::jsonb,
    system_prompt   TEXT            DEFAULT '',
    settings        JSONB           DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     DEFAULT now()
);

-- ===========================================================================
-- 2. catalogue_items (inventory)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS catalogue_items (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    wa_product_id   VARCHAR(128),
    name            VARCHAR(256)    NOT NULL,
    category        VARCHAR(64)     DEFAULT '',
    price           NUMERIC(12,2)   DEFAULT 0,
    attributes      JSONB           DEFAULT '{}'::jsonb,
    description     TEXT            DEFAULT '',
    images          JSONB           DEFAULT '[]'::jsonb,
    active          BOOLEAN         DEFAULT true,
    sold            BOOLEAN         DEFAULT false,
    reserved_by     VARCHAR(32),
    created_at      TIMESTAMPTZ     DEFAULT now(),
    updated_at      TIMESTAMPTZ     DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_catalogue_items_business_active
    ON catalogue_items (business_id, active);
CREATE INDEX IF NOT EXISTS ix_catalogue_items_category
    ON catalogue_items (category);

-- ===========================================================================
-- 3. faqs
-- ===========================================================================
CREATE TABLE IF NOT EXISTS faqs (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    question        TEXT            NOT NULL,
    answer          TEXT            NOT NULL,
    category        VARCHAR(64)     DEFAULT 'general'
);

CREATE INDEX IF NOT EXISTS ix_faqs_business_category
    ON faqs (business_id, category);

-- ===========================================================================
-- 4. staff (owner / SDR)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS staff (
    wa_id           VARCHAR(32)     PRIMARY KEY,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name            VARCHAR(128)    NOT NULL,
    role            VARCHAR(16)     NOT NULL CHECK (role IN ('owner', 'sdr')),
    status          VARCHAR(16)     DEFAULT 'active' CHECK (status IN ('active', 'invited', 'removed')),
    otp_hash        VARCHAR(256),
    otp_expires_at  TIMESTAMPTZ,
    attempts        INTEGER         DEFAULT 0,
    added_by        VARCHAR(32),
    created_at      TIMESTAMPTZ     DEFAULT now(),
    last_active_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_staff_business_role
    ON staff (business_id, role);

-- ===========================================================================
-- 5. customers (leads)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS customers (
    wa_id           VARCHAR(32)     PRIMARY KEY,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name            VARCHAR(128)    DEFAULT 'Customer',
    channel         VARCHAR(32)     DEFAULT 'whatsapp',
    source          VARCHAR(256),
    lead_status     VARCHAR(16)     DEFAULT 'new'
                        CHECK (lead_status IN ('new', 'warm', 'hot', 'quiet', 'converted')),
    interested_cars JSONB           DEFAULT '[]'::jsonb,
    first_seen      TIMESTAMPTZ     DEFAULT now(),
    last_active     TIMESTAMPTZ     DEFAULT now(),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS ix_customers_business_lead
    ON customers (business_id, lead_status);
CREATE INDEX IF NOT EXISTS ix_customers_last_active
    ON customers (last_active);

-- ===========================================================================
-- 6. conversations
-- ===========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    customer_wa_id  VARCHAR(32)     NOT NULL REFERENCES customers(wa_id) ON DELETE CASCADE,
    assigned_to     VARCHAR(32)     REFERENCES staff(wa_id) ON DELETE SET NULL,
    status          VARCHAR(24)     DEFAULT 'active'
                        CHECK (status IN ('active', 'escalated', 'relay_active', 'resolved')),
    escalation_reason TEXT          DEFAULT '',
    started_at      TIMESTAMPTZ     DEFAULT now(),
    last_updated_at TIMESTAMPTZ     DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_conversations_customer
    ON conversations (customer_wa_id);
CREATE INDEX IF NOT EXISTS ix_conversations_status
    ON conversations (status);
CREATE INDEX IF NOT EXISTS ix_conversations_business_status
    ON conversations (business_id, status);

-- ===========================================================================
-- 7. messages
-- ===========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id VARCHAR(36)     NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16)     NOT NULL
                        CHECK (role IN ('customer', 'agent', 'owner', 'sdr')),
    content         TEXT            DEFAULT '',
    message_type    VARCHAR(24)     DEFAULT 'text',
    wa_msg_id       VARCHAR(128),
    images          JSONB           DEFAULT '[]'::jsonb,
    is_escalation   BOOLEAN         DEFAULT false,
    escalation_reason TEXT          DEFAULT '',
    timestamp       TIMESTAMPTZ     DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_ts
    ON messages (conversation_id, "timestamp");
CREATE INDEX IF NOT EXISTS ix_messages_wa_msg_id
    ON messages (wa_msg_id);

-- ===========================================================================
-- 8. escalations
-- ===========================================================================
CREATE TABLE IF NOT EXISTS escalations (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id VARCHAR(36)     NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    trigger         VARCHAR(64)     NOT NULL,
    summary         TEXT            DEFAULT '',
    status          VARCHAR(24)     DEFAULT 'pending'
                        CHECK (status IN ('pending', 'acknowledged', 'owner_active', 'resolved')),
    created_at      TIMESTAMPTZ     DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_escalations_conversation
    ON escalations (conversation_id);
CREATE INDEX IF NOT EXISTS ix_escalations_status
    ON escalations (status);

-- ===========================================================================
-- 9. relay_sessions
-- ===========================================================================
CREATE TABLE IF NOT EXISTS relay_sessions (
    id                  VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    staff_wa_id         VARCHAR(32)  NOT NULL REFERENCES staff(wa_id) ON DELETE CASCADE,
    customer_wa_id      VARCHAR(32)  NOT NULL REFERENCES customers(wa_id) ON DELETE CASCADE,
    conversation_id     VARCHAR(36)  NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    started_at          TIMESTAMPTZ  DEFAULT now(),
    last_active_at      TIMESTAMPTZ  DEFAULT now(),
    status              VARCHAR(16)  DEFAULT 'active'
                            CHECK (status IN ('active', 'closed', 'expired')),
    inactivity_timeout_minutes INTEGER DEFAULT 15,
    total_timeout_minutes      INTEGER DEFAULT 20
);

CREATE INDEX IF NOT EXISTS ix_relay_sessions_staff
    ON relay_sessions (staff_wa_id, status);
CREATE INDEX IF NOT EXISTS ix_relay_sessions_customer
    ON relay_sessions (customer_wa_id, status);

-- ===========================================================================
-- 10. daily_wraps
-- ===========================================================================
CREATE TABLE IF NOT EXISTS daily_wraps (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    business_id     VARCHAR(64)     NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    date            VARCHAR(10)     NOT NULL,
    data            JSONB           DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     DEFAULT now(),

    CONSTRAINT uq_daily_wrap_business_date UNIQUE (business_id, date)
);

-- ===========================================================================
-- 11. owner_setup (onboarding wizard)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS owner_setup (
    wa_id           VARCHAR(32)     PRIMARY KEY REFERENCES staff(wa_id) ON DELETE CASCADE,
    current_step    VARCHAR(64)     DEFAULT 'business_name',
    collected       JSONB           DEFAULT '{}'::jsonb,
    active          BOOLEAN         DEFAULT true,
    started_at      TIMESTAMPTZ     DEFAULT now(),
    updated_at      TIMESTAMPTZ     DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

-- ===========================================================================
-- 12. message_logs (Rahul's existing flat log - web clone compat)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS message_logs (
    id              VARCHAR(36)     PRIMARY KEY DEFAULT gen_random_uuid()::text,
    wa_id           VARCHAR(32)     NOT NULL,
    role            VARCHAR(24)     NOT NULL,
    direction       VARCHAR(16)     NOT NULL,
    channel         VARCHAR(32)     NOT NULL,
    text            TEXT            DEFAULT '',
    msg_type        VARCHAR(32)     DEFAULT 'text',
    external_msg_id VARCHAR(128),
    images          JSONB           DEFAULT '[]'::jsonb,
    meta            JSONB           DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_message_logs_wa_id     ON message_logs (wa_id);
CREATE INDEX IF NOT EXISTS ix_message_logs_role      ON message_logs (role);
CREATE INDEX IF NOT EXISTS ix_message_logs_direction ON message_logs (direction);
CREATE INDEX IF NOT EXISTS ix_message_logs_channel   ON message_logs (channel);
CREATE INDEX IF NOT EXISTS ix_message_logs_ext_id    ON message_logs (external_msg_id);
CREATE INDEX IF NOT EXISTS ix_message_logs_created   ON message_logs (created_at);

-- ===========================================================================
-- Auto-update updated_at on catalogue_items
-- ===========================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_catalogue_items_updated_at
    BEFORE UPDATE ON catalogue_items
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_owner_setup_updated_at
    BEFORE UPDATE ON owner_setup
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================================================
-- Seed demo business (single-tenant for hackathon)
-- ===========================================================================
INSERT INTO businesses (id, name, type, vertical, owner_phone, greeting)
VALUES (
    'demo-sharma-motors',
    'Sharma Motors',
    'dealership',
    'used_cars',
    '919876543210',
    'Welcome to Sharma Motors! How can I help you today?'
)
ON CONFLICT (id) DO NOTHING;

-- Seed default owner staff record
INSERT INTO staff (wa_id, business_id, name, role, status)
VALUES (
    '919876543210',
    'demo-sharma-motors',
    'Rajesh',
    'owner',
    'active'
)
ON CONFLICT (wa_id) DO NOTHING;
