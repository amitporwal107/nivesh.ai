-- 004_nidp_macro_reference.sql — Macro yields + reference master data.
--
-- Covers:
--   8.1   rbi_yields    — RBI ReferenceRateArchive G-Sec yields (fixes the
--                         current `^TNX = US 10Y` bug in macro_ingester)
--   10.1  nse_holidays  — NSE trading holiday calendar (prevents
--                         schedulers from firing on closed days)

SET search_path TO nidp, public;

-- ── rbi_yields ──────────────────────────────────────────────────────
-- Multi-tenor G-Sec yields from RBI Reference Rate Archive. Long-form:
-- one row per (date, tenor, source) so we can carry overnight + 1Y +
-- 5Y + 10Y in the same table without column proliferation.
CREATE TABLE IF NOT EXISTS nidp.rbi_yields (
    as_of_date      DATE NOT NULL,
    tenor           TEXT NOT NULL,                   -- 'OVERNIGHT' | '91D' | '364D' | '1Y' | '5Y' | '10Y'
    yield_pct       NUMERIC(8,4) NOT NULL,
    instrument      TEXT,                            -- 'TBILL' | 'GSEC' | 'POLICY_REPO'
    source          TEXT NOT NULL,                   -- 'RBI_REF_RATE' | 'CCIL'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, tenor, source)
);

CREATE INDEX IF NOT EXISTS idx_rbi_yields_tenor_date
    ON nidp.rbi_yields(tenor, as_of_date DESC);


-- ── nse_holidays ────────────────────────────────────────────────────
-- Per-segment calendar so schedulers (CM vs F&O vs commodities) can
-- query the segment they care about. Refreshed annually + on-event
-- (special holidays announced mid-year).
CREATE TABLE IF NOT EXISTS nidp.nse_holidays (
    holiday_date    DATE NOT NULL,
    segment         TEXT NOT NULL,                   -- 'CM' | 'FO' | 'CD' | 'COM' | 'DEBT' | 'MF'
    description     TEXT,
    source          TEXT NOT NULL,                   -- 'NSE_HOLIDAY_MASTER'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (holiday_date, segment, source)
);

CREATE INDEX IF NOT EXISTS idx_nse_holidays_segment_date
    ON nidp.nse_holidays(segment, holiday_date);


INSERT INTO nidp.schema_migrations(filename) VALUES ('004_nidp_macro_reference.sql')
    ON CONFLICT (filename) DO NOTHING;
