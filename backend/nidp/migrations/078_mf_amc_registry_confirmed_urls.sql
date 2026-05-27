-- Migration 078: Persist confirmed working AMC portfolio URLs from 2026-05-27 ingestion run.
--
-- Context: All T1 AMC portfolio ingestion completed successfully for March + April 2026.
-- T2 Axis (March only) and T4 Mirae (April only) also confirmed working.
-- T2 UTI, T3 ABSL/ICICI Pru/Kotak remain blocked (SPA / CDN / CAPTCHA / Cognito auth).
--
-- Important parser notes:
--   - Nippon, Axis, Mirae store weight_pct as DECIMAL FRACTION (0.0421 = 4.21%).
--     Parser must multiply by 100 before inserting.
--   - SBI, HDFC, Tata store weight_pct as PERCENTAGE (4.21 stored as 4.21).
--   - HDFC per-fund xlsx discovery page publishes 100-200 individual fund files per month.
--   - SBI single xlsx covers ALL schemes (486 scheme codes).
--   - Nippon single xls covers ALL schemes (529 scheme codes).
--   - Tata single xlsx has Index sheet → sheet_code → fund_name mapping.
--   - Axis single xlsx (multi-sheet with Index) accessed via Playwright CMS API or direct download.
--     CMS token endpoint blocks direct HTTP; requires browser session.
--   - Mirae per-scheme xlsx URL pattern: /docs/default-source/portfolios/{code}-{month}{year}.xlsx
--     Known scheme codes as of 2026-05-27: see portfolio_candidates below.

-- ── SBI ──────────────────────────────────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://www.sbimf.com/en-us/Investor-Service/Monthly-Portfolio',
    portfolio_discovery_url    = 'https://www.sbimf.com/en-us/Investor-Service/Monthly-Portfolio',
    portfolio_candidates       = '[
        "https://www.sbimf.com/docs/default-source/scheme-portfolios/all-schemes-monthly-portfolio---as-on-30th-april-2026.xlsx",
        "https://www.sbimf.com/docs/default-source/scheme-portfolios/all-schemes-monthly-portfolio---as-on-31st-march-2026.xlsx"
    ]'::jsonb,
    extraction_strategy        = 'direct_xlsx_multi_sheet',
    render_mode                = 'static',
    validation_strategy        = 'isin_weight_pct',
    tier                       = 'T1',
    regex_pattern              = 'all-schemes-monthly-portfolio.*\\.xlsx',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'sbi';

-- ── HDFC ─────────────────────────────────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://files.hdfcfund.com/s3fs-public/',
    portfolio_discovery_url    = 'https://www.hdfcfund.com/tools-and-resources/fund-portfolio',
    portfolio_candidates       = '[
        "https://files.hdfcfund.com/s3fs-public/2026-05/",
        "https://files.hdfcfund.com/s3fs-public/2026-04/"
    ]'::jsonb,
    extraction_strategy        = 'listing_page_per_fund_xlsx',
    render_mode                = 'static',
    validation_strategy        = 'isin_weight_pct',
    tier                       = 'T1',
    regex_pattern              = 'Monthly HDFC .+ - \\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December) 20\\d{2}\\.xlsx',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'hdfc';

-- ── NIPPON ────────────────────────────────────────────────────────────────────
-- NOTE: weight_pct stored as decimal fraction in xlsx (0.0421 = 4.21%) — multiply × 100.
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://mf.nipponindiaim.com/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-30-April-26.xls',
    portfolio_discovery_url    = 'https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures',
    portfolio_candidates       = '[
        "https://mf.nipponindiaim.com/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-30-April-26.xls",
        "https://mf.nipponindiaim.com/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-31-Mar-26.xls"
    ]'::jsonb,
    extraction_strategy        = 'direct_xls_multi_sheet',
    render_mode                = 'static',
    validation_strategy        = 'isin_weight_decimal_fraction',
    tier                       = 'T1',
    regex_pattern              = 'NIMF-MONTHLY-PORTFOLIO-\\d{2}-[A-Za-z]+-\\d{2}\\.xls',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'nippon';

-- ── TATA ─────────────────────────────────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://betacms.tatamutualfund.com/system/files/2026-05/Monthly%20Portfolio%20as%20on%2030th%20April%202026%20%281%29.xlsx',
    portfolio_discovery_url    = 'https://www.tatamutualfund.com/investor-service/scheme-portfolio',
    portfolio_candidates       = '[
        "https://betacms.tatamutualfund.com/system/files/2026-05/Monthly%20Portfolio%20as%20on%2030th%20April%202026%20%281%29.xlsx",
        "https://betacms.tatamutualfund.com/system/files/2026-04/Monthly%20Portfolio%20as%20on%2031st%20March%202026.xlsx"
    ]'::jsonb,
    extraction_strategy        = 'direct_xlsx_multi_sheet_with_index',
    render_mode                = 'static',
    validation_strategy        = 'isin_weight_pct',
    tier                       = 'T1',
    regex_pattern              = 'Monthly Portfolio as on .+ 20\\d{2}.*\\.xlsx',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'tata';

