-- ── Corporate Event Intelligence ─────────────────────────────────────
-- Three tables:
--   nidp.event_calendar          — upcoming/past corporate result dates (NSE)
--   nidp.nse_financials_quarterly — structured quarterly P&L extracted from
--                                   company IR pages + NSE XBRL
--   nidp.corporate_event_signals  — AI-generated analysis per event
--                                   (bullish/bearish signal, key factors,
--                                    historical comparison, estimated impact)

-- ── 1. Event Calendar ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.event_calendar (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    company_name    TEXT,
    event_type      TEXT NOT NULL,    -- 'quarterly_results' | 'board_meeting'
                                      -- | 'agm' | 'dividend' | 'bonus'
                                      -- | 'buyback' | 'rights' | 'split'
    event_date      DATE NOT NULL,
    period          TEXT,             -- 'Q1 FY26', 'Q4 FY25', etc.
    purpose         TEXT,             -- raw NSE purpose string
    ex_date         DATE,             -- ex-dividend / ex-bonus / ex-split date
    record_date     DATE,
    source          TEXT NOT NULL DEFAULT 'nse',
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, event_type, event_date, period)
);

CREATE INDEX IF NOT EXISTS idx_event_calendar_symbol_date
    ON nidp.event_calendar(symbol, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_event_calendar_date_type
    ON nidp.event_calendar(event_date DESC, event_type);


-- ── 2. Quarterly Financials ──────────────────────────────────────────
-- Populated by nse_financials ingester from NSE XBRL + company IR pages.
-- Banking-specific columns (NIM, interest) are nullable for non-banks.
CREATE TABLE IF NOT EXISTS nidp.nse_financials_quarterly (
    id                      BIGSERIAL PRIMARY KEY,
    symbol                  TEXT NOT NULL,
    period_end              DATE NOT NULL,
    period_start            DATE,
    period_type             TEXT NOT NULL DEFAULT 'quarterly',  -- 'quarterly'|'annual'
    consolidated            BOOLEAN NOT NULL DEFAULT FALSE,
    audited                 BOOLEAN,

    -- Income Statement (₹ Crore)
    revenue_from_ops_cr     NUMERIC(18,2),
    other_income_cr         NUMERIC(18,2),
    total_income_cr         NUMERIC(18,2),
    total_expenses_cr       NUMERIC(18,2),
    ebitda_cr               NUMERIC(18,2),
    finance_costs_cr        NUMERIC(18,2),
    depreciation_cr         NUMERIC(18,2),
    pbt_before_exc_cr       NUMERIC(18,2),
    exceptional_items_cr    NUMERIC(18,2),
    pbt_cr                  NUMERIC(18,2),
    tax_expense_cr          NUMERIC(18,2),
    pat_cr                  NUMERIC(18,2),
    pat_attrib_owners_cr    NUMERIC(18,2),

    -- Per Share
    eps_basic               NUMERIC(10,4),
    eps_diluted             NUMERIC(10,4),
    face_value              NUMERIC(10,2),

    -- Balance Sheet snapshot
    total_equity_cr         NUMERIC(18,2),
    long_term_debt_cr       NUMERIC(18,2),
    short_term_debt_cr      NUMERIC(18,2),
    cash_and_equiv_cr       NUMERIC(18,2),

    -- Banking-specific
    interest_earned_cr      NUMERIC(18,2),
    interest_expended_cr    NUMERIC(18,2),
    nim_pct                 NUMERIC(8,4),

    -- Metadata
    source                  TEXT NOT NULL DEFAULT 'nse_xbrl',
                                          -- 'nse_xbrl'|'company_ir'|'llm_extracted'
    filing_id               TEXT,         -- NSE filing reference
    ir_url                  TEXT,         -- source URL if scraped
    broadcast_at            TIMESTAMPTZ,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, period_end, consolidated)
);

