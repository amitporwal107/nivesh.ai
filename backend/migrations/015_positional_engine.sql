-- 015_positional_engine.sql
-- Positional Trading Engine: 5–30 day trade recommendations driven by
-- technical features computed off daily OHLCV + Chartink scan gates.
--
-- Layered ON TOP of the existing V3 fundamental scoring (stock_master /
-- stock_primitives / stock_scores). The positional engine is a separate
-- short-horizon overlay; it does not replace fundamental scoring.

-- ── Daily OHLCV + delivery primitives ───────────────────────────────────
CREATE TABLE IF NOT EXISTS stock_ohlcv (
    nse_symbol      TEXT NOT NULL,
    bar_date        DATE NOT NULL,
    open_price      NUMERIC(14, 4) NOT NULL,
    high_price      NUMERIC(14, 4) NOT NULL,
    low_price       NUMERIC(14, 4) NOT NULL,
    close_price     NUMERIC(14, 4) NOT NULL,
    volume          BIGINT,
    delivery_qty    BIGINT,
    delivery_pct    NUMERIC(6, 2),
    source          TEXT,                       -- 'bhavcopy' | 'manual' | 'broker'
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nse_symbol, bar_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_ohlcv_date ON stock_ohlcv(bar_date DESC);


-- ── Chartink scan-hit log: which symbols passed which scan, on which date.
-- Treated as a *gate* by the scoring layer, not as a feature itself.
CREATE TABLE IF NOT EXISTS chartink_scan_hits (
    scan_date       DATE NOT NULL,
    scan_name       TEXT NOT NULL,              -- e.g. 'atlas_fresh.trend_up'
    nse_symbol      TEXT NOT NULL,
    extra           JSONB,                      -- raw row from Chartink CSV
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scan_date, scan_name, nse_symbol)
);

CREATE INDEX IF NOT EXISTS idx_chartink_hits_symbol ON chartink_scan_hits(nse_symbol, scan_date DESC);


-- ── Per-symbol-per-day computed features. Append-only; (symbol,date) PK.
-- Stored as numeric columns (fast filtering) plus a JSONB blob for
-- everything that's diagnostic-only (intermediate values, swing levels).
CREATE TABLE IF NOT EXISTS stock_technical_features (
    nse_symbol          TEXT NOT NULL,
    as_of_date          DATE NOT NULL,

    -- Sub-scores (0..1, higher = better)
    trend_score         NUMERIC(5, 4),
    momentum_score      NUMERIC(5, 4),
    structure_score     NUMERIC(5, 4),
    accumulation_score  NUMERIC(5, 4),
    sector_score        NUMERIC(5, 4),
    risk_score          NUMERIC(5, 4),

    -- Final composite + classification
    final_score         NUMERIC(5, 4),
    confidence          TEXT,                   -- HIGH | MEDIUM | LOW
    stage               TEXT,                   -- ACCUMULATION | EARLY_BREAKOUT | BREAKOUT | EXTENDED | WEAK

    -- Key raw values (frequently filtered on)
    close_price         NUMERIC(14, 4),
    sma_50              NUMERIC(14, 4),
    sma_200             NUMERIC(14, 4),
    rsi_14              NUMERIC(6, 2),
    atr_14              NUMERIC(14, 4),
    return_5d_pct       NUMERIC(7, 2),
    return_20d_pct      NUMERIC(7, 2),

    -- Trade plan inputs (used by trade_planner)
    breakout_level      NUMERIC(14, 4),
    support_level       NUMERIC(14, 4),
    resistance_level    NUMERIC(14, 4),

    -- Diagnostic blob (every intermediate, for explainability)
    components          JSONB,

    engine_version      TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nse_symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_stech_score    ON stock_technical_features(as_of_date DESC, final_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_stech_stage    ON stock_technical_features(as_of_date DESC, stage);


-- ── Final ranked positional recommendations with concrete trade plans.
-- One row per (symbol, signal_date). Reasons + scan attribution stored
-- alongside so the UI can show "why this trade".
CREATE TABLE IF NOT EXISTS positional_signals (
    nse_symbol          TEXT NOT NULL,
    signal_date         DATE NOT NULL,

    final_score         NUMERIC(5, 4) NOT NULL,
    confidence          TEXT NOT NULL,
    stage               TEXT NOT NULL,
    timeframe_days_min  INTEGER NOT NULL DEFAULT 5,
    timeframe_days_max  INTEGER NOT NULL DEFAULT 15,

    -- Trade plan
    entry_price         NUMERIC(14, 4) NOT NULL,
    stoploss            NUMERIC(14, 4) NOT NULL,
    target_price        NUMERIC(14, 4) NOT NULL,
    risk_reward         NUMERIC(6, 2) NOT NULL,

    -- Attribution
    source_scans        TEXT[],                 -- chartink scan names that hit
    reasons             JSONB,                  -- list of human-readable reasons

    engine_version      TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nse_symbol, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_psignals_date  ON positional_signals(signal_date DESC, final_score DESC);
CREATE INDEX IF NOT EXISTS idx_psignals_stage ON positional_signals(signal_date DESC, stage);


-- ── Outcome tracking for the learning loop (section 11A in spec).
-- Populated by a daily job that revisits old signals and computes whether
-- target/SL hit, plus realised return. Feeds future weight adjustments.
CREATE TABLE IF NOT EXISTS positional_outcomes (
    nse_symbol          TEXT NOT NULL,
    signal_date         DATE NOT NULL,
    horizon_days        INTEGER NOT NULL,       -- evaluated at this many bars
    outcome             TEXT,                   -- TARGET_HIT | SL_HIT | OPEN | EXPIRED
    realised_return_pct NUMERIC(7, 2),
    bars_to_outcome     INTEGER,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nse_symbol, signal_date, horizon_days)
);
