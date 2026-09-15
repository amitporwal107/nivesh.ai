-- Complete nidp.mf_amc_master so scheme rows stop losing their amc_id.
--
-- The problem
-- -----------
-- amfi_nav resolves a scheme's amc_id by prefix-matching amc_name_raw against
-- nidp.mf_amc_master. That master held only 10 AMCs, so every scheme from the
-- other 41 AMCs present in the AMFI feed got a NULL amc_id: 5,154 of 14,454
-- rows in nidp.mf_scheme_master, 5,149 of which DO carry amc_name_raw. The AMC
-- was known all along; there was simply nothing to map it to.
--
-- That silent gap is not cosmetic. The mf_holdings quant adapter looks schemes
-- up with `WHERE amc_id = 'quant'`, matched zero rows, and dropped all 29 funds
-- it had already downloaded and parsed ("unresolved fund name" x29, 2,692
-- holding rows discarded). Any adapter keyed on amc_id hits the same wall, and
-- GET /v1/mf/amcs lists `WHERE enabled = TRUE` so it was reporting 10 AMCs
-- when the warehouse holds 51.
--
-- Ids follow the existing convention (absl, icici_pru, ...) and reuse the exact
-- ids already in nidp.mf_amc_source_registry for the two AMCs that appear in
-- both: quant and jm_financial.
--
-- Prefix-collision note: the resolver matches
--     lower(amc_name_raw) LIKE lower(a.amc_name) || '%'
-- so "quant Mutual Fund" is a prefix of "Quantum Mutual Fund". Storing the FULL
-- amc_name for both (not a bare "quant") lets the resolver's
-- `ORDER BY length(a.amc_name) DESC LIMIT 1` pick the right one -- Quantum
-- resolves to quantum, quant to quant. Verified in the backfill assertion below.
--
-- The runner wraps each file in a transaction, so a failure rolls the whole
-- thing back.

INSERT INTO nidp.mf_amc_master (amc_id, amc_name) VALUES
    ('360_one', '360 ONE Mutual Fund'),
    ('abakkus', 'Abakkus Mutual Fund'),
    ('angel_one', 'Angel One Mutual Fund'),
    ('bajaj_finserv', 'Bajaj Finserv Mutual Fund'),
    ('bandhan', 'Bandhan Mutual Fund'),
    ('bank_of_india', 'Bank of India Mutual Fund'),
    ('baroda_bnp_paribas', 'Baroda BNP Paribas Mutual Fund'),
    ('canara_robeco', 'Canara Robeco Mutual Fund'),
    ('capitalmind', 'Capitalmind Mutual Fund'),
    ('choice', 'Choice Mutual Fund'),
    ('dsp', 'DSP Mutual Fund'),
    ('edelweiss', 'Edelweiss Mutual Fund'),
    ('franklin_templeton', 'Franklin Templeton Mutual Fund'),
    ('groww', 'Groww Mutual Fund'),
    ('helios', 'Helios Mutual Fund'),
    ('hsbc', 'HSBC Mutual Fund'),
    ('il_and_fs', 'IL&FS Mutual Fund (IDF)'),
    ('invesco', 'Invesco Mutual Fund'),
    ('iti', 'ITI Mutual Fund'),
    ('jio_blackrock', 'Jio BlackRock Mutual Fund'),
    ('jm_financial', 'JM Financial Mutual Fund'),
    ('lic', 'LIC Mutual Fund'),
    ('mahindra_manulife', 'Mahindra Manulife Mutual Fund'),
    ('motilal_oswal', 'Motilal Oswal Mutual Fund'),
    ('navi', 'Navi Mutual Fund'),
    ('nj', 'NJ Mutual Fund'),
    ('old_bridge', 'Old Bridge Mutual Fund'),
    ('pgim_india', 'PGIM India Mutual Fund'),
    ('ppfas', 'PPFAS Mutual Fund'),
    ('quant', 'quant Mutual Fund'),
    ('quantum', 'Quantum Mutual Fund'),
    ('samco', 'Samco Mutual Fund'),
    ('shriram', 'Shriram Mutual Fund'),
    ('sundaram', 'Sundaram Mutual Fund'),
    ('taurus', 'Taurus Mutual Fund'),
    ('the_wealth_company', 'The Wealth Company Mutual Fund'),
    ('trust', 'Trust Mutual Fund'),
    ('unifi', 'Unifi Mutual Fund'),
    ('union', 'Union Mutual Fund'),
    ('whiteoak_capital', 'WhiteOak Capital Mutual Fund'),
    ('zerodha', 'Zerodha Mutual Fund')
ON CONFLICT (amc_id) DO NOTHING;

-- Repoint nidp.mf_scheme_master at the live local table.
--
-- The canonical name is a pass-through VIEW over prod_data.mf_scheme_master, a
-- FOREIGN TABLE — so an UPDATE against it is pushed to PRODUCTION (the first
-- attempt at this migration was caught by prod's own FK: "remote SQL command:
-- UPDATE nidp.mf_scheme_master ... Key (amc_id)=(dsp) is not present"). Reads
-- through it are also stale: nidp.mf_scheme_master_local is the table amfi_nav
-- actually writes (it resolves an unwritable target at run time) and holds
-- 14,527 rows against the view's 14,454, with 14,280 touched in the last 2 days.
--
-- CREATE OR REPLACE keeps the SAME view object, so nidp.v_international_funds
-- and the nidp.v_v3_mf_primitives MATERIALIZED view stay bound to it and need
-- no rebuild — the CASCADE-and-repopulate that 132_localize_mf_nav_daily
-- deliberately deferred. Column names and types are identical to the local
-- table (verified position by position), which CREATE OR REPLACE requires, and
-- a single-table pass-through stays auto-updatable so writes keep working.
CREATE OR REPLACE VIEW nidp.mf_scheme_master AS
SELECT scheme_code, scheme_name, amc_id, amc_name_raw, isin_growth, isin_idcw,
       scheme_type, scheme_category, benchmark_id, launch_date, status,
       latest_nav, latest_nav_date, first_seen_at, updated_at
  FROM nidp.mf_scheme_master_local;

-- Backfill the unmapped schemes on the LOCAL table (never through the view --
-- see above), using the SAME rule the amfi_nav writer applies on insert so a
-- re-run of the ingester is a no-op rather than a second, differently-shaped
-- answer.
UPDATE nidp.mf_scheme_master_local s
   SET amc_id = (
           SELECT m.amc_id
             FROM nidp.mf_amc_master m
            WHERE lower(s.amc_name_raw) LIKE lower(m.amc_name) || '%'
            ORDER BY length(m.amc_name) DESC
            LIMIT 1
       ),
       updated_at = NOW()
 WHERE coalesce(s.amc_id, '') = ''
   AND s.amc_name_raw IS NOT NULL
   AND EXISTS (
           SELECT 1
             FROM nidp.mf_amc_master m
            WHERE lower(s.amc_name_raw) LIKE lower(m.amc_name) || '%'
       );

ANALYZE nidp.mf_amc_master;
ANALYZE nidp.mf_scheme_master_local;
