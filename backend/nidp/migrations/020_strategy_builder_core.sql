-- 020_strategy_builder_core.sql — Strategy Builder core tables.
--
-- Multi-asset (STOCK | MF) strategy authoring on top of NIDP. A
-- "strategy" is a versioned JSON DSL document owned by a user; every
-- save creates a new immutable strategy_version. Backtest + live runs
-- are recorded in strategy_runs; per-trade results in strategy_trades.
--
-- Storage rules:
--   • strategies + versions live in the application schema (`public`)
--     because they are user-owned mutable records, not facts.
--   • Runs + trades are append-only — once a backtest is recorded it
--     becomes immutable history.
--   • user_universes also app-schema; symbols stored as TEXT[] for
--     simple membership queries.

SET search_path TO public;

-- ── strategies ──────────────────────────────────────────────────────
-- One row per strategy, owned by one user. The active definition is
-- the version with `is_active=true` in strategy_versions.
CREATE TABLE IF NOT EXISTS strategies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID NOT NULL,                   -- → users.id (no FK; users live in MongoDB historically)
    name            TEXT NOT NULL,
    description     TEXT,
    asset_class     TEXT NOT NULL,                   -- 'STOCK' | 'MF'
    is_public_template BOOLEAN NOT NULL DEFAULT FALSE, -- admin-promoted template visible to all users
    is_archived     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (asset_class IN ('STOCK','MF'))
);

CREATE INDEX IF NOT EXISTS idx_strategies_owner
    ON strategies(owner_id) WHERE NOT is_archived;
CREATE INDEX IF NOT EXISTS idx_strategies_public
    ON strategies(is_public_template) WHERE is_public_template;


-- ── strategy_versions ───────────────────────────────────────────────
-- Immutable definition history. Each save creates a new row; the
-- application picks the latest is_active=true row for execution.
-- Older versions stay so historical backtests remain reproducible.
CREATE TABLE IF NOT EXISTS strategy_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL,                -- 1, 2, 3, …
    definition      JSONB NOT NULL,                  -- the DSL document
    dsl_version     TEXT NOT NULL DEFAULT '1',       -- DSL grammar version
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,   -- only one active per strategy
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID NOT NULL,
    UNIQUE (strategy_id, version_no)
);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_strategy
    ON strategy_versions(strategy_id, version_no DESC);
-- Partial index for the hot lookup ("get active version of strategy X")
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_active_version
    ON strategy_versions(strategy_id) WHERE is_active;


-- ── user_universes ──────────────────────────────────────────────────
-- User-defined symbol lists. For MF, "symbols" stores scheme_codes.
CREATE TABLE IF NOT EXISTS user_universes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    asset_class     TEXT NOT NULL,                   -- 'STOCK' | 'MF'
    symbols         TEXT[] NOT NULL DEFAULT '{}',
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (asset_class IN ('STOCK','MF'))
);

CREATE INDEX IF NOT EXISTS idx_user_universes_owner
    ON user_universes(owner_id);


