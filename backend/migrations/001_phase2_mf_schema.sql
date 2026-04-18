-- nivesh Phase 2 Postgres schema (UUID-based, as confirmed by user screenshot)
--
-- Tables:
--   instrument_master              — canonical instrument registry (mfs + equities)
--   mutual_fund_holdings           — per-fund stock allocation rows (scraped)
--   mutual_fund_performance_ratios — per-fund risk/return ratios (scraped)
--   mutual_fund_metadata           — AUM, NAV, expense ratio, slug (scraped)
--   scrape_audit_log               — per-scrape attempt row for the dashboard

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS instrument_master (
    instrument_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol            TEXT,                -- AMFI scheme_code / NSE symbol
    instrument_name   TEXT NOT NULL,
    instrument_type   TEXT CHECK (instrument_type IN ('EQUITY','MUTUAL_FUND','SGB')),
    isin              TEXT,
    exchange          TEXT,
    currency          TEXT DEFAULT 'INR',
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_im_symbol_type
    ON instrument_master(symbol, instrument_type) WHERE symbol IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_im_isin
    ON instrument_master(isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_im_name_trgm
    ON instrument_master(lower(instrument_name));

CREATE TABLE IF NOT EXISTS mutual_fund_holdings (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instrument_id          UUID NOT NULL REFERENCES instrument_master(instrument_id),
    holding_instrument_id  UUID REFERENCES instrument_master(instrument_id),  -- nullable if stock not seeded
    holding_name           TEXT NOT NULL,
    holding_stock_slug     TEXT,
    holding_sector         TEXT,
    holding_type           TEXT,
    weight_percent         NUMERIC(5,2),
    rank                   INTEGER,
    holding_date           DATE DEFAULT CURRENT_DATE,
    created_at             TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mfh_instr_date
    ON mutual_fund_holdings(instrument_id, holding_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mfh_instr_date_rank
    ON mutual_fund_holdings(instrument_id, holding_date, rank);

CREATE TABLE IF NOT EXISTS mutual_fund_performance_ratios (
    instrument_id      UUID NOT NULL REFERENCES instrument_master(instrument_id),
    ratios_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    pe_ratio           NUMERIC(6,2),
    pb_ratio           NUMERIC(6,2),
    alpha              NUMERIC(6,2),
    beta               NUMERIC(6,3),
    sharpe             NUMERIC(6,3),
    sortino            NUMERIC(6,3),
    std_dev            NUMERIC(6,3),
    ret_1y             NUMERIC(6,2),
    ret_3y             NUMERIC(6,2),
    ret_5y             NUMERIC(6,2),
    created_at         TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (instrument_id, ratios_date)
);

CREATE TABLE IF NOT EXISTS mutual_fund_metadata (
    instrument_id    UUID PRIMARY KEY REFERENCES instrument_master(instrument_id),
    groww_slug       TEXT,
    aum_cr           NUMERIC(12,2),
    nav              NUMERIC(12,4),
    nav_date         DATE,
    expense_ratio    NUMERIC(5,2),
    rating           INTEGER,
    risk_label       TEXT,
    category         TEXT,
    last_scraped_at  TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_audit_log (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instrument_id       UUID REFERENCES instrument_master(instrument_id),
    instrument_name     TEXT,
    slug                TEXT,
    status              TEXT CHECK (status IN ('ok','partial','failed','skipped')),
    holdings_count      INTEGER,
    validation_issues   TEXT,
    source              TEXT,                     -- fresh|cache|stale-cache
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sal_created ON scrape_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sal_instr ON scrape_audit_log(instrument_id, created_at DESC);
