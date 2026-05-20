-- 061_nidp_sebi_category_master.sql
--
-- The canonical SEBI Mutual Fund Categorisation master.
--
-- Why this exists
-- ───────────────
-- Pre-2026-05-21, two parallel sources of "what is a SEBI category" lived
-- in the codebase:
--   1. public.benchmark_master   (Nivesh app DB, migration 002, 33 rows)
--      — keyed by category, used by services/pg_writer.py + nav_analytics.py
--      to look up a fund's benchmark index.
--   2. services/mf_category_enricher.py regex patterns
--      — emits labels for the duplicate-fund clusterer.
--
-- They had drifted: enricher emits "Aggressive Hybrid", master has just
-- "Hybrid". A fund that the enricher labels "Multi Asset Allocation" has
-- no row in the master, so its benchmark lookup returns NULL. The user
-- directed (2026-05-20): one source of truth, comprehensive, on NIDP.
--
-- This migration creates that source of truth. After this lands:
--   - This table is the only place that defines a "valid SEBI category".
--   - The enricher's emitted labels MUST exist in this seed
--     (enforced by tests/test_sebi_category_master_vocab.py).
--   - The legacy public.benchmark_master is marked deprecated; a
--     follow-up PR will update its readers to fetch from NIDP and the
--     legacy table will be dropped once readers migrate.
--
-- Schema
-- ──────
-- One row per (category, sub_category) pair. Examples:
--   ('Large Cap',          NULL,           'Equity', …)
--   ('Index Fund',         'Nifty 50',     'Other',  …)
--   ('Index Fund',         'Sensex',       'Other',  …)
--   ('Sectoral/Thematic',  'Banking',      'Equity', …)
--
-- parent_class is the user's 2026-05-20 framework dimension
-- (Equity / Debt / Hybrid / Solution / Other) for high-level filtering.

SET search_path TO nidp, public;


