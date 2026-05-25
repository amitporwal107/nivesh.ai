-- 064_dq_universal_rules.sql
--
-- Closes the "feed wrote 0 rows but DQ said PASSED" loophole that hid
-- mf_holdings_monthly + mf_scheme_disclosure_snapshot being empty for weeks
-- (and snapshot_builder for 3 days, mf_derived for the SQL GroupingError, etc.).
--
-- Two changes:
--
--   1. Adds rule_kind TEXT NOT NULL DEFAULT 'per_row' to
--      dq.expectations_active. Two values today:
--        per_row    — existing behavior. Expression evaluated against
--                     every row in the table for the target_date,
--                     a row is BAD if expression is FALSE.
--        aggregate  — new. Expression IS a full boolean SQL fragment
--                     against the table (subquery / sum / count check).
--                     The whole rule passes iff the expression is TRUE.
--                     This is the only way to express "did this feed
--                     write at least N rows today?" — a table-level
--                     assertion that per-row mode cannot represent.
--
--   2. Inserts UNIVERSAL aggregate rules per catalogued nidp table:
--        - freshness_<table>       max(date_col) is recent enough
--        - min_rows_<table>        count(*) on latest date >= historical p10 × 0.7
--      For tables that are currently empty (mf_holdings_monthly,
--      mf_scheme_disclosure_snapshot) the floor is set to 1 so the
--      gate fails until those scrapers are fixed.
--
-- Why this matters:
--   Today the DQ system has rules on 3 tables (fii_dii_flows, mf_nav_daily,
--   prices_eod). When a brand-new ingester silently breaks — schema drift,
--   transformation drop, AMC URL change — there are no rules to catch it.
--   This migration installs the universal "the feed actually produced data"
--   floor on every catalogued table. From here, the AI Expectation author
--   can build on top with business-rule expectations (which it should be
--   re-run against these tables now that the deterministic floor exists).
--
-- Idempotent. Safe to re-run.

SET search_path TO dq, nidp, public;

-- ── 1. Schema change ────────────────────────────────────────────────
ALTER TABLE dq.expectations_active
    ADD COLUMN IF NOT EXISTS rule_kind TEXT NOT NULL DEFAULT 'per_row';

ALTER TABLE dq.expectations_active
    DROP CONSTRAINT IF EXISTS expectations_active_rule_kind_check;
ALTER TABLE dq.expectations_active
    ADD  CONSTRAINT expectations_active_rule_kind_check
         CHECK (rule_kind IN ('per_row', 'aggregate'));

COMMENT ON COLUMN dq.expectations_active.rule_kind IS
'per_row = expression evaluated row-by-row (default, legacy); '
'aggregate = expression is a full boolean SQL fragment evaluated once per (table, target_date). '
'Aggregate rules are the only way to express table-level assertions like row-count floors and freshness.';


-- ── 2. Universal rules per table ────────────────────────────────────
-- Pattern: one freshness + one min_rows aggregate rule per catalogued
-- table. Floors derived from 30-day p10 (computed 2026-05-21) with a
-- 30% softening margin so we don't false-positive on the natural
-- variance of bhavcopy etc.
--
-- Helper macro: this WITH-VALUES block is the source of truth for
-- (dataset_name, date_column, freshness_lag_days, min_rows_for_latest_date).
WITH universal_rules (dataset_name, date_col, lag_days, min_rows, cadence) AS (
    VALUES
        -- Daily NSE market data (allow 2 weekend days of lag)
        ('prices_eod',                   'as_of_date',   2,    2300, 'daily'),
        ('prices_eod_adjusted',          'as_of_date',   2,    2300, 'daily'),
        ('delivery_data',                'as_of_date',   2,    2200, 'daily'),
        ('index_eod',                    'as_of_date',   2,     140, 'daily'),
        ('fno_bhavcopy',                 'as_of_date',   2,   27000, 'daily'),
        ('fii_dii_flows',                'as_of_date',   2,       2, 'daily'),
        ('bulk_deals',                   'as_of_date',   2,       1, 'daily'),
        ('block_deals',                  'as_of_date',   2,       1, 'daily'),
        ('rbi_yields',                   'as_of_date',   3,       4, 'daily'),
        ('fred_macro',                   'as_of_date',   3,       6, 'daily'),
        -- Forward-dated calendar (ex_date is in future)
        ('corporate_actions',            'ex_date',     90,       1, 'event'),
        ('index_constituents',           'as_of_date',  35,     100, 'monthly'),
        -- Quarterly fundamentals (3 months tolerance)
        ('shareholding_pattern',         'period_end',  95,     200, 'quarterly'),
        ('nse_financials_quarterly',     'period_end',  95,     200, 'quarterly'),
        -- Corporate announcements (stream — should land daily)
        ('corporate_announcements',      'filed_at',     2,      50, 'high-freq'),
        -- Mutual funds
        ('mf_nav_daily',                 'nav_date',     2,    8000, 'daily'),
        -- ── KNOWN-EMPTY: floor=1 forces the gate to fail until upstream
        --    scrapers are fixed. Today these write 0 rows even though
        --    job_log reports PARTIAL with validation=PASSED.
        ('mf_holdings_monthly',          'as_of_month', 35,       1, 'monthly'),
        ('mf_scheme_disclosure_snapshot','snapshot_date', 35,     1, 'monthly'),
        ('mf_scheme_events',             'event_date',  60,       1, 'event'),
        ('mf_amfi_circulars',            'published_at', 7,       1, 'daily'),
        -- Derived (computed by engines, should keep pace with bhavcopy)
        ('stock_features_daily',         'as_of_date',   2,    2200, 'daily'),
        ('stock_daily_snapshot',         'as_of_date',   2,    2800, 'daily'),
        ('market_daily_snapshot',        'as_of_date',   2,       1, 'daily'),
        ('mf_derived_analytics',         'as_of_date',   3,    8000, 'daily')
)

