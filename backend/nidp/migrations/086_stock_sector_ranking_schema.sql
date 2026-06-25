-- Migration 086: Stock sector ranking output columns
--
-- Adds the structured ranking output to v3_stock_scores_daily so the sector
-- scoring engine can persist competition rank, status, audit trail (contributions,
-- penalties, overlays), and staleness timestamps per stock per day.
--
-- All additions use ADD COLUMN IF NOT EXISTS — safe to re-run.
-- v3_stock_scores_daily is a regular PG table (not a TimescaleDB hypertable),
-- so ALTER TABLE locks are millisecond-range on the current ~180K-row dataset.

-- ── v3_stock_scores_daily: ranking + status + audit columns ───────────────────

ALTER TABLE nidp.v3_stock_scores_daily
    ADD COLUMN IF NOT EXISTS sector_rank          INTEGER,
    ADD COLUMN IF NOT EXISTS sector_pct           NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS sector_size          INTEGER,
    ADD COLUMN IF NOT EXISTS status               VARCHAR(24),
    ADD COLUMN IF NOT EXISTS gate_failure_reason  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS applied_penalties    JSONB,
    ADD COLUMN IF NOT EXISTS applied_overlays     JSONB,
    ADD COLUMN IF NOT EXISTS contributions        JSONB,
    ADD COLUMN IF NOT EXISTS last_ranked_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_as_of           DATE;

-- Indexes that downstream consumers (rec engine, DaaS, copilot) will use most:
-- 1. Filter to ranked stocks for a given date
CREATE INDEX IF NOT EXISTS idx_v3_scores_status_date
    ON nidp.v3_stock_scores_daily (status, as_of_date DESC)
    WHERE status IS NOT NULL;

-- 2. Per-sector leaderboard (used by ranking compute and DaaS screener)
CREATE INDEX IF NOT EXISTS idx_v3_scores_sector_rank
    ON nidp.v3_stock_scores_daily (sector_profile, sector_rank, as_of_date DESC)
    WHERE sector_rank IS NOT NULL;

-- ── sector_master: sector benchmark index mapping ─────────────────────────────
-- Needed so the technical scorer can compute sector-relative return (RS component).

ALTER TABLE nidp.sector_master
    ADD COLUMN IF NOT EXISTS sector_benchmark_index TEXT;

-- Seed the 8 profile → NSE index mappings.
-- sector_master.sector values come from migration 080 (NSE equity master labels).
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty Bank'               WHERE sector ILIKE '%banking%' OR sector ILIKE '%bank%';
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty Financial Services'  WHERE sector_benchmark_index IS NULL AND (sector ILIKE '%finance%' OR sector ILIKE '%nbfc%');
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty IT'                  WHERE sector_benchmark_index IS NULL AND (sector ILIKE '%information technology%' OR sector ILIKE '%software%');
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty FMCG'               WHERE sector_benchmark_index IS NULL AND (sector ILIKE '%fmcg%' OR sector ILIKE '%consumer staple%');
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty Pharma'             WHERE sector_benchmark_index IS NULL AND (sector ILIKE '%pharma%' OR sector ILIKE '%healthcare%');
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty Infrastructure'     WHERE sector_benchmark_index IS NULL AND (sector ILIKE '%capital goods%' OR sector ILIKE '%infrastructure%');
UPDATE nidp.sector_master SET sector_benchmark_index = 'Nifty 500'                WHERE sector_benchmark_index IS NULL AND sector IS NOT NULL;
