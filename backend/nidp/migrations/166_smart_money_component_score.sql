-- 166: Smart Money accumulation/distribution component score (SHADOW MODE) + rank comparison.
--
-- DECISION THIS ENCODES (2026-10-22)
-- Smart Money becomes an ADDITIONAL COMPONENT of the existing stock-selection engine, not a
-- second engine with its own ranking. This table holds the component only; it does not write
-- nidp.v3_stock_scores_daily and does not change any user-visible score. Promotion into the
-- production composite is a later, evidence-led step (see v_smart_money_shadow_rank below).
--
-- WHY THE COMPONENT IS DISCLOSED-EVIDENCE ONLY
-- The obvious design — "a pillar containing MF changes + FII/DII changes + deals + delivery/volume
-- proxies" — double-counts, because the live engine already consumes most of those:
--   * nidp/services/sector_scoring/governance.py already scores promoter_pct_change_qoq,
--     fii_pct_change_qoq, dii_pct_change_qoq and promoter_pledged_pct inside the FUNDAMENTAL pillar.
--   * delivery %, relative volume and volatility already sit in the TECHNICAL pillar's
--     volume/volatility sub-scores.
-- Re-scoring those here would give the same evidence two votes, which is exactly what the source
-- requirement forbids ("prevent duplicated or highly correlated features from receiving undue
-- weight"). So this component scores the evidence the engine does NOT already see: scheme-level
-- mutual-fund holdings CHANGE, from nidp.mf_holdings_deltas. That is evidence class A
-- (disclosed holdings), and it is kept structurally separate from class-C market proxies — the
-- proxy columns here are carried for display and divergence checks, never folded into the score.
--
-- MISSING DATA IS NULL, NEVER ZERO
-- Only ~33% of the scored universe currently has a validated MF holdings delta. A symbol with no
-- disclosed evidence gets NULL scores and evidence_class 'insufficient' — not 0, which would read
-- as "institutions are not accumulating" when the truth is "we cannot see". The consumer must
-- redistribute weight over present components, the way composer.py already does for cycle_position.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.smart_money_scores_daily (
    as_of_date      DATE        NOT NULL,   -- the scoring date (joins the rest of the engine)
    symbol          TEXT        NOT NULL,
    security_isin   TEXT,

    -- ── The component. 0-100, or NULL when there is no disclosed evidence. ──
    accumulation_score  NUMERIC(6,2),
    distribution_score  NUMERIC(6,2),       -- deliberately separate, never netted into one number

    -- ── Evidence classification (source doc §17) ──
    -- 'A' disclosed holdings change · 'B' disclosed transaction · 'D' composite · 'insufficient'
    evidence_class  TEXT        NOT NULL DEFAULT 'insufficient',

    -- ── Explainability: the raw inputs behind the score, so a card can say WHY ──
    schemes_increasing  INTEGER,
    schemes_reducing    INTEGER,
    amcs_increasing     INTEGER,            -- independent-holder count, not scheme count
    schemes_new         INTEGER,
    schemes_exited      INTEGER,
    net_shares_delta    NUMERIC,            -- share COUNT change, never value
    net_shares_pct      NUMERIC,            -- vs prior holding; NULL when prior was 0
    weight_delta_pp     NUMERIC,            -- portfolio-weight conviction, percentage points
    months_observed     INTEGER,            -- disclosure months with validated evidence
    months_accumulating INTEGER,            -- of those, months with net positive share change
    single_amc_signal   BOOLEAN,            -- concentrated: must not read as broad confirmation

    -- ── Component contributions (sub-signal -> {value, normalised, weight}) ──
    components      JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- ── Class-C proxies, carried for divergence display. NOT inputs to the score. ──
    proxy_delivery_pct_avg_20 NUMERIC,
    proxy_vol_z20             NUMERIC,

    -- ── Confidence / freshness (source doc §22) ──
    data_confidence   TEXT      NOT NULL DEFAULT 'insufficient',  -- high|medium|low|insufficient
    coverage_pct      NUMERIC(5,2),         -- share of sub-signals populated
    latest_reporting_date DATE,             -- newest disclosure month behind this row
    freshness_status  TEXT,                 -- fresh|ageing|stale, judged against monthly cadence
    lookback_months   INTEGER,

    source_references TEXT[],
    config_version    TEXT      NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (as_of_date, symbol),
    CONSTRAINT sms_evidence_class_chk CHECK (evidence_class IN ('A','B','D','insufficient')),
    CONSTRAINT sms_confidence_chk CHECK (data_confidence IN ('high','medium','low','insufficient')),
    CONSTRAINT sms_freshness_chk CHECK (freshness_status IS NULL
        OR freshness_status IN ('fresh','ageing','stale')),
    -- No disclosed evidence must never carry a directional score.
    CONSTRAINT sms_insufficient_has_no_score_chk CHECK (
        evidence_class <> 'insufficient'
        OR (accumulation_score IS NULL AND distribution_score IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_sms_date_acc ON nidp.smart_money_scores_daily (as_of_date, accumulation_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_sms_symbol   ON nidp.smart_money_scores_daily (symbol, as_of_date DESC);

COMMENT ON TABLE nidp.smart_money_scores_daily IS
  'Disclosed mutual-fund accumulation/distribution as an additional component of the existing '
  'stock-selection engine (shadow mode — does not write v3_stock_scores_daily). Scores class-A '
  'disclosed holdings change only; FII/DII QoQ and delivery/volume are excluded because '
  'governance.py and the technical pillar already score them. NULL means unseen, not zero.';

-- ── Shadow rank comparison ──────────────────────────────────────────────────────────────────
-- Answers the only question that should decide promotion: does adding this component change the
-- ranking, and where? It applies a CANDIDATE weight without touching production, re-normalising
-- over present components exactly as composer.py does — so a symbol with no disclosed evidence
-- keeps its existing score rather than being penalised for our blindness.
--
-- The candidate weight is deliberately a literal here, not config: this view exists to be read
-- and argued with, not to be depended on by code.
CREATE OR REPLACE VIEW nidp.v_smart_money_shadow_rank AS
WITH w AS (SELECT 0.20::numeric AS sm_weight)
SELECT v.as_of_date,
       v.symbol,
       v.sector,
       v.final_score                              AS live_score,
       s.accumulation_score                       AS smart_money_score,
       s.evidence_class,
       s.data_confidence,
       -- Shadow composite: blend only where disclosed evidence exists; otherwise keep live score.
       CASE WHEN s.accumulation_score IS NULL THEN v.final_score
            ELSE round(v.final_score * (1 - w.sm_weight) + s.accumulation_score * w.sm_weight, 2)
       END                                        AS shadow_score,
       rank() OVER (PARTITION BY v.as_of_date ORDER BY v.final_score DESC NULLS LAST) AS live_rank,
       rank() OVER (PARTITION BY v.as_of_date ORDER BY
            CASE WHEN s.accumulation_score IS NULL THEN v.final_score
                 ELSE v.final_score * (1 - w.sm_weight) + s.accumulation_score * w.sm_weight
            END DESC NULLS LAST)                  AS shadow_rank
  FROM nidp.v3_stock_scores_daily v
  CROSS JOIN w
  LEFT JOIN nidp.smart_money_scores_daily s
         ON s.symbol = v.symbol AND s.as_of_date = v.as_of_date;

COMMENT ON VIEW nidp.v_smart_money_shadow_rank IS
  'Live vs shadow ranking with the Smart Money component applied at a candidate 20% weight. '
  'Symbols without disclosed evidence keep their live score (no penalty for missing data). '
  'Read this before promoting the component into the production composite.';