-- ── AXIS ─────────────────────────────────────────────────────────────────────
-- NOTE: weight_pct stored as decimal fraction in xlsx (0.0426 = 4.26%) — multiply × 100.
-- March 2026 confirmed ingested (28 schemes / 1720 rows).
-- April 2026 consolidated monthly NOT yet available via CMS API as of 2026-05-27.
-- CMS token endpoint blocks direct HTTP — requires Playwright session to obtain Bearer token.
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://www.axismf.com/cms/get-scheme-documents',
    portfolio_discovery_url    = 'https://www.axismf.com/downloads/category/monthly-portfolio',
    portfolio_candidates       = '[
        {
            "type": "cms_api",
            "token_url": "https://www.axismf.com/cms/token",
            "endpoint": "https://www.axismf.com/cms/get-scheme-documents",
            "body": {"sdType": "yearMonthSchemeDocs", "sdID": "sdMonthSchemePortfolio", "year": "{year}", "month": "{month}", "schemeCode": "Consolidated"},
            "note": "Bearer token obtained from /cms/token; requires Playwright (direct HTTP blocked). Returns per-scheme xlsx links. April 2026 returns only weekly/adhoc, not consolidated monthly."
        }
    ]'::jsonb,
    extraction_strategy        = 'cms_api_bearer_token_playwright',
    render_mode                = 'playwright',
    validation_strategy        = 'isin_weight_decimal_fraction',
    tier                       = 'T2',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    portfolio_last_fail        = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'axis';

-- ── MIRAE ────────────────────────────────────────────────────────────────────
-- NOTE: weight_pct stored as decimal fraction in xlsx (0.0255 = 2.55%) — multiply × 100.
-- Per-scheme slug pattern confirmed working for April 2026 (10 schemes / 363 rows).
-- March 2026 URLs return HTML (not published) — April 2026 is earliest available.
-- Slugs discovered via Playwright on the portfolio disclosure page (Sitecore CMS).
UPDATE nidp.mf_amc_source_registry SET
    portfolio_url              = 'https://www.miraeassetmf.co.in/docs/default-source/portfolios/',
    portfolio_discovery_url    = 'https://www.miraeassetmf.co.in/investor-services/portfolio-disclosure',
    portfolio_candidates       = '[
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/ipafof-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/macmf-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/energy-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/defenfof-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/manbt-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/man1dltf-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/mafcf-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/1dgrowth-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/macif-{month}{year}.xlsx",
        "https://www.miraeassetmf.co.in/docs/default-source/portfolios/200ewfof-{month}{year}.xlsx"
    ]'::jsonb,
    extraction_strategy        = 'per_scheme_slug_xlsx_sitecore_cdn',
    render_mode                = 'playwright_discovery_then_direct',
    validation_strategy        = 'isin_weight_decimal_fraction',
    tier                       = 'T4',
    regex_pattern              = '/docs/default-source/portfolios/[a-z0-9]+-[a-z]+20[0-9]{2}\\.xlsx',
    portfolio_last_ok          = '2026-05-27 00:00:00+00',
    updated_at                 = NOW()
WHERE amc_id = 'mirae';

-- ── UTI (BLOCKED — full SPA) ─────────────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    extraction_strategy        = 'spa_js_rendered_no_static_url',
    render_mode                = 'playwright_blocked',
    tier                       = 'T2',
    portfolio_last_fail        = '2026-05-27 00:00:00+00',
    portfolio_candidates       = '[{
        "blocked": true,
        "reason": "Full React SPA — every unknown path returns home page (13988 bytes). Needs authenticated browser session or DevTools network capture to find XHR download API.",
        "suggested_fix": "Intercept network requests during manual Playwright session; extract the XHR endpoint that fetches the portfolio xlsx."
    }]'::jsonb,
    updated_at                 = NOW()
WHERE amc_id = 'uti';

-- ── ICICI PRU (BLOCKED — CDN IP block) ───────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    extraction_strategy        = 'cdn_ip_blocked_from_nidp_vm',
    render_mode                = 'playwright_blocked',
    tier                       = 'T3',
    portfolio_last_fail        = '2026-05-27 00:00:00+00',
    portfolio_candidates       = '[{
        "blocked": true,
        "reason": "icicipruamc.com resolves to Azure CDN IP 13.107.246.68 which refuses connections from GCP datacenter IPs. iciciprumf.com alternate domain is a JS SPA with CSRF token.",
        "suggested_fix": "Run ingester from non-datacenter IP (residential proxy / Nivesh app-vm) or use AMFI fallback data."
    }]'::jsonb,
    updated_at                 = NOW()
WHERE amc_id = 'icici_pru';

-- ── ABSL (BLOCKED — AWS Cognito auth) ────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    extraction_strategy        = 'aws_api_gateway_cognito_auth',
    render_mode                = 'api_auth_blocked',
    tier                       = 'T3',
    portfolio_last_fail        = '2026-05-27 00:00:00+00',
    portfolio_candidates       = '[{
        "blocked": true,
        "api": "https://api.adityabirlacapital.com/mf/portfolio/monthly/download",
        "reason": "AWS API Gateway + Cognito IAM — returns 403 ForbiddenException (x-amzn-ErrorType: ForbiddenException) without valid Cognito identity token.",
        "suggested_fix": "Script Cognito SRP auth flow with pycognito using valid app credentials (if ToS permits), or capture session token via Playwright intercepting XHR."
    }]'::jsonb,
    updated_at                 = NOW()
WHERE amc_id = 'absl';

-- ── KOTAK (BLOCKED — Radware CAPTCHA) ────────────────────────────────────────
UPDATE nidp.mf_amc_source_registry SET
    extraction_strategy        = 'radware_bot_manager_captcha',
    render_mode                = 'playwright_blocked',
    tier                       = 'T3',
    portfolio_last_fail        = '2026-05-27 00:00:00+00',
    portfolio_candidates       = '[{
        "blocked": true,
        "reason": "Radware Bot Manager CAPTCHA on all Kotak endpoints including API calls. JS fingerprinting detects headless browsers.",
        "suggested_fix": "CAPTCHA-solving service (2captcha / Anti-Captcha) or manual session cookie injection; both are unreliable against Radware."
    }]'::jsonb,
    updated_at                 = NOW()
WHERE amc_id = 'kotak';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('078_mf_amc_registry_confirmed_urls.sql')
ON CONFLICT (filename) DO NOTHING;
