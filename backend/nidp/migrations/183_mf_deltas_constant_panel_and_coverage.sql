-- 183: deltas at the canonical fund grain on a CONSTANT PANEL, a real measured coverage_pct,
--      and an audit trail for restated holdings.
--
-- Three defects, one migration, because they are the same defect seen from three sides: a number
-- that is published without the thing that makes it true.
--
-- ── 1. DELTAS WERE COMPUTED PER PLAN VARIANT, ON A GROWING PANEL ───────────────────────────
-- nidp.mf_holdings_deltas is keyed (scheme_code, security_isin, current_month), so one fund's
-- month-over-month change is written once per plan/option variant — four to eight identical rows
-- whose shares_delta any consumer then sums (migration 182 measured the 4.09x). Migration 177
-- patched the BREADTH view by counting distinct (amc_id, previous_shares, current_shares) blocks;
-- that is a workaround at the read side, and it cannot fix the stored delta itself.
--
-- Worse, the panel GROWS. Measured 2026-10-23 on nidp.v_mf_holdings_canonical: 20,604 canonical
-- fund-ISIN rows in 2025-09 against 38,318 in 2026-09, and the AMC count went 7 -> 11 (SBI's own
-- XLSX feed starts 2026-09, Axis 2026-05). A month-on-month difference over that panel reads
-- "we started indexing this AMC" as "mutual funds bought", which is a fabricated signal of
-- exactly the kind this layer exists to prevent. HAL: 64 funds in 2025-09 -> 132 in 2026-09.
--
-- The fix, in the service (mf_holdings_deltas) and recorded here as columns:
--   * one row per CANONICAL fund (amc_id + base_scheme) x ISIN x month, written under the
--     representative scheme_code so existing joins to nidp.mf_scheme_master keep working;
--   * panel_status = 'constant_panel' only when the SAME canonical fund was observed in the
--     comparison month. 'panel_entry' means the fund is new to our index, and those rows keep
--     change_class 'unknown' / validation_status 'coverage_gap' — never a direction;
--   * naive_previous_shares / naive_current_shares keep the pre-dedupe sums, so the inflation
--     this fixes stays auditable instead of disappearing from the record;
--   * computed_basis says which pass wrote the row, so the legacy plan-variant rows can be
--     removed deterministically when a month is recomputed.
--
-- ── 2. coverage_pct WAS THE CONSTANT 100.00 ────────────────────────────────────────────────
-- nidp.smart_money_scores_daily.coverage_pct is 100.00 on all 25,313 rows (verified 2026-10-23):
-- it measures how many of the five sub-signals were populated, and all five always are. Under the
-- name "coverage" next to holdings data it reads as "we see all of the mutual-fund holding",
-- which is false by a factor of two: the measured figure is 0.56 (Nifty 500, 2026-09, n=408,
-- nidp.v_mf_stock_coverage). The sub-signal number is not deleted — it moves to
-- subsignal_coverage_pct, which is what it always was — and coverage_pct becomes the MEASURED
-- share of the disclosed mutual-fund holding that we can actually see, with coverage_basis
-- naming the case. Where the company does not disclose both mf_pct and total_shares it is NULL,
-- never 0 and never 100.
--
-- Existing rows are set to NULL rather than converted: no measured coverage was computed when
-- they were written, and inventing one now would be the same fault in a new place. They are
-- refilled the next time the scorer runs.
--
-- ── 3. A BACKFILL COULD SILENTLY RESTATE A PUBLISHED MONTH ─────────────────────────────────
-- mf_holdings/writer.py upserts ON CONFLICT (scheme_code, as_of_month, security_name,
-- security_isin, source) DO UPDATE SET quantity = EXCLUDED.quantity, so re-ingesting a month
-- that an AMC has re-published overwrites the number we already served, leaving no trace. Of the
-- 118 stored AMC-month source URLs, migration 171 found 14 late re-uploads (icici_pru 8, ppfas 5,
-- uti 1) — re-publication is a thing that actually happens here, not a hypothetical.
-- mf_holdings_restatements records every such change (old -> new, when, which run) via a trigger,
-- so a correction is an auditable event. The trigger fires only when a value really changes, so a
-- re-ingest that writes the same numbers costs nothing and logs nothing.
--
-- Idempotent: safe to re-run.

