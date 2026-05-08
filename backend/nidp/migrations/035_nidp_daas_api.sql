-- ── DaaS API key + usage tracking ──────────────────────────────────
-- Public Data-as-a-Service surface. Distinct from the internal
-- query_api (single shared bearer token); here every external caller
-- gets a per-key credential with per-plan rate limits + a daily quota.
--
-- Keys are issued by `python -m nidp.cli daas-keygen ...` which prints
-- the raw token exactly once and writes only the SHA-256 hash here. We
-- never store the cleartext token; a leak in this table cannot grant
-- API access on its own.

CREATE TABLE IF NOT EXISTS nidp.daas_api_keys (
    key_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_prefix       TEXT NOT NULL,                       -- first 12 chars of the raw key, for human identification
    key_hash         TEXT NOT NULL UNIQUE,                -- sha256(raw_key)
    name             TEXT NOT NULL,                       -- "AcmeCorp prod", "swag's notebook", …
    owner_email      TEXT NOT NULL,
    plan             TEXT NOT NULL,                       -- 'free' | 'standard' | 'pro' | 'internal'
    rate_limit_rpm   INTEGER NOT NULL,                    -- per-minute cap (per process — best-effort)
    daily_quota      INTEGER,                             -- NULL = unlimited
    status           TEXT NOT NULL DEFAULT 'active',      -- 'active' | 'revoked'
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ,                         -- NULL = no expiry
    last_used_at     TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_daas_keys_status_owner
    ON nidp.daas_api_keys(status, owner_email);


-- Per-day request counter. UPSERTed inline on each authorised request.
-- Cheaper than aggregating daas_usage_log on hot path; the log table
-- below is for replay/analytics, this is for live quota enforcement.
CREATE TABLE IF NOT EXISTS nidp.daas_daily_usage (
    key_id         UUID NOT NULL REFERENCES nidp.daas_api_keys(key_id) ON DELETE CASCADE,
    day            DATE NOT NULL,
    request_count  BIGINT NOT NULL DEFAULT 0,
    error_count    BIGINT NOT NULL DEFAULT 0,
    last_request_at TIMESTAMPTZ,
    PRIMARY KEY (key_id, day)
);

CREATE INDEX IF NOT EXISTS idx_daas_daily_usage_day
    ON nidp.daas_daily_usage(day DESC);


-- Append-only request log. Sampled write (every request when sampling
-- is on; can be disabled via NIDP_DAAS_LOG_REQUESTS=0). Used for usage
-- analytics + abuse investigation.
CREATE TABLE IF NOT EXISTS nidp.daas_usage_log (
    request_id     UUID NOT NULL DEFAULT gen_random_uuid(),
    key_id         UUID NOT NULL,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    method         TEXT NOT NULL,
    path           TEXT NOT NULL,
    query_string   TEXT,
    status_code    INTEGER NOT NULL,
    rows_returned  INTEGER,
    latency_ms     INTEGER,
    client_ip      INET,
    user_agent     TEXT,
    error_message  TEXT,
    PRIMARY KEY (request_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_daas_usage_log_key_ts
    ON nidp.daas_usage_log(key_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_daas_usage_log_ts
    ON nidp.daas_usage_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_daas_usage_log_status
    ON nidp.daas_usage_log(status_code, ts DESC) WHERE status_code >= 400;


DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.daas_usage_log', 'ts',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


-- ── v_daas_key_status ───────────────────────────────────────────────
-- One row per active key with today's request count + last-7d totals.
-- Powers the admin Console's DaaS panel.
CREATE OR REPLACE VIEW nidp.v_daas_key_status AS
SELECT
    k.key_id,
    k.key_prefix,
    k.name,
    k.owner_email,
    k.plan,
    k.rate_limit_rpm,
    k.daily_quota,
    k.status,
    k.created_at,
    k.expires_at,
    k.last_used_at,
    COALESCE(today.request_count, 0)  AS today_requests,
    COALESCE(today.error_count, 0)    AS today_errors,
    COALESCE(week.requests_7d, 0)     AS requests_7d,
    COALESCE(week.errors_7d, 0)       AS errors_7d
FROM nidp.daas_api_keys k
LEFT JOIN LATERAL (
    SELECT request_count, error_count
      FROM nidp.daas_daily_usage
     WHERE key_id = k.key_id AND day = CURRENT_DATE
) today ON TRUE
LEFT JOIN LATERAL (
    SELECT
        SUM(request_count)::BIGINT AS requests_7d,
        SUM(error_count)::BIGINT   AS errors_7d
      FROM nidp.daas_daily_usage
     WHERE key_id = k.key_id
       AND day >= CURRENT_DATE - INTERVAL '7 days'
) week ON TRUE;


INSERT INTO nidp.schema_migrations(filename) VALUES ('035_nidp_daas_api.sql')
    ON CONFLICT (filename) DO NOTHING;
