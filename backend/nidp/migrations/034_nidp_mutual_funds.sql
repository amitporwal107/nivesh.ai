-- 034_nidp_mutual_funds.sql — Mutual Fund datalake (raw external feeds).
--
-- Scope: external/raw datasources only. Derived analytics (returns,
-- risk, scoring, overlap, embeddings, recs, narratives) live in
-- backend/services/, not here. User-portfolio (CAS upload) is also
-- a separate workstream.
--
-- Tables:
--   mf_amc_master                 — AMC metadata (seed-driven, ~45 rows)
--   mf_scheme_master              — canonical scheme metadata, AMFI-driven
--   mf_nav_daily                  — daily NAV time series (Timescale hypertable)
--   mf_holdings_monthly           — monthly portfolio holdings (top-N AMCs v1)
--   mf_amfi_circulars             — addenda/notices (lifecycle event source)
--   mf_scheme_disclosure_snapshot — weekly SID/risk-o-meter/manager/TER snapshot
--   mf_scheme_events              — derived events from snapshot diffs
--   mf_benchmark_master           — scheme→index mapping; reuses nidp.index_close
--
-- Sources (per discussion):
--   amfi_nav        → AMFI NAVAll.txt (daily; carries scheme master too)
--   amfi_nav_history→ MFAPI.in JSON (backfill / gap-fill)
--   amfi_circulars  → AMFI notices/circulars HTML
--   mf_disclosure_snapshot → top-10 AMC SID pages, weekly snapshot+diff
--   mf_holdings     → top-10 AMC monthly portfolio disclosures (M+10 lag)

SET search_path TO nidp, public;


-- ── AMC master ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.mf_amc_master (
    amc_id          TEXT PRIMARY KEY,         -- short slug, e.g. 'sbi','icici_pru'
    amc_name        TEXT NOT NULL,            -- 'SBI Mutual Fund'
    amfi_amc_code   TEXT,                     -- AMFI registered code if known
    registrar       TEXT,                     -- 'CAMS' | 'KFINTECH'
    website         TEXT,
    -- Top-10 AMCs are scraped for SID/holdings in v1.
    in_top_n        BOOLEAN NOT NULL DEFAULT FALSE,
    aum_inr_crore   NUMERIC(14,2),            -- approximate, refreshed quarterly
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── Scheme master ───────────────────────────────────────────────────
-- Upserted by amfi_nav from NAVAll.txt (the file carries scheme metadata
-- inline as section headers). Treat AMFI scheme_code as canonical PK.
CREATE TABLE IF NOT EXISTS nidp.mf_scheme_master (
    scheme_code        TEXT PRIMARY KEY,            -- AMFI scheme code
    scheme_name        TEXT NOT NULL,
    amc_id             TEXT REFERENCES nidp.mf_amc_master(amc_id),
    amc_name_raw       TEXT,                        -- as printed in NAVAll.txt; resolves to amc_id
    isin_growth        TEXT,                        -- "ISIN Div Payout/ISIN Growth"
    isin_idcw          TEXT,                        -- "ISIN Div Reinvestment"
    scheme_type        TEXT,                        -- 'Open Ended Schemes' / 'Close Ended Schemes' / 'Interval Fund Schemes'
    scheme_category    TEXT,                        -- e.g. 'Equity Scheme - Large Cap Fund'
    benchmark_id       TEXT,                        -- FK to mf_benchmark_master once resolved
    launch_date        DATE,                        -- populated from disclosure snapshot when available
    status             TEXT NOT NULL DEFAULT 'active',
    -- Last NAV touch — convenience pointer; authoritative is mf_nav_daily.
    latest_nav         NUMERIC(14,4),
    latest_nav_date    DATE,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('active','closed','merged','suspended'))
);

CREATE INDEX IF NOT EXISTS idx_mf_scheme_amc      ON nidp.mf_scheme_master(amc_id);
CREATE INDEX IF NOT EXISTS idx_mf_scheme_category ON nidp.mf_scheme_master(scheme_category);
CREATE INDEX IF NOT EXISTS idx_mf_scheme_isin_g   ON nidp.mf_scheme_master(isin_growth)
    WHERE isin_growth IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mf_scheme_isin_d   ON nidp.mf_scheme_master(isin_idcw)
    WHERE isin_idcw IS NOT NULL;


