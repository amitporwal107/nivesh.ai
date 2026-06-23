-- 107_fix_screener_q4_pat_contamination.sql
-- Data-correctness fix (equity fundamentals).
--
-- Migration 101 corrected Q4-annual contamination (a March "quarterly" row holding the
-- full-year figure) but gated on revenue_from_ops_cr, which is NULL for banks/NBFCs — so
-- it missed them. The SD-05/07/08 Screener backfills then re-introduced contaminated March
-- rows. Symptom: HDFCBANK TTM PAT = 137,364 cr (~2x reality) because its March row held the
-- annual 79,219 cr instead of the ~19-21k quarterly figure.
--
-- This correction uses PAT as the contamination signature (present for every company,
-- including banks): a true Q4 can never exceed the sum of the same FY's first three
-- quarters, so march_pat > prior3_pat is the unambiguous "this row holds the annual figure"
-- tell. true_Q4 = annual - (Q1+Q2+Q3). Scoped to Screener sources; the signature self-gates
-- (an already-corrected row has march_pat < prior3_pat and is skipped), so re-running is
-- idempotent. The `<= 2 * prior3` guard skips ambiguous/strongly-seasonal cases (matches 101).

WITH p3 AS (
  SELECT m.id,
    sum(p.revenue_from_ops_cr) rev, sum(p.pat_cr) pat,
    sum(p.eps_basic) epsb, sum(p.eps_diluted) epsd,
    count(*) nq
  FROM nidp.nse_financials_quarterly m
  JOIN nidp.nse_financials_quarterly p
    ON p.symbol = m.symbol AND p.consolidated = m.consolidated
   AND upper(p.period_type) = 'QUARTERLY'
   AND p.period_end IN (make_date(extract(year FROM m.period_end)::int - 1, 6, 30),
                        make_date(extract(year FROM m.period_end)::int - 1, 9, 30),
                        make_date(extract(year FROM m.period_end)::int - 1, 12, 31))
  WHERE upper(m.period_type) = 'QUARTERLY'
    AND extract(month FROM m.period_end) = 3
    AND m.source LIKE 'screener%'
  GROUP BY m.id
)
UPDATE nidp.nse_financials_quarterly t SET
  pat_cr              = t.pat_cr - p3.pat,
  revenue_from_ops_cr = CASE WHEN t.revenue_from_ops_cr IS NOT NULL AND p3.rev  IS NOT NULL
                             THEN t.revenue_from_ops_cr - p3.rev  ELSE t.revenue_from_ops_cr END,
  eps_basic           = CASE WHEN t.eps_basic   IS NOT NULL AND p3.epsb IS NOT NULL
                             THEN t.eps_basic   - p3.epsb ELSE t.eps_basic   END,
  eps_diluted         = CASE WHEN t.eps_diluted IS NOT NULL AND p3.epsd IS NOT NULL
                             THEN t.eps_diluted - p3.epsd ELSE t.eps_diluted END,
  period_start        = make_date(extract(year FROM t.period_end)::int, 1, 1)
FROM p3
WHERE t.id = p3.id AND p3.nq = 3
  AND t.pat_cr IS NOT NULL AND p3.pat IS NOT NULL
  AND t.pat_cr > p3.pat            -- annual signature: Q4 can't exceed 9-month earnings
  AND t.pat_cr <= 2 * p3.pat;      -- skip ambiguous / strongly seasonal

INSERT INTO nidp.schema_migrations (filename)
VALUES ('107_fix_screener_q4_pat_contamination.sql')
ON CONFLICT (filename) DO NOTHING;
