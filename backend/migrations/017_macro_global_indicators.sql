-- 017_macro_global_indicators.sql
--
-- PR-2.5: Add global market indicators to the macro layer.
--
-- New columns on macro_daily:
--   india_vix          — NSE India VIX (^INDIAVIX)        — fear gauge
--   us_vix             — CBOE VIX (^VIX)                  — global risk-off proxy
--   dxy                — US Dollar Index (DX-Y.NYB)       — EM flow signal
--   sp500              — S&P 500 (^GSPC)                  — overnight US close
--   nasdaq             — Nasdaq Composite (^IXIC)         — IT/tech leader
--   nikkei             — Nikkei 225 (^N225)               — Asia open
--   hang_seng          — Hang Seng (^HSI)                 — Asia open
--
-- All nullable — partial-day failures don't block the row insert. The
-- regime engine treats nulls as "no signal" and falls back to the PR-1
-- 3-input classifier when global signals are missing.
--
-- Source / confidence columns share the existing pattern:
--   source_<metric> + confidence_<metric>

ALTER TABLE macro_daily
    ADD COLUMN IF NOT EXISTS india_vix          NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS us_vix             NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS dxy                NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS sp500              NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS nasdaq             NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS nikkei             NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS hang_seng          NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS source_india_vix   VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_us_vix      VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_dxy         VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_sp500       VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_nasdaq      VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_nikkei      VARCHAR(32),
    ADD COLUMN IF NOT EXISTS source_hang_seng   VARCHAR(32),
    ADD COLUMN IF NOT EXISTS confidence_india_vix  NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_us_vix     NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_dxy        NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_sp500      NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_nasdaq     NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_nikkei     NUMERIC(4, 2),
    ADD COLUMN IF NOT EXISTS confidence_hang_seng  NUMERIC(4, 2);


-- macro_features extension — 5d momentum for each new global signal +
-- the composite risk score the engine derives from them.
ALTER TABLE macro_features
    ADD COLUMN IF NOT EXISTS india_vix_z         NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS us_vix_z            NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS dxy_momentum_5d     NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS sp500_overnight_pct NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS nasdaq_overnight_pct NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS asia_open_pct       NUMERIC(8, 4),  -- avg of Nikkei + Hang Seng momentum
    ADD COLUMN IF NOT EXISTS composite_risk_score NUMERIC(6, 3);  -- -1 .. +1


-- macro_state extension — also store the composite risk score so the
-- /api/macro/today response can surface it without a join.
ALTER TABLE macro_state
    ADD COLUMN IF NOT EXISTS composite_risk_score NUMERIC(6, 3),
    ADD COLUMN IF NOT EXISTS preopen_summary      TEXT;
