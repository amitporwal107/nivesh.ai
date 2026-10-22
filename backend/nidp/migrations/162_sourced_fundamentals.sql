-- 162_sourced_fundamentals.sql
-- ROE, ROCE, debt-to-equity, P/B and market cap from a named source, with the source recorded.
--
-- nidp.populate_stock_features_extended computes these five from our own filings, and on a
-- warehouse without share capital and net worth (staging, 2026-10-12: 0 of 2,469 rows) every
-- one is NULL. Phase 1 takes them from the Trendlyne MCP server instead
-- (services/trendlyne_fundamentals, pass "r1"). Phase 2 will compute them here again; it then
-- writes the same columns under its own source name, so nothing below names a provider except
-- the one seed row that ranks it.
--
--   nidp.stock_fundamental_values       one row per company, figure and source: the value as
--                                       supplied, the source's own field name, unit, basis,
--                                       dates, and sanity flags
--   nidp.fundamentals_source_priority   which source wins when two hold a company (lower first)
--   stock_features_daily.fundamentals_source / fundamentals_as_of
--                                       where that row's five figures came from, and as of when
--   nidp.market_cap_bucket(cr)          the cap thresholds the engine already uses, in one place
--   nidp.populate_stock_fundamentals_sourced(date)
--                                       copies the preferred source's figures into that day's
--                                       feature rows; the fundamental engine calls it right
--                                       after populate_stock_features_extended, which rewrites
--                                       the same columns on every run.

CREATE TABLE IF NOT EXISTS nidp.stock_fundamental_values (
    symbol             TEXT        NOT NULL,
    metric             TEXT        NOT NULL,   -- the stock_features_daily column it feeds
    source             TEXT        NOT NULL,   -- who supplied it, e.g. 'trendlyne_mcp'
    value              NUMERIC,                -- exactly as supplied; NULL = the source has no value (never 0)
    usable             BOOLEAN     NOT NULL DEFAULT TRUE,   -- FALSE = kept on record, not copied to the feature row
    flags              TEXT[]      NOT NULL DEFAULT '{}',   -- why, e.g. {negative_book_value}
    unit               TEXT        NOT NULL,   -- 'percent' | 'ratio' | 'inr_crore'
    provider_field     TEXT,                   -- the source's own name for the figure, as it answered: 'ROE Ann. %'
    provider_parameter TEXT,                   -- what was asked for: 'roea'
    period_basis       TEXT        NOT NULL,   -- 'annual' (latest reported fiscal year) | 'ttm' | 'point_in_time'
    period_end         DATE,                   -- the period the figure refers to, when the source states one
    consolidated       BOOLEAN,                -- the source's basis where it was verified; NULL = not stated
    as_of_date         DATE        NOT NULL,   -- the day the figures are as of (for price-based ones, the session whose close was used)
    provider_date      DATE,                   -- the date the source stamped on its reply
    fetched_at         TIMESTAMPTZ NOT NULL,
    built_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_run_id      UUID,
    PRIMARY KEY (symbol, metric, source),
    CONSTRAINT stock_fundamental_values_metric_chk
        CHECK (metric IN ('roe_pct', 'roce_pct', 'debt_to_equity', 'pb', 'market_cap_cr')),
    CONSTRAINT stock_fundamental_values_unit_chk
        CHECK (unit IN ('percent', 'ratio', 'inr_crore')),
    CONSTRAINT stock_fundamental_values_basis_chk
        CHECK (period_basis IN ('annual', 'ttm', 'point_in_time')),
    -- Whatever writes here, a usable figure fits its feature column and a usable market cap is positive.
    CONSTRAINT stock_fundamental_values_usable_chk
        CHECK (NOT usable OR value IS NULL
               OR (metric =  'market_cap_cr' AND value > 0)
               OR (metric <> 'market_cap_cr' AND abs(value) < 100000))
);

COMMENT ON TABLE nidp.stock_fundamental_values IS
    'ROE, ROCE, debt-to-equity, P/B and market cap as supplied by a named source (source column), one row per company, figure and source. Read by nidp.populate_stock_fundamentals_sourced.';

CREATE TABLE IF NOT EXISTS nidp.fundamentals_source_priority (
    source    TEXT PRIMARY KEY,
    priority  INTEGER NOT NULL,                -- lower wins when two sources hold the same company
    note      TEXT
);

INSERT INTO nidp.fundamentals_source_priority (source, priority, note)
VALUES ('trendlyne_mcp', 10, 'Phase 1: ratios as computed by the Trendlyne MCP server')
ON CONFLICT (source) DO NOTHING;

ALTER TABLE nidp.stock_features_daily
    ADD COLUMN IF NOT EXISTS fundamentals_source TEXT,
    ADD COLUMN IF NOT EXISTS fundamentals_as_of  DATE;

