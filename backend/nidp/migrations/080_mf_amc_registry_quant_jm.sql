-- Migration 080: Register quant MF and JM Financial in mf_amc_source_registry.
--
-- quant MF (T2): ASP.NET two-step WebMethod API
--   Step 1: POST /statutorydisclosures.aspx/displaydisclouser1 → month list
--   Step 2: POST /statutorydisclosures.aspx/displaydisclouser2 → per-fund xlsx links
--   29 funds; weight stored as percentage (4.21 = 4.21%) — no multiplication needed.
--   API confirmed working: April + March 2026 ingested (1,725 rows, 29 funds each month).
--
-- JM Financial (T3): Static CMS per-fund fortnightly xlsx
--   Base URL: /CMS/downloads/Portfolio Disclosure/Fortnightly Portfolio of Schemes/
--   5 funds: Short Duration, Overnight, Medium to Long, Low Duration, Liquid.
--   Note: Overnight fund holds CBLO/triparty repos (no ISIN) → 0 rows expected.
--   weight stored as percentage.
--   API confirmed working: May 15 2026 fortnightly (107 rows, 4 funds with ISIN data).

INSERT INTO nidp.mf_amc_source_registry
    (amc_id, amc_name, portfolio_url, portfolio_discovery_url, portfolio_candidates,
     extraction_strategy, render_mode, validation_strategy, tier,
     portfolio_last_ok, updated_at)
VALUES
(
    'quant',
    'quant Mutual Fund',
    'https://www.quantmutual.com/statutory-disclosures',
    'https://www.quantmutual.com/statutory-disclosures',
    '[
        {
            "type": "aspnet_webmethod",
            "step1": {
                "url": "https://www.quantmutual.com/statutorydisclosures.aspx/displaydisclouser1",
                "method": "POST",
                "headers": {"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest"},
                "body": {"id": "{year}", "cat": "MONTHLY PORTFOLIO - FUND - WISE"}
            },
            "step2": {
                "url": "https://www.quantmutual.com/statutorydisclosures.aspx/displaydisclouser2",
                "method": "POST",
                "headers": {"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest"},
                "body": {"id": "{month_num}", "cat": "MONTHLY PORTFOLIO - FUND - WISE", "tab": "{year}"},
                "note": "Returns HTML with <a href> per-fund xlsx links. month_num: Jan=1..Dec=12. Parse .d field from JSON response."
            },
            "base_url": "https://www.quantmutual.com",
            "file_pattern": "/Admin/disclouser/quant_{FundName}_{Mon}_{YYYY}.xlsx"
        }
    ]'::jsonb,
    'aspnet_webmethod_two_step',
    'api',
    'isin_weight_pct',
    'T2',
    '2026-05-27 00:00:00+00',
    NOW()
),
(
    'jm_financial',
    'JM Financial Mutual Fund',
    'https://www.jmfinancialmf.com/downloads/Portfolio-Disclosure',
    'https://www.jmfinancialmf.com/downloads/Portfolio-Disclosure',
    '[
        {
            "type": "static_cms_files",
            "base_url": "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/",
            "pattern": "Fortnightly%20Portfolio-%20JM%20{FundNameEncoded}%20-%20{Month}%20{Day}%2C%20{Year}.xlsx",
            "known_funds": [
                "Short Duration Fund",
                "Overnight Fund",
                "Medium to Long Duration Fund",
                "Low Duration Fund",
                "Liquid Fund"
            ],
            "confirmed_working_urls": [
                "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/Fortnightly%20Portfolio-%20JM%20Short%20Duration%20Fund%20-%20May%2015,%202026.xlsx",
                "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/Fortnightly%20Portfolio-%20JM%20Overnight%20Fund%20-%20%20%20May%2015,%202026.xlsx",
                "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/Fortnightly%20Portfolio-%20JM%20Medium%20to%20Long%20Duration%20Fund%20-%20May%2015,%202026.xlsx",
                "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/Fortnightly%20Portfolio-%20JM%20Low%20Duration%20Fund%20-%20%20May%2015,%202026.xlsx",
                "https://www.jmfinancialmf.com/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/Fortnightly%20Portfolio-%20JM%20Liquid%20Fund%20-%20%20%20May%2015%202026.xlsx"
            ],
            "note": "Fortnightly disclosure only (no monthly consolidated). Overnight fund holds CBLO/repos — 0 ISINs expected. jmmfapi.jmfinancialmf.com returns AES-encrypted data — do NOT use the API, use direct static links."
        }
    ]'::jsonb,
    'static_cms_per_fund_xlsx',
    'static',
    'isin_weight_pct',
    'T3',
    '2026-05-27 00:00:00+00',
    NOW()
)
ON CONFLICT (amc_id) DO UPDATE
    SET portfolio_url              = EXCLUDED.portfolio_url,
        portfolio_discovery_url    = EXCLUDED.portfolio_discovery_url,
        portfolio_candidates       = EXCLUDED.portfolio_candidates,
        extraction_strategy        = EXCLUDED.extraction_strategy,
        render_mode                = EXCLUDED.render_mode,
        validation_strategy        = EXCLUDED.validation_strategy,
        tier                       = EXCLUDED.tier,
        portfolio_last_ok          = EXCLUDED.portfolio_last_ok,
        updated_at                 = NOW();


INSERT INTO nidp.schema_migrations (filename)
VALUES ('080_mf_amc_registry_quant_jm.sql')
ON CONFLICT (filename) DO NOTHING;
