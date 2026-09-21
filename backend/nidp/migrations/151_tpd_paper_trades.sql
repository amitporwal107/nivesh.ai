-- 151_tpd_paper_trades.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Ten-Percent Days — Paper Trade Simulation Engine v1 (owner's PRD, 2026-09-18).
-- EOD prediction → next-session-open paper entry → six-session tracking → evaluation. No live execution.
--
-- Written by tpd_model.paper (research host, nightly after run_v4.sh); read by the DaaS router paper_trades.py
-- (internal plan only) behind the app's move_odds allowlist. Additive, nothing else reads or writes these tables.
-- PRD §10 tables, prefixed tpd_ (standing clearance: additive tpd_* tables only), plus what the PRD asks for elsewhere:
--
--   tpd_paper_rule_sets                  the pre-registered rules (rules_v1.json), their hash and registration time
--   tpd_paper_prediction_snapshots       PRD 10.1 — the complete ranked universe per portfolio; IMMUTABLE (trigger):
--                                        a correction is a new prediction_version row that names what it supersedes
--   tpd_paper_trades                     PRD 10.2 + the entry/stop/target fields of the owner's follow-up
--   tpd_paper_trade_daily_observations   PRD 10.3 + high watermark, drawdown, exit status
--   tpd_paper_trade_exits                every evaluation mode per trade (PRD 7.2), costs separate from gross
--   tpd_paper_trade_events               every state transition (PRD 9)
--   tpd_paper_universe_outcomes          the path of every eligible ranked row (benchmarks, calibration, custom baskets)
--   tpd_paper_benchmark_results          benchmarks A–D per session and mode (PRD 12)
--   tpd_paper_index_bars                 the Nifty 50 bars benchmark D used, with their source
--   tpd_paper_evaluations                the evaluation report per run; forward and replay never pooled
-- `sample` separates the forward paper sample from the labelled historical replay in every table.
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_rule_sets (
    rules_id        TEXT PRIMARY KEY,
    rules_sha256    TEXT NOT NULL UNIQUE,
    git_sha         TEXT NOT NULL,
    registered_at   TIMESTAMPTZ NOT NULL,
    rules           JSONB NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_prediction_snapshots (
    prediction_id            BIGSERIAL PRIMARY KEY,
    sample                   TEXT NOT NULL CHECK (sample IN ('forward', 'replay')),
    prediction_version       INTEGER NOT NULL DEFAULT 1 CHECK (prediction_version >= 1),
    supersedes               BIGINT REFERENCES nidp.tpd_paper_prediction_snapshots (prediction_id),
    prediction_date          DATE NOT NULL,
    prediction_timestamp     TIMESTAMPTZ NOT NULL,
    data_cutoff_timestamp    TIMESTAMPTZ NOT NULL,
    next_trading_session     DATE NOT NULL,
    symbol                   TEXT NOT NULL,
    isin                     TEXT,
    portfolio_type           TEXT NOT NULL CHECK (portfolio_type IN ('P5-NEXT', 'P10-NEXT')),
    target_pct               NUMERIC(5,2) NOT NULL,
    horizon_sessions         INTEGER NOT NULL,
    movement_probability     NUMERIC(8,5) NOT NULL,
    direction_probability    NUMERIC(8,5),            -- NULL: v4 has no direction head (never synthesised)
    expected_return          NUMERIC(10,6),           -- NULL: v4 has no expected-return output
    predicted_regime         TEXT,                    -- NULL: v4 records no per-row regime
    p_opposite               NUMERIC(8,5),            -- the same threshold's down estimate (benchmark C, the page)
    p_other_threshold        NUMERIC(8,5),            -- P(+10%) on a P5 row, P(+5%) on a P10 row
    model_rank               INTEGER NOT NULL,        -- among all scored rows
    rank                     INTEGER,                 -- among eligible rows; NULL when excluded
    selection_status         TEXT NOT NULL CHECK (selection_status IN ('SELECTED', 'NOT_SELECTED', 'EXCLUDED')),
    exclusion_reason         TEXT,
    model_version            TEXT NOT NULL,
    feature_version          TEXT NOT NULL,
    snapshot_sha256          TEXT NOT NULL,           -- the frozen model output this row was read from
    rules_id                 TEXT NOT NULL REFERENCES nidp.tpd_paper_rule_sets (rules_id),
    counts_toward_evaluation BOOLEAN NOT NULL,
    eligibility_snapshot     JSONB,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sample, prediction_date, symbol, portfolio_type, model_version, feature_version, prediction_version),
    CHECK ((selection_status = 'EXCLUDED') = (rank IS NULL)),
    CHECK ((selection_status = 'EXCLUDED') = (exclusion_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_tpd_paper_snap_lookup ON nidp.tpd_paper_prediction_snapshots (sample, portfolio_type, prediction_date DESC, rank);

CREATE OR REPLACE FUNCTION nidp.tpd_paper_snapshots_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'tpd_paper_prediction_snapshots is immutable (% refused); insert a new prediction_version that supersedes it', TG_OP;
END $$;
DROP TRIGGER IF EXISTS trg_tpd_paper_snapshots_immutable ON nidp.tpd_paper_prediction_snapshots;
CREATE TRIGGER trg_tpd_paper_snapshots_immutable BEFORE UPDATE OR DELETE ON nidp.tpd_paper_prediction_snapshots
    FOR EACH ROW EXECUTE FUNCTION nidp.tpd_paper_snapshots_immutable();

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_trades (
    trade_id                 BIGSERIAL PRIMARY KEY,
    prediction_id            BIGINT NOT NULL UNIQUE REFERENCES nidp.tpd_paper_prediction_snapshots (prediction_id),
    sample                   TEXT NOT NULL CHECK (sample IN ('forward', 'replay')),
    portfolio_type           TEXT NOT NULL,
    symbol                   TEXT NOT NULL,
    prediction_date          DATE NOT NULL,
    intended_entry_date      DATE NOT NULL,
    entry_date               DATE,
    entry_timestamp          TIMESTAMPTZ,
    entry_price              NUMERIC(14,4),
    entry_source             TEXT,
    entry_method             TEXT NOT NULL DEFAULT 'next_session_official_open',
    entry_price_adjustment_status TEXT,
    prev_close               NUMERIC(14,4),
    gap_from_previous_close  NUMERIC(12,6),
    entry_slippage           NUMERIC(12,6),
    quantity                 NUMERIC(18,6),
    allocated_capital        NUMERIC(18,2) NOT NULL,
    target_pct               NUMERIC(5,2) NOT NULL,
    stop_pct                 NUMERIC(8,4),
    max_holding_sessions     INTEGER NOT NULL,
    atr_14                   NUMERIC(14,4),
    support_level            NUMERIC(14,4),
    resistance_level         NUMERIC(14,4),
    stop_loss_price          NUMERIC(14,4),
    stop_method              TEXT,
    target_1_price           NUMERIC(14,4),
    target_2_price           NUMERIC(14,4),
    risk_percent             NUMERIC(12,6),
    reward_percent           NUMERIC(12,6),
    risk_reward_ratio        NUMERIC(10,4),
    status                   TEXT NOT NULL CHECK (status IN ('PENDING_ENTRY', 'ENTERED', 'MONITORING', 'EXITED', 'EVALUATED',
                                                            'ENTRY_UNAVAILABLE', 'DATA_ERROR', 'CORPORATE_ACTION_REVIEW',
                                                            'SUSPENDED', 'CANCELLED_BY_RULE')),
    status_reason            TEXT,
    flags                    TEXT[] NOT NULL DEFAULT '{}',
    sessions_observed        INTEGER NOT NULL DEFAULT 0,
    exit_mode                TEXT NOT NULL DEFAULT 'EOD-1',          -- the headline mode the exit_* columns describe
    exit_date                DATE,
    exit_price               NUMERIC(14,4),
    exit_reason              TEXT,
    gross_return             NUMERIC(12,6),
    costs                    NUMERIC(18,6),
    net_return               NUMERIC(12,6),
    mfe                      NUMERIC(12,6),
    mae                      NUMERIC(12,6),
    max_drawdown             NUMERIC(12,6),
    target_hit               BOOLEAN,
    target_before_stop       BOOLEAN,
    counts_toward_evaluation BOOLEAN NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tpd_paper_trades_lookup ON nidp.tpd_paper_trades (sample, portfolio_type, prediction_date DESC);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_trade_daily_observations (
    trade_id              BIGINT NOT NULL REFERENCES nidp.tpd_paper_trades (trade_id),
    session_date          DATE NOT NULL,
    days_held             INTEGER NOT NULL CHECK (days_held BETWEEN 0 AND 5),
    open_price            NUMERIC(14,4),
    high_price            NUMERIC(14,4),
    low_price             NUMERIC(14,4),
    close_price           NUMERIC(14,4),
    volume                BIGINT,
    adjustment_factor     NUMERIC(14,8) NOT NULL DEFAULT 1,
    return_from_entry     NUMERIC(12,6),
    open_return           NUMERIC(12,6),
    high_return           NUMERIC(12,6),
    low_return            NUMERIC(12,6),
    high_watermark        NUMERIC(12,6),
    drawdown_from_entry   NUMERIC(12,6),
    mfe_to_date           NUMERIC(12,6),
    mae_to_date           NUMERIC(12,6),
    target_hit            BOOLEAN NOT NULL DEFAULT FALSE,
    stop_hit              BOOLEAN NOT NULL DEFAULT FALSE,
    exit_status           TEXT,
    data_quality_status   TEXT NOT NULL,
    PRIMARY KEY (trade_id, session_date)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_trade_exits (
    trade_id        BIGINT NOT NULL REFERENCES nidp.tpd_paper_trades (trade_id),
    mode            TEXT NOT NULL CHECK (mode IN ('EOD-1', 'EOD-3', 'EOD-5', 'FIXED', 'TARGET_STOP')),
    state           TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSED', 'NO_BAR_AT_EXIT')),
    exit_date       DATE,
    exit_price      NUMERIC(14,4),
    exit_reason     TEXT,
    sessions_held   INTEGER,
    gross_return    NUMERIC(12,6),
    cost_pct        NUMERIC(6,3) NOT NULL,
    net_return      NUMERIC(12,6),
    net_return_050  NUMERIC(12,6),
    net_return_100  NUMERIC(12,6),
    mfe             NUMERIC(12,6),
    mae             NUMERIC(12,6),
    target_hit      BOOLEAN,
    stop_hit        BOOLEAN,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_id, mode)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_trade_events (
    trade_id      BIGINT NOT NULL REFERENCES nidp.tpd_paper_trades (trade_id),
    to_status     TEXT NOT NULL,
    from_status   TEXT,
    effective_at  TIMESTAMPTZ NOT NULL,     -- when the state became true (e.g. the entry session's close)
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note          TEXT NOT NULL,
    PRIMARY KEY (trade_id, to_status)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_universe_outcomes (
    prediction_id      BIGINT PRIMARY KEY REFERENCES nidp.tpd_paper_prediction_snapshots (prediction_id),
    entry_status       TEXT NOT NULL,
    entry_reason       TEXT,
    flags              TEXT[] NOT NULL DEFAULT '{}',
    entry_price        REAL,
    gap                REAL,
    atr_14             REAL,
    stop_loss_price    REAL,
    stop_method        TEXT,
    target_price       REAL,
    sessions_observed  SMALLINT NOT NULL,
    session_dates      DATE[] NOT NULL,
    r_open             REAL[],
    r_high             REAL[],
    r_low              REAL[],
    r_close            REAL[],
    model_label_hit    BOOLEAN,
    ts_exit_index      SMALLINT,
    ts_gross           REAL,
    ts_reason          TEXT,
    size_group         TEXT,
    sector             TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_benchmark_results (
    sample            TEXT NOT NULL CHECK (sample IN ('forward', 'replay')),
    portfolio_type    TEXT NOT NULL,
    prediction_date   DATE NOT NULL,
    entry_session     DATE NOT NULL,
    benchmark         TEXT NOT NULL CHECK (benchmark IN ('MODEL', 'A_ALL', 'A_RANDOM5', 'B_MATCHED', 'C_MOVEMENT', 'D_NIFTY50')),
    mode              TEXT NOT NULL,
    state             TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSED')),
    n                 INTEGER NOT NULL,
    members           TEXT[] NOT NULL DEFAULT '{}',
    gross_mean        DOUBLE PRECISION,
    net_mean          DOUBLE PRECISION,
    target_hit_rate   DOUBLE PRECISION,
    positive_rate     DOUBLE PRECISION,
    source            TEXT,
    rules_id          TEXT NOT NULL REFERENCES nidp.tpd_paper_rule_sets (rules_id),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (sample, portfolio_type, prediction_date, benchmark, mode, rules_id)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_index_bars (
    index_name   TEXT NOT NULL,
    as_of_date   DATE NOT NULL,
    open_price   NUMERIC(14,4) NOT NULL,
    close_price  NUMERIC(14,4) NOT NULL,
    source       TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_name, as_of_date)
);

CREATE TABLE IF NOT EXISTS nidp.tpd_paper_evaluations (
    evaluation_id     BIGSERIAL PRIMARY KEY,
    sample            TEXT NOT NULL CHECK (sample IN ('forward', 'replay')),
    portfolio_type    TEXT NOT NULL,
    rules_id          TEXT NOT NULL REFERENCES nidp.tpd_paper_rule_sets (rules_id),
    as_of_session     DATE NOT NULL,
    inputs_sha256     TEXT NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload           JSONB NOT NULL,
    UNIQUE (sample, portfolio_type, rules_id, inputs_sha256)
);
CREATE INDEX IF NOT EXISTS idx_tpd_paper_eval_latest ON nidp.tpd_paper_evaluations (sample, portfolio_type, computed_at DESC);

INSERT INTO nidp.schema_migrations (filename)
VALUES ('151_tpd_paper_trades.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
