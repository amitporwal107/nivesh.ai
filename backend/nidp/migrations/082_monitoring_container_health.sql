-- Migration 082: Container health monitoring table
-- Used by container_health_collector.py (cron every minute) to persist
-- Docker container status so Grafana can visualize infra health.

CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.container_health (
    id              BIGSERIAL       PRIMARY KEY,
    container_name  TEXT            NOT NULL,
    container_image TEXT,
    status          TEXT            NOT NULL,       -- running, exited, paused, restarting, dead
    health          TEXT,                           -- healthy, unhealthy, starting, none
    uptime_seconds  BIGINT,
    ports           TEXT,
    environment     TEXT            NOT NULL DEFAULT 'unknown',  -- prod, staging, infra
    collected_at    TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_container_health_name_time
    ON monitoring.container_health (container_name, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_container_health_collected
    ON monitoring.container_health (collected_at DESC);

-- Auto-cleanup: keep 7 days of history.  Run via cron or pg_cron.
-- DELETE FROM monitoring.container_health WHERE collected_at < now() - interval '7 days';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('082_monitoring_container_health.sql')
ON CONFLICT (filename) DO NOTHING;