-- ── Deltas: canonical identity, panel status, and the naive figure for audit ────────────────
ALTER TABLE nidp.mf_holdings_deltas
    ADD COLUMN IF NOT EXISTS amc_id                TEXT,
    ADD COLUMN IF NOT EXISTS base_scheme           TEXT,
    -- amc_id || '|' || base_scheme: the fund whose decision this row describes.
    ADD COLUMN IF NOT EXISTS canonical_fund_key    TEXT,
    -- Every plan/option scheme_code that collapsed into this row, so nothing is hidden.
    ADD COLUMN IF NOT EXISTS variant_scheme_codes  TEXT[],
    ADD COLUMN IF NOT EXISTS variant_rows          INTEGER,
    ADD COLUMN IF NOT EXISTS panel_status          TEXT,
    -- The pre-dedupe sums across plan variants, for audit only. Never a quantity to publish.
    ADD COLUMN IF NOT EXISTS naive_previous_shares NUMERIC,
    ADD COLUMN IF NOT EXISTS naive_current_shares  NUMERIC,
    -- Derivative legs seen for this fund/ISIN/month, excluded from the share count by design.
    ADD COLUMN IF NOT EXISTS derivative_rows       INTEGER,
    ADD COLUMN IF NOT EXISTS computed_basis        TEXT;

-- Rows written before this migration are plan-variant rows: label them, so a recompute can
-- remove them deterministically instead of leaving duplicates behind at the old grain.
UPDATE nidp.mf_holdings_deltas
   SET computed_basis = 'plan_variant_rows'
 WHERE computed_basis IS NULL;

ALTER TABLE nidp.mf_holdings_deltas
    ALTER COLUMN computed_basis SET DEFAULT 'plan_variant_rows';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'mf_holdings_deltas_panel_chk'
                      AND conrelid = 'nidp.mf_holdings_deltas'::regclass) THEN
        ALTER TABLE nidp.mf_holdings_deltas
            ADD CONSTRAINT mf_holdings_deltas_panel_chk CHECK (
                panel_status IS NULL OR panel_status IN ('constant_panel', 'panel_entry'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'mf_holdings_deltas_basis_chk'
                      AND conrelid = 'nidp.mf_holdings_deltas'::regclass) THEN
        ALTER TABLE nidp.mf_holdings_deltas
            ADD CONSTRAINT mf_holdings_deltas_basis_chk CHECK (
                computed_basis IN ('canonical_fund', 'plan_variant_rows'));
    END IF;
    -- A fund that is new to our index must never carry a direction.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'mf_holdings_deltas_panel_entry_unknown_chk'
                      AND conrelid = 'nidp.mf_holdings_deltas'::regclass) THEN
        ALTER TABLE nidp.mf_holdings_deltas
            ADD CONSTRAINT mf_holdings_deltas_panel_entry_unknown_chk CHECK (
                panel_status IS DISTINCT FROM 'panel_entry' OR change_class = 'unknown');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mf_hold_delta_fund
    ON nidp.mf_holdings_deltas (canonical_fund_key, current_month);
CREATE INDEX IF NOT EXISTS idx_mf_hold_delta_panel
    ON nidp.mf_holdings_deltas (current_month, panel_status);

COMMENT ON COLUMN nidp.mf_holdings_deltas.canonical_fund_key IS
  'amc_id || ''|'' || base_scheme — one fund, plan/option variants collapsed. A row with '
  'computed_basis = ''canonical_fund'' is one fund''s decision; summing shares_delta over these '
  'rows is correct, which it was not at the old plan-variant grain (4.09x).';