-- ── Daily NAV ───────────────────────────────────────────────────────
-- ~10k schemes × ~250 trading days/yr = ~2.5M rows/yr. Timescale
-- hypertable so retention/compression are easy later.
CREATE TABLE IF NOT EXISTS nidp.mf_nav_daily (
    scheme_code     TEXT NOT NULL,
    nav_date        DATE NOT NULL,
    nav             NUMERIC(14,4) NOT NULL,
    repurchase_nav  NUMERIC(14,4),
    sale_nav        NUMERIC(14,4),
    source          TEXT NOT NULL,                 -- 'AMFI_NAVALL' | 'MFAPI'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scheme_code, nav_date, source)
);

CREATE INDEX IF NOT EXISTS idx_mf_nav_date  ON nidp.mf_nav_daily(nav_date);

-- Hypertable creation is idempotent via if_not_exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.mf_nav_daily', 'nav_date',
            chunk_time_interval => INTERVAL '90 days',
            if_not_exists => TRUE
        );
    END IF;
END $$;


-- ── Monthly holdings ────────────────────────────────────────────────
-- SEBI mandates monthly portfolio disclosure with up-to-10-day lag.
-- Each AMC publishes either Excel/CSV or PDF. v1: top-10 AMCs only.
CREATE TABLE IF NOT EXISTS nidp.mf_holdings_monthly (
    scheme_code        TEXT NOT NULL,
    as_of_month        DATE NOT NULL,                -- first day of disclosure month
    security_isin      TEXT,                          -- nullable: cash/derivatives have no ISIN
    security_name      TEXT NOT NULL,
    instrument_type    TEXT,                          -- 'EQUITY' | 'DEBT' | 'CASH' | 'DERIVATIVE' | 'REIT' | 'OTHER'
    sector             TEXT,
    rating             TEXT,                          -- credit rating for debt
    quantity           NUMERIC(20,4),
    market_value_inr   NUMERIC(20,2),
    weight_pct         NUMERIC(7,4),
    source             TEXT NOT NULL,                 -- e.g. 'SBI_MF_PORTFOLIO_XLSX'
    source_url         TEXT,
    source_run_id      UUID NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- (scheme, month, security_name) is the practical natural key —
    -- ISIN is missing for cash/derivatives so it can't be in PK.
    PRIMARY KEY (scheme_code, as_of_month, security_name, source)
);

CREATE INDEX IF NOT EXISTS idx_mf_hold_month ON nidp.mf_holdings_monthly(as_of_month);
CREATE INDEX IF NOT EXISTS idx_mf_hold_isin  ON nidp.mf_holdings_monthly(security_isin)
    WHERE security_isin IS NOT NULL;


