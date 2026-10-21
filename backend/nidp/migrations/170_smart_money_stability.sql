-- 170: repeatable stability monitoring for the Smart Money accumulation component (Gate B).
--
-- WHY
-- Promotion of the component into the production composite is gated on observing it across
-- several scoring dates, not on one snapshot. These views turn that from a hand-written query
-- into something a person or a job can read each month.
--
-- WHAT THE NUMBERS MEAN, AND THE TRAP IN THEM
-- The component uses a rolling N-month disclosure lookback (default 3), so two scoring dates one
-- month apart SHARE most of their input: at lookback 3 they share 2 of 3 months. A high
-- month-over-month correlation is therefore partly mechanical and must not be read as evidence of
-- a stable signal on its own. The honest test is correlation at a spacing >= lookback, where the
-- windows do not overlap at all. Measured 2026-10-22: 0.872 at 1 month (2/3 shared), 0.741 at 2,
-- 0.589 at 3 (NO overlap), 0.466 at 6. The signal genuinely persists.
--
-- The flip side, which matters for the product: a signal that retains ~65% of its top quintile
-- month to month carries little NEW information per month. That supports treating it as a
-- standing tilt (the bounded overlay in migration 168) rather than as a candidate generator.
--
-- Persistence is NOT predictive value. Nothing here says the signal forecasts returns; that is a
-- separate question and still blocked on published_at (migration 169) for honest point-in-time work.
--
-- Idempotent: safe to re-run.

-- Per scoring date: how much is covered and how confident.
CREATE OR REPLACE VIEW nidp.v_smart_money_coverage_by_date AS
SELECT as_of_date,
       count(*)                                                   AS scored_symbols,
       count(*) FILTER (WHERE data_confidence = 'high')            AS conf_high,
       count(*) FILTER (WHERE data_confidence = 'medium')          AS conf_medium,
       count(*) FILTER (WHERE data_confidence = 'low')             AS conf_low,
       count(*) FILTER (WHERE single_amc_signal)                   AS single_amc,
       round(avg(months_observed), 2)                              AS avg_months_observed,
       round(avg(coverage_pct), 1)                                 AS avg_subsignal_coverage_pct,
       max(latest_reporting_date)                                  AS latest_disclosure,
       min(lookback_months)                                        AS lookback_months,
       max(config_version)                                         AS config_version
  FROM nidp.smart_money_scores_daily
 GROUP BY as_of_date;

COMMENT ON VIEW nidp.v_smart_money_coverage_by_date IS
  'Per scoring date: Smart Money component coverage and confidence mix. Read alongside '
  'v_smart_money_stability before considering promotion.';

-- Correlation of the component against its own earlier values, at every spacing. The `overlapping`
-- flag is the thing to look at: FALSE rows are the ones that carry evidence.
CREATE OR REPLACE VIEW nidp.v_smart_money_stability AS
WITH dates AS (
    SELECT as_of_date, row_number() OVER (ORDER BY as_of_date) AS rn,
           min(lookback_months) AS lookback
      FROM nidp.smart_money_scores_daily
     GROUP BY as_of_date
),
pairs AS (
    SELECT a.as_of_date AS from_date, b.as_of_date AS to_date,
           (b.rn - a.rn) AS steps, a.lookback
      FROM dates a JOIN dates b ON b.rn > a.rn
)
SELECT p.from_date,
       p.to_date,
       p.steps                                                     AS steps_apart,
       -- TRUE when the two lookback windows share input, which inflates the correlation.
       (p.steps < p.lookback)                                      AS overlapping,
       count(*)                                                    AS common_symbols,
       round(corr(x.accumulation_score, y.accumulation_score)::numeric, 3) AS accumulation_corr,
       round(corr(x.distribution_score, y.distribution_score)::numeric, 3) AS distribution_corr
  FROM pairs p
  JOIN nidp.smart_money_scores_daily x ON x.as_of_date = p.from_date
  JOIN nidp.smart_money_scores_daily y ON y.as_of_date = p.to_date AND y.symbol = x.symbol
 GROUP BY p.from_date, p.to_date, p.steps, p.lookback
HAVING count(*) > 0;

COMMENT ON VIEW nidp.v_smart_money_stability IS
  'Self-correlation of the Smart Money component across scoring dates. `overlapping` = TRUE means '
  'the two lookback windows share disclosure months, so the correlation is partly mechanical — '
  'judge stability on the overlapping = FALSE rows only.';

-- Where this period's top quintile sits next period: an interpretable churn/turnover read.
CREATE OR REPLACE VIEW nidp.v_smart_money_quintile_churn AS
WITH q AS (
    SELECT as_of_date, symbol, accumulation_score,
           ntile(5) OVER (PARTITION BY as_of_date ORDER BY accumulation_score) AS quintile
      FROM nidp.smart_money_scores_daily
),
seq AS (SELECT DISTINCT as_of_date, row_number() OVER (ORDER BY as_of_date) rn
          FROM nidp.smart_money_scores_daily GROUP BY as_of_date),
step AS (SELECT a.as_of_date AS from_date, b.as_of_date AS to_date
           FROM seq a JOIN seq b ON b.rn = a.rn + 1)
SELECT s.from_date, s.to_date, a.quintile AS from_quintile, b.quintile AS to_quintile,
       count(*) AS symbols
  FROM step s
  JOIN q a ON a.as_of_date = s.from_date
  JOIN q b ON b.as_of_date = s.to_date AND b.symbol = a.symbol
 GROUP BY s.from_date, s.to_date, a.quintile, b.quintile;

COMMENT ON VIEW nidp.v_smart_money_quintile_churn IS
  'Quintile transition counts for the accumulation component between consecutive scoring dates. '
  'High retention in quintile 5 means a sticky signal — stable, but carrying little new '
  'information per period.';
