-- 176: bulk/block deal history from the Trendlyne MCP feed, with transfer detection.
--
-- WHY A NEW SOURCE
-- nidp.bulk_deals / nidp.block_deals come from NSE's ROLLING csv (content/equities/bulk.csv): the
-- service's target_date only FILTERS that window, so it can never produce history. Measured
-- 2026-10-22: 7 days of bulk deals and 2 of block, against study scoring dates of 2025-12..2026-09
-- — zero overlap, so no deal feature was evaluable at all. This feed carries per-stock history
-- (capped at 200 rows per stock, which the vendor states in its response).
-- Kept separate from the NSE tables: different source, cadence and revision behaviour.
--
-- THE TRAP THIS SCHEMA EXISTS TO CATCH
-- A disclosed deal is evidence that a TRANSACTION occurred, not that an institution is
-- accumulating. The feed makes this concrete — on HAL, 2025-09-19:
--     GOLDMAN SACHS BANK EUROPE SE - ODI    Block Purchase  297,251 @ 4856.8
--     GOLDMAN SACHS (SINGAPORE) PTE - ODI   Block Sell      297,251 @ 4856.8
-- Identical quantity, price and date, between two entities of the same group: a book transfer, not
-- demand. A naive "an institution bought" rule scores it bullish. v_trendlyne_deals_net below
-- pairs these off before computing any net flow.
--
-- POINT-IN-TIME
-- deal_date is the TRADE date. Exchanges publish these after the close, so a strategy scoring on
-- date D may only use deals with deal_date < D — never deal_date = D. The feed gives no
-- publication timestamp, so that strict inequality is the conservative rule and it is enforced in
-- the feature view rather than left to each caller.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.trendlyne_deals (
    symbol          TEXT        NOT NULL,
    deal_date       DATE        NOT NULL,       -- trade date
    client_name     TEXT        NOT NULL,
    deal_type       TEXT        NOT NULL,       -- 'Bulk' | 'Block' (as the vendor labels it)
    action          TEXT        NOT NULL,       -- 'Purchase' | 'Sell'
    quantity        NUMERIC     NOT NULL,
    price           NUMERIC(18,4),
    traded_percent  NUMERIC(12,6),              -- vendor's % traded; nullable in the feed
    exchange        TEXT,                       -- NSE | BSE (same deal can appear on both)
    source          TEXT        NOT NULL DEFAULT 'trendlyne_mcp',
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_run_id   UUID,
    -- The same client can transact the same stock twice in a day at different prices, so price is
    -- part of the key; exchange too, since a deal is reported per exchange.
    PRIMARY KEY (symbol, deal_date, client_name, action, quantity, price, exchange)
);

CREATE INDEX IF NOT EXISTS idx_tl_deals_symbol_date ON nidp.trendlyne_deals (symbol, deal_date DESC);
CREATE INDEX IF NOT EXISTS idx_tl_deals_date        ON nidp.trendlyne_deals (deal_date);
CREATE INDEX IF NOT EXISTS idx_tl_deals_client      ON nidp.trendlyne_deals (client_name);

COMMENT ON TABLE nidp.trendlyne_deals IS
  'Per-stock bulk/block deal history from the Trendlyne MCP feed (vendor caps at 200 rows per '
  'stock). Both sides of every deal are retained. Evidence of a transaction, NOT of intent — see '
  'nidp.v_trendlyne_deals_net for offsetting-transfer removal.';

-- Pairs off offsetting legs, then exposes what is left as genuinely one-sided disclosed flow.
CREATE OR REPLACE VIEW nidp.v_trendlyne_deals_net AS
WITH d AS (
    SELECT *,
           -- An identical quantity and price on the same date with the opposite action is the
           -- signature of a negotiated transfer rather than net demand. Matching on
           -- (symbol, date, quantity, price) catches it regardless of how the two entities are
           -- named, which matters because group members are named inconsistently.
           EXISTS (
             SELECT 1 FROM nidp.trendlyne_deals o
              WHERE o.symbol = t.symbol AND o.deal_date = t.deal_date
                AND o.quantity = t.quantity AND o.price = t.price
                AND o.action <> t.action
           ) AS offsetting_pair
      FROM nidp.trendlyne_deals t
)
SELECT symbol,
       deal_date,
       count(*)                                                              AS legs,
       count(*) FILTER (WHERE offsetting_pair)                               AS offsetting_legs,
       -- One-sided activity only: the part that is not a matched transfer.
       count(DISTINCT client_name) FILTER (WHERE action = 'Purchase' AND NOT offsetting_pair)
                                                                             AS buying_clients,
       count(DISTINCT client_name) FILTER (WHERE action = 'Sell' AND NOT offsetting_pair)
                                                                             AS selling_clients,
       sum(quantity) FILTER (WHERE action = 'Purchase' AND NOT offsetting_pair)
                                                                             AS qty_bought,
       sum(quantity) FILTER (WHERE action = 'Sell' AND NOT offsetting_pair)   AS qty_sold,
       coalesce(sum(quantity) FILTER (WHERE action = 'Purchase' AND NOT offsetting_pair), 0)
       - coalesce(sum(quantity) FILTER (WHERE action = 'Sell' AND NOT offsetting_pair), 0)
                                                                             AS net_qty,
       sum(quantity * price) FILTER (WHERE NOT offsetting_pair)              AS gross_value_inr,
       bool_or(deal_type = 'Block')                                          AS had_block,
       bool_or(deal_type = 'Bulk')                                           AS had_bulk,
       -- TRUE when every leg paired off: a pure transfer day with no net disclosed demand.
       (count(*) = count(*) FILTER (WHERE offsetting_pair))                  AS pure_transfer_day
  FROM d
 GROUP BY symbol, deal_date;

COMMENT ON VIEW nidp.v_trendlyne_deals_net IS
  'Per symbol-day disclosed deal activity with offsetting legs removed. pure_transfer_day = every '
  'leg matched an opposite leg at the same quantity and price, i.e. an ownership transfer with no '
  'net demand. Consumers scoring on date D must filter deal_date < D: exchanges publish after the '
  'close, so same-day deals were not knowable at entry.';
