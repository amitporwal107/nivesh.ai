-- 004_audit_log.sql — append-only audit log (PRD §11.2, 7-year retention).
--
-- Every write that touches PAN-linked rows must leave a trace here:
-- user creation, job status transitions, snapshot activation/deactivation.
--
-- Design constraints:
--   * IMMUTABLE — no UPDATE/DELETE allowed by policy (enforced by trigger).
--   * actor always present: 'system' for autonomous transitions, the
--     application service for operator actions.
--   * pan_hash stored (not pan_enc) so audit records are safe to query
--     without a decryption key.
--   * JSONB payload keeps the schema open-ended; typed columns enforce the
--     important dimensions (event_type, entity_type, entity_id).

CREATE TABLE IF NOT EXISTS portfolio_ingestion.audit_log (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at   TIMESTAMPTZ NOT NULL    DEFAULT now(),
    event_type    TEXT        NOT NULL,   -- USER_CREATED | JOB_STATUS | SNAPSHOT_ACTIVATED | SNAPSHOT_DEACTIVATED
    entity_type   TEXT        NOT NULL,   -- user | job | snapshot
    entity_id     UUID        NOT NULL,
    pan_hash      VARCHAR(64) NOT NULL,
    actor         TEXT        NOT NULL    DEFAULT 'system',
    payload       JSONB       NOT NULL    DEFAULT '{}'
);

-- Query patterns: by pan_hash + time, by entity, by event type window.
CREATE INDEX IF NOT EXISTS idx_audit_pan_time
    ON portfolio_ingestion.audit_log (pan_hash, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_entity
    ON portfolio_ingestion.audit_log (entity_type, entity_id, occurred_at DESC);

-- Immutability trigger: any attempt to UPDATE or DELETE a row raises an error.
CREATE OR REPLACE FUNCTION portfolio_ingestion.audit_log_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log rows are immutable (attempted %). '
                    'Retain for 7 years per policy.',
                    TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_log_immutable ON portfolio_ingestion.audit_log;
CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON portfolio_ingestion.audit_log
    FOR EACH ROW EXECUTE FUNCTION portfolio_ingestion.audit_log_immutable();