CREATE TABLE IF NOT EXISTS nidp.sebi_category_master (
    category_id        SERIAL PRIMARY KEY,

    category           TEXT NOT NULL,
                       -- SEBI primary category. E.g. "Large Cap", "Index Fund",
                       -- "Aggressive Hybrid". Stable label — matches what
                       -- services/mf_category_enricher.py emits.

    sub_category       TEXT,
                       -- Finer grain when applicable; NULL otherwise.
                       --   Index Fund      → "Nifty 50" / "Nifty Next 50" / ...
                       --   Sectoral/Thematic → "Banking" / "Pharma" / ...

    parent_class       TEXT NOT NULL,
                       -- "Equity" | "Debt" | "Hybrid" | "Solution" | "Other"
                       -- (per user's 2026-05-20 SEBI framework)

    benchmark_name     TEXT,
                       -- SEBI-mandated benchmark (TRI = Total Return Index).
                       -- NULL for categories where SEBI doesn't mandate one
                       -- or where the benchmark depends on the underlying
                       -- (e.g. Fund of Funds).

    benchmark_symbol   TEXT,
                       -- Slug. Used to join nidp.index_close.index_name
                       -- when the benchmark is a published index.

    description        TEXT,

    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
                       -- Soft-delete. Set FALSE when SEBI retires a
                       -- category — keeps historical FKs valid.

    seeded_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (category, sub_category)
);

CREATE INDEX IF NOT EXISTS idx_sebi_category_parent
    ON nidp.sebi_category_master(parent_class) WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_sebi_category_active
    ON nidp.sebi_category_master(category) WHERE is_active;

COMMENT ON TABLE nidp.sebi_category_master IS
'SEBI mutual fund categorisation master. Single source of truth for valid '
'(category, sub_category) pairs. Consumed by services/mf_category_enricher '
'and pairwise-overlap clusterer. Supersedes legacy public.benchmark_master.';


-- ── Seed: Equity Funds ────────────────────────────────────────────────
INSERT INTO nidp.sebi_category_master (category, sub_category, parent_class, benchmark_name, benchmark_symbol, description) VALUES
    ('Large Cap',         NULL, 'Equity', 'NIFTY 100 TRI',                  'NIFTY_100_TRI',                'Top 100 by market cap; ≥80% in large caps'),
    ('Large & Mid Cap',   NULL, 'Equity', 'NIFTY LargeMidcap 250 TRI',      'NIFTY_LARGEMIDCAP_250_TRI',    '≥35% large + ≥35% mid cap'),
    ('Mid Cap',           NULL, 'Equity', 'NIFTY Midcap 150 TRI',           'NIFTY_MIDCAP_150_TRI',         '≥65% in mid caps (101-250 by cap)'),
    ('Small Cap',         NULL, 'Equity', 'NIFTY Smallcap 250 TRI',         'NIFTY_SMALLCAP_250_TRI',       '≥65% in small caps (251+ by cap)'),
    ('Multi Cap',         NULL, 'Equity', 'NIFTY 500 Multicap 50:25:25 TRI','NIFTY_500_MULTICAP_TRI',       'Min 25% each in large/mid/small'),
    ('Flexi Cap',         NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                '≥65% equity; dynamic cap allocation'),
    ('Focused Fund',      NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                'Max 30 stocks across all caps'),
    ('Value Fund',        NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                'Value-investing strategy'),
    ('Contra Fund',       NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                'Contrarian strategy (alt of Value)'),
    ('ELSS',              NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                'Tax-saving; 3-year lock-in'),
    ('Dividend Yield',    NULL, 'Equity', 'NIFTY 500 TRI',                  'NIFTY_500_TRI',                'Dividend-paying stock focus'),

    -- Sectoral / Thematic — one row per sector keyword the enricher emits
    ('Sectoral/Thematic', 'Banking',         'Equity', 'NIFTY Bank TRI',           'NIFTY_BANK_TRI',         NULL),
    ('Sectoral/Thematic', 'Pharma',          'Equity', 'NIFTY Pharma TRI',         'NIFTY_PHARMA_TRI',       NULL),
    ('Sectoral/Thematic', 'IT',              'Equity', 'NIFTY IT TRI',             'NIFTY_IT_TRI',           NULL),
    ('Sectoral/Thematic', 'FMCG',            'Equity', 'NIFTY FMCG TRI',           'NIFTY_FMCG_TRI',         NULL),
    ('Sectoral/Thematic', 'Consumption',     'Equity', 'NIFTY Consumption TRI',    'NIFTY_CONSUMPTION_TRI',  NULL),
    ('Sectoral/Thematic', 'Infrastructure',  'Equity', 'NIFTY Infrastructure TRI', 'NIFTY_INFRA_TRI',        NULL),
    ('Sectoral/Thematic', 'Energy',          'Equity', 'NIFTY Energy TRI',         'NIFTY_ENERGY_TRI',       NULL),
    ('Sectoral/Thematic', 'Auto',            'Equity', 'NIFTY Auto TRI',           'NIFTY_AUTO_TRI',         NULL),
    ('Sectoral/Thematic', 'MNC',             'Equity', 'NIFTY MNC TRI',            'NIFTY_MNC_TRI',          NULL),
    ('Sectoral/Thematic', 'PSU',             'Equity', 'NIFTY PSU TRI',            'NIFTY_PSU_TRI',          NULL),
    -- Generic Thematic — fund's thesis is non-sectoral (e.g. ESG, manufacturing)
    ('Sectoral/Thematic', NULL,              'Equity', 'NIFTY 500 TRI',            'NIFTY_500_TRI',          'Thematic default — non-sectoral thesis')
ON CONFLICT (category, sub_category) DO NOTHING;


-- ── Seed: Debt Funds ──────────────────────────────────────────────────
INSERT INTO nidp.sebi_category_master (category, sub_category, parent_class, benchmark_name, benchmark_symbol, description) VALUES
    ('Liquid',                NULL, 'Debt', 'CRISIL Liquid Fund Index',          'CRISIL_LIQUID',          '≤91 day maturity instruments'),
    ('Ultra Short Duration',  NULL, 'Debt', 'CRISIL Ultra Short Duration Debt Index', 'CRISIL_ULTRA_SHORT', 'Macaulay duration 3-6 months'),
    ('Low Duration',          NULL, 'Debt', 'CRISIL Low Duration Debt Index',    'CRISIL_LOW_DURATION',    'Macaulay duration 6-12 months'),
    ('Short Duration',        NULL, 'Debt', 'CRISIL Short Duration Debt Index',  'CRISIL_SHORT_DURATION',  'Macaulay duration 1-3 years'),
    ('Medium Duration',       NULL, 'Debt', 'CRISIL Medium Duration Debt Index', 'CRISIL_MEDIUM_DURATION', 'Macaulay duration 3-4 years'),
    ('Medium to Long Duration', NULL, 'Debt', 'CRISIL Medium-to-Long Duration Debt Index', 'CRISIL_MEDIUM_LONG', 'Macaulay duration 4-7 years'),
    ('Long Duration',         NULL, 'Debt', 'CRISIL Long Duration Debt Index',   'CRISIL_LONG_DURATION',   'Macaulay duration >7 years'),
    ('Money Market',          NULL, 'Debt', 'CRISIL Money Market Fund Index',    'CRISIL_MONEY_MARKET',    'Money market instruments ≤1y'),
    ('Corporate Bond',        NULL, 'Debt', 'CRISIL Corporate Bond Fund Index',  'CRISIL_CORP_BOND',       '≥80% in highest-rated corporate bonds'),
    ('Credit Risk',           NULL, 'Debt', 'CRISIL Credit Risk Fund Index',     'CRISIL_CREDIT_RISK',     '≥65% in below-highest-rated bonds'),
    ('Banking & PSU',         NULL, 'Debt', 'CRISIL Banking & PSU Debt Index',   'CRISIL_BANKING_PSU',     '≥80% bank/PSU/PFI debt'),
    ('Gilt',                  NULL, 'Debt', 'CRISIL Dynamic Gilt Index',         'CRISIL_GILT',            '≥80% in G-Secs across durations'),
    ('Gilt 10Y Constant',     NULL, 'Debt', 'CRISIL 10 Year Gilt Index',         'CRISIL_GILT_10Y',        'Constant 10y G-Sec exposure'),
    ('Dynamic Bond',          NULL, 'Debt', 'CRISIL Composite Bond Fund Index',  'CRISIL_COMP_BOND',       'Dynamic duration across the curve'),
    ('Overnight',             NULL, 'Debt', 'CRISIL Overnight Index',            'CRISIL_OVERNIGHT',       '1-day maturity instruments'),
    ('Floater',               NULL, 'Debt', 'CRISIL Floating Rate Fund Index',   'CRISIL_FLOATER',         '≥65% floating-rate instruments')
ON CONFLICT (category, sub_category) DO NOTHING;


-- ── Seed: Hybrid Funds ────────────────────────────────────────────────
INSERT INTO nidp.sebi_category_master (category, sub_category, parent_class, benchmark_name, benchmark_symbol, description) VALUES
    ('Aggressive Hybrid',       NULL, 'Hybrid', 'NIFTY 50 Hybrid Composite Debt 65:35 TRI', 'NIFTY_HYBRID_65_35', '65-80% equity, rest debt'),
    ('Balanced Advantage',      NULL, 'Hybrid', 'NIFTY 50 Hybrid Composite Debt 50:50 TRI', 'NIFTY_HYBRID_50_50', 'Dynamic equity allocation'),
    ('Equity Savings',          NULL, 'Hybrid', 'NIFTY Equity Savings Index',                'NIFTY_EQUITY_SAVINGS', 'Equity + arbitrage + debt'),
    ('Multi Asset Allocation',  NULL, 'Hybrid', NULL,                                         NULL,                  'Min 3 asset classes, ≥10% each'),
    ('Arbitrage',               NULL, 'Hybrid', 'NIFTY 50 Arbitrage Index',                   'NIFTY_ARBITRAGE',     '≥65% arbitrage opportunities'),
    ('Conservative Hybrid',     NULL, 'Hybrid', 'CRISIL Hybrid 85+15 Conservative Index',     'CRISIL_HYBRID_85_15', '10-25% equity, 75-90% debt'),
    ('Balanced Hybrid',         NULL, 'Hybrid', 'NIFTY 50 Hybrid Composite Debt 50:50 TRI',   'NIFTY_HYBRID_50_50',  '40-60% equity (no arbitrage)')
ON CONFLICT (category, sub_category) DO NOTHING;


-- ── Seed: Solution-Oriented ───────────────────────────────────────────
INSERT INTO nidp.sebi_category_master (category, sub_category, parent_class, benchmark_name, benchmark_symbol, description) VALUES
    ('Retirement Fund',   NULL, 'Solution', NULL, NULL, '5y or retirement-age lock-in'),
    ('Children''s Fund',  NULL, 'Solution', NULL, NULL, '5y or majority-age lock-in')
ON CONFLICT (category, sub_category) DO NOTHING;


-- ── Seed: Other (Index, Gold, FoF, International) ─────────────────────
INSERT INTO nidp.sebi_category_master (category, sub_category, parent_class, benchmark_name, benchmark_symbol, description) VALUES
    -- Index Fund — one row per tracked index. Sub-category is what
    -- mf_category_enricher.parse_sebi_from_name returns.
    ('Index Fund', 'Nifty 50',              'Other', 'NIFTY 50 TRI',                'NIFTY_50_TRI',              'Tracks NSE Nifty 50'),
    ('Index Fund', 'Nifty 50 Equal Weight', 'Other', 'NIFTY 50 Equal Weight TRI',   'NIFTY_50_EQUAL_WEIGHT_TRI', 'Equal-weighted Nifty 50'),
    ('Index Fund', 'Nifty Next 50',         'Other', 'NIFTY Next 50 TRI',           'NIFTY_NEXT_50_TRI',         'Tracks Nifty Next 50'),
    ('Index Fund', 'Nifty 100',             'Other', 'NIFTY 100 TRI',               'NIFTY_100_TRI',             NULL),
    ('Index Fund', 'Nifty 500',             'Other', 'NIFTY 500 TRI',               'NIFTY_500_TRI',             NULL),
    ('Index Fund', 'Nifty Midcap 150',      'Other', 'NIFTY Midcap 150 TRI',        'NIFTY_MIDCAP_150_TRI',      NULL),
    ('Index Fund', 'Nifty Smallcap 250',    'Other', 'NIFTY Smallcap 250 TRI',      'NIFTY_SMALLCAP_250_TRI',    NULL),
    ('Index Fund', 'Nifty Bank',            'Other', 'NIFTY Bank TRI',              'NIFTY_BANK_TRI',            NULL),
    ('Index Fund', 'Nifty IT',              'Other', 'NIFTY IT TRI',                'NIFTY_IT_TRI',              NULL),
    ('Index Fund', 'Sensex',                'Other', 'S&P BSE Sensex TRI',          'BSE_SENSEX_TRI',            'Tracks BSE Sensex'),
    ('Index Fund', 'BSE 500',               'Other', 'S&P BSE 500 TRI',             'BSE_500_TRI',               NULL),

    -- Other top-level categories
    ('Gold ETF',           NULL, 'Other', 'Domestic Price of Physical Gold', 'GOLD_PRICE_INR', 'Physical gold price reference'),
    ('Fund of Funds',      NULL, 'Other', NULL,                              NULL,             'Invests in other MFs; benchmark depends on underlying'),
    ('International Fund', NULL, 'Other', 'MSCI World TRI',                  'MSCI_WORLD_TRI', 'Geo-diversified equity exposure')
ON CONFLICT (category, sub_category) DO NOTHING;


-- ── Legacy public.benchmark_master deprecation note ───────────────────
-- The Nivesh app DB still has public.benchmark_master (migration 002
-- in the main migrations folder). Its readers — services/pg_writer.py
-- line 249 and services/nav_analytics.py line 278 — will be migrated
-- to read from nidp.sebi_category_master (via a DAAS endpoint) in a
-- follow-up PR. Until then, both tables coexist; the NIDP one is the
-- write-side (any new SEBI category goes here first) and the legacy
-- benchmark_master is the read-side for those two consumers only.


INSERT INTO nidp.schema_migrations (filename)
VALUES ('061_nidp_sebi_category_master.sql')
ON CONFLICT (filename) DO NOTHING;
