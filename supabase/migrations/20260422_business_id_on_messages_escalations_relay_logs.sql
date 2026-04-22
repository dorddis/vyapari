-- Phase 3.5: per-row tenant tagging on Message, Escalation, RelaySession, MessageLog.
--
-- All four tables carried tenant via JOIN chains (conversation -> customer
-- -> business_id, or Staff -> business_id). Direct column + index lets
-- multi-tenant audit queries run without joins and lets a future RLS
-- policy target these tables directly.
--
-- Columns are NULLABLE for back-compat with pre-P3.5 rows. Phase 6
-- hardening runs a backfill job + flips to NOT NULL.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS business_id VARCHAR(64)
        REFERENCES businesses(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_messages_business_id
    ON messages (business_id);

ALTER TABLE escalations
    ADD COLUMN IF NOT EXISTS business_id VARCHAR(64)
        REFERENCES businesses(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_escalations_business_id
    ON escalations (business_id);

ALTER TABLE relay_sessions
    ADD COLUMN IF NOT EXISTS business_id VARCHAR(64)
        REFERENCES businesses(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_relay_sessions_business_id
    ON relay_sessions (business_id);

ALTER TABLE message_logs
    ADD COLUMN IF NOT EXISTS business_id VARCHAR(64)
        REFERENCES businesses(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_message_logs_business_id
    ON message_logs (business_id);
