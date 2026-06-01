-- Migration 088: Environment overview monitoring tables
-- Adds service_health (HTTP probe results), cron_registry (static cron catalog),
-- vm_inventory (static VM reference), and extends container_health with
-- VM name, CPU %, memory, and HTTP health-check columns.
--
-- Companion collectors:
--   container_health_collector.py  (enhanced — adds cpu/mem/vm)
--   service_health_collector.py    (new — HTTP probes all REST endpoints)

SET search_path TO monitoring, nidp, public;

-- ── 1. Extend container_health with resource + identity columns ──────────────
ALTER TABLE monitoring.container_health
    ADD COLUMN IF NOT EXISTS vm               TEXT    NOT NULL DEFAULT 'nidp-stack-vm',
    ADD COLUMN IF NOT EXISTS cpu_percent      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS mem_usage_mb     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS mem_limit_mb     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS http_url         TEXT,
    ADD COLUMN IF NOT EXISTS http_status_code INT,
    ADD COLUMN IF NOT EXISTS http_response_ms INT;

CREATE INDEX IF NOT EXISTS idx_container_health_vm_time
    ON monitoring.container_health (vm, collected_at DESC);

-- ── 2. Service health: HTTP probe results ────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitoring.service_health (
    id              BIGSERIAL       PRIMARY KEY,
    collected_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),
    vm              TEXT            NOT NULL,
    service_name    TEXT            NOT NULL,
    url             TEXT            NOT NULL,
    environment     TEXT            NOT NULL DEFAULT 'prod',
    is_up           BOOLEAN,
    http_status     INT,
    response_ms     INT,
    error_msg       TEXT
);

SELECT create_hypertable(
    'monitoring.service_health', 'collected_at',
    if_not_exists => TRUE,
    migrate_data   => TRUE
);

