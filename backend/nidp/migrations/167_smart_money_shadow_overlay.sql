-- 167: replace the Smart Money shadow blend with a bounded, confidence-scaled OVERLAY.
--
-- WHY THE FIRST SHADOW DESIGN WAS WRONG (measured 2026-10-21 on staging)
-- Migration 166's view blended the component as a 20%-weighted pillar:
--     shadow = live * 0.8 + smart_money * 0.2
-- Run against real data that moved the ranking by an average of 97.5 places (max 962). The cause
-- is a scale mismatch, not signal:
--     * nidp.v3_stock_scores_daily.final_score has stddev 9.53 — a compressed distribution
--       (min 21.9, avg 45.2, max 80.3).
--     * accumulation_score is a percentile rank, i.e. uniform 0-100, stddev ~29.
-- So at 20% weight the new component contributed ~5.8 points of spread against the existing
-- engine's ~7.6 — a single component with nearly the ranking authority of all the others
-- combined. Worse, the biggest demotions were all `data_confidence = 'low'` names (one AMC, one
-- month of evidence) dropping ~900 places: thin evidence acting as strong negative evidence,
-- which the source requirement explicitly forbids ("do not let missing institutional data
-- automatically count as negative evidence").
--
-- THE FIX: the same shape the engine already uses for events.
-- composer.py applies event evidence as an additive, bounded overlay —
-- `final = clamp(raw + event_overlay - red_flag_penalty)` with `overlay = max(-30, min(15, ...))`.
-- Disclosed-holdings evidence is the same kind of thing: a tilt on a quality score, not a quality
-- score of its own. So the overlay here is:
--
--     direction = (accumulation_score - distribution_score) / 100      -- about -1..+1
--     overlay   = clamp(direction * confidence_factor * concentration_factor * 8, -8, +8)
--
--   confidence_factor   high 1.0 · medium 0.6 · low 0.25   — thin evidence barely moves anything
--   concentration_factor 0.5 when single_amc_signal         — one fund house is not confirmation
--   +/-8 points          comparable to, and smaller than, the event overlay's range
--
-- A symbol with no disclosed evidence gets overlay 0 and keeps its live score exactly. Missing
-- evidence is neutral, never negative.
--
-- Still shadow mode: this view writes nothing and no production code reads it. It exists to be
-- argued with before the overlay is moved into composer.py.
--
-- Idempotent: safe to re-run.

-- Dropped rather than replaced: the column list changes, and CREATE OR REPLACE VIEW cannot
-- rename or reorder columns. Safe because this view is shadow-only — no code reads it.
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
)
SELECT o.as_of_date,
       o.symbol,
       o.sector,
       o.final_score                      AS live_score,
       o.accumulation_score               AS smart_money_score,
       o.distribution_score               AS smart_money_distribution,
       o.evidence_class,
       o.data_confidence,
       o.amcs_increasing,
       o.months_observed,
       o.single_amc_signal,
       round(o.smart_money_overlay, 2)    AS smart_money_overlay,
       -- Clamped to the engine's own 0-100 range, as composer.py does.
       round(greatest(0, least(100, o.final_score + o.smart_money_overlay)), 2) AS shadow_score,
       rank() OVER (PARTITION BY o.as_of_date ORDER BY o.final_score DESC NULLS LAST) AS live_rank,
       rank() OVER (PARTITION BY o.as_of_date
                    ORDER BY greatest(0, least(100, o.final_score + o.smart_money_overlay))
                    DESC NULLS LAST) AS shadow_rank
  FROM o;

COMMENT ON VIEW nidp.v_smart_money_shadow_rank IS
  'Live vs shadow ranking with disclosed MF accumulation applied as a bounded (+/-8), '
  'confidence-scaled, concentration-damped ADDITIVE overlay — the same shape composer.py uses for '
  'event evidence. Replaced a 20% weighted blend that moved ranks by ~97 places on average purely '
  'through a scale mismatch (final_score stddev 9.5 vs a uniform percentile). No disclosed '
  'evidence => overlay 0 and the live score is unchanged.';