-- ── strategy_runs ───────────────────────────────────────────────────
-- One row per backtest or live execution. Append-only history.
-- run_type='BACKTEST' for historical sweep, 'LIVE' for daily cron.
CREATE TABLE IF NOT EXISTS strategy_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version_id      UUID NOT NULL REFERENCES strategy_versions(id),
    run_type        TEXT NOT NULL,                   -- 'BACKTEST' | 'LIVE'
    status          TEXT NOT NULL,                   -- 'RUNNING' | 'OK' | 'FAILED'
    -- Backtest window (NULL for LIVE runs)
    backtest_from   DATE,
    backtest_to     DATE,
    -- LIVE runs use as_of_date instead
    as_of_date      DATE,
    -- Aggregate metrics (computed at run end, NULL until status=OK)
    metrics         JSONB,                           -- {win_rate, profit_factor, max_dd, sharpe, …}
    equity_curve    JSONB,                           -- [{date, equity, drawdown}, …]
    trade_count     INTEGER,
    -- Provenance — which NIDP snapshot date was used as data anchor
    snapshot_as_of  DATE,
    -- Error capture
    error_message   TEXT,
    -- Timing
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    triggered_by    UUID,                            -- user_id, NULL for cron
    CHECK (run_type IN ('BACKTEST','LIVE')),
    CHECK (status IN ('RUNNING','OK','FAILED'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_strategy
    ON strategy_runs(strategy_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_runs_live
    ON strategy_runs(strategy_id, as_of_date DESC) WHERE run_type='LIVE';


-- ── strategy_trades ─────────────────────────────────────────────────
-- One row per simulated or recommended entry. For backtests, exit_*
-- fields are populated at exit; for LIVE runs, they remain NULL until
-- the engine observes the exit condition on a future bar.
CREATE TABLE IF NOT EXISTS strategy_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES strategy_runs(id) ON DELETE CASCADE,
    strategy_id     UUID NOT NULL,                   -- denormalised for fast filtering
    symbol          TEXT NOT NULL,                   -- stock symbol or MF scheme_code
    -- Entry
    entry_date      DATE NOT NULL,
    entry_price     NUMERIC(14,4) NOT NULL,
    entry_reason    TEXT,                            -- short human label
    score           NUMERIC(8,4),                    -- composite score at entry
    -- Plan
    stoploss_price  NUMERIC(14,4),
    target_price    NUMERIC(14,4),
    qty             INTEGER,                         -- sized by allocation rule (NULL until placed)
    -- Exit (NULL until trade closes)
    exit_date       DATE,
    exit_price      NUMERIC(14,4),
    exit_reason     TEXT,                            -- 'STOPLOSS' | 'TARGET' | 'TIME' | 'TRAILING' | 'STRATEGY_EXIT'
    pnl_pct         NUMERIC(10,4),
    pnl_abs         NUMERIC(14,4),
    holding_days    INTEGER,
    -- Costs
    brokerage       NUMERIC(10,4),
    slippage_pct    NUMERIC(8,4),
    -- Metadata
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_trades_run
    ON strategy_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_strategy_trades_strategy_entry
    ON strategy_trades(strategy_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_trades_open
    ON strategy_trades(strategy_id, symbol) WHERE exit_date IS NULL;


-- ── strategy_signals ────────────────────────────────────────────────
-- LIVE run output: today's actionable signals. Distinct from trades —
-- a signal is "this matched the entry rule on date D"; whether the
-- user takes it is their decision. Cron writes one row per matched
-- (strategy, symbol, date) triple. Idempotent on conflict.
CREATE TABLE IF NOT EXISTS strategy_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    run_id          UUID NOT NULL REFERENCES strategy_runs(id),
    as_of_date      DATE NOT NULL,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,                   -- 'ENTRY' | 'EXIT' | 'WATCH'
    entry_price     NUMERIC(14,4),
    stoploss_price  NUMERIC(14,4),
    target_price    NUMERIC(14,4),
    score           NUMERIC(8,4),
    reasons         JSONB,                           -- ["rsi14 > 55", "vol_z20 = 2.1", …]
    notified_at     TIMESTAMPTZ,                     -- NULL until alerts dispatched
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, as_of_date, symbol, action),
    CHECK (action IN ('ENTRY','EXIT','WATCH'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy_date
    ON strategy_signals(strategy_id, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_unnotified
    ON strategy_signals(strategy_id) WHERE notified_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_strategy_signals_date
    ON strategy_signals(as_of_date DESC);


-- ── strategy_alerts ─────────────────────────────────────────────────
-- User subscription preferences for receiving signal notifications.
-- One row per (strategy_id, user_id, channel) so users can mix email +
-- Telegram + webhook on the same strategy.
CREATE TABLE IF NOT EXISTS strategy_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    channel         TEXT NOT NULL,                   -- 'EMAIL' | 'TELEGRAM' | 'WEBHOOK'
    target          TEXT NOT NULL,                   -- email address / telegram chat_id / webhook URL
    min_score       NUMERIC(8,4),                    -- only fire when score ≥ this
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (strategy_id, user_id, channel, target),
    CHECK (channel IN ('EMAIL','TELEGRAM','WEBHOOK'))
);


-- ── strategy_audit ──────────────────────────────────────────────────
-- Append-only log of strategy create/edit/archive events. Important
-- for governance (especially once strategies become public templates).
CREATE TABLE IF NOT EXISTS strategy_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL,
    actor_id        UUID NOT NULL,
    action          TEXT NOT NULL,                   -- 'CREATE' | 'UPDATE' | 'ARCHIVE' | 'PROMOTE_TEMPLATE' | …
    prev_definition JSONB,                           -- previous active version's DSL (for UPDATE)
    new_definition  JSONB,                           -- new version's DSL
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_audit_strategy
    ON strategy_audit(strategy_id, created_at DESC);


-- Track migration application (mirrors NIDP pattern)
INSERT INTO nidp.schema_migrations(filename) VALUES ('020_strategy_builder_core.sql')
    ON CONFLICT (filename) DO NOTHING;
