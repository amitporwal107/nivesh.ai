-- 042_nidp_portfolio_bridge.sql
-- Bridge user portfolio holdings into NIDP intelligence layer WITHOUT
-- altering existing NSDL-CAS upload/portfolio persistence flows.

SET search_path TO nidp, public;

CREATE SCHEMA IF NOT EXISTS portfolio;

-- Raw synchronized holdings from upstream portfolio system.
CREATE TABLE IF NOT EXISTS portfolio.user_holdings_snapshot (
    snapshot_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_user_id     TEXT NOT NULL,
    snapshot_date        DATE NOT NULL,
    source_system        TEXT NOT NULL DEFAULT 'nsdl_cas',
    asset_class          TEXT NOT NULL, -- EQUITY | MF | ETF | DEBT | CASH | OTHER
    symbol               TEXT,
    isin                 TEXT,
    amfi_scheme_code     TEXT,
    instrument_name      TEXT,
    quantity             NUMERIC(20,6),
    avg_buy_price        NUMERIC(20,6),
    market_value_inr     NUMERIC(20,2) NOT NULL,
    weight_pct           NUMERIC(10,6),
    metadata_json        JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (external_user_id, snapshot_date, COALESCE(isin,''), COALESCE(symbol,''), COALESCE(amfi_scheme_code,''), source_system)
);

CREATE INDEX IF NOT EXISTS idx_port_user_date ON portfolio.user_holdings_snapshot(external_user_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_port_isin ON portfolio.user_holdings_snapshot(isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_port_symbol ON portfolio.user_holdings_snapshot(symbol) WHERE symbol IS NOT NULL;

-- Resolved mapping to ref.security_master.
CREATE TABLE IF NOT EXISTS portfolio.holding_security_map (
    map_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id          UUID NOT NULL REFERENCES portfolio.user_holdings_snapshot(snapshot_id) ON DELETE CASCADE,
    security_id          UUID REFERENCES ref.security_master(security_id),
    match_confidence     NUMERIC(5,2) NOT NULL DEFAULT 0,
    match_method         TEXT NOT NULL DEFAULT 'unmatched', -- isin | amfi | symbol | fuzzy | unmatched
    resolved_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_hmap_security ON portfolio.holding_security_map(security_id);

-- Daily user portfolio intelligence snapshot.
CREATE TABLE IF NOT EXISTS portfolio.user_intelligence_snapshot (
    intelligence_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_user_id     TEXT NOT NULL,
    snapshot_date        DATE NOT NULL,
    total_market_value_inr NUMERIC(20,2) NOT NULL,
    equity_weight_pct    NUMERIC(10,4),
    mf_weight_pct        NUMERIC(10,4),
    top_sector           TEXT,
    top_sector_weight_pct NUMERIC(10,4),
    concentration_top5_pct NUMERIC(10,4),
    unresolved_weight_pct NUMERIC(10,4),
    avg_beta_90d         NUMERIC(10,6),
    avg_rsi_14           NUMERIC(10,6),
    high_corr_pairs      INTEGER,
    quality_tier         TEXT,
    summary_json         JSONB,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (external_user_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_uintel_user_date ON portfolio.user_intelligence_snapshot(external_user_id, snapshot_date DESC);

INSERT INTO nidp.schema_migrations(filename)
VALUES ('042_nidp_portfolio_bridge.sql')
ON CONFLICT (filename) DO NOTHING;