COMMENT ON COLUMN nidp.mf_holdings_deltas.panel_status IS
  '''constant_panel'' = the same canonical fund was observed in the comparison month, so the '
  'change is a real portfolio movement. ''panel_entry'' = the fund is new to OUR index (we went '
  'from 7 to 11 AMCs and 20,604 to 38,318 fund-ISIN rows in a year); such a row is never a '
  'direction. Filter to constant_panel before aggregating flows.';
COMMENT ON COLUMN nidp.mf_holdings_deltas.naive_previous_shares IS
  'Pre-dedupe sum across plan variants, kept only so the duplication this grain removes stays '
  'measurable. Never publish it as a share count.';
COMMENT ON COLUMN nidp.mf_holdings_deltas.computed_basis IS
  '''canonical_fund'' (written by the deduplicated pass) | ''plan_variant_rows'' (legacy, one row '
  'per plan variant, 4.09x inflated). The recompute deletes the legacy rows for the months it '
  'rewrites rather than leaving both grains in the table.';

-- ── Stock-level flow, constant panel vs naive, so the difference is always visible ─────────
CREATE OR REPLACE VIEW nidp.v_mf_stock_flow_monthly AS
SELECT d.security_isin,
       d.current_month,
       count(*)                                                                 AS funds_total,
       count(*) FILTER (WHERE d.panel_status = 'constant_panel')                 AS funds_constant_panel,
       count(*) FILTER (WHERE d.panel_status = 'panel_entry')                    AS funds_panel_entry,
       -- The honest flow: only funds we observed in BOTH months.
       sum(d.shares_delta) FILTER (WHERE d.panel_status = 'constant_panel'
                                     AND d.change_class <> 'unknown')            AS net_shares_delta,
       sum(d.shares_delta) FILTER (WHERE d.panel_status = 'constant_panel'
                                     AND d.change_class IN ('increase', 'new'))   AS shares_added,
       sum(d.shares_delta) FILTER (WHERE d.panel_status = 'constant_panel'
                                     AND d.change_class IN ('decrease', 'possible_exit')) AS shares_reduced,
       count(DISTINCT d.amc_id) FILTER (WHERE d.panel_status = 'constant_panel'
                                          AND d.change_class IN ('increase', 'new'))      AS amcs_increasing,
       count(DISTINCT d.amc_id) FILTER (WHERE d.panel_status = 'constant_panel'
                                          AND d.change_class IN ('decrease', 'possible_exit')) AS amcs_reducing,
       -- Everything a panel-expansion month would have added. Reported, never summed into flow.
       sum(d.current_shares) FILTER (WHERE d.panel_status = 'panel_entry')        AS panel_entry_shares,
       -- The pre-dedupe equivalent, for audit: what the old grain would have published.
       sum(coalesce(d.naive_current_shares, 0) - coalesce(d.naive_previous_shares, 0))
           FILTER (WHERE d.panel_status = 'constant_panel')                       AS naive_net_shares_delta,
       max(d.known_from)                                                          AS known_from,
       CASE WHEN count(*) = count(*) FILTER (WHERE d.known_from_basis = 'published')
            THEN 'published' ELSE 'observed' END                                  AS known_from_basis
  FROM nidp.mf_holdings_deltas d
 WHERE d.computed_basis = 'canonical_fund'
 GROUP BY d.security_isin, d.current_month;

COMMENT ON VIEW nidp.v_mf_stock_flow_monthly IS
  'Per (ISIN, month): disclosed mutual-fund share flow over a CONSTANT PANEL of funds — funds we '
  'observed in both compared months — so newly indexed AMCs cannot read as buying. '
  'funds_panel_entry / panel_entry_shares report the expansion separately; '
  'naive_net_shares_delta is the pre-dedupe figure, for audit only. Reads only rows written by '
  'the canonical pass, so it is empty until the deduplicated recompute has run.';

-- ── coverage_pct: a measured number, or NULL ───────────────────────────────────────────────
ALTER TABLE nidp.smart_money_scores_daily
    -- What coverage_pct actually measured until now: the share of the five sub-signals populated.
    ADD COLUMN IF NOT EXISTS subsignal_coverage_pct NUMERIC(5,2),
    -- How coverage_pct was arrived at: 'measured' | 'isin_not_listed_eq_be' |
    -- 'company_discloses_no_mf_pct_or_total_shares' | 'measured_exceeds_disclosed' | 'not_measured'
    ADD COLUMN IF NOT EXISTS coverage_basis         TEXT;

-- Relabel, then stop asserting a coverage nobody measured.
UPDATE nidp.smart_money_scores_daily
   SET subsignal_coverage_pct = coalesce(subsignal_coverage_pct, coverage_pct),
       coverage_basis         = coalesce(coverage_basis, 'not_measured'),
       coverage_pct           = NULL
 WHERE subsignal_coverage_pct IS NULL;

COMMENT ON COLUMN nidp.smart_money_scores_daily.coverage_pct IS
  'MEASURED share of the disclosed mutual-fund holding of this stock that our indexed AMCs '
  'account for: canonical shares / (total_shares x mf_pct), from nidp.v_mf_stock_coverage. '
  'NULL where the company does not disclose both inputs — coverage_basis says which case. It was '
  'a constant 100.00 until migration 183; that figure was the sub-signal count and now lives in '
  'subsignal_coverage_pct.';
COMMENT ON COLUMN nidp.smart_money_scores_daily.subsignal_coverage_pct IS
  'Share of the five scoring sub-signals that were populated for this symbol-date. This is what '
  'coverage_pct held before migration 183 (always 100.00).';

-- The published number keeps its meaning: avg_subsignal_coverage_pct now reads the column that
-- actually holds the sub-signal count, and the measured holdings coverage is added beside it.
CREATE OR REPLACE VIEW nidp.v_smart_money_coverage_by_date AS
SELECT as_of_date,
       count(*)                                                   AS scored_symbols,
       count(*) FILTER (WHERE data_confidence = 'high')            AS conf_high,
       count(*) FILTER (WHERE data_confidence = 'medium')          AS conf_medium,
       count(*) FILTER (WHERE data_confidence = 'low')             AS conf_low,
       count(*) FILTER (WHERE single_amc_signal)                   AS single_amc,
       round(avg(months_observed), 2)                              AS avg_months_observed,
       round(avg(subsignal_coverage_pct), 1)                       AS avg_subsignal_coverage_pct,
       max(latest_reporting_date)                                  AS latest_disclosure,
       min(lookback_months)                                        AS lookback_months,
       max(config_version)                                         AS config_version,
       -- Added by 183: the real holdings coverage behind the scores on this date.
       count(coverage_pct)                                         AS symbols_with_measured_coverage,
       round(avg(coverage_pct), 1)                                 AS avg_measured_coverage_pct,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY coverage_pct)::numeric, 1)
                                                                   AS median_measured_coverage_pct
  FROM nidp.smart_money_scores_daily
 GROUP BY as_of_date;

