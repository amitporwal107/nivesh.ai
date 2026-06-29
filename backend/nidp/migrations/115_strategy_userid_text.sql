-- 115_strategy_userid_text.sql — Strategy Builder user-id columns UUID -> TEXT.
--
-- 020_strategy_builder_core typed the user-owner columns as UUID, but the app's
-- real user ids are `user_<hex>` strings (Mongo `users.user_id`), NOT UUIDs.
-- So every Strategy Builder create/list/backtest by a real user hit
-- "invalid input syntax for type uuid" → HTTP 500. Widen these columns to TEXT.
--
-- Entity PKs/FKs (id / strategy_id / version_id / run_id) stay UUID — those are
-- real gen_random_uuid() keys. Only the user-reference columns change.
--
-- Idempotent + safe: IF EXISTS guards the tables; ALTER ... TYPE TEXT on an
-- already-TEXT column is a no-op. Runs after 020 in the nidp-public loop, so the
-- tables exist by the time this applies (to the app `public` schema).

SET search_path TO public;

ALTER TABLE IF EXISTS strategies        ALTER COLUMN owner_id     TYPE TEXT USING owner_id::text;
ALTER TABLE IF EXISTS strategy_versions ALTER COLUMN created_by   TYPE TEXT USING created_by::text;
ALTER TABLE IF EXISTS user_universes    ALTER COLUMN owner_id     TYPE TEXT USING owner_id::text;
ALTER TABLE IF EXISTS strategy_runs     ALTER COLUMN triggered_by TYPE TEXT USING triggered_by::text;
ALTER TABLE IF EXISTS strategy_alerts   ALTER COLUMN user_id      TYPE TEXT USING user_id::text;
ALTER TABLE IF EXISTS strategy_audit    ALTER COLUMN actor_id     TYPE TEXT USING actor_id::text;