COMMENT ON COLUMN nidp.stock_features_daily.fundamentals_source IS
    'Where this row''s roe_pct, roce_pct, debt_to_equity, pb, market_cap_cr and market_cap_bucket came from: a source in nidp.stock_fundamental_values, or nidp_computed for the engine''s own calculation. NULL when all are empty.';
COMMENT ON COLUMN nidp.stock_features_daily.fundamentals_as_of IS
    'The day those figures are as of. For a sourced row, market cap and P/B use that day''s close, not this row''s.';

-- The thresholds populate_stock_features_extended applies inline (rupees crore).
CREATE OR REPLACE FUNCTION nidp.market_cap_bucket(p_market_cap_cr numeric)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
    SELECT CASE
        WHEN p_market_cap_cr IS NULL OR p_market_cap_cr <= 0 THEN NULL
        WHEN p_market_cap_cr >= 50000 THEN 'LARGE_CAP'
        WHEN p_market_cap_cr >= 10000 THEN 'MID_CAP'
        WHEN p_market_cap_cr >=  1000 THEN 'SMALL_CAP'
        ELSE 'MICRO_CAP' END
$function$;

CREATE OR REPLACE FUNCTION nidp.populate_stock_fundamentals_sourced(p_target_date date)
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
DECLARE v_rows INTEGER;
BEGIN
    -- 1. Companies for which a ranked source holds figures dated on or before the target day.
    --    All five columns are taken from that one source, so a row never mixes two sources;
    --    a figure the source lacks, or one marked unusable, is NULL. The values are copied as
    --    supplied: market cap and P/B are NOT re-scaled to the row's own close, which is why
    --    the row carries fundamentals_as_of. A snapshot dated after the target day is never
    --    used, so rebuilding an old day cannot pull in later figures.
    WITH chosen AS (
        SELECT DISTINCT ON (v.symbol) v.symbol, v.source
          FROM nidp.stock_fundamental_values v
          JOIN nidp.fundamentals_source_priority p ON p.source = v.source
         WHERE v.as_of_date <= p_target_date
         ORDER BY v.symbol, p.priority, v.source
    ), snap AS (
        SELECT v.symbol, v.source, MAX(v.as_of_date) AS as_of,
               MAX(v.value) FILTER (WHERE v.metric = 'roe_pct'        AND v.usable) AS roe_pct,
               MAX(v.value) FILTER (WHERE v.metric = 'roce_pct'       AND v.usable) AS roce_pct,
               MAX(v.value) FILTER (WHERE v.metric = 'debt_to_equity' AND v.usable) AS debt_to_equity,
               MAX(v.value) FILTER (WHERE v.metric = 'pb'             AND v.usable) AS pb,
               MAX(v.value) FILTER (WHERE v.metric = 'market_cap_cr'  AND v.usable) AS market_cap_cr
          FROM nidp.stock_fundamental_values v
          JOIN chosen c ON c.symbol = v.symbol AND c.source = v.source
         WHERE v.as_of_date <= p_target_date
         GROUP BY v.symbol, v.source
    )
    UPDATE nidp.stock_features_daily f
       SET roe_pct             = s.roe_pct,
           roce_pct            = s.roce_pct,
           debt_to_equity      = s.debt_to_equity,
           pb                  = s.pb,
           market_cap_cr       = s.market_cap_cr,
           market_cap_bucket   = nidp.market_cap_bucket(s.market_cap_cr),
           fundamentals_source = s.source,
           fundamentals_as_of  = s.as_of
      FROM snap s
     WHERE f.symbol = s.symbol AND f.as_of_date = p_target_date;
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    -- 2. Every other row of the day keeps what populate_stock_features_extended computed and
    --    is labelled as such, so a label left by an earlier run can never outlive its values.
    UPDATE nidp.stock_features_daily f
       SET fundamentals_source = CASE WHEN COALESCE(f.roe_pct, f.roce_pct, f.debt_to_equity, f.pb, f.market_cap_cr) IS NOT NULL
                                      THEN 'nidp_computed' END,
           fundamentals_as_of  = CASE WHEN COALESCE(f.roe_pct, f.roce_pct, f.debt_to_equity, f.pb, f.market_cap_cr) IS NOT NULL
                                      THEN p_target_date END
     WHERE f.as_of_date = p_target_date
       AND NOT EXISTS (SELECT 1
                         FROM nidp.stock_fundamental_values v
                         JOIN nidp.fundamentals_source_priority p ON p.source = v.source
                        WHERE v.symbol = f.symbol AND v.as_of_date <= p_target_date);

    RETURN v_rows;
END;
$function$;