COMMENT ON VIEW nidp.v_smart_money_coverage_by_date IS
  'Per scoring date: Smart Money component coverage and confidence mix. avg_subsignal_coverage_pct '
  'is how much of the scoring input was populated; avg/median_measured_coverage_pct is how much of '
  'the disclosed mutual-fund holding we actually see (0.56 of it, Nifty 500 2026-09) — do not read '
  'the first as the second, which is what the constant 100.00 invited.';

-- ── Restatements: a backfill may correct a published month, but not quietly ────────────────
CREATE TABLE IF NOT EXISTS nidp.mf_holdings_restatements (
    restatement_id   BIGSERIAL PRIMARY KEY,
    scheme_code      TEXT        NOT NULL,
    as_of_month      DATE        NOT NULL,
    security_isin    TEXT,
    security_name    TEXT        NOT NULL,
    source           TEXT        NOT NULL,
    field            TEXT        NOT NULL,          -- quantity | market_value_inr | weight_pct
    old_value        NUMERIC,
    new_value        NUMERIC,
    old_source_url   TEXT,
    new_source_url   TEXT,
    old_ingested_at  TIMESTAMPTZ,
    restated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    restated_by_run  UUID,
    CONSTRAINT mf_holdings_restatements_field_chk
        CHECK (field IN ('quantity', 'market_value_inr', 'weight_pct'))
);

CREATE INDEX IF NOT EXISTS idx_mf_restate_month ON nidp.mf_holdings_restatements (as_of_month);
CREATE INDEX IF NOT EXISTS idx_mf_restate_when  ON nidp.mf_holdings_restatements (restated_at DESC);

COMMENT ON TABLE nidp.mf_holdings_restatements IS
  'Every change a later ingest made to an already-stored holding (quantity / market value / '
  'weight), written by a trigger on nidp.mf_holdings_monthly. A published snapshot may be '
  'corrected — SEBI-era re-uploads happen, 14 of 118 AMC-months per migration 171 — but it may '
  'not be corrected silently. Empty is the expected state; rows here are the audit trail of a '
  'restatement, and the reason a figure we served last month may differ today.';

