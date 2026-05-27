-- Migration 073: mf_amc_source_registry
--
-- Stores canonical download URLs for each AMC's disclosure pages:
-- TER, AUM, portfolio, and factsheet landing pages.
-- Used by mf_disclosure_snapshot and mf_holdings adapters to discover
-- xlsx/pdf links without hardcoding them in Python.
--
-- amc_id matches the keys in mf_disclosure_snapshot/amc_dispatch.py ADAPTERS dict.

CREATE TABLE IF NOT EXISTS nidp.mf_amc_source_registry (
    amc_id                TEXT        PRIMARY KEY,   -- 'sbi', 'icici_pru', etc.
    amc_name              TEXT        NOT NULL,
    ter_url               TEXT,                       -- landing page for TER disclosure
    aum_url               TEXT,                       -- landing page for AUM disclosure
    portfolio_url         TEXT,                       -- landing page for monthly portfolio
    factsheet_url         TEXT,                       -- landing page for factsheets
    ter_candidates        JSONB       DEFAULT '[]',   -- ordered fallback URL list
    aum_candidates        JSONB       DEFAULT '[]',
    portfolio_candidates  JSONB       DEFAULT '[]',
    ter_last_ok           TIMESTAMPTZ,
    aum_last_ok           TIMESTAMPTZ,
    portfolio_last_ok     TIMESTAMPTZ,
    ter_last_fail         TIMESTAMPTZ,
    aum_last_fail         TIMESTAMPTZ,
    portfolio_last_fail   TIMESTAMPTZ,
    active                BOOLEAN     DEFAULT TRUE,
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- Seed data: top-10 AMCs with their disclosure landing pages
INSERT INTO nidp.mf_amc_source_registry
    (amc_id, amc_name, ter_url, aum_url, portfolio_url, factsheet_url)
VALUES

    ('sbi', 'SBI MF',
     'https://www.sbimf.com/portfolios',
     'https://www.sbimf.com/aum-disclosure',
     'https://www.sbimf.com/portfolios',
     'https://www.sbimf.com/en-us/downloads'),

    ('icici_pru', 'ICICI Prudential MF',
     'https://www.icicipruamc.com/downloads/total-expense-ratio',
     'https://www.icicipruamc.com/downloads/average-aum',
     'https://www.icicipruamc.com/downloads/monthly-portfolio',
     'https://www.icicipruamc.com/downloads/fund-factsheets'),

    ('hdfc', 'HDFC MF',
     'https://www.hdfcfund.com/statutory-disclosure/total-expense-ratio',
     'https://www.hdfcfund.com/statutory-disclosure/aum',
     'https://www.hdfcfund.com/statutory-disclosure/portfolio',
     'https://www.hdfcfund.com/downloads'),

    ('nippon', 'Nippon India MF',
     'https://mf.nipponindiaim.com/investor-service/downloads/total-expense-ratio',
     'https://mf.nipponindiaim.com/investor-service/downloads/average-aum',
     'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures',
     'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures'),

    ('kotak', 'Kotak MF',
     'https://www.kotakmf.com/Information/total-expense-ratio',
     'https://www.kotakmf.com/Information/average-aum',
     'https://www.kotakmf.com/Information/monthly-portfolio',
     'https://www.kotakmf.com/Information/factsheets'),

    ('absl', 'Aditya Birla Sun Life MF',
     'https://mutualfund.adityabirlacapital.com/total-expense-ratio',
     'https://mutualfund.adityabirlacapital.com/average-aum',
     'https://mutualfund.adityabirlacapital.com/forms-and-downloads/disclosures',
     'https://mutualfund.adityabirlacapital.com/forms-and-downloads/factsheets'),

    ('uti', 'UTI MF',
     'https://www.utimf.com/forms-and-downloads/ter',
     'https://www.utimf.com/forms-and-downloads/aum',
     'https://www.utimf.com/forms-and-downloads/portfolio',
     'https://www.utimf.com/forms-and-downloads/factsheets'),

    ('axis', 'Axis MF',
     'https://www.axismf.com/downloads/total-expense-ratio',
     'https://www.axismf.com/downloads/average-aum',
     'https://www.axismf.com/downloads/monthly-portfolio',
     'https://www.axismf.com/downloads/factsheets'),

    ('mirae', 'Mirae Asset MF',
     'https://www.miraeassetmf.co.in/downloads/total-expense-ratio',
     'https://www.miraeassetmf.co.in/downloads/average-aum',
     'https://www.miraeassetmf.co.in/downloads',
     'https://www.miraeassetmf.co.in/downloads'),

    ('tata', 'Tata MF',
     'https://www.tatamutualfund.com/total-expense-ratio',
     'https://www.tatamutualfund.com/average-aum',
     'https://www.tatamutualfund.com/downloads',
     'https://www.tatamutualfund.com/downloads')

ON CONFLICT (amc_id) DO UPDATE SET
    amc_name      = EXCLUDED.amc_name,
    ter_url       = EXCLUDED.ter_url,
    aum_url       = EXCLUDED.aum_url,
    portfolio_url = EXCLUDED.portfolio_url,
    factsheet_url = EXCLUDED.factsheet_url,
    updated_at    = NOW();


INSERT INTO nidp.schema_migrations (filename)
VALUES ('073_mf_amc_source_registry.sql')
ON CONFLICT (filename) DO NOTHING;
