-- 149_tpd_move_odds_publish.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Published Ten-Percent Days estimates for the Research page's "Move odds" screen.
--
-- The model freezes each night's estimates as a hashed snapshot on the research host
-- (tpd_model.forward_v4). tpd_model.publish copies a verified, counted snapshot into these
-- tables, insert-only and idempotent on the snapshot's hash, so the served numbers are exactly
-- the frozen ones (spec C7) and a republish can never change a past run. Nothing else reads
-- these tables; the DaaS router move_odds.py (internal plan only) is the one reader, behind the
-- app's move_odds allowlist flag.
--
--   tpd_runs           one row per published snapshot (provenance)
--   tpd_run_estimates  p per (run, head, symbol)
--   tpd_run_stocks     company name, sector and the fixed inputs on record, with data dates
--   tpd_run_events     up to 3 classified events per stock on record at the freeze (media titles NULL)
--   tpd_run_grades     per-run, per-head outcome summary once the session's bars are in
--   tpd_run_refusals   a run refused on incomplete data (the page says "withheld", never shows an older run)
--   tpd_model_record   base rate and highest-10 hit rate from the pre-registered test window
--   tpd_band_record    how each probability band turned out in that window
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;

CREATE TABLE IF NOT EXISTS nidp.tpd_runs (
    run_id                      BIGSERIAL PRIMARY KEY,
    model                       TEXT NOT NULL,
    refit                       TEXT NOT NULL DEFAULT 'monthly',
    status                      TEXT NOT NULL CHECK (status IN ('final', 'provisional')),
    data_as_of                  DATE NOT NULL,
    target_session              DATE NOT NULL,
    frozen_at                   TIMESTAMPTZ NOT NULL,
    published_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_sha256             TEXT NOT NULL UNIQUE,
    lock_sha256                 TEXT NOT NULL,
    git_sha                     TEXT NOT NULL,
    universe_size               INTEGER NOT NULL,
    scored                      INTEGER NOT NULL,
    input_count                 INTEGER,
    train_rows                  INTEGER,
    train_end                   DATE,
    skipped_holidays            DATE[] NOT NULL DEFAULT '{}',
    counts_toward_verdict       BOOLEAN NOT NULL,
    results_filed_in_universe   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tpd_runs_model_target ON nidp.tpd_runs (model, status, target_session DESC);

CREATE TABLE IF NOT EXISTS nidp.tpd_run_estimates (
    run_id       BIGINT NOT NULL REFERENCES nidp.tpd_runs (run_id),
    head         TEXT NOT NULL CHECK (head IN ('p_up5_1d', 'p_down5_1d', 'p_up10_1d', 'p_down10_1d')),
    symbol       TEXT NOT NULL,
    p            DOUBLE PRECISION NOT NULL CHECK (p >= 0 AND p <= 1),
    p_base_rate  DOUBLE PRECISION NOT NULL CHECK (p_base_rate >= 0 AND p_base_rate <= 1),
    PRIMARY KEY (run_id, head, symbol)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_run_stocks (
    run_id         BIGINT NOT NULL REFERENCES nidp.tpd_runs (run_id),
    symbol         TEXT NOT NULL,
    company_name   TEXT,
    sector         TEXT,
    inputs         JSONB NOT NULL,
    results_filed  BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_run_events (
    run_id         BIGINT NOT NULL REFERENCES nidp.tpd_runs (run_id),
    symbol         TEXT NOT NULL,
    ord            SMALLINT NOT NULL CHECK (ord BETWEEN 1 AND 3),
    event_time     TIMESTAMPTZ NOT NULL,
    source_label   TEXT NOT NULL,
    is_media       BOOLEAN NOT NULL,
    event_type     TEXT NOT NULL,
    event_subtype  TEXT NOT NULL,
    direction      TEXT NOT NULL,
    title          TEXT,
    url            TEXT,
    method         TEXT NOT NULL,
    PRIMARY KEY (run_id, symbol, ord),
    CHECK (NOT is_media OR title IS NULL)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_run_grades (
    run_id        BIGINT NOT NULL REFERENCES nidp.tpd_runs (run_id),
    head          TEXT NOT NULL,
    graded_rows   INTEGER NOT NULL,
    touched       INTEGER NOT NULL,
    top10_hits    INTEGER NOT NULL,
    graded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, head)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_run_refusals (
    model           TEXT NOT NULL,
    target_session  DATE NOT NULL,
    reason          TEXT NOT NULL,
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (model, target_session, reason)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_model_record (
    model           TEXT NOT NULL,
    head            TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('test_2025')),
    window_label    TEXT NOT NULL,
    sessions        INTEGER NOT NULL,
    base_rate       DOUBLE PRECISION NOT NULL,
    top10_hit_rate  DOUBLE PRECISION NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (model, head, source)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_band_record (
    model         TEXT NOT NULL,
    head          TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('test_2025')),
    band_lo       DOUBLE PRECISION NOT NULL,
    band_hi       DOUBLE PRECISION NOT NULL,
    rows          INTEGER NOT NULL,
    realised      DOUBLE PRECISION,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (model, head, source, band_lo)
);

INSERT INTO nidp.schema_migrations (filename)
VALUES ('149_tpd_move_odds_publish.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
