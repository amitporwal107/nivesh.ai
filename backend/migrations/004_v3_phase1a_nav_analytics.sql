-- V3 Engine Phase 1a: columns for NAV-derived primitives.
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS max_drawdown_pct      NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS consistency_score     NUMERIC(4,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS downside_capture_pct  NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS aum_trend_score       NUMERIC(4,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS nav_analytics_at      TIMESTAMP;
