-- Migration 092: Add fundamental risk analytics to PRA engine output
--
-- Extends pra.component_var with per-holding fundamental metrics and a
-- composite risk score. Extends pra.portfolio_risk_results with a
-- portfolio-level fundamental risk summary.

-- ── 1. Per-holding fundamental columns on pra.component_var ───────────────
ALTER TABLE pra.component_var
    ADD COLUMN IF NOT EXISTS altman_z_score       NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS debt_to_equity       NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS interest_coverage    NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS current_ratio        NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS cfo_pat_ratio        NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS promoter_pledged_pct NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS free_float_pct       NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS operating_margin_pct NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS fundamental_risk_score NUMERIC(6,1),  -- 0-100, higher = riskier
    ADD COLUMN IF NOT EXISTS risk_flags           TEXT[]           -- e.g. {DISTRESS_ZONE,HIGH_PLEDGE}
    ;

-- ── 2. Portfolio-level fundamental risk summary ────────────────────────────
ALTER TABLE pra.portfolio_risk_results
    ADD COLUMN IF NOT EXISTS portfolio_fundamental_risk_score NUMERIC(6,1),
    ADD COLUMN IF NOT EXISTS n_high_fundamental_risk          INTEGER,
    ADD COLUMN IF NOT EXISTS pct_value_high_fundamental_risk  NUMERIC(6,2)
    ;
