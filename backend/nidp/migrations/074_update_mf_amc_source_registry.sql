-- Migration 074: Extend mf_amc_source_registry with discovery engine fields.
--
-- Adds the columns described in docs/NIDP_FEEDS/AMC_DISCLOSURES_AND_TER_REPORTS_STARTEGY.md:
--   extraction_strategy  — 'static_html' | 'playwright' | 'xhr_intercept' | 'recursive'
--   render_mode          — 'static' | 'headless' | NULL
--   regex_pattern        — POSIX regex to filter href links on the discovery page
--   validation_strategy  — 'mime' | 'content_keyword' | NULL
--   tier                 — T1 / T2 / T3 / T4 per the doc
--
-- Also corrects discovery_url values to match the doc (migration 073 had some stale paths).
--
-- KEY DESIGN PRINCIPLE (per strategy doc):
--   STORE discovery_url + extraction_strategy + regex, NOT final file URLs.
--   File URLs change monthly; discovery URLs are stable for 1-2 years.

ALTER TABLE nidp.mf_amc_source_registry
    ADD COLUMN IF NOT EXISTS ter_discovery_url       TEXT,
    ADD COLUMN IF NOT EXISTS aum_discovery_url       TEXT,
    ADD COLUMN IF NOT EXISTS portfolio_discovery_url TEXT,
    ADD COLUMN IF NOT EXISTS extraction_strategy     TEXT  DEFAULT 'static_html',
    ADD COLUMN IF NOT EXISTS render_mode             TEXT  DEFAULT 'static',
    ADD COLUMN IF NOT EXISTS regex_pattern           TEXT,
    ADD COLUMN IF NOT EXISTS validation_strategy     TEXT  DEFAULT 'mime',
    ADD COLUMN IF NOT EXISTS tier                    TEXT;

-- Update T1 AMCs (static HTML — BeautifulSoup, no browser needed)
-- Strategy: parse `a[href$='.pdf'], a[href$='.xlsx']` on the discovery page
-- and filter with regex.

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.hdfcfund.com/statutory-disclosure/total-expense-ratio-of-mutual-fund-schemes',
    portfolio_discovery_url = 'https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio',
    factsheet_url           = 'https://www.hdfcfund.com/mutual-funds/factsheets',
    extraction_strategy     = 'static_html',
    render_mode             = 'static',
    regex_pattern           = '.*(expense.ratio|ter|total.expense).*\.(pdf|xlsx)',
    validation_strategy     = 'mime',
    tier                    = 'T1',
    updated_at              = NOW()
WHERE amc_id = 'hdfc';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://mf.nipponindiaim.com/investor-services/downloads/total-expense-ratio-of-mutual-fund-schemes',
    portfolio_discovery_url = 'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures',
    extraction_strategy     = 'static_html',
    render_mode             = 'static',
    regex_pattern           = '.*(TotalExpenseRatio|expense.ratio|ter|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'mime',
    tier                    = 'T1',
    updated_at              = NOW()
WHERE amc_id = 'nippon';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.sbimf.com/disclosure',
    portfolio_discovery_url = 'https://www.sbimf.com/en-us/portfolios',
    factsheet_url           = 'https://www.sbimf.com/en-us/factsheets',
    extraction_strategy     = 'static_html',
    render_mode             = 'static',
    regex_pattern           = '.*(expense.ratio|ter|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'mime',
    tier                    = 'T1',
    updated_at              = NOW()
WHERE amc_id = 'sbi';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.tatamutualfund.com/statutory-disclosures',
    portfolio_discovery_url = 'https://www.tatamutualfund.com/schemes-related/portfolio',
    extraction_strategy     = 'static_html',
    render_mode             = 'static',
    regex_pattern           = '.*(expense.ratio|ter|statutory|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'mime',
    tier                    = 'T1',
    updated_at              = NOW()
WHERE amc_id = 'tata';

-- T2 AMC (UTI — stable but partially dynamic)
UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.utimf.com/forms-and-downloads/',
    portfolio_discovery_url = 'https://www.utimf.com/forms-and-downloads/',
    factsheet_url           = 'https://www.utimf.com/factsheets/',
    extraction_strategy     = 'static_html',
    render_mode             = 'static',
    regex_pattern           = '.*(expense|ter|portfolio|factsheet).*\.(pdf|xlsx)',
    validation_strategy     = 'mime',
    tier                    = 'T2',
    updated_at              = NOW()
WHERE amc_id = 'uti';

-- T3 AMCs (React/JS-driven — Playwright needed, deferred)
UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.icicipruamc.com/about-us/statutory-disclosures',
    portfolio_discovery_url = 'https://www.icicipruamc.com/news-and-media/downloads?currentTabFilter=OtherSchemeDisclosures&subCatTabFilter=Monthly+Portfolio+Disclosures',
    factsheet_url           = 'https://www.icicipruamc.com/downloads/fund-factsheets',
    extraction_strategy     = 'playwright',
    render_mode             = 'headless',
    regex_pattern           = '.*(portfolio|expense|ter).*\.(pdf|xlsx)',
    validation_strategy     = 'content_keyword',
    tier                    = 'T3',
    updated_at              = NOW()
WHERE amc_id = 'icici_pru';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.axismf.com/statutory-disclosures',
    portfolio_discovery_url = 'https://www.axismf.com/downloads',
    extraction_strategy     = 'playwright',
    render_mode             = 'headless',
    regex_pattern           = '.*(expense|ter|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'content_keyword',
    tier                    = 'T3',
    updated_at              = NOW()
WHERE amc_id = 'axis';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.kotakmf.com/Information/about-mutual-funds/statutory-disclosure',
    portfolio_discovery_url = 'https://www.kotakmf.com/Information/about-mutual-funds/factsheets',
    extraction_strategy     = 'playwright',
    render_mode             = 'headless',
    regex_pattern           = '.*(expense|ter|portfolio|factsheet).*\.(pdf|xlsx)',
    validation_strategy     = 'content_keyword',
    tier                    = 'T3',
    updated_at              = NOW()
WHERE amc_id = 'kotak';

UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://mutualfund.adityabirlacapital.com/downloads',
    portfolio_discovery_url = 'https://mutualfund.adityabirlacapital.com/resources',
    extraction_strategy     = 'xhr_intercept',
    render_mode             = 'headless',
    regex_pattern           = '.*(expense|ter|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'content_keyword',
    tier                    = 'T3',
    updated_at              = NOW()
WHERE amc_id = 'absl';

-- T4 AMC (Mirae — recursive/hybrid)
UPDATE nidp.mf_amc_source_registry SET
    ter_discovery_url       = 'https://www.miraeassetmf.co.in/investor-services/statutory-disclosures',
    portfolio_discovery_url = 'https://www.miraeassetmf.co.in/downloads',
    extraction_strategy     = 'recursive',
    render_mode             = 'headless',
    regex_pattern           = '.*(expense|ter|portfolio).*\.(pdf|xlsx)',
    validation_strategy     = 'content_keyword',
    tier                    = 'T4',
    updated_at              = NOW()
WHERE amc_id = 'mirae';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('074_update_mf_amc_source_registry.sql')
ON CONFLICT (filename) DO NOTHING;
