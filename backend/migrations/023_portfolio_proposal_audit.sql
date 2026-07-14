-- 023_portfolio_proposal_audit.sql
-- Per-proposal audit trail for the copilot Portfolio Builder (PRD D4).
-- Persists the record produced by services.selection.build_audit_record():
-- the inputs, scoring weights, scoring-config version, the picks made and the
-- rejected candidates (with gate/overlap reasons). Forward-only / additive.
--
-- Written by services.portfolio_proposal_audit.persist() once per generated
-- proposal. Best-effort from the builder's side — a failed audit write must
-- never break proposal generation (the writer logs + returns None).

CREATE TABLE IF NOT EXISTS portfolio_proposal_audit (
    proposal_id            UUID PRIMARY KEY,
    user_id                TEXT,
    inputs                 JSONB NOT NULL,
    weights                JSONB,
    scoring_config_version TEXT,
    picks                  JSONB,
    rejected               JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_proposal_audit_created
    ON portfolio_proposal_audit (created_at DESC);