-- Freshness rules
INSERT INTO dq.expectations_active (
    dataset_name, name, description, expression, severity, source,
    active, rule_kind, rationale, business_impact, promoted_by, promoted_at
)
SELECT
    dataset_name,
    'freshness_'           || dataset_name             AS name,
    'Latest '              || date_col                 ||
        ' must be within ' || lag_days::text || ' days of today'  AS description,
    '(SELECT max('         || quote_ident(date_col)    ||
        ') >= CURRENT_DATE - INTERVAL '''             ||
        lag_days::text     || ' days'' FROM nidp.'    ||
        quote_ident(dataset_name) || ')'                              AS expression,
    'CRITICAL'             AS severity,
    'promoted'             AS source,
    TRUE                   AS active,
    'aggregate'            AS rule_kind,
    'Universal freshness floor from migration 064. Lag tuned to cadence: '
        || cadence || '. Without this rule a feed that silently stops '
        || 'producing data has no DQ signal.'        AS rationale,
    'Stale '||dataset_name||' poisons every downstream score that reads it. '
        'V3 scoring, snapshot_builder, intelligence_layer all gate on this.'
                                                     AS business_impact,
    'migration_064',
    NOW()
FROM universal_rules
ON CONFLICT (dataset_name, name) DO NOTHING;

-- Minimum-row-count rules (per latest target_date)
WITH universal_rules (dataset_name, date_col, lag_days, min_rows, cadence) AS (
    VALUES
        ('prices_eod',                   'as_of_date',   2,    2300, 'daily'),
        ('prices_eod_adjusted',          'as_of_date',   2,    2300, 'daily'),
        ('delivery_data',                'as_of_date',   2,    2200, 'daily'),
        ('index_eod',                    'as_of_date',   2,     140, 'daily'),
        ('fno_bhavcopy',                 'as_of_date',   2,   27000, 'daily'),
        ('fii_dii_flows',                'as_of_date',   2,       2, 'daily'),
        ('bulk_deals',                   'as_of_date',   2,       1, 'daily'),
        ('block_deals',                  'as_of_date',   2,       1, 'daily'),
        ('rbi_yields',                   'as_of_date',   3,       4, 'daily'),
        ('fred_macro',                   'as_of_date',   3,       6, 'daily'),
        ('corporate_actions',            'ex_date',     90,       1, 'event'),
        ('index_constituents',           'as_of_date',  35,     100, 'monthly'),
        ('shareholding_pattern',         'period_end',  95,     200, 'quarterly'),
        ('nse_financials_quarterly',     'period_end',  95,     200, 'quarterly'),
        ('corporate_announcements',      'filed_at',     2,      50, 'high-freq'),
        ('mf_nav_daily',                 'nav_date',     2,    8000, 'daily'),
        ('mf_holdings_monthly',          'as_of_month', 35,       1, 'monthly'),
        ('mf_scheme_disclosure_snapshot','snapshot_date', 35,     1, 'monthly'),
        ('mf_scheme_events',             'event_date',  60,       1, 'event'),
        ('mf_amfi_circulars',            'published_at', 7,       1, 'daily'),
        ('stock_features_daily',         'as_of_date',   2,    2200, 'daily'),
        ('stock_daily_snapshot',         'as_of_date',   2,    2800, 'daily'),
        ('market_daily_snapshot',        'as_of_date',   2,       1, 'daily'),
        ('mf_derived_analytics',         'as_of_date',   3,    8000, 'daily')
)
INSERT INTO dq.expectations_active (
    dataset_name, name, description, expression, severity, source,
    active, rule_kind, rationale, business_impact, promoted_by, promoted_at
)
SELECT
    dataset_name,
    'min_rows_latest_'     || dataset_name              AS name,
    'On the latest available ' || date_col ||
        ', the table must hold at least ' || min_rows::text || ' rows' AS description,
    -- Aggregate expression: counts rows on the latest available date in the
    -- table. Comparing to "today" would false-fire on weekends; we compare
    -- to the table's own max(date) which respects holidays naturally.
    '(SELECT count(*) >= ' || min_rows::text || ' FROM nidp.' ||
        quote_ident(dataset_name) || ' WHERE ' || quote_ident(date_col) ||
        ' = (SELECT max(' || quote_ident(date_col) || ') FROM nidp.' ||
        quote_ident(dataset_name) || '))'              AS expression,
    'CRITICAL'             AS severity,
    'promoted'             AS source,
    TRUE                   AS active,
    'aggregate'            AS rule_kind,
    'Universal row-count floor from migration 064. Min rows derived from '
        || '30-day p10 × 0.7 (or 1 for currently-empty tables to force a '
        || 'finding until the upstream scraper is fixed).'  AS rationale,
    'Silent transformation drops (schema drift, AMC URL change, etc.) '
        || 'produce a feed that runs to "PARTIAL" without writing data. '
        || 'This rule catches exactly that scenario.'        AS business_impact,
    'migration_064',
    NOW()
FROM universal_rules
ON CONFLICT (dataset_name, name) DO NOTHING;


-- ── 3. Audit ────────────────────────────────────────────────────────
INSERT INTO nidp.schema_migrations (filename)
VALUES ('064_dq_universal_rules.sql')
ON CONFLICT (filename) DO NOTHING;

COMMENT ON CONSTRAINT expectations_active_rule_kind_check ON dq.expectations_active IS
'Added by migration 064. Aggregate-kind rules let us express table-level '
'assertions (freshness, row count) that the per-row evaluator cannot represent.';
