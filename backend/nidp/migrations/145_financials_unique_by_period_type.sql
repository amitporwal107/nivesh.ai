-- 145_financials_unique_by_period_type.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- A March quarter and its fiscal year each get their own row.
--
-- nidp.nse_financials_quarterly holds quarterly rows AND fiscal-year rows, but the live unique
-- index nse_financials_quarterly_sym_period_cons_uniq is (symbol, period_end, consolidated).
-- A March quarter and its fiscal year both end on 31-Mar, so they competed for ONE row:
-- measured on staging 2026-09-14, 274 March quarters (2025/2026) in the Nifty 500 + next 500
-- are missing because an annual row holds the key. Every "latest 4 quarters" window then reaches
-- back a fifth quarter: 124 stocks have a non-consecutive current TTM (wrong TTM profit, P/E,
-- ROE) and 147 a wrong prior-year window (wrong growth). Commit 420808e1 stopped an annual
-- upsert overwriting a quarter's income statement, but the quarter still had nowhere to live
-- whenever the year got there first (nse_financials/service.py writes the annual P&L before
-- the latest quarter), and 143 had to discard annual figures for the same reason.
--
-- This migration puts period_type into the key; the writers' ON CONFLICT targets change with it.
--
-- 1. period_type is lowercased first (only rows that differ; 112 did this once, the writers
--    lowercase on insert). Once the value is part of the key, 'QUARTERLY' and 'quarterly' would
--    be two different keys.
-- 2. The new unique index (symbol, period_end, consolidated, period_type) is built BEFORE the
--    old one is dropped, so the table is never without a uniqueness guarantee. It cannot fail on
--    existing data: the old index already makes (symbol, period_end, consolidated) unique.
--    It contains period_end, the hypertable's partitioning column, as TimescaleDB requires.
--
-- 3. The PRIMARY KEY (symbol, period_end, consolidated, source) is widened to include
--    period_type as well. Left alone it would reject exactly the rows this migration is for.
--    ON CONFLICT used to rewrite `source` but never `period_type`, so a fiscal-year row that a
--    quarterly writer later landed on carries that writer's source. Example, daily feed on a
--    Q4 results day: service.py writes the annual P&L (source 'screener_in_annual',
--    period_type 'annual') and then the March quarter (source 'screener_in') onto the same row
--    -> the row is period_type 'annual', source 'screener_in'. The next 'screener_in' write for
--    that March quarter no longer conflicts on the new key, so it INSERTs - and
--    (symbol, period_end, consolidated, 'screener_in') collides with the annual row in the old
--    primary key: a unique violation, and the March quarter still cannot be stored.
--    Today's writers never use one source for both period types (quarterly: screener_in,
--    nse_integrated_xbrl, nse_xbrl, nse_xbrl_backfill, company_ir; annual: screener_in_annual,
--    yahoo_finance), so the problem is the history in the rows, not the code.
--    The widened key is implied by the new unique index; it is kept as the primary key
--    so the table still has one.
--
-- 4. Nothing is retyped or deleted. Fiscal-year rows that absorbed a March quarter's income
--    statement still hold it until the Screener backfill rewrites the year (its annual P&L now
--    lands on its own row and COALESCEs the real figures back in); the NOTICE counts them.
--    Re-run backfill_screener_historical after this migration so the missing March quarters
--    come back as their own rows.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── 1. One spelling per period type ──────────────────────────────────────────
UPDATE nidp.nse_financials_quarterly
   SET period_type = lower(period_type)
 WHERE period_type <> lower(period_type);

-- ── 2. New key first, then drop the old one ─────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS nse_financials_quarterly_sym_period_cons_type_uniq
    ON nidp.nse_financials_quarterly (symbol, period_end, consolidated, period_type);

-- The old key may exist as a bare index or as a UNIQUE constraint; handle both.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = 'nidp.nse_financials_quarterly'::regclass
                  AND conname  = 'nse_financials_quarterly_sym_period_cons_uniq') THEN
        ALTER TABLE nidp.nse_financials_quarterly
            DROP CONSTRAINT nse_financials_quarterly_sym_period_cons_uniq;
    END IF;
END $$;
DROP INDEX IF EXISTS nidp.nse_financials_quarterly_sym_period_cons_uniq;

-- ── 3. Primary key: add period_type (see header, point 3) ───────────────────
DO $$
DECLARE
    v_pkey     TEXT;
    v_has_type BOOLEAN;
BEGIN
    SELECT c.conname,
           EXISTS (SELECT 1
                     FROM pg_attribute a
                    WHERE a.attrelid = c.conrelid
                      AND a.attname  = 'period_type'
                      AND a.attnum   = ANY (c.conkey))
      INTO v_pkey, v_has_type
      FROM pg_constraint c
     WHERE c.conrelid = 'nidp.nse_financials_quarterly'::regclass
       AND c.contype  = 'p';

    IF v_pkey IS NOT NULL AND NOT v_has_type THEN
        EXECUTE format('ALTER TABLE nidp.nse_financials_quarterly DROP CONSTRAINT %I', v_pkey);
        ALTER TABLE nidp.nse_financials_quarterly
            ADD CONSTRAINT nse_financials_quarterly_pkey
            PRIMARY KEY (symbol, period_end, consolidated, period_type, source);
    END IF;
END $$;

-- ── Guard: no unique index may still leave period_type out ──────────────────
-- Any such index would keep a March quarter and its fiscal year colliding; fail the whole
-- migration (it is one transaction) rather than leave the writers half-fixed.
DO $$
DECLARE
    v_blocking TEXT;
BEGIN
    SELECT string_agg(i.indexrelid::regclass::text, ', ')
      INTO v_blocking
      FROM pg_index i
     WHERE i.indrelid = 'nidp.nse_financials_quarterly'::regclass
       AND i.indisunique
       AND NOT EXISTS (SELECT 1
                         FROM pg_attribute a
                        WHERE a.attrelid = i.indrelid
                          AND a.attname  = 'period_type'
                          AND a.attnum   = ANY (i.indkey));
    IF v_blocking IS NOT NULL THEN
        RAISE EXCEPTION '145: unique index(es) without period_type remain on '
                        'nidp.nse_financials_quarterly: %', v_blocking;
    END IF;
END $$;

-- ── Report ───────────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_mar_years_alone INT;
    v_years_quarter_source INT;
BEGIN
    -- Fiscal-year rows on 31-Mar with no March-quarter row beside them (before any backfill
    -- re-run this is every such year: until now the two could not coexist).
    SELECT count(*) INTO v_mar_years_alone
      FROM nidp.nse_financials_quarterly a
     WHERE a.period_type = 'annual'
       AND extract(month FROM a.period_end) = 3
       AND NOT EXISTS (SELECT 1 FROM nidp.nse_financials_quarterly q
                        WHERE q.symbol       = a.symbol
                          AND q.period_end   = a.period_end
                          AND q.consolidated = a.consolidated
                          AND q.period_type  = 'quarterly');

    -- Fiscal-year rows whose last income-statement write came from a quarterly writer.
    SELECT count(*) INTO v_years_quarter_source
      FROM nidp.nse_financials_quarterly
     WHERE period_type = 'annual'
       AND source NOT IN ('screener_in_annual', 'yahoo_finance');

    RAISE NOTICE '145: % March fiscal-year rows have no March-quarter row yet; % fiscal-year '
                 'rows carry a quarterly writer''s source (may hold a quarter''s figures until '
                 'the Screener annual P&L is re-run)', v_mar_years_alone, v_years_quarter_source;
END $$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('145_financials_unique_by_period_type.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
