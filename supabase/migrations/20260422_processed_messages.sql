-- Phase 3.6: DB-backed inbound-webhook idempotency.
--
-- Replaces state.py's in-memory _processed_msg_ids dict with a
-- cross-replica-safe UNIQUE constraint. Two replicas racing on the
-- same Meta-retried wamid will have their INSERTs collide on the
-- composite PK; the loser's rollback drops the duplicate dispatch.

CREATE TABLE IF NOT EXISTS processed_messages (
    business_id   VARCHAR(64) NOT NULL,
    wa_msg_id     VARCHAR(128) NOT NULL,
    processed_at  TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (business_id, wa_msg_id)
);

CREATE INDEX IF NOT EXISTS ix_processed_messages_at
    ON processed_messages (processed_at);