CREATE INDEX IF NOT EXISTS idx_financials_symbol_period
    ON nidp.nse_financials_quarterly(symbol, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_financials_period_end
    ON nidp.nse_financials_quarterly(period_end DESC);


-- ── 3. Corporate Event Signals ───────────────────────────────────────
-- AI-generated analysis for each captured event. One row per event,
-- updated if the event is re-analysed. The signal_json column carries
-- the full Claude response (key factors, historical comparison,
-- estimated impact range, reasoning).
CREATE TABLE IF NOT EXISTS nidp.corporate_event_signals (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    event_type      TEXT NOT NULL,    -- mirrors event_calendar.event_type
    event_date      DATE NOT NULL,
    period          TEXT,

    -- Top-level signal (derived from signal_json)
    sentiment       TEXT NOT NULL,    -- 'strongly_bullish' | 'bullish' |
                                      -- 'neutral' | 'bearish' | 'strongly_bearish'
    confidence      NUMERIC(5,2),     -- 0-100
    estimated_move_pct_low   NUMERIC(8,2),   -- e.g. -3.0
    estimated_move_pct_high  NUMERIC(8,2),   -- e.g. +8.0

    -- Full AI analysis (JSON)
    signal_json     JSONB NOT NULL,   -- {summary, key_factors[], risks[],
                                      --  historical_comparison, peer_context,
                                      --  data_used{}}

    -- Source data snapshot used for analysis
    financials_id   BIGINT REFERENCES nidp.nse_financials_quarterly(id),
    announcement_id BIGINT,           -- ref to nidp.announcements if applicable

    model_used      TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    analysed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (symbol, event_type, event_date, period)
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_date
    ON nidp.corporate_event_signals(symbol, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_sentiment_date
    ON nidp.corporate_event_signals(sentiment, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_date
    ON nidp.corporate_event_signals(event_date DESC);


-- ── 4. Company IR URLs ───────────────────────────────────────────────
-- Maps NSE symbol → investor relations page URL.
-- Seeded for Nifty 500; extended by the IR discovery service.
CREATE TABLE IF NOT EXISTS nidp.company_ir_urls (
    symbol          TEXT PRIMARY KEY,
    ir_url          TEXT NOT NULL,
    results_url     TEXT,             -- direct results sub-page if known
    url_verified_at TIMESTAMPTZ,
    last_scraped_at TIMESTAMPTZ,
    notes           TEXT
);


-- ── Seed Nifty 50 IR URLs ────────────────────────────────────────────
INSERT INTO nidp.company_ir_urls (symbol, ir_url, results_url) VALUES
    ('RELIANCE',    'https://www.ril.com/InvestorRelations.aspx',                   NULL),
    ('TCS',         'https://www.tcs.com/investor-relations',                        NULL),
    ('HDFCBANK',    'https://www.hdfcbank.com/content/bbp/repositories/723fb80a-2dde-42a3-9793-7ae1be57c87f/?folderPath=/Website/Personal/Investor-Relations/', NULL),
    ('BHARTIARTL',  'https://www.airtel.in/investor-relations/',                     NULL),
    ('ICICIBANK',   'https://www.icicibank.com/aboutus/annual.page',                 NULL),
    ('INFY',        'https://www.infosys.com/investors.html',                        NULL),
    ('SBIN',        'https://sbi.co.in/web/investor-relations/financial-results',    'https://sbi.co.in/web/investor-relations/financial-results'),
    ('HINDUNILVR',  'https://www.hul.co.in/investor-relations/',                     NULL),
    ('ITC',         'https://www.itcportal.com/investor-relations/',                 NULL),
    ('LT',          'https://www.larsentoubro.com/investor-relations/',              NULL),
    ('KOTAKBANK',   'https://www.kotak.com/en/investor-relations.html',              NULL),
    ('BAJFINANCE',  'https://www.bajajfinserv.in/bajaj-finance-investor-relations',  NULL),
    ('WIPRO',       'https://www.wipro.com/investors/',                              NULL),
    ('HCLTECH',     'https://www.hcltech.com/investors',                             NULL),
    ('AXISBANK',    'https://www.axisbank.com/shareholders-corner',                  NULL),
    ('ASIANPAINT',  'https://www.asianpaints.com/about/investor-relations.html',     NULL),
    ('MARUTI',      'https://www.marutisuzuki.com/corporate/investors',              NULL),
    ('SUNPHARMA',   'https://www.sunpharma.com/investors',                           NULL),
    ('TATAMOTORS',  'https://www.tatamotors.com/investors/',                         NULL),
    ('NTPC',        'https://www.ntpc.co.in/en/investors',                           NULL),
    ('POWERGRID',   'https://www.powergridindia.com/investor-relations',             NULL),
    ('ULTRACEMCO',  'https://www.ultratechcement.com/investors',                     NULL),
    ('NESTLEIND',   'https://www.nestle.in/investors',                               NULL),
    ('TITAN',       'https://www.titancompany.in/investors',                         NULL),
    ('ADANIENT',    'https://www.adanienterprises.com/investors',                    NULL),
    ('ADANIPORTS',  'https://www.adaniports.com/Investors',                          NULL),
    ('JSWSTEEL',    'https://www.jsw.in/investors/jsw-steel',                        NULL),
    ('TATASTEEL',   'https://www.tatasteel.com/investors/',                          NULL),
    ('HINDALCO',    'https://www.hindalco.com/investors',                            NULL),
    ('ONGC',        'https://www.ongcindia.com/wps/wcm/connect/ongc/home/investor-relations/', NULL),
    ('COALINDIA',   'https://www.coalindia.in/en-us/investors.aspx',                NULL),
    ('BPCL',        'https://www.bharatpetroleum.in/Investors.aspx',                NULL),
    ('CIPLA',       'https://www.cipla.com/investors',                               NULL),
    ('DRREDDY',     'https://www.drreddys.com/investors/',                           NULL),
    ('DIVISLAB',    'https://www.divislab.com/investor-relations/',                  NULL),
    ('TECHM',       'https://www.techmahindra.com/en-in/investors/',                 NULL),
    ('BAJAJFINSV',  'https://www.bajajfinserv.in/investor-relations',                NULL),
    ('GRASIM',      'https://www.grasim.com/investors',                              NULL),
    ('INDUSINDBK',  'https://www.indusind.com/iblogs/investor-relations/',           NULL),
    ('BRITANNIA',   'https://www.britannia.co.in/investor-relations/',               NULL),
    ('EICHERMOT',   'https://www.eichermotors.com/investors',                        NULL),
    ('APOLLOHOSP',  'https://www.apollohospitals.com/investor-relations/',           NULL),
    ('TATACONSUM',  'https://www.tataconsumer.com/investors',                        NULL),
    ('HEROMOTOCO',  'https://www.heromotocorp.com/en-in/investors.html',             NULL),
    ('M&M',         'https://www.mahindra.com/investors',                            NULL),
    ('BAJAJ-AUTO',  'https://www.bajajauto.com/investors',                           NULL),
    ('SBILIFE',     'https://www.sbilife.co.in/en/investor-relations',               NULL),
    ('HDFCLIFE',    'https://www.hdfclife.com/investor-relations',                   NULL),
    ('SHRIRAMFIN',  'https://www.shriramfinance.in/investor-relations',              NULL)
ON CONFLICT (symbol) DO NOTHING;


INSERT INTO nidp.schema_migrations(filename)
    VALUES ('036_nidp_corporate_events.sql')
    ON CONFLICT (filename) DO NOTHING;
