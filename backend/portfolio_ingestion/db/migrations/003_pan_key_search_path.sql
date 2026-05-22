-- 003_pan_key_search_path.sql — fix function-body name resolution.
--
-- Migration 002 created pi_encrypt_pan / pi_decrypt_pan whose bodies call
-- the unqualified ``pi_pan_key()``. SQL function bodies resolve names
-- against the CALLER's search_path at execution time, not the search_path
-- in effect when CREATE FUNCTION ran. asyncpg sessions default to
-- ``public`` only, so the call failed in production-shaped traffic.
--
-- The robust fix is to attach ``SET search_path`` directly to each
-- function so the body always finds the helper. This makes the functions
-- independent of caller context — the right shape for security-sensitive
-- code that gets called from many places.

CREATE OR REPLACE FUNCTION portfolio_ingestion.pi_encrypt_pan(plain_pan TEXT)
RETURNS BYTEA AS $$
    SELECT public.pgp_sym_encrypt(plain_pan, portfolio_ingestion.pi_pan_key());
$$ LANGUAGE SQL VOLATILE SET search_path = portfolio_ingestion, public;

CREATE OR REPLACE FUNCTION portfolio_ingestion.pi_decrypt_pan(cipher BYTEA)
RETURNS TEXT AS $$
    SELECT public.pgp_sym_decrypt(cipher, portfolio_ingestion.pi_pan_key());
$$ LANGUAGE SQL VOLATILE SET search_path = portfolio_ingestion, public;
