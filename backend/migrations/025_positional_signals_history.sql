-- 025 — AI scanner signals are versioned, not silently overwritten (finding N17), and each signal's stop method is
-- stored as data (finding N13). Phase 2.1 of docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md.
--
-- Before this, a scanner re-run for a date that already had signals rewrote entry / stop / target in place
-- (ON CONFLICT DO UPDATE), so a paper trade could cite levels that no longer existed anywhere. Now the row a re-run
-- replaces is first copied, unchanged, into positional_signals_history, and the live row's `revision` goes up by one.
-- A re-run that produces the same levels writes no history and keeps its revision.
--
-- Additive and idempotent: two nullable columns and one new table. Nothing existing is rewritten. The pipeline checks
-- for these objects and, when they are missing, keeps the old upsert and logs an ERROR saying history is not recorded
-- (services/positional_engine/pipeline.signal_history_ready).
--
-- Rollback: DROP TABLE positional_signals_history; ALTER TABLE positional_signals DROP COLUMN revision,
-- DROP COLUMN stop_method;  (the pipeline then falls back to the old upsert by itself).

ALTER TABLE positional_signals ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1;
ALTER TABLE positional_signals ADD COLUMN IF NOT EXISTS stop_method JSONB;

CREATE TABLE IF NOT EXISTS positional_signals_history (
    nse_symbol          TEXT NOT NULL,
    signal_date         DATE NOT NULL,
    revision            INTEGER NOT NULL,          -- the revision this row WAS while it was live
    final_score         NUMERIC(5, 4),
    confidence          TEXT,
    stage               TEXT,
    timeframe_days_min  INTEGER,
    timeframe_days_max  INTEGER,
    entry_price         NUMERIC(14, 4),
    stoploss            NUMERIC(14, 4),
    target_price        NUMERIC(14, 4),
    risk_reward         NUMERIC(6, 2),
    source_scans        TEXT[],
    reasons             JSONB,
    engine_version      TEXT,
    stop_method         JSONB,
    computed_at         TIMESTAMPTZ,               -- when the superseded row was computed
    superseded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by       TEXT NOT NULL,             -- 'rerun' (an upsert changed it) | 'replace' (a day rewrite deleted it)
    PRIMARY KEY (nse_symbol, signal_date, revision)
);

CREATE INDEX IF NOT EXISTS idx_psignals_hist_date ON positional_signals_history(signal_date DESC);