-- ── AMFI circulars / addenda ────────────────────────────────────────
-- Source for scheme lifecycle events (mergers, renames, regulatory
-- changes). Detected by URL on listing page; body fetched if HTML/PDF
-- and stored in raw archive.
CREATE TABLE IF NOT EXISTS nidp.mf_amfi_circulars (
    circular_id      TEXT PRIMARY KEY,         -- hash of url
    published_at     DATE,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    kind             TEXT,                     -- 'notice' | 'circular' | 'addendum'
    body_text        TEXT,                     -- extracted text if obtainable
    raw_artifact_path TEXT,                    -- pointer into raw_archive
    source_run_id    UUID NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mf_circ_published ON nidp.mf_amfi_circulars(published_at DESC);


-- ── Scheme disclosure snapshot (weekly diff source) ─────────────────
-- We snapshot the values that drive event detection (TER, risk-o-meter,
-- managers). Diffing two consecutive snapshots produces mf_scheme_events.
CREATE TABLE IF NOT EXISTS nidp.mf_scheme_disclosure_snapshot (
    scheme_code        TEXT NOT NULL,
    snapshot_date      DATE NOT NULL,
    ter_pct            NUMERIC(6,4),                  -- regular plan
    ter_pct_direct     NUMERIC(6,4),                  -- direct plan
    risk_o_meter       TEXT,                          -- 'Low'..'Very High'
    primary_manager    TEXT,
    secondary_manager  TEXT,
    aum_inr_crore      NUMERIC(14,2),
    source_url         TEXT,
    source_run_id      UUID NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scheme_code, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_mf_disclose_date ON nidp.mf_scheme_disclosure_snapshot(snapshot_date);


-- ── Scheme events (derived from snapshot diffs + circular parsing) ──
CREATE TABLE IF NOT EXISTS nidp.mf_scheme_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheme_code     TEXT NOT NULL,
    event_type      TEXT NOT NULL,            -- 'ter_change' | 'manager_change' | 'risk_change' | 'merger' | 'rename' | 'launch' | 'closure'
    event_date      DATE NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    source          TEXT NOT NULL,            -- 'snapshot_diff' | 'amfi_circular' | 'manual'
    source_ref      TEXT,                     -- circular_id / snapshot_date / etc.
    source_run_id   UUID,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (event_type IN ('ter_change','manager_change','risk_change','merger','rename','launch','closure'))
);

CREATE INDEX IF NOT EXISTS idx_mf_events_scheme ON nidp.mf_scheme_events(scheme_code, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_mf_events_type   ON nidp.mf_scheme_events(event_type, event_date DESC);


-- ── Benchmark master ────────────────────────────────────────────────
-- Maps a scheme's named benchmark to an index_code already ingested by
-- nidp.index_close. Most large-cap MF benchmarks (NIFTY 50 TRI, NIFTY
-- 500 TRI, etc.) align with NSE indices we already track.
CREATE TABLE IF NOT EXISTS nidp.mf_benchmark_master (
    benchmark_id    TEXT PRIMARY KEY,            -- slug, e.g. 'nifty_50_tri'
    name            TEXT NOT NULL,               -- 'NIFTY 50 TRI'
    index_code      TEXT,                        -- joins nidp.index_close.index_name when available
    provider        TEXT,                        -- 'NSE' | 'BSE' | 'CRISIL' | etc.
    notes           TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);


-- ── Seed: top-10 AMCs ───────────────────────────────────────────────
-- AUM figures are approximate (May 2026 ranking). Refreshed quarterly.
INSERT INTO nidp.mf_amc_master (amc_id, amc_name, registrar, in_top_n, aum_inr_crore, website) VALUES
  ('sbi',         'SBI Mutual Fund',                  'CAMS',     TRUE, 1240000.00, 'https://www.sbimf.com'),
  ('icici_pru',   'ICICI Prudential Mutual Fund',     'CAMS',     TRUE, 1090000.00, 'https://www.icicipruamc.com'),
  ('hdfc',        'HDFC Mutual Fund',                 'CAMS',     TRUE,  920000.00, 'https://www.hdfcfund.com'),
  ('nippon',      'Nippon India Mutual Fund',         'KFINTECH', TRUE,  700000.00, 'https://mf.nipponindiaim.com'),
  ('kotak',       'Kotak Mahindra Mutual Fund',       'CAMS',     TRUE,  580000.00, 'https://www.kotakmf.com'),
  ('absl',        'Aditya Birla Sun Life Mutual Fund','CAMS',     TRUE,  440000.00, 'https://mutualfund.adityabirlacapital.com'),
  ('uti',         'UTI Mutual Fund',                  'KFINTECH', TRUE,  390000.00, 'https://www.utimf.com'),
  ('axis',        'Axis Mutual Fund',                 'KFINTECH', TRUE,  345000.00, 'https://www.axismf.com'),
  ('tata',        'Tata Mutual Fund',                 'CAMS',     TRUE,  220000.00, 'https://www.tatamutualfund.com'),
  ('mirae',       'Mirae Asset Mutual Fund',          'KFINTECH', TRUE,  215000.00, 'https://www.miraeassetmf.co.in')
ON CONFLICT (amc_id) DO UPDATE SET
    amc_name      = EXCLUDED.amc_name,
    registrar     = EXCLUDED.registrar,
    in_top_n      = EXCLUDED.in_top_n,
    aum_inr_crore = EXCLUDED.aum_inr_crore,
    website       = EXCLUDED.website,
    updated_at    = NOW();


-- ── Seed: benchmark master (most-used MF benchmarks) ────────────────
INSERT INTO nidp.mf_benchmark_master (benchmark_id, name, index_code, provider) VALUES
  ('nifty_50_tri',          'NIFTY 50 TRI',                'NIFTY 50',          'NSE'),
  ('nifty_100_tri',         'NIFTY 100 TRI',               'NIFTY 100',         'NSE'),
  ('nifty_200_tri',         'NIFTY 200 TRI',               'NIFTY 200',         'NSE'),
  ('nifty_500_tri',         'NIFTY 500 TRI',               'NIFTY 500',         'NSE'),
  ('nifty_midcap_150_tri',  'NIFTY Midcap 150 TRI',        'NIFTY MIDCAP 150',  'NSE'),
  ('nifty_smallcap_250_tri','NIFTY Smallcap 250 TRI',      'NIFTY SMLCAP 250',  'NSE'),
  ('nifty_bank_tri',        'NIFTY Bank TRI',              'NIFTY BANK',        'NSE'),
  ('nifty_it_tri',          'NIFTY IT TRI',                'NIFTY IT',          'NSE'),
  ('crisil_short_bond',     'CRISIL Short Term Bond Index', NULL,                'CRISIL'),
  ('crisil_composite_bond', 'CRISIL Composite Bond Index',  NULL,                'CRISIL'),
  ('crisil_liquid',         'CRISIL Liquid Fund Index',     NULL,                'CRISIL')
ON CONFLICT (benchmark_id) DO UPDATE SET
    name       = EXCLUDED.name,
    index_code = EXCLUDED.index_code,
    provider   = EXCLUDED.provider;


-- ── Register MF feeds in nidp.feeds catalog ─────────────────────────
INSERT INTO nidp.feeds (feed_id, name, description, retrieval_kind, source_table, tier, params_schema)
VALUES
  ('mf_scheme_master',
   'Mutual Fund Scheme Master',
   'Canonical mutual fund scheme catalog: AMFI scheme codes, ISINs, AMC, category, benchmark. Sourced from AMFI daily NAV file.',
   'structured',
   'nidp.mf_scheme_master',
   'free',
   '{"amc_id":{"type":"string"},"category":{"type":"string"},"isin":{"type":"string"}}'::jsonb),

  ('mf_nav_daily',
   'Mutual Fund Daily NAV',
   'Daily NAV time series for all mutual fund schemes, sourced from AMFI NAVAll.txt.',
   'structured',
   'nidp.mf_nav_daily',
   'free',
   '{"scheme_codes":{"type":"array","items":{"type":"string"}},"from_date":{"type":"string"},"to_date":{"type":"string"}}'::jsonb),

  ('mf_holdings_monthly',
   'Mutual Fund Monthly Holdings',
   'Monthly portfolio holdings for top-10 AMCs (per SEBI disclosure). M+10 lag. Securities, weights, sectors.',
   'structured',
   'nidp.mf_holdings_monthly',
   'free',
   '{"scheme_codes":{"type":"array","items":{"type":"string"}},"as_of_month":{"type":"string"},"security_isin":{"type":"string"}}'::jsonb),

  ('mf_scheme_events',
   'Mutual Fund Scheme Events',
   'Derived events: TER changes, fund-manager changes, risk-o-meter changes, mergers, renames. From snapshot diffs and AMFI circulars.',
   'structured',
   'nidp.mf_scheme_events',
   'free',
   '{"scheme_codes":{"type":"array","items":{"type":"string"}},"event_types":{"type":"array","items":{"type":"string"}},"from_date":{"type":"string"}}'::jsonb),

  ('mf_amfi_circulars',
   'AMFI Notices & Circulars',
   'AMFI-published notices, circulars, and addenda. Lifecycle event source for scheme mergers/renames/regulatory changes.',
   'text',
   'nidp.mf_amfi_circulars',
   'free',
   '{"from_date":{"type":"string"},"kind":{"enum":["notice","circular","addendum"]}}'::jsonb)
ON CONFLICT (feed_id) DO UPDATE SET
    name           = EXCLUDED.name,
    description    = EXCLUDED.description,
    retrieval_kind = EXCLUDED.retrieval_kind,
    source_table   = EXCLUDED.source_table,
    tier           = EXCLUDED.tier,
    params_schema  = EXCLUDED.params_schema,
    updated_at     = NOW();


INSERT INTO nidp.schema_migrations(filename) VALUES ('034_nidp_mutual_funds.sql')
ON CONFLICT DO NOTHING;
