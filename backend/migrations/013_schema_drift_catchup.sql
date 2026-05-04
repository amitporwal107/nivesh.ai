-- 013_schema_drift_catchup.sql
--
-- Captures columns that were added to the preview Postgres ad-hoc but
-- never made it into a migration file. Re-running this on a database
-- that already has the columns is a no-op thanks to IF NOT EXISTS.
--
-- Surfaced when post_deploy_migrate ran against a fresh prod Neon and
-- the smoke check failed on `moneycontrol_imid`.

ALTER TABLE mutual_fund_metadata
  ADD COLUMN IF NOT EXISTS credit_quality_score   NUMERIC,
  ADD COLUMN IF NOT EXISTS duration_risk_score    NUMERIC,
  ADD COLUMN IF NOT EXISTS ytm                    NUMERIC,
  ADD COLUMN IF NOT EXISTS modified_duration      NUMERIC,
  ADD COLUMN IF NOT EXISTS moneycontrol_imid      TEXT,
  ADD COLUMN IF NOT EXISTS investment_style       TEXT,
  ADD COLUMN IF NOT EXISTS morningstar_rating     INTEGER;

CREATE INDEX IF NOT EXISTS idx_mfmd_moneycontrol_imid
  ON mutual_fund_metadata (moneycontrol_imid)
  WHERE moneycontrol_imid IS NOT NULL;
