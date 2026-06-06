-- 091_mf_rolling_returns.sql
--
-- Gap 4: Rolling return distribution table.
--
-- Stores summary statistics for rolling CAGR windows of 12, 36, and 60 months.
-- Computed by mf_analytics_engine after each daily run via
-- calculator.rolling_returns_distribution().
--
-- Why summary stats (not raw array)?
--   14k schemes × 3 windows × up to ~1000 rolling points = 42M values if stored raw.
--   Nine percentile columns + positive_pct capture the full distribution shape at
--   ~90 bytes per row, vs ~40 KB per row for raw JSONB.
--
-- positive_pct is a cleaner consistency metric than consistency_score:
--   consistency_score = fraction of 12m windows beating category avg  (relative)
--   positive_pct      = fraction of N-month windows with positive CAGR (absolute)
-- Both are useful; positive_pct is the standard metric cited in fund factsheets.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.mf_rolling_returns (
    scheme_code     TEXT        NOT NULL,
    as_of_date      DATE        NOT NULL,
    window_months   INTEGER     NOT NULL,   -- 12 | 36 | 60

    obs_count       INTEGER,                -- rolling windows computed
    positive_pct    NUMERIC(5,2),           -- % windows with positive CAGR

    -- Distribution (annualised CAGR, %)
    ret_min         NUMERIC(10,4),
    ret_p10         NUMERIC(10,4),
    ret_p25         NUMERIC(10,4),
    ret_p50         NUMERIC(10,4),          -- median
    ret_p75         NUMERIC(10,4),
    ret_p90         NUMERIC(10,4),
    ret_max         NUMERIC(10,4),

    built_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (scheme_code, as_of_date, window_months)
);

CREATE INDEX IF NOT EXISTS idx_mf_rolling_scheme_date
    ON nidp.mf_rolling_returns (scheme_code, as_of_date DESC, window_months);

CREATE INDEX IF NOT EXISTS idx_mf_rolling_date_window
    ON nidp.mf_rolling_returns (as_of_date DESC, window_months);

COMMENT ON TABLE nidp.mf_rolling_returns IS
'Rolling CAGR distribution summary per (scheme, date, window). '
'Windows: 12m (252 bars), 36m (756 bars), 60m (1260 bars). '
'Computed by mf_analytics_engine after each run. '
'positive_pct = fraction of windows with positive CAGR — not zero-filled when NULL.';

COMMENT ON COLUMN nidp.mf_rolling_returns.positive_pct IS
'% of rolling windows with CAGR > 0. For a 5-year fund, a 1y rolling positive_pct '
'of 85% means NAV was up in 85% of all 1-year periods. Industry-standard consistency metric.';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('095_mf_rolling_returns.sql')
ON CONFLICT (filename) DO NOTHING;
