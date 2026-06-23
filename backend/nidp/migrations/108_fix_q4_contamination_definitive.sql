-- 108_fix_q4_contamination_definitive.sql
-- Contamination round 2 — DEFINITIVE signature (no seasonal false-positives).
--
-- Migration 107 used a PAT heuristic (march_pat > 9-month sum) with a `<= 2x` guard, so it
-- (a) skipped strongly-contaminated rows where the March value far exceeds 9 months, and
-- (b) a broader 1.8x screen flagged 476 symbols of which only 15 are truly contaminated —
-- the rest are legitimately seasonal (sugar, real estate, etc.) where one quarter really is
-- much larger. Correcting those would CREATE errors.
--
-- The unambiguous signature: the Screener backfill writes both a quarterly and an annual row
-- per FY; a quarterly row whose PAT equals that FY's ANNUAL row (within 3%) is the annual
-- figure mislabelled as a quarter. true_Q4 = annual - (Q1+Q2+Q3). Self-gating (a corrected
-- row no longer equals the annual), so re-running is idempotent.

WITH ann AS (
  SELECT symbol, consolidated, period_end, pat_cr AS ann_pat,
         revenue_from_ops_cr AS ann_rev, eps_basic AS ann_eps
    FROM nidp.nse_financials_quarterly
   WHERE period_type ILIKE 'annual' AND pat_cr IS NOT NULL
),
contaminated AS (
  SELECT q.id, q.symbol, q.consolidated, q.period_end
    FROM nidp.nse_financials_quarterly q
    JOIN ann a ON a.symbol = q.symbol AND a.consolidated = q.consolidated
              AND a.period_end = q.period_end
   WHERE upper(q.period_type) = 'QUARTERLY' AND q.source LIKE 'screener%'
     AND q.pat_cr IS NOT NULL AND a.ann_pat <> 0
     AND abs(q.pat_cr - a.ann_pat) / abs(a.ann_pat) < 0.03   -- definitive: quarterly == annual
),
priors AS (
  SELECT c.id,
         sum(p.pat_cr) p_pat, sum(p.revenue_from_ops_cr) p_rev, sum(p.eps_basic) p_eps,
         count(*) nq
    FROM contaminated c
    JOIN nidp.nse_financials_quarterly p
      ON p.symbol = c.symbol AND p.consolidated = c.consolidated
     AND upper(p.period_type) = 'QUARTERLY'
     AND p.period_end IN (make_date(extract(year FROM c.period_end)::int - 1, 6, 30),
                          make_date(extract(year FROM c.period_end)::int - 1, 9, 30),
                          make_date(extract(year FROM c.period_end)::int - 1, 12, 31))
   GROUP BY c.id
)
UPDATE nidp.nse_financials_quarterly t SET
  pat_cr              = t.pat_cr - pr.p_pat,
  revenue_from_ops_cr = CASE WHEN t.revenue_from_ops_cr IS NOT NULL AND pr.p_rev IS NOT NULL
                             THEN t.revenue_from_ops_cr - pr.p_rev ELSE t.revenue_from_ops_cr END,
  eps_basic           = CASE WHEN t.eps_basic IS NOT NULL AND pr.p_eps IS NOT NULL
                             THEN t.eps_basic - pr.p_eps ELSE t.eps_basic END,
  period_start        = make_date(extract(year FROM t.period_end)::int, 1, 1)
FROM priors pr
WHERE t.id = pr.id AND pr.nq = 3 AND pr.p_pat IS NOT NULL;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('108_fix_q4_contamination_definitive.sql')
ON CONFLICT (filename) DO NOTHING;
