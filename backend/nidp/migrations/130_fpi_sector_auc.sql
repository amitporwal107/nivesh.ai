-- Fortnightly FPI sector-wise AUC and net investment (NSDL FPI Monitor).
--
-- Source: https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx
-- Each static report file covers a CALENDAR MONTH and carries four measures:
--     AUC as on <mid>   | Net Investment <1st-mid> | Net Investment <mid-end> | AUC as on <end>
-- so one fetch yields TWO fortnights. Consecutive files therefore overlap by one
-- fortnight; the primary key makes that overlap a free cross-check rather than a
-- duplicate (the later file wins, which is correct — NSDL revises the older half).
--
-- Grain is one row per (fortnight end, sector, asset class). `net_inv_*` is the flow
-- DURING the fortnight ending on report_date; `auc_*` is the stock AS OF report_date.
-- Keeping both on one row is what lets a caller answer "did FPIs add to Financial
-- Services this fortnight, and off what base" without a self-join.
--
-- sector_norm is the join key to nidp.sector_master.sector. It is stored rather than
-- resolved at read time because NSDL uses BSE's 22-sector Common Industry
-- Classification (see the report's own footnote) while sector_master carries NSE's
-- macro-sector labels; the alias map lives in parser.py::SECTOR_ALIASES and is
-- applied once at ingest so downstream joins stay a plain equality.
SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.fpi_sector_auc (
    report_date      date        NOT NULL,
    sector           text        NOT NULL,
    asset_class      text        NOT NULL,
    auc_inr_cr       numeric(18,2),
    auc_usd_mn       numeric(18,2),
    net_inv_inr_cr   numeric(18,2),
    net_inv_usd_mn   numeric(18,2),
    usd_inr_rate     numeric(12,4),
    sector_norm      text,
    source           text        NOT NULL DEFAULT 'NSDL_FPI_FORTNIGHTLY',
    source_url       text,
    source_run_id    uuid,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fpi_sector_auc_pkey PRIMARY KEY (report_date, sector, asset_class, source)
);

-- "Flows into sector X over the last N fortnights" — the dominant read pattern.
CREATE INDEX IF NOT EXISTS idx_fpi_sector_auc_sector_date
    ON nidp.fpi_sector_auc (sector_norm, report_date DESC)
    WHERE sector_norm IS NOT NULL;

-- "Which sectors saw the biggest FPI equity flow this fortnight" — the screen behind
-- the sector-rotation view. Partial on EQUITY because that is the only asset class
-- with a non-zero flow for most sectors.
CREATE INDEX IF NOT EXISTS idx_fpi_sector_auc_date_equity
    ON nidp.fpi_sector_auc (report_date DESC, net_inv_inr_cr DESC)
    WHERE asset_class = 'EQUITY';

COMMENT ON TABLE nidp.fpi_sector_auc IS
    'Fortnightly FPI sector-wise AUC + net investment from NSDL FPI Monitor. '
    'Grain: (report_date=fortnight end, sector, asset_class). '
    'auc_* = stock as of report_date; net_inv_* = flow during the fortnight ending then.';
