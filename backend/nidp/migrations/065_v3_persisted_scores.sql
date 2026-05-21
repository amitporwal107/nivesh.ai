-- 065_v3_persisted_scores.sql
--
-- Persisted V3 composite scores (Quality + Health) for MF schemes and stocks.
-- Computed nightly by services.v3_scores_engine and served via DaaS.
--
-- Scope: Quality + Health only. Exit/Add are portfolio-aware (need overlap,
-- tax_ratio, sector_gap) and stay on-the-fly downstream when a user's
-- portfolio is in context. Persisting universe-wide Exit/Add with neutral
-- defaults would mislead consumers into reading them as portfolio-specific.
--
-- Key choice (history): both tables keyed by (as_of_date, isin/symbol) so
-- consumers can pull time series, not just latest. ~14k schemes × 365d ≈ 5M
-- rows/yr — fits a regular table; promote to hypertable later if it grows.
--
-- Coverage tracking: every score row carries a coverage_pct (= 1 −
-- missing_weight / total_weight). This is the honesty signal — two funds
-- both showing "Quality: 75" may have very different effective bases, and
-- UI / ranking logic must gate on coverage_pct to compare fairly.
--
-- Idempotent. Safe to re-run.

SET search_path TO nidp, public;

-- ── MF V3 scores ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.v3_mf_scores_daily (
    as_of_date              DATE        NOT NULL,
    isin                    TEXT        NOT NULL,
    scheme_code             TEXT        NOT NULL,
    scheme_name             TEXT,
    fund_category           TEXT,                       -- classifier output: equity/debt/hybrid
    sub_category            TEXT,

    -- Quality
    quality_score           NUMERIC(6,2),               -- 0–100, NULL if no inputs
    quality_components      JSONB,                      -- {comp_name: 0-10 value}
    quality_missing         TEXT[],                     -- component names with NULL primitive
    quality_eff_weights     JSONB,                      -- renormalised weights (sum = 100)
    quality_coverage_pct    NUMERIC(5,2),               -- 1 − missing_w/total_w, 0–100

    -- Health
    health_score            NUMERIC(6,2),
    health_components       JSONB,
    health_missing          TEXT[],
    health_eff_weights      JSONB,
    health_coverage_pct     NUMERIC(5,2),

    -- Meta
    weight_profile          JSONB,                      -- raw weight table used
    engine_version          TEXT        NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (as_of_date, isin)
);

CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_isin_date
    ON nidp.v3_mf_scores_daily (isin, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_date
    ON nidp.v3_mf_scores_daily (as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_scheme_code_date
    ON nidp.v3_mf_scores_daily (scheme_code, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_quality_latest
    ON nidp.v3_mf_scores_daily (as_of_date, quality_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_health_latest
    ON nidp.v3_mf_scores_daily (as_of_date, health_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_v3_mf_scores_category
    ON nidp.v3_mf_scores_daily (fund_category, as_of_date DESC);

COMMENT ON TABLE  nidp.v3_mf_scores_daily IS
'V3 MF composite scores (Quality + Health) per (as_of_date, isin). '
'Populated by services.v3_scores_engine.mf. Served via /v1/mf/scores/*.';
COMMENT ON COLUMN nidp.v3_mf_scores_daily.quality_coverage_pct IS
'Fraction of intended quality weight backed by non-NULL primitives, 0-100. '
'Ranking must gate on this — two funds with the same displayed score may '
'have very different bases (see project_scoring_ux_defer_until_v3.md).';


-- ── Stock V3 scores ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.v3_stock_scores_daily (
    as_of_date              DATE        NOT NULL,
    symbol                  TEXT        NOT NULL,
    sector                  TEXT,
    industry                TEXT,
    market_cap_bucket       TEXT,

    -- Quality
    quality_score           NUMERIC(6,2),
    quality_components      JSONB,
    quality_coverage_pct    NUMERIC(5,2),

    -- Health
    health_score            NUMERIC(6,2),
    health_components       JSONB,
    health_coverage_pct     NUMERIC(5,2),

    -- Meta
    engine_version          TEXT        NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (as_of_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_sym_date
    ON nidp.v3_stock_scores_daily (symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_date
    ON nidp.v3_stock_scores_daily (as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_quality_latest
    ON nidp.v3_stock_scores_daily (as_of_date, quality_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_sector
    ON nidp.v3_stock_scores_daily (sector, as_of_date DESC);

COMMENT ON TABLE  nidp.v3_stock_scores_daily IS
'V3 Stock composite scores (Quality + Health) per (as_of_date, symbol). '
'Populated by services.v3_scores_engine.stock. Served via /v1/stocks/scores/*.';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.quality_coverage_pct IS
'Fraction of intended quality weight backed by non-NULL primitives, 0-100. '
'Use for ranking-eligibility gates downstream.';


-- ── Convenience latest-row views ────────────────────────────────────
CREATE OR REPLACE VIEW nidp.v_v3_mf_scores_latest AS
SELECT DISTINCT ON (isin) *
  FROM nidp.v3_mf_scores_daily
 ORDER BY isin, as_of_date DESC;

CREATE OR REPLACE VIEW nidp.v_v3_stock_scores_latest AS
SELECT DISTINCT ON (symbol) *
  FROM nidp.v3_stock_scores_daily
 ORDER BY symbol, as_of_date DESC;

COMMENT ON VIEW nidp.v_v3_mf_scores_latest IS
'Latest persisted V3 MF score per ISIN. DaaS /v1/mf/scores/{isin} reads this.';
COMMENT ON VIEW nidp.v_v3_stock_scores_latest IS
'Latest persisted V3 stock score per symbol. DaaS /v1/stocks/scores/{symbol} reads this.';


-- ── Audit ───────────────────────────────────────────────────────────
INSERT INTO nidp.schema_migrations (filename)
VALUES ('065_v3_persisted_scores.sql')
ON CONFLICT (filename) DO NOTHING;
