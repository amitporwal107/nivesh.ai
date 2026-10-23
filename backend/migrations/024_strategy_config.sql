-- 024_strategy_config.sql
-- Per-strategy "Bot details" settings — the stored form of NiveshConfig
-- (docs/STRATEGY_BUILDER_CONFIG_SPEC.md §4.3).
--
-- The spec writes this table as bot_config(bot_id → bots); this codebase has no
-- `bots` table, so the owning row is public.strategies and the table is
-- strategy_config(strategy_id → strategies). One row per strategy, created on the
-- first PUT /api/strategy-builder/strategies/{id}/config; a strategy with no row
-- runs on config.AI_DEFAULTS.
--
-- ORDERING DEPENDENCY (the only file in backend/migrations/ with one): the FK below
-- needs public.strategies, which is created by a DIFFERENT runner's file —
-- backend/nidp/migrations/020_strategy_builder_core.sql — while
-- backend/scripts/post_deploy_migrate.py only scans backend/migrations/. On a database
-- where nidp 020 has not been applied this file CANNOT succeed, so it fails loudly and
-- by name in the guard below rather than with a bare `relation "strategies" does not
-- exist`. Apply the nidp migrations first, then re-run this one.
--
-- The CHECK constraints below mirror NiveshConfig.FIELD_RANGES
-- (backend/services/ai_trader/config.py) exactly, so the database cannot hold a
-- value the class would reject on the way back out. `pyramiding`'s upper bound is the
-- SMALLINT domain itself (32767), which FIELD_RANGES states as its maximum.
--
-- Honesty note: `pyramiding` and `short_margin_pct` are STORED but do not reach the
-- engine yet — the DSL backtester is long-only and counts no same-direction entries.
-- Only initial_capital and commission_pct affect a run today.
--
-- Forward-only, additive, re-runnable (IF NOT EXISTS throughout).

-- Every object is schema-qualified instead of carrying a `SET search_path`: this file is
-- executed on a connection borrowed from the app's own pg_client pool, where a plain SET
-- would outlive the transaction and leak onto every later borrower (and SET LOCAL would
-- silently do nothing if the file ever ran outside one).

DO $guard$
BEGIN
    IF to_regclass('public.strategies') IS NULL THEN
        RAISE EXCEPTION
            'migration 024_strategy_config.sql needs table public.strategies, which is created by backend/nidp/migrations/020_strategy_builder_core.sql — apply the nidp migrations first, then re-run this file';
    END IF;
END
$guard$;

CREATE TABLE IF NOT EXISTS public.strategy_config (
    strategy_id      UUID PRIMARY KEY REFERENCES public.strategies(id) ON DELETE CASCADE,
    schema_version   SMALLINT      NOT NULL DEFAULT 1,     -- config.SCHEMA_VERSION
    -- Reserved and never written by Bot details: a DSL strategy's universe lives in
    -- the strategy_versions definition (`universe: {type, ref}`), so the Bot details
    -- tab shows symbols READ-ONLY and derives them from the active version. The
    -- column stays for a future explicit symbol picker (spec §2, §4.4).
    symbols          TEXT[],
    initial_capital  NUMERIC(18,2) NOT NULL,
    commission_pct   NUMERIC(6,4)  NOT NULL,
    pyramiding       SMALLINT      NOT NULL,
    short_margin_pct NUMERIC(5,2)  NOT NULL,
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CHECK (initial_capital > 0 AND initial_capital <= 10000000000),  -- `0 < x <= 1e10`
    CHECK (commission_pct >= 0 AND commission_pct <= 5),             -- `0 <= x <= 5`
    CHECK (pyramiding >= 0 AND pyramiding <= 32767),                 -- SMALLINT's own domain
    CHECK (short_margin_pct > 0 AND short_margin_pct <= 100)         -- `0 < x <= 100`
);

-- No secondary index: every read is "the config of strategy X", which the primary
-- key already serves. An index on updated_at would only be dead weight.
