-- 168: fix NULL handling in the Smart Money shadow view.
--
-- BUG (found 2026-10-21 while measuring the overlay)
-- Postgres GREATEST/LEAST IGNORE NULL arguments rather than propagating them, unlike ordinary
-- arithmetic. So for a row with final_score IS NULL:
--     least(100, NULL + overlay) -> least(100, NULL) -> 100
--     greatest(0, 100)                               -> 100
-- i.e. a scoreless row came out with shadow_score = 100 and ranked #1. nidp.v3_stock_scores_daily
-- carries a `__coverage__` sentinel row with a NULL final_score, so the shadow ranking was topped
-- by a non-stock whose score we do not have — exactly the "missing data must never become a
-- confident number" failure this feature is supposed to prevent, reproduced in the view meant to
-- measure it.
--
-- Fix: clamp only when there is a score, and exclude non-symbol sentinel rows from the ranking.
--
-- Idempotent: safe to re-run.

DROP VIEW IF EXISTS nidp.v_smart_money_shadow_rank;

CREATE VIEW nidp.v_smart_money_shadow_rank AS
WITH k AS (SELECT 8.0::numeric AS max_overlay),
o AS (
    SELECT v.as_of_date,
           v.symbol,
           v.sector,
           v.final_score,
           s.accumulation_score,
           s.distribution_score,
           s.evidence_class,
           s.data_confidence,
           s.amcs_increasing,
           s.months_observed,
           s.single_amc_signal,
           CASE
             WHEN s.accumulation_score IS NULL OR s.distribution_score IS NULL THEN 0::numeric
             ELSE greatest(-k.max_overlay, least(k.max_overlay,
                    ((s.accumulation_score - s.distribution_score) / 100.0)
                    * CASE s.data_confidence WHEN 'high' THEN 1.0
                                             WHEN 'medium' THEN 0.6
                                             ELSE 0.25 END
                    * CASE WHEN s.single_amc_signal THEN 0.5 ELSE 1.0 END
                    * k.max_overlay))
           END AS smart_money_overlay
      FROM nidp.v3_stock_scores_daily v
      CROSS JOIN k
      LEFT JOIN nidp.smart_money_scores_daily s
             ON s.symbol = v.symbol AND s.as_of_date = v.as_of_date
     -- Sentinel/metadata rows carry no score and are not stocks; they must not be ranked.
     WHERE v.symbol NOT LIKE '\_\_%'
),
scored AS (
    SELECT o.*,
           -- Clamp only when a live score exists. A NULL score stays NULL and is ranked last.
           CASE WHEN o.final_score IS NULL THEN NULL
                ELSE greatest(0::numeric, least(100::numeric,
                              o.final_score + o.smart_money_overlay))
           END AS shadow_score_raw
      FROM o
)
SELECT s.as_of_date,
       s.symbol,
       s.sector,
       s.final_score                   AS live_score,
       s.accumulation_score            AS smart_money_score,
       s.distribution_score            AS smart_money_distribution,
       s.evidence_class,
       s.data_confidence,
       s.amcs_increasing,
       s.months_observed,
       s.single_amc_signal,
       round(s.smart_money_overlay, 2) AS smart_money_overlay,
       round(s.shadow_score_raw, 2)    AS shadow_score,
       rank() OVER (PARTITION BY s.as_of_date ORDER BY s.final_score      DESC NULLS LAST) AS live_rank,
       rank() OVER (PARTITION BY s.as_of_date ORDER BY s.shadow_score_raw DESC NULLS LAST) AS shadow_rank
  FROM scored s;

COMMENT ON VIEW nidp.v_smart_money_shadow_rank IS
  'Live vs shadow ranking with disclosed MF accumulation as a bounded (+/-8), confidence-scaled, '
  'concentration-damped additive overlay — the shape composer.py uses for event evidence. '
  'No disclosed evidence => overlay 0, live score unchanged. A NULL live score stays NULL '
  '(GREATEST/LEAST ignore NULLs, which previously ranked a scoreless sentinel row #1). '
  'Shadow only: nothing in production reads this.';
