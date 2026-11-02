-- 190: durable record of every warehouse write made by the TrueData fundamentals job
--      (backend/nidp/services/truedata_fundamentals).
--
-- WHY
-- The job fills balance-sheet columns and finance costs on rows OTHER sources own (mostly trendlyne_mcp and
-- screener_in*), inserts fiscal-year rows only where none exist, and writes fiscal-year cash flows. The supervised
-- load of 2 Nov 2026 recorded its fills in nse_financials_quarterly.raw_data, but other writers replace raw_data
-- wholesale (the Trendlyne build: raw_data = EXCLUDED.raw_data), so that record does not survive. This table is the
-- record instead: one row per warehouse row a run touched, with the columns it filled and the values it wrote, so
-- `python -m nidp.services.truedata_fundamentals --rollback RUN_ID` can undo a run exactly:
--   * inserted rows are deleted while still the run's (source 'truedata', source_run_id = run_id);
--   * filled columns are set back to NULL only while they still hold values_written (they were NULL before the fill,
--     by construction); a value another writer has put there since is kept.
--
-- Not recorded here: the supervised loads of 2 Nov 2026 (runs 1586b55f…, 4259f69b…, 43fcbd3a…), made before this
-- table existed. Their record is the manifests next to the raw data on the app VM
-- (/home/deploy/nivesh-truedata-raw/manifests/<run>.csv); nothing is backfilled because their raw_data tags may already
-- have been replaced, and a guessed "value written" would make the rollback inexact.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.truedata_fundamentals_fills (
    id              BIGSERIAL   PRIMARY KEY,
    run_id          UUID        NOT NULL,              -- = nidp.job_log.run_id of the run
    kind            TEXT        NOT NULL,              -- what TrueData statement the values came from
    table_written    TEXT        NOT NULL,              -- the nidp table written
    symbol          TEXT        NOT NULL,
    period_end      DATE        NOT NULL,
    consolidated    BOOLEAN     NOT NULL,
    period_type     TEXT        NOT NULL,              -- the touched row's period_type ('annual' for cash flow)
    row_source      TEXT,                              -- the touched row's source (the row's owner)
    td_filing_id    BIGINT      NOT NULL,              -- TrueData filing id the values came from
    unit            TEXT        NOT NULL,              -- the filing's reporting unit: crore | million | lakh | thousand | rupee
    unit_how        TEXT        NOT NULL,              -- how the unit was established (anchor and ratio)
    columns_filled  TEXT[]      NOT NULL DEFAULT '{}', -- columns written (for a fill: they were NULL before)
    values_written  JSONB       NOT NULL DEFAULT '{}'::jsonb,   -- {column: value in crore, as written}
    inserted        BOOLEAN     NOT NULL,              -- TRUE: the run created the row; FALSE: it filled NULL columns
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    rolled_back_at  TIMESTAMPTZ,                       -- set by --rollback
    CONSTRAINT truedata_fundamentals_fills_kind_chk
        CHECK (kind IN ('balance_sheet', 'cash_flow', 'finance_costs')),
    CONSTRAINT truedata_fundamentals_fills_table_chk
        CHECK (table_written IN ('nse_financials_quarterly', 'nse_financials_cashflow')),
    CONSTRAINT truedata_fundamentals_fills_unit_chk
        CHECK (unit IN ('crore', 'million', 'lakh', 'thousand', 'rupee')),
    CONSTRAINT truedata_fundamentals_fills_once
        UNIQUE (run_id, kind, table_written, symbol, period_end, consolidated, period_type)
);

CREATE INDEX IF NOT EXISTS idx_td_fundamentals_fills_row
    ON nidp.truedata_fundamentals_fills (symbol, period_end, consolidated);

COMMENT ON TABLE nidp.truedata_fundamentals_fills IS
  'One row per warehouse row a TrueData fundamentals run touched (services/truedata_fundamentals): which columns it '
  'filled, the values it wrote, whether it inserted the row. The rollback of a run reads only this table. Kept after '
  'a rollback (rolled_back_at) as the audit trail.';
