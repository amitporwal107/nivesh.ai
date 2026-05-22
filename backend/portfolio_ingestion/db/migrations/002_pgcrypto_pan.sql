-- 002_pgcrypto_pan.sql — column-level PAN encryption via pgcrypto.
--
-- The `pan_enc BYTEA` column was reserved in 001. This migration:
--   * confirms pgcrypto is available (was created in 001 for gen_random_uuid)
--   * defines pi_encrypt_pan / pi_decrypt_pan SQL helpers that use the
--     ``portfolio_ingestion.pan_encryption_key`` runtime setting, OR fall
--     back to a fixed-for-staging key if unset. The key is set per-session
--     by the application via SET LOCAL.
--   * leaves existing rows untouched (no key available inside the migration
--     itself; the app re-encrypts on the next time it touches each user).
--
-- The application reads the key from PI_PAN_ENCRYPTION_KEY and passes it
-- into the session via SET LOCAL on every transaction that needs decrypt.

CREATE EXTENSION IF NOT EXISTS pgcrypto;        -- idempotent

-- Important: pgcrypto installs into ``public``. Keep both schemas on the
-- search path so unqualified calls resolve cleanly.
SET search_path TO portfolio_ingestion, public;

-- Resolve the session-scoped key; falls back to a placeholder so the SQL
-- compiles in environments that haven't wired the key yet. The placeholder
-- key MUST be replaced in real environments — see PI_PAN_ENCRYPTION_KEY.
CREATE OR REPLACE FUNCTION pi_pan_key() RETURNS TEXT AS $$
DECLARE
    k TEXT;
BEGIN
    BEGIN
        k := current_setting('portfolio_ingestion.pan_encryption_key', true);
    EXCEPTION WHEN OTHERS THEN
        k := NULL;
    END;
    IF k IS NULL OR k = '' THEN
        -- staging-only placeholder; the app should always SET LOCAL the real
        -- key before any decrypt. Encrypts under this key are never readable
        -- after the env is reconfigured — by design.
        k := 'pi-placeholder-rotate-me';
    END IF;
    RETURN k;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION pi_encrypt_pan(plain_pan TEXT) RETURNS BYTEA AS $$
    -- Fully qualify so the function resolves regardless of caller search_path
    SELECT public.pgp_sym_encrypt(plain_pan, pi_pan_key());
$$ LANGUAGE SQL VOLATILE;

CREATE OR REPLACE FUNCTION pi_decrypt_pan(cipher BYTEA) RETURNS TEXT AS $$
    SELECT public.pgp_sym_decrypt(cipher, pi_pan_key());
$$ LANGUAGE SQL VOLATILE;

COMMENT ON FUNCTION pi_encrypt_pan(TEXT) IS
  'Encrypt a PAN under the session-scoped key set via SET LOCAL portfolio_ingestion.pan_encryption_key.';
COMMENT ON FUNCTION pi_decrypt_pan(BYTEA) IS
  'Decrypt a PAN previously encrypted by pi_encrypt_pan with the same session key.';
