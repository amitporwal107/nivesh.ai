-- 026_strategy_store_v2.sql
-- The shared strategy store, v2 (Strategy Copilot Phase 1.1; owner decision D1, 2026-10-28: everything that can be
-- backtested lives in the Strategy Builder tables, including the Strategy Lab wizard's saved structures).
-- Design: docs/strategy_copilot_review_20261028/PROPOSAL_strategy_store_v2.md §2.
--
-- What it does, all additive:
--   * strategies: asset_class may also be FNO or MIXED; new columns say where a strategy came from (source,
--     template_id, cloned_from, cloned_from_version), what it trades (underlying) and the Idempotency-Key of the
--     request that created it (create_idempotency_key + create_fingerprint, unique per owner).
--   * strategy_versions: schema_version ('1' = the equity DSL, '2' = the legs document), the version it was saved
--     from (parent_version_id), change_summary, source_prompt / model_provenance / field_status for the Copilot
--     (Phase 1.3), and the request's Idempotency-Key (unique per strategy).
--   * a trigger makes a version row immutable: only is_active may change (the v1 PATCH route flips it).
-- Existing rows are not rewritten: they read as schema_version '1', source 'user'.
--
-- ORDERING DEPENDENCY (as 024): public.strategies is created by backend/nidp/migrations/020_strategy_builder_core.sql,
-- which the app-migrate loop applies AFTER this directory. On a database without it this file fails loudly by name;
-- apply the nidp migrations, then re-run it.
--
-- Re-runnable and atomic: one transaction; every step is IF NOT EXISTS or drop-and-recreate of an object this file
-- owns. Objects are schema-qualified (no SET search_path; see 024 for why).

BEGIN;

DO $guard$
BEGIN
    IF to_regclass('public.strategies') IS NULL OR to_regclass('public.strategy_versions') IS NULL THEN
        RAISE EXCEPTION
            'migration 026_strategy_store_v2.sql needs public.strategies and public.strategy_versions, created by backend/nidp/migrations/020_strategy_builder_core.sql — apply the nidp migrations first, then re-run this file';
    END IF;
END
$guard$;

-- ── strategies ───────────────────────────────────────────────────────────────
ALTER TABLE public.strategies DROP CONSTRAINT IF EXISTS strategies_asset_class_check;
ALTER TABLE public.strategies
    ADD CONSTRAINT strategies_asset_class_check CHECK (asset_class IN ('STOCK', 'MF', 'FNO', 'MIXED'));

ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'user';
ALTER TABLE public.strategies DROP CONSTRAINT IF EXISTS strategies_source_check;
ALTER TABLE public.strategies
    ADD CONSTRAINT strategies_source_check CHECK (source IN ('user', 'ai', 'template', 'clone', 'plan'));
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS template_id TEXT;
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS underlying TEXT;
-- No foreign key: a clone keeps pointing at its source after the source is archived.
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS cloned_from UUID;
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS cloned_from_version UUID;
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS create_idempotency_key TEXT;
ALTER TABLE public.strategies ADD COLUMN IF NOT EXISTS create_fingerprint TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategies_owner_create_key
    ON public.strategies (owner_id, create_idempotency_key) WHERE create_idempotency_key IS NOT NULL;

-- ── strategy_versions ────────────────────────────────────────────────────────
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS schema_version TEXT NOT NULL DEFAULT '1';
ALTER TABLE public.strategy_versions DROP CONSTRAINT IF EXISTS strategy_versions_schema_version_check;
ALTER TABLE public.strategy_versions
    ADD CONSTRAINT strategy_versions_schema_version_check CHECK (schema_version IN ('1', '2'));
ALTER TABLE public.strategy_versions
    ADD COLUMN IF NOT EXISTS parent_version_id UUID REFERENCES public.strategy_versions (id);
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS change_summary TEXT;
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS source_prompt TEXT;
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS model_provenance JSONB;
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS field_status JSONB;
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
-- Added last: services/strategy_store.py reads this column's presence as "026 is applied" (one transaction, so all
-- of the above exists whenever it does).
ALTER TABLE public.strategy_versions ADD COLUMN IF NOT EXISTS request_fingerprint TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_versions_idempotency_key
    ON public.strategy_versions (strategy_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- ── versions are immutable ───────────────────────────────────────────────────
-- Every column except is_active, present and future, compared as one JSON value.
CREATE OR REPLACE FUNCTION public.strategy_versions_immutable() RETURNS trigger
    LANGUAGE plpgsql AS
$fn$
BEGIN
    IF (to_jsonb(NEW) - 'is_active') IS DISTINCT FROM (to_jsonb(OLD) - 'is_active') THEN
        RAISE EXCEPTION 'strategy_versions rows are immutable: only is_active may change (version %). Save a new version instead.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$fn$;

DROP TRIGGER IF EXISTS trg_strategy_versions_immutable ON public.strategy_versions;
CREATE TRIGGER trg_strategy_versions_immutable
    BEFORE UPDATE ON public.strategy_versions
    FOR EACH ROW EXECUTE FUNCTION public.strategy_versions_immutable();

COMMIT;
