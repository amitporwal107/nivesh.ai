-- 006_nidp_views.sql — Nifty-500-scoped views.
--
-- "Run on Nifty 500" is a query-time concern, not an ingestion-time one
-- (NSE bhavcopy / delivery / FII-DII are whole-market). These views
-- expose just the Nifty 500 slice for each domain so downstream code
-- and analysts get a single, named, stable surface to query against.
--
-- Membership semantics:
--   We resolve membership using the *latest* effective-dated row in
--   nidp.index_constituents for index_name='Nifty 500'. This means
--   the view is point-in-time-current — it reflects today's Nifty 500
--   composition applied across all historical price/delivery/flow
--   data.
--
-- For point-in-time-AS-OF queries (i.e. "what was the Nifty 500 on
-- 2024-03-31?"), join nidp.index_constituents directly with an
-- as_of_date filter rather than using these views. They are a
-- convenience surface, not a substitute for the time-series.

SET search_path TO nidp, public;


-- ── Membership helper view ──────────────────────────────────────────
-- Latest Nifty 500 constituents only. Always reflects the most recent
-- ingested constituent list.
CREATE OR REPLACE VIEW nidp.v_nifty500_members AS
WITH latest AS (
    SELECT MAX(as_of_date) AS as_of_date
      FROM nidp.index_constituents
     WHERE index_name = 'Nifty 500'
)
SELECT ic.symbol, ic.isin, ic.company_name, ic.industry, ic.as_of_date
  FROM nidp.index_constituents ic
  JOIN latest l USING (as_of_date)
 WHERE ic.index_name = 'Nifty 500';

COMMENT ON VIEW nidp.v_nifty500_members IS
    'Latest Nifty 500 constituent list. Refreshed when index_constituents lands a new effective-dated batch.';


-- ── Per-domain Nifty-500-scoped views ───────────────────────────────

CREATE OR REPLACE VIEW nidp.v_nifty500_prices_eod AS
SELECT p.*
  FROM nidp.prices_eod p
  JOIN nidp.v_nifty500_members m ON m.symbol = p.symbol;

COMMENT ON VIEW nidp.v_nifty500_prices_eod IS
    'EOD OHLCV restricted to current Nifty 500 constituents.';


CREATE OR REPLACE VIEW nidp.v_nifty500_delivery AS
SELECT d.*
  FROM nidp.delivery_data d
  JOIN nidp.v_nifty500_members m ON m.symbol = d.symbol;

COMMENT ON VIEW nidp.v_nifty500_delivery IS
    'Daily delivery % restricted to current Nifty 500 constituents.';


CREATE OR REPLACE VIEW nidp.v_nifty500_corporate_actions AS
SELECT ca.*
  FROM nidp.corporate_actions ca
  JOIN nidp.v_nifty500_members m ON m.symbol = ca.symbol;

COMMENT ON VIEW nidp.v_nifty500_corporate_actions IS
    'Corporate actions restricted to current Nifty 500 constituents.';


CREATE OR REPLACE VIEW nidp.v_nifty500_bulk_deals AS
SELECT bd.*
  FROM nidp.bulk_deals bd
  JOIN nidp.v_nifty500_members m ON m.symbol = bd.symbol;


CREATE OR REPLACE VIEW nidp.v_nifty500_block_deals AS
SELECT bd.*
  FROM nidp.block_deals bd
  JOIN nidp.v_nifty500_members m ON m.symbol = bd.symbol;


-- ── Convenience: latest close per Nifty 500 stock ───────────────────
CREATE OR REPLACE VIEW nidp.v_nifty500_latest_close AS
SELECT DISTINCT ON (p.symbol)
       p.symbol, p.as_of_date, p.close_price, p.volume, p.turnover, p.isin
  FROM nidp.prices_eod p
  JOIN nidp.v_nifty500_members m ON m.symbol = p.symbol
 ORDER BY p.symbol, p.as_of_date DESC;


-- ── Coverage metadata ───────────────────────────────────────────────
-- Quick "how complete is the warehouse?" probe — used by the data-
-- health dashboard and the post-backfill report. Returns one row.
CREATE OR REPLACE VIEW nidp.v_warehouse_coverage AS
SELECT
    (SELECT count(*) FROM nidp.v_nifty500_members)            AS nifty500_members,
    (SELECT count(DISTINCT as_of_date) FROM nidp.prices_eod)  AS prices_eod_distinct_days,
    (SELECT min(as_of_date) FROM nidp.prices_eod)             AS prices_eod_first,
    (SELECT max(as_of_date) FROM nidp.prices_eod)             AS prices_eod_last,
    (SELECT count(DISTINCT as_of_date) FROM nidp.delivery_data) AS delivery_distinct_days,
    (SELECT count(DISTINCT as_of_date) FROM nidp.fii_dii_flows) AS fii_dii_distinct_days,
    (SELECT count(*) FROM nidp.corporate_actions)             AS corp_actions_total,
    (SELECT count(*) FROM nidp.bulk_deals)                    AS bulk_deals_total,
    (SELECT count(*) FROM nidp.block_deals)                   AS block_deals_total,
    (SELECT count(*) FROM nidp.nse_holidays)                  AS holidays_known;


INSERT INTO nidp.schema_migrations(filename) VALUES ('006_nidp_views.sql')
    ON CONFLICT (filename) DO NOTHING;
