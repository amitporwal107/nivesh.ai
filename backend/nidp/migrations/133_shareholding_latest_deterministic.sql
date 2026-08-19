-- 133_shareholding_latest_deterministic.sql
--
-- Make nidp.v_shareholding_latest return EXACTLY ONE ROW PER SYMBOL.
--
-- Measured on nidp_staging 2026-08-19, before this migration:
--
--     view_rows | symbols | surplus
--     ----------+---------+---------
--          3342 |    2325 |    1017      -- 318 symbols x4, 63 symbols x2
--
-- The view is documented as "latest quarter per symbol" and every consumer treats
-- it that way, so anything JOINing it silently multiplies rows. Two independent
-- defects produce that, and both are fixed here.
--
-- DEFECT 1 — the `prev` CTE fans out.
--   It joins shareholding_pattern to itself on (symbol, period_end), which is NOT
--   unique: the table's PK is (symbol, period_end, SOURCE). A symbol carrying both
--   an NSE_SHP and a screener_in row at the current quarter and at the previous one
--   produces 2x2 = 4 `prev` rows, and the final LEFT JOIN emits all four.
--
-- DEFECT 2 — `rn = 1` is a coin flip, and the sources disagree.
--   row_number() PARTITION BY symbol ORDER BY period_end DESC has no tiebreak, so
--   when two sources share the latest quarter Postgres picks one arbitrarily. That
--   is not cosmetic: of the 329 symbols with both sources at their latest quarter,
--   promoter_pct differs on 44, fii_pct on 80 and dii_pct on 123. The platform was
--   reporting whichever row the plan happened to emit first.
--
-- WHY NSE_SHP WINS. Not by preference — by measurement. Every shareholding row must
-- satisfy promoter_pct + public_pct = 100 (public_pct is the all-non-promoter
-- aggregate). On staging:
--
--     source      | rows_checked | violations | pct
--     ------------+--------------+------------+------
--     NSE_SHP     |         4482 |         20 |  0.4
--     screener_in |         4236 |       2756 | 65.1
--
-- screener_in also carries 9 rows stamped to non-quarter-end dates (2026-07-31,
-- 2026-05-31, 2026-04-30). NSE_SHP carries none. The exchange XBRL filing is the
-- golden source; screener_in is kept only because it is the ONLY source of
-- pre-2026-03-31 history (NSE_SHP starts at 2026-03-31), and it is now used solely
-- as a fallback where NSE has filed nothing.
--
-- NOTHING IS DELETED. This changes which row is READ, not which rows exist. The
-- DQ tripwire on the table (compound_unique(symbol, period_end), deliberately
-- tighter than the PK) stays, because the duplicates are still worth surfacing.
--
-- Rollback: re-run 025_nidp_shareholding_pattern.sql, which holds the previous
-- definition verbatim.

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_shareholding_latest AS
WITH deduped AS (
    -- Exactly one row per (symbol, period_end). DISTINCT ON keeps the first row of
    -- each group under the ORDER BY, so the precedence below is the whole decision.
    SELECT DISTINCT ON (s.symbol, s.period_end) s.*
      FROM nidp.shareholding_pattern s
     ORDER BY s.symbol, s.period_end,
              CASE s.source
                  WHEN 'NSE_SHP'      THEN 0   -- exchange XBRL filing; 0.4% violation rate
                  WHEN 'NSE_SAST_CSV' THEN 1   -- exchange SAST file; promoter + pledge only
                  WHEN 'screener_in'  THEN 2   -- scraped; 65.1% violation rate, history only
                  ELSE 3
              END,
              -- Final tiebreak so a source added later is still deterministic on
              -- day one, rather than silently reintroducing the coin flip.
              s.source
), ranked AS (
    SELECT d.*,
           ROW_NUMBER() OVER (PARTITION BY d.symbol ORDER BY d.period_end DESC) AS rn
      FROM deduped d
), prev AS (
    -- Sourced from `deduped`, not the raw table: this is what removes the fan-out.
    SELECT cur.symbol, cur.period_end,
           cur.promoter_pct AS cur_promoter,  prv.promoter_pct AS prv_promoter,
           cur.fii_pct      AS cur_fii,       prv.fii_pct      AS prv_fii,
           cur.dii_pct      AS cur_dii,       prv.dii_pct      AS prv_dii,
           cur.mf_pct       AS cur_mf,        prv.mf_pct       AS prv_mf,
           cur.promoter_pledged_to_total_pct AS cur_pledge,
           prv.promoter_pledged_to_total_pct AS prv_pledge
      FROM deduped cur
      LEFT JOIN deduped prv
        ON prv.symbol = cur.symbol
       AND prv.period_end = (
           SELECT MAX(d2.period_end) FROM deduped d2
            WHERE d2.symbol = cur.symbol AND d2.period_end < cur.period_end
       )
)
SELECT
    r.symbol,
    r.period_end,
    r.promoter_pct,
    r.promoter_pledged_pct,
    r.promoter_pledged_to_total_pct,
    r.fii_pct,
    r.dii_pct,
    r.mf_pct,
    r.insurance_pct,
    r.public_pct,
    r.individual_pct,
    ROUND((p.cur_promoter - p.prv_promoter)::numeric, 4) AS promoter_pct_change_qoq,
    ROUND((p.cur_fii      - p.prv_fii)::numeric, 4)      AS fii_pct_change_qoq,
    ROUND((p.cur_dii      - p.prv_dii)::numeric, 4)      AS dii_pct_change_qoq,
    ROUND((p.cur_mf       - p.prv_mf)::numeric, 4)       AS mf_pct_change_qoq,
    ROUND((p.cur_pledge   - p.prv_pledge)::numeric, 4)   AS pledge_pct_change_qoq,
    r.broadcast_at,
    r.source_run_id
  FROM ranked r
  LEFT JOIN prev p
    ON p.symbol = r.symbol AND p.period_end = r.period_end
 WHERE r.rn = 1;

COMMENT ON VIEW nidp.v_shareholding_latest IS
  'Latest quarter per symbol + QoQ deltas. Exactly one row per symbol: source '
  'precedence NSE_SHP > NSE_SAST_CSV > screener_in resolves same-quarter duplicates '
  '(migration 133). Consumers may JOIN this without deduplicating.';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('133_shareholding_latest_deterministic.sql')
    ON CONFLICT (filename) DO NOTHING;
