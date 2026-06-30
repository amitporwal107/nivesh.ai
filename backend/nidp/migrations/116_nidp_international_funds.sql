-- 116_nidp_international_funds.sql — International Funds dashboard data layer.
--
-- Goal: a single, real-data-backed universe of *international investment
-- options for Indian investors* for the end-user "International Funds"
-- dashboard — across every access route, not just AMFI mutual funds:
--   Indian FoF · Indian Feeder · Indian ETF (overseas index) · Indian Domestic
--   (indirect global) · LRS Direct (US-listed ETFs bought via LRS brokers).
--
-- This replaces the ad-hoc Groww scrape-cache (`international_funds_cache` in
-- Mongo) that previously backed the recommender.
--
-- Design:
--   * nidp.international_investment_master — curated universe, seeded from
--     backend/nidp/seeds/india_international_funds_master.csv (the human-edited
--     source of truth). Keeps the access route, vehicle, geography, category,
--     expense and subscription status verbatim, plus two optional linkage keys:
--       - ticker      → US-listed symbol priced by the yfinance feed below
--                       (route = 'LRS Direct').
--       - scheme_code → AMFI scheme for Indian-routed funds, so the view can
--                       enrich them with NIDP NAV / analytics. Left NULL until
--                       a verified mapping exists (we don't guess it here).
--   * nidp.international_etf_price — latest price per US-listed ticker, upserted
--     by backend/nidp/services/intl_etf_prices/fetch_etf_prices.py (yfinance).
--   * nidp.v_international_funds — the dashboard view: master row + a unified
--     price block (LRS ticker price, else AMFI NAV) + NIDP analytics where the
--     scheme is linked and scored.

SET search_path TO nidp, public;


-- ── Curated master universe ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.international_investment_master (
    instrument_key       TEXT PRIMARY KEY,         -- stable slug (or lowercased ticker)
    fund_name            TEXT NOT NULL,
    amc                  TEXT,                      -- NULL for LRS-direct (no AMC)
    route                TEXT NOT NULL,             -- Indian FoF | Indian Feeder | Indian ETF | Indian Domestic | LRS Direct
    vehicle_type         TEXT,                      -- FoF | Feeder Fund | Domestic ETF (overseas index) | US-listed ETF | Domestic Equity Fund
    underlying           TEXT,                      -- benchmark / underlying ETF / basket
    geography            TEXT,                      -- US | Global | Europe | China | Japan | ... | Commodity
    category             TEXT,                      -- finer descriptor from the master sheet
    expense_ratio_text   TEXT,                      -- raw, preserves "1.00%+" / "approx" nuance
    expense_ratio_pct    NUMERIC(7,4),              -- parsed lower-bound %, NULL if unparseable
    subscription_status  TEXT,                      -- raw status note from the sheet
    status_class         TEXT,                      -- coarse: open | closed | verify
    ticker               TEXT,                      -- US-listed symbol → nidp.international_etf_price (LRS Direct)
    scheme_code          TEXT,                      -- AMFI scheme → nidp.mf_scheme_master (Indian routes), NULL until verified
    notes                TEXT,
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (route IN ('Indian FoF','Indian Feeder','Indian ETF','Indian Domestic','LRS Direct')),
    CHECK (status_class IN ('open','closed','verify'))
);

CREATE INDEX IF NOT EXISTS idx_intl_master_route  ON nidp.international_investment_master(route);
CREATE INDEX IF NOT EXISTS idx_intl_master_geo    ON nidp.international_investment_master(geography);
CREATE INDEX IF NOT EXISTS idx_intl_master_ticker ON nidp.international_investment_master(ticker)
    WHERE ticker IS NOT NULL;

COMMENT ON TABLE nidp.international_investment_master IS
  'Curated universe of international investment options for Indian investors '
  '(FoF / Feeder / Indian ETF / Domestic / LRS-direct US ETFs). Seeded from '
  'backend/nidp/seeds/india_international_funds_master.csv. Source of truth for '
  'GET /api/funds/international.';


-- ── US-listed ticker price feed (yfinance) ──────────────────────────
-- One latest-snapshot row per ticker, upserted by the fetch_etf_prices job.
-- Prices are delayed (~15m on the free tier) and quoted in the ticker's own
-- currency (USD for US-listed ETFs).
CREATE TABLE IF NOT EXISTS nidp.international_etf_price (
    ticker          TEXT PRIMARY KEY,
    last_price      NUMERIC(18,4),
    currency        TEXT,
    previous_close  NUMERIC(18,4),
    day_high        NUMERIC(18,4),
    day_low         NUMERIC(18,4),
    year_high       NUMERIC(18,4),
    year_low        NUMERIC(18,4),
    volume          BIGINT,
    market_cap      NUMERIC(22,2),
    exchange        TEXT,
    source          TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE nidp.international_etf_price IS
  'Latest delayed price per US-listed ticker (yfinance), upserted by '
  'backend/nidp/services/intl_etf_prices/fetch_etf_prices.py --to-db. Joined '
  'into nidp.v_international_funds for LRS-direct rows.';


-- ── Seed the master universe (generated from the CSV; keep in sync) ──
INSERT INTO nidp.international_investment_master
    (instrument_key, fund_name, amc, route, vehicle_type, underlying, geography,
     category, expense_ratio_text, expense_ratio_pct, subscription_status,
     status_class, ticker, notes)
VALUES
  ('motilal-oswal-nasdaq-100-fof', 'Motilal Oswal Nasdaq 100 FOF', 'Motilal Oswal', 'Indian FoF', 'FoF', 'Nasdaq-100 Index', 'US', 'US Tech/Large Cap', '0.20%', 0.20, 'Verify - often open', 'verify', NULL, 'Largest US tech-tracking FoF by AUM'),
  ('mirae-asset-nyse-fang-fof', 'Mirae Asset NYSE FANG+ FoF', 'Mirae Asset', 'Indian FoF', 'FoF', 'NYSE FANG+ Index', 'US', 'US Mega-cap Tech', '0.30%', 0.30, 'Verify - periodically closed', 'closed', NULL, 'Concentrated 10-stock index'),
  ('kotak-us-specific-equity-passive-fof', 'Kotak US Specific Equity Passive FoF', 'Kotak', 'Indian FoF', 'FoF', 'S&P 500 / US ETF', 'US', 'US Broad Market', '0.20%', 0.20, 'Verify - periodically closed', 'closed', NULL, 'Tracks US passive ETF'),
  ('navi-nasdaq100-us-specific-equity-passive-fof', 'Navi Nasdaq100 US Specific Equity Passive FoF', 'Navi', 'Indian FoF', 'FoF', 'Nasdaq-100 Index', 'US', 'US Tech/Large Cap', '0.20%', 0.20, 'Verify - often open', 'verify', NULL, 'Low-cost passive option'),
  ('edelweiss-us-technology-equity-fof', 'Edelweiss US Technology Equity FoF', 'Edelweiss', 'Indian FoF', 'FoF', 'US Technology basket', 'US', 'US Technology Sector', '0.70%', 0.70, 'Verify - periodically closed', 'closed', NULL, 'Active-leaning tech tilt'),
  ('aditya-birla-sun-life-us-equity-passive-fof', 'Aditya Birla Sun Life US Equity Passive FoF', 'Aditya Birla Sun Life', 'Indian FoF', 'FoF', 'US Equity Index', 'US', 'US Broad Market', '0.26%', 0.26, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('bandhan-us-specific-equity-active-fof', 'Bandhan US Specific Equity Active FoF', 'Bandhan', 'Indian FoF', 'FoF', 'US Equities (active)', 'US', 'US Broad Market', '0.70%', 0.70, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('icici-prudential-us-bluechip-equity-fund', 'ICICI Prudential US Bluechip Equity Fund', 'ICICI Prudential', 'Indian Feeder', 'Feeder Fund', 'US Bluechip basket', 'US', 'US Large Cap', '1.10%', 1.10, 'Verify - periodically closed', 'closed', NULL, 'Older feeder structure, actively managed'),
  ('franklin-india-feeder-franklin-us-opportunities-fund', 'Franklin India Feeder - Franklin US Opportunities Fund', 'Franklin Templeton', 'Indian Feeder', 'Feeder Fund', 'Franklin US Opportunities Fund', 'US', 'US Growth', '1.00%+', 1.00, 'Verify - periodically closed', 'closed', NULL, 'Feeds into Luxembourg-domiciled master fund'),
  ('invesco-india-invesco-global-consumer-trends-fof', 'Invesco India - Invesco Global Consumer Trends FoF', 'Invesco', 'Indian FoF', 'FoF', 'Invesco Global Consumer Trends Fund', 'Global', 'Global Consumer Theme', '0.60%+', 0.60, 'Reopened May 2026 - verify headroom', 'verify', NULL, 'High volatility thematic fund'),
  ('invesco-india-invesco-global-equity-income-fof', 'Invesco India - Invesco Global Equity Income FoF', 'Invesco', 'Indian FoF', 'FoF', 'Invesco Global Equity Income Fund', 'Global', 'Global Dividend/Income', '0.60%+', 0.60, 'Reopened May 2026 - verify headroom', 'verify', NULL, '46-stock concentrated global income strategy'),
  ('invesco-india-invesco-pan-european-equity-fof', 'Invesco India - Invesco Pan European Equity FoF', 'Invesco', 'Indian FoF', 'FoF', 'Invesco Pan European Equity Fund', 'Europe', 'European Equity', '0.60%+', 0.60, 'Reopened May 2026 - verify headroom', 'verify', NULL, 'Large-cap European value/transition tilt'),
  ('invesco-eqqq-nasdaq-100-etf-fof', 'Invesco EQQQ NASDAQ-100 ETF FoF', 'Invesco', 'Indian FoF', 'FoF', 'Invesco EQQQ NASDAQ-100 UCITS ETF', 'US', 'US Tech/Large Cap', '0.30%', 0.30, 'Closed since Apr 2024 - separate ETF cap', 'closed', NULL, 'Suspended under USD 1bn overseas ETF limit'),
  ('edelweiss-greater-china-equity-offshore-fund', 'Edelweiss Greater China Equity Offshore Fund', 'Edelweiss', 'Indian Feeder', 'Feeder Fund', 'China equities basket', 'China', 'Country - China', '1.00%+', 1.00, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('pgim-india-global-select-real-estate-securities-fof', 'PGIM India Global Select Real Estate Securities FoF', 'PGIM India', 'Indian FoF', 'FoF', 'Global REITs basket', 'Global', 'Real Estate/REITs', '0.75%+', 0.75, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('dsp-global-innovation-fof', 'DSP Global Innovation FoF', 'DSP', 'Indian FoF', 'FoF', 'Global innovation/disruption basket', 'Global', 'Global Thematic - Innovation', '0.75%+', 0.75, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('aditya-birla-sun-life-global-excellence-equity-fof', 'Aditya Birla Sun Life Global Excellence Equity FoF', 'Aditya Birla Sun Life', 'Indian FoF', 'FoF', 'Global large-cap equity basket', 'Global', 'Global Diversified', '0.75%+', 0.75, 'Verify - periodically closed', 'closed', NULL, NULL),
  ('nippon-india-us-equity-opportunities-fund', 'Nippon India US Equity Opportunities Fund', 'Nippon India', 'Indian Feeder', 'Feeder Fund', 'US equities basket', 'US', 'US Broad Market', '1.00%+', 1.00, 'Closed since Feb 2024', 'closed', NULL, 'Existing SIPs only'),
  ('nippon-india-japan-equity-fund', 'Nippon India Japan Equity Fund', 'Nippon India', 'Indian Feeder', 'Feeder Fund', 'Japan equities basket', 'Japan', 'Country - Japan', '1.00%+', 1.00, 'Closed since Feb 2024', 'closed', NULL, 'Existing SIPs only'),
  ('nippon-india-taiwan-equity-fund', 'Nippon India Taiwan Equity Fund', 'Nippon India', 'Indian Feeder', 'Feeder Fund', 'Taiwan equities basket', 'Taiwan', 'Country - Taiwan', '1.00%+', 1.00, 'Closed since Feb 2024', 'closed', NULL, 'Existing SIPs only'),
  ('nippon-india-etf-hang-seng-bees', 'Nippon India ETF Hang Seng BeES', 'Nippon India', 'Indian ETF', 'Domestic ETF (overseas index)', 'Hang Seng Index', 'Hong Kong', 'Country - Hong Kong', '1.00%+', 1.00, 'Closed since Feb 2024', 'closed', NULL, 'Lists on NSE like a normal ETF'),
  ('motilal-oswal-nasdaq-100-etf', 'Motilal Oswal NASDAQ 100 ETF', 'Motilal Oswal', 'Indian ETF', 'Domestic ETF (overseas index)', 'Nasdaq-100 Index', 'US', 'US Tech/Large Cap', '0.30%+', 0.30, 'Verify - subject to ETF cap', 'verify', NULL, 'Lists on NSE'),
  ('icici-prudential-mnc-fund', 'ICICI Prudential MNC Fund', 'ICICI Prudential', 'Indian Domestic', 'Domestic Equity Fund', 'Indian-listed MNC subsidiaries', 'India (indirect global)', 'Indirect Global Exposure', '1.00%+', 1.00, 'Always open', 'open', NULL, 'Indirect play - no LRS/overseas cap issue'),
  ('spy', 'SPY', NULL, 'LRS Direct', 'US-listed ETF', 'S&P 500 Index', 'US', 'US Broad Market', '0.0945%', 0.0945, 'Open via LRS broker', 'open', 'SPY', 'Buy via Vested/INDmoney Direct/IBKR'),
  ('voo', 'VOO', NULL, 'LRS Direct', 'US-listed ETF', 'S&P 500 Index', 'US', 'US Broad Market', '0.03%', 0.03, 'Open via LRS broker', 'open', 'VOO', 'Lower cost S&P 500 alternative to SPY'),
  ('qqq', 'QQQ', NULL, 'LRS Direct', 'US-listed ETF', 'Nasdaq-100 Index', 'US', 'US Tech/Large Cap', '0.20%', 0.20, 'Open via LRS broker', 'open', 'QQQ', NULL),
  ('vti', 'VTI', NULL, 'LRS Direct', 'US-listed ETF', 'CRSP US Total Market Index', 'US', 'US Total Market', '0.03%', 0.03, 'Open via LRS broker', 'open', 'VTI', NULL),
  ('vxus', 'VXUS', NULL, 'LRS Direct', 'US-listed ETF', 'FTSE Global All Cap ex US Index', 'Ex-US Global', 'Global ex-US', '0.07%', 0.07, 'Open via LRS broker', 'open', 'VXUS', NULL),
  ('vea', 'VEA', NULL, 'LRS Direct', 'US-listed ETF', 'FTSE Developed Markets ex US Index', 'Developed ex-US', 'Developed Markets', '0.05%', 0.05, 'Open via LRS broker', 'open', 'VEA', NULL),
  ('vwo', 'VWO', NULL, 'LRS Direct', 'US-listed ETF', 'FTSE Emerging Markets Index', 'Emerging Markets', 'Emerging Markets', '0.07%', 0.07, 'Open via LRS broker', 'open', 'VWO', NULL),
  ('schd', 'SCHD', NULL, 'LRS Direct', 'US-listed ETF', 'Dow Jones US Dividend 100 Index', 'US', 'US Dividend', '0.06%', 0.06, 'Open via LRS broker', 'open', 'SCHD', NULL),
  ('arkk', 'ARKK', NULL, 'LRS Direct', 'US-listed ETF', 'Actively managed - disruptive innovation', 'US/Global', 'Thematic - Innovation', '0.75%', 0.75, 'Open via LRS broker', 'open', 'ARKK', NULL),
  ('gld', 'GLD', NULL, 'LRS Direct', 'US-listed ETF', 'Gold bullion', 'Commodity', 'Gold', '0.40%', 0.40, 'Open via LRS broker', 'open', 'GLD', NULL)
ON CONFLICT (instrument_key) DO UPDATE SET
    fund_name           = EXCLUDED.fund_name,
    amc                 = EXCLUDED.amc,
    route               = EXCLUDED.route,
    vehicle_type        = EXCLUDED.vehicle_type,
    underlying          = EXCLUDED.underlying,
    geography           = EXCLUDED.geography,
    category            = EXCLUDED.category,
    expense_ratio_text  = EXCLUDED.expense_ratio_text,
    expense_ratio_pct   = EXCLUDED.expense_ratio_pct,
    subscription_status = EXCLUDED.subscription_status,
    status_class        = EXCLUDED.status_class,
    ticker              = EXCLUDED.ticker,
    notes               = EXCLUDED.notes,
    updated_at          = NOW();


-- ── Dashboard view ──────────────────────────────────────────────────
CREATE OR REPLACE VIEW nidp.v_international_funds AS

WITH latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct AS ter_direct,
        aum_inr_crore  AS aum_cr,
        risk_o_meter,
        primary_manager
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
)

SELECT
    m.instrument_key,
    m.fund_name,
    m.amc,
    m.route,
    m.vehicle_type,
    m.underlying,
    m.geography,
    m.category,
    m.expense_ratio_text,
    m.expense_ratio_pct,
    m.subscription_status,
    m.status_class,
    m.ticker,
    m.scheme_code,
    m.notes,

    -- Unified price block: LRS-direct ticker price first, else AMFI NAV.
    COALESCE(pr.last_price, ms.latest_nav)                          AS price,
    CASE WHEN pr.ticker IS NOT NULL THEN COALESCE(pr.currency,'USD')
         WHEN ms.scheme_code IS NOT NULL THEN 'INR'
         ELSE NULL END                                             AS price_currency,
    CASE
        WHEN pr.last_price IS NOT NULL AND pr.previous_close IS NOT NULL
             AND pr.previous_close <> 0
        THEN ROUND((pr.last_price - pr.previous_close) / pr.previous_close * 100, 2)
        ELSE NULL
    END                                                            AS change_pct,
    CASE WHEN pr.ticker IS NOT NULL THEN 'yfinance'
         WHEN ms.latest_nav IS NOT NULL THEN 'amfi_nav'
         ELSE NULL END                                             AS price_source,
    COALESCE(pr.fetched_at, ms.latest_nav_date::timestamptz)       AS price_as_of,
    pr.year_high,
    pr.year_low,

    -- NIDP analytics for linked + scored Indian schemes (NULL otherwise).
    sn.aum_cr,
    sn.risk_o_meter,
    p.ret_1y,
    p.ret_3y,
    p.ret_5y,
    p.sharpe,
    p.max_drawdown_pct,
    (p.scheme_code IS NOT NULL)                                    AS analytics_available

FROM nidp.international_investment_master m
LEFT JOIN nidp.international_etf_price  pr ON pr.ticker = m.ticker
LEFT JOIN nidp.mf_scheme_master        ms ON ms.scheme_code = m.scheme_code
LEFT JOIN latest_snap                  sn ON sn.scheme_code = m.scheme_code
LEFT JOIN nidp.v_v3_mf_primitives      p  ON p.scheme_code = m.scheme_code
WHERE m.enabled;

COMMENT ON VIEW nidp.v_international_funds IS
  'End-user International Funds dashboard: the curated cross-route universe '
  '(international_investment_master) with a unified price block (LRS ticker '
  'price via yfinance, else AMFI NAV) and NIDP analytics where the scheme is '
  'linked + scored. Source of truth for GET /api/funds/international.';


INSERT INTO nidp.schema_migrations(filename) VALUES ('116_nidp_international_funds.sql')
ON CONFLICT DO NOTHING;