CREATE INDEX IF NOT EXISTS idx_service_health_name_time
    ON monitoring.service_health (service_name, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_service_health_vm_time
    ON monitoring.service_health (vm, collected_at DESC);

-- ── 3. Cron registry: static catalog of all scheduled jobs ──────────────────
CREATE TABLE IF NOT EXISTS monitoring.cron_registry (
    vm              TEXT            NOT NULL,
    job_name        TEXT            NOT NULL,
    schedule_cron   TEXT            NOT NULL,
    schedule_ist    TEXT            NOT NULL,
    description     TEXT,
    run_as          TEXT            NOT NULL DEFAULT 'nidp',
    enabled         BOOLEAN         NOT NULL DEFAULT TRUE,
    PRIMARY KEY (vm, job_name)
);

-- Seed all NIDP cron jobs (nidp-stack-vm)
INSERT INTO monitoring.cron_registry (vm, job_name, schedule_cron, schedule_ist, description) VALUES
  ('nidp-stack-vm', 'bhavcopy',                    '0 19 * * 1-5',     'IST 19:00 Mon-Fri',           'NSE EOD bhavcopy data'),
  ('nidp-stack-vm', 'index_close',                 '0 19 * * 1-5',     'IST 19:00 Mon-Fri',           'NSE index close data'),
  ('nidp-stack-vm', 'fii_dii',                     '30 19 * * 1-5',    'IST 19:30 Mon-Fri',           'FII/DII cash flow data'),
  ('nidp-stack-vm', 'bulk_deals',                  '30 19 * * 1-5',    'IST 19:30 Mon-Fri',           'NSE bulk deals'),
  ('nidp-stack-vm', 'block_deals',                 '30 19 * * 1-5',    'IST 19:30 Mon-Fri',           'NSE block deals'),
  ('nidp-stack-vm', 'fno_bhavcopy',                '30 19 * * 1-5',    'IST 19:30 Mon-Fri',           'F&O segment bhavcopy'),
  ('nidp-stack-vm', 'delivery',                    '30 10 * * 2-6',    'IST 10:30 Tue-Sat (T+1)',     'Delivery volume data'),
  ('nidp-stack-vm', 'corporate_actions',           '0 20 * * *',       'IST 20:00 daily',             'Corporate actions'),
  ('nidp-stack-vm', 'rbi_yields',                  '30 20 * * 1-5',    'IST 20:30 Mon-Fri',           'RBI yield curve data'),
  ('nidp-stack-vm', 'fred_macro',                  '0 21 * * *',       'IST 21:00 daily',             'FRED macroeconomic data'),
  ('nidp-stack-vm', 'nse_calendar',                '0 6 1 * *',        'IST 06:00 day 1',             'NSE market calendar'),
  ('nidp-stack-vm', 'index_constituents',          '30 6 1 * *',       'IST 06:30 day 1',             'NSE index constituents'),
  ('nidp-stack-vm', 'nse_financials',              '30 20 * * *',      'IST 20:30 daily',             'NSE company financials'),
  ('nidp-stack-vm', 'nse_financials.bank_npa_patch','0 21 * * *',      'IST 21:00 daily',             'Bank NPA patch (standalone)'),
  ('nidp-stack-vm', 'nse_shareholding',            '0 21 * * *',       'IST 21:00 daily',             'NSE shareholding pattern'),
  ('nidp-stack-vm', 'nse_equity_master',           '0 7 * * 0',        'IST 07:00 Sunday',            'NSE equity master list'),
  ('nidp-stack-vm', 'price_adjuster',              '30 22 * * 1-5',    'IST 22:30 Mon-Fri',           'Adj-close price calculation'),
  ('nidp-stack-vm', 'snapshot_builder',            '0 22 * * 1-5',     'IST 22:00 Mon-Fri',           'EOD stock snapshot'),
  ('nidp-stack-vm', 'corporate_announcements_nse', '*/10 9-23 * * 1-5','every 10m IST 09-23 Mon-Fri', 'NSE corporate announcements'),
  ('nidp-stack-vm', 'corporate_announcements_bse', '*/10 9-23 * * 1-5','every 10m IST 09-23 Mon-Fri', 'BSE corporate announcements'),
  ('nidp-stack-vm', 'announcement_classifier',     '*/30 * * * *',     'every 30m',                   'S4 event/impact classifier'),
  ('nidp-stack-vm', 'document_parser',             '*/15 * * * *',     'every 15m',                   'S5 document parser'),
  ('nidp-stack-vm', 'amfi_nav',                    '0 20 * * 1-5',     'IST 20:00 Mon-Fri',           'AMFI daily NAV'),
  ('nidp-stack-vm', 'amfi_circulars',              '0 9 * * *',        'IST 09:00 daily',             'AMFI circulars'),
  ('nidp-stack-vm', 'mf_disclosure_snapshot',      '0 10 12 * *',      'IST 10:00 day 12',            'MF disclosure snapshot'),
  ('nidp-stack-vm', 'mf_holdings',                 '0 11 12 * *',      'IST 11:00 day 12',            'MF portfolio holdings'),
  ('nidp-stack-vm', 'event_calendar',              '30 6,20 * * 1-5',  'IST 06:30 + 20:30 Mon-Fri',   'Corporate event calendar'),
  ('nidp-stack-vm', 'event_day_poller',            '*/5 9-16 * * 1-5', 'every 5m IST 09-16 Mon-Fri',  'Event day intraday poller'),
  ('nidp-stack-vm', 'd1_prep',                     '0 19 * * 1-5',     'IST 19:00 Mon-Fri',           'D+1 prep (events)'),
  ('nidp-stack-vm', 'intelligence',                '0 20 * * 1-5',     'IST 20:00 Mon-Fri',           'Intelligence run'),
  ('nidp-stack-vm', 'quality_gate',                '30 22 * * 1-5',    'IST 22:30 Mon-Fri',           'Post-ingestion DQ gate'),
  ('nidp-stack-vm', 'mf_analytics_engine',         '30 20 * * 1-5',    'IST 20:30 Mon-Fri',           'MF analytics engine'),
  ('nidp-stack-vm', 'mf_category_ranking',         '0 21 * * 1-5',     'IST 21:00 Mon-Fri',           'MF category ranking'),
  ('nidp-stack-vm', 'technical_indicator_engine',  '35 22 * * 1-5',    'IST 22:35 Mon-Fri',           'Technical indicators'),
  ('nidp-stack-vm', 'fundamental_engine',          '5 23 * * 1-5',     'IST 23:05 Mon-Fri',           'Fundamental scoring engine'),
  ('nidp-stack-vm', 'mf_derived_refresh',          '50 23 * * 1-5',    'IST 23:50 Mon-Fri',           'MF derived analytics refresh'),
  ('nidp-stack-vm', 'bank_scoring',                '30 21 * * *',      'IST 21:30 daily',             'Bank quality scoring'),
  ('nidp-stack-vm', 'v3_scores_engine',            '55 23 * * 1-5',    'IST 23:55 Mon-Fri',           'V3 composite scoring'),
  ('nidp-stack-vm', 'analytics_refresh',           '10 0 * * 2-6',     'IST 00:10 Tue-Sat',           'Analytics perf layer refresh'),
  ('nidp-stack-vm', 'amc_urls_drift_check',        '0 8 * * *',        'IST 08:00 daily',             'AMC URL drift checker'),
  ('nidp-stack-vm', 'portfolio_holdings_sync',     '0 23 * * 1-5',     'IST 23:00 Mon-Fri',           'Portfolio holdings sync'),
  ('nidp-stack-vm', 'portfolio_transactions_sync', '10 23 * * 1-5',    'IST 23:10 Mon-Fri',           'Portfolio transactions sync'),
  ('nidp-stack-vm', 'portfolio_goals_sync',        '15 23 * * 1-5',    'IST 23:15 Mon-Fri',           'Portfolio goals sync'),
  ('nidp-stack-vm', 'intelligence_layer',          '20 23 * * 1-5',    'IST 23:20 Mon-Fri',           'Intelligence layer materialiser'),
  ('nidp-stack-vm', 'portfolio_intelligence_sync', '30 23 * * 1-5',    'IST 23:30 Mon-Fri',           'Portfolio intelligence sync'),
  ('nidp-stack-vm', 'pra_engine',                  '45 23 * * 1-5',    'IST 23:45 Mon-Fri',           'Portfolio Risk Analytics engine'),
  ('nidp-stack-vm', 'parquet_exporter',            '30 0 * * 2-6',     'IST 00:30 Tue-Sat',           'Parquet WARM-layer export'),
  ('nidp-stack-vm', 'container_health_collector',  '* * * * *',        'every minute',                'Docker container health collector'),
  ('nidp-stack-vm', 'service_health_collector',    '* * * * *',        'every minute',                'REST service HTTP health checker'),
  ('nidp-stack-vm', 'gate4_replication_check',     '* * * * *',        'every minute',                'TimescaleDB replication check')
ON CONFLICT (vm, job_name) DO UPDATE
  SET schedule_cron = EXCLUDED.schedule_cron,
      schedule_ist  = EXCLUDED.schedule_ist,
      description   = EXCLUDED.description,
      enabled       = TRUE;

-- ── 4. VM inventory: static reference for both VMs ──────────────────────────
CREATE TABLE IF NOT EXISTS monitoring.vm_inventory (
    vm_name         TEXT            PRIMARY KEY,
    display_name    TEXT            NOT NULL,
    external_ip     TEXT,
    internal_ip     TEXT,
    domain          TEXT,
    region          TEXT            DEFAULT 'asia-south1',
    role            TEXT            NOT NULL
);

INSERT INTO monitoring.vm_inventory (vm_name, display_name, external_ip, internal_ip, domain, role) VALUES
  ('nidp-stack-vm', 'NIDP Stack VM',    NULL,           '10.160.0.3',  'data.niveshcopilot.com',    'data-pipeline'),
  ('nivesh-app-vm', 'Nivesh App VM',    '34.47.250.214','10.160.0.2',  'niveshcopilot.com',          'app-server')
ON CONFLICT (vm_name) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      domain       = EXCLUDED.domain,
      role         = EXCLUDED.role;

-- ── 5. Alert events: store inbound Grafana webhook alerts ────────────────────
CREATE TABLE IF NOT EXISTS monitoring.alert_events (
    id              BIGSERIAL       PRIMARY KEY,
    received_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
    alert_name      TEXT            NOT NULL,
    state           TEXT            NOT NULL,          -- firing, resolved
    severity        TEXT,                              -- critical, warning, info
    labels          JSONB,
    annotations     JSONB,
    generator_url   TEXT,
    environment     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_events_time
    ON monitoring.alert_events (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_events_state
    ON monitoring.alert_events (state, received_at DESC);

-- ── 6. View: latest container status per container ───────────────────────────
CREATE OR REPLACE VIEW monitoring.v_latest_containers AS
SELECT DISTINCT ON (vm, container_name)
    vm,
    environment,
    container_name,
    container_image,
    status,
    health,
    cpu_percent,
    mem_usage_mb,
    mem_limit_mb,
    ports,
    http_url,
    http_status_code,
    http_response_ms,
    uptime_seconds,
    collected_at
FROM monitoring.container_health
ORDER BY vm, container_name, collected_at DESC;

-- ── 7. View: latest service health per service ───────────────────────────────
CREATE OR REPLACE VIEW monitoring.v_latest_services AS
SELECT DISTINCT ON (vm, service_name)
    vm,
    service_name,
    url,
    environment,
    is_up,
    http_status,
    response_ms,
    error_msg,
    collected_at
FROM monitoring.service_health
ORDER BY vm, service_name, collected_at DESC;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('088_monitoring_environment_overview.sql')
ON CONFLICT (filename) DO NOTHING;