CREATE OR REPLACE FUNCTION nidp.log_mf_holdings_restatement() RETURNS trigger AS $fn$
BEGIN
    -- Only real changes are logged, so an idempotent re-ingest writes nothing here.
    IF NEW.quantity IS DISTINCT FROM OLD.quantity THEN
        INSERT INTO nidp.mf_holdings_restatements
            (scheme_code, as_of_month, security_isin, security_name, source, field,
             old_value, new_value, old_source_url, new_source_url, old_ingested_at, restated_by_run)
        VALUES (OLD.scheme_code, OLD.as_of_month, OLD.security_isin, OLD.security_name, OLD.source,
                'quantity', OLD.quantity, NEW.quantity, OLD.source_url, NEW.source_url,
                OLD.ingested_at, NEW.source_run_id);
    END IF;
    IF NEW.market_value_inr IS DISTINCT FROM OLD.market_value_inr THEN
        INSERT INTO nidp.mf_holdings_restatements
            (scheme_code, as_of_month, security_isin, security_name, source, field,
             old_value, new_value, old_source_url, new_source_url, old_ingested_at, restated_by_run)
        VALUES (OLD.scheme_code, OLD.as_of_month, OLD.security_isin, OLD.security_name, OLD.source,
                'market_value_inr', OLD.market_value_inr, NEW.market_value_inr,
                OLD.source_url, NEW.source_url, OLD.ingested_at, NEW.source_run_id);
    END IF;
    IF NEW.weight_pct IS DISTINCT FROM OLD.weight_pct THEN
        INSERT INTO nidp.mf_holdings_restatements
            (scheme_code, as_of_month, security_isin, security_name, source, field,
             old_value, new_value, old_source_url, new_source_url, old_ingested_at, restated_by_run)
        VALUES (OLD.scheme_code, OLD.as_of_month, OLD.security_isin, OLD.security_name, OLD.source,
                'weight_pct', OLD.weight_pct, NEW.weight_pct,
                OLD.source_url, NEW.source_url, OLD.ingested_at, NEW.source_run_id);
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

COMMENT ON FUNCTION nidp.log_mf_holdings_restatement() IS
  'Writes nidp.mf_holdings_restatements when an upsert changes a stored holding value. Uses IS '
  'DISTINCT FROM so a NULL -> value correction is logged too.';

DROP TRIGGER IF EXISTS trg_mf_holdings_restatement ON nidp.mf_holdings_monthly;
CREATE TRIGGER trg_mf_holdings_restatement
    AFTER UPDATE ON nidp.mf_holdings_monthly
    FOR EACH ROW
    WHEN (OLD.quantity         IS DISTINCT FROM NEW.quantity
       OR OLD.market_value_inr IS DISTINCT FROM NEW.market_value_inr
       OR OLD.weight_pct       IS DISTINCT FROM NEW.weight_pct)
    EXECUTE FUNCTION nidp.log_mf_holdings_restatement();

-- Which published months have been restated, how much, and when.
CREATE OR REPLACE VIEW nidp.v_mf_holdings_restatement_summary AS
SELECT as_of_month,
       field,
       count(*)                                                        AS restatements,
       count(DISTINCT scheme_code)                                     AS schemes_affected,
       count(DISTINCT security_isin)                                   AS securities_affected,
       count(*) FILTER (WHERE old_value IS NULL)                        AS filled_from_null,
       count(*) FILTER (WHERE old_value IS NOT NULL AND new_value IS NULL) AS cleared_to_null,
       round(avg(abs(new_value - old_value) / nullif(abs(old_value), 0)), 4) AS mean_abs_rel_change,
       max(abs(new_value - old_value) / nullif(abs(old_value), 0))       AS max_abs_rel_change,
       min(restated_at)                                                AS first_restated_at,
       max(restated_at)                                                AS last_restated_at
  FROM nidp.mf_holdings_restatements
 GROUP BY as_of_month, field;

COMMENT ON VIEW nidp.v_mf_holdings_restatement_summary IS
  'Per reporting month and field: how often an already-published holding was later changed. Read '
  'this before trusting a historical comparison that spans a restatement — and before concluding '
  'that a number we served earlier was wrong rather than corrected.';
