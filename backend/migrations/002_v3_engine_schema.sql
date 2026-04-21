-- V3 Engine Phase 0a: schema for NAV/AUM history, extended MF metadata, benchmark master.
-- Applied additively. Safe to re-run.

-- 1) Daily NAV history (AMFI EOD dump, accumulates forward from first cron run)
CREATE TABLE IF NOT EXISTS mutual_fund_nav_history (
    instrument_id UUID NOT NULL REFERENCES instrument_master(instrument_id) ON DELETE CASCADE,
    nav_date      DATE NOT NULL,
    nav           NUMERIC(12, 4) NOT NULL,
    source        TEXT DEFAULT 'amfi',
    created_at    TIMESTAMP DEFAULT now(),
    PRIMARY KEY (instrument_id, nav_date)
);
CREATE INDEX IF NOT EXISTS idx_navh_date ON mutual_fund_nav_history(nav_date);

-- 2) AUM monthly snapshots (accumulate forward)
CREATE TABLE IF NOT EXISTS mutual_fund_aum_history (
    instrument_id UUID NOT NULL REFERENCES instrument_master(instrument_id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    aum_cr        NUMERIC(12, 2) NOT NULL,
    source        TEXT DEFAULT 'groww',
    created_at    TIMESTAMP DEFAULT now(),
    PRIMARY KEY (instrument_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_aumh_date ON mutual_fund_aum_history(snapshot_date);

-- 3) Extend mutual_fund_metadata with V3 primitives we need to scrape
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS launch_date DATE;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS manager_name TEXT;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS manager_tenure_years NUMERIC(4, 1);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS expense_ratio_direct NUMERIC(5, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS expense_ratio_regular NUMERIC(5, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS benchmark_index TEXT;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS sub_category TEXT;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS amfi_scheme_code TEXT;

CREATE INDEX IF NOT EXISTS idx_mfmd_amfi_code ON mutual_fund_metadata(amfi_scheme_code) WHERE amfi_scheme_code IS NOT NULL;

-- 4) Category → Benchmark mapping (SEBI standard)
CREATE TABLE IF NOT EXISTS benchmark_master (
    category          TEXT PRIMARY KEY,   -- e.g. "Large Cap", "Mid Cap"
    benchmark_name    TEXT NOT NULL,      -- e.g. "NIFTY 100 TRI"
    benchmark_symbol  TEXT,               -- e.g. "NIFTY_100_TRI"
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT now()
);

-- Seed common SEBI categories → benchmarks (TRI = Total Return Index, the SEBI-mandated benchmark)
INSERT INTO benchmark_master (category, benchmark_name, benchmark_symbol, notes) VALUES
    ('Large Cap',          'NIFTY 100 TRI',            'NIFTY_100_TRI',           'SEBI standard for Large Cap'),
    ('Mid Cap',            'NIFTY Midcap 150 TRI',     'NIFTY_MIDCAP_150_TRI',    'SEBI standard for Mid Cap'),
    ('Small Cap',          'NIFTY Smallcap 250 TRI',   'NIFTY_SMALLCAP_250_TRI',  'SEBI standard for Small Cap'),
    ('Large & Mid Cap',    'NIFTY LargeMidcap 250 TRI','NIFTY_LARGEMIDCAP_250_TRI', 'SEBI standard'),
    ('Multi Cap',          'NIFTY 500 Multicap 50:25:25 TRI', 'NIFTY_500_MULTICAP', 'SEBI standard'),
    ('Flexi Cap',          'NIFTY 500 TRI',            'NIFTY_500_TRI',           'SEBI standard for Flexi Cap'),
    ('Focused',            'NIFTY 500 TRI',            'NIFTY_500_TRI',           'Typical benchmark'),
    ('Value Oriented',     'NIFTY 500 TRI',            'NIFTY_500_TRI',           'Typical benchmark'),
    ('ELSS',               'NIFTY 500 TRI',            'NIFTY_500_TRI',           'SEBI standard for ELSS'),
    ('Contra',             'NIFTY 500 TRI',            'NIFTY_500_TRI',           'Typical benchmark'),
    ('Dividend Yield',     'NIFTY 500 TRI',            'NIFTY_500_TRI',           'Typical benchmark'),
    ('Index',              'NIFTY 50 TRI',             'NIFTY_50_TRI',            'Default index benchmark'),
    ('Hybrid',             'NIFTY 50 Hybrid Composite Debt 65:35 TRI', 'NIFTY_HYBRID_65_35', 'Aggressive Hybrid'),
    ('Dynamic Asset Allocation', 'NIFTY 50 Hybrid Composite Debt 50:50 TRI', 'NIFTY_HYBRID_50_50', 'BAF default'),
    ('Arbitrage',          'NIFTY 50 Arbitrage Index', 'NIFTY_ARBITRAGE',         'SEBI standard'),
    ('Liquid',             'CRISIL Liquid Fund Index', 'CRISIL_LIQUID',           'SEBI standard for Liquid'),
    ('Ultra Short Duration', 'CRISIL Ultra Short Duration Debt Index', 'CRISIL_ULTRA_SHORT', 'SEBI standard'),
    ('Low Duration',       'CRISIL Low Duration Debt Index', 'CRISIL_LOW_DURATION', 'SEBI standard'),
    ('Short Duration',     'CRISIL Short Duration Debt Index', 'CRISIL_SHORT_DURATION', 'SEBI standard'),
    ('Medium Duration',    'CRISIL Medium Duration Debt Index', 'CRISIL_MEDIUM_DURATION', 'SEBI standard'),
    ('Long Duration',      'CRISIL Long Duration Debt Index', 'CRISIL_LONG_DURATION', 'SEBI standard'),
    ('Gilt',               'CRISIL Dynamic Gilt Index', 'CRISIL_GILT',             'SEBI standard for Gilt'),
    ('Corporate Bond',     'CRISIL Corporate Bond Fund Index', 'CRISIL_CORP_BOND', 'SEBI standard'),
    ('Credit Risk',        'CRISIL Credit Risk Fund Index', 'CRISIL_CREDIT_RISK', 'SEBI standard'),
    ('Money Market',       'CRISIL Money Market Fund Index', 'CRISIL_MONEY_MARKET', 'SEBI standard'),
    ('Gold',               'Price of Gold',            'GOLD_PRICE_INR',          'Domestic gold price'),
    ('International',      'MSCI World TRI',           'MSCI_WORLD_TRI',          'Typical international benchmark'),
    ('Sectoral - Banking', 'NIFTY Bank TRI',           'NIFTY_BANK_TRI',          'Sectoral Banking'),
    ('Sectoral - Pharma',  'NIFTY Pharma TRI',         'NIFTY_PHARMA_TRI',        'Sectoral Pharma'),
    ('Sectoral - IT',      'NIFTY IT TRI',             'NIFTY_IT_TRI',            'Sectoral IT'),
    ('Sectoral - FMCG',    'NIFTY FMCG TRI',           'NIFTY_FMCG_TRI',          'Sectoral FMCG'),
    ('Sectoral - Infra',   'NIFTY Infrastructure TRI', 'NIFTY_INFRA_TRI',         'Sectoral Infra'),
    ('Thematic',           'NIFTY 500 TRI',            'NIFTY_500_TRI',           'Thematic default'),
    ('Commodity',          'Commodity Index',          'COMMODITY_INDEX',         'Generic commodity')
ON CONFLICT (category) DO NOTHING;

-- 5) Track AMFI NAV fetch runs
CREATE TABLE IF NOT EXISTS amfi_nav_fetch_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    fetched_at   TIMESTAMP DEFAULT now(),
    rows_parsed  INTEGER,
    rows_upserted INTEGER,
    rows_skipped INTEGER,
    duration_ms  INTEGER,
    status       TEXT,        -- 'ok' | 'failed' | 'partial'
    error_msg    TEXT
);
CREATE INDEX IF NOT EXISTS idx_amfilog_fetched ON amfi_nav_fetch_log(fetched_at DESC);
