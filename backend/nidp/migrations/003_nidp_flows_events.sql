-- 003_nidp_flows_events.sql — Institutional flows, corporate actions, deals.
--
-- Covers:
--   2.1  fii_dii_flows      — NSE fii_stats (cash + F&O segments)
--   6.1  corporate_actions  — NSE CA feed (splits, bonus, dividends, …)
--   7.1  bulk_deals         — NSE bulk.csv
--   7.2  block_deals        — NSE block.csv

SET search_path TO nidp, public;

-- ── fii_dii_flows ───────────────────────────────────────────────────
-- NSE publishes one daily file with multiple rows: FII + DII × cash +
-- F&O segments. We normalise to long form so signal queries are
-- straightforward GROUP BY (category, segment).
CREATE TABLE IF NOT EXISTS nidp.fii_dii_flows (
    as_of_date      DATE NOT NULL,
    category        TEXT NOT NULL,                   -- 'FII' | 'DII' | 'PROP' | 'CLIENT'
    segment         TEXT NOT NULL,                   -- 'EQUITY_CASH' | 'INDEX_FUTURES' | 'INDEX_OPTIONS' | 'STOCK_FUTURES' | 'STOCK_OPTIONS'
    buy_value_cr    NUMERIC(16,4),                   -- ₹ crores
    sell_value_cr   NUMERIC(16,4),
    net_value_cr    NUMERIC(16,4),
    buy_contracts   BIGINT,                          -- F&O only; NULL for cash
    sell_contracts  BIGINT,
    net_contracts   BIGINT,
    open_interest   BIGINT,                          -- F&O only
    source          TEXT NOT NULL,                   -- 'NSE_FII_DII'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, category, segment, source)
);

CREATE INDEX IF NOT EXISTS idx_fii_dii_date
    ON nidp.fii_dii_flows(as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_fii_dii_category_date
    ON nidp.fii_dii_flows(category, as_of_date DESC);


-- ── corporate_actions ───────────────────────────────────────────────
-- NSE CA feed: one file per day containing all upcoming actions.
-- We append-only by (symbol, action_type, ex_date, source). When NSE
-- corrects a previously-announced action (rare), the new row replaces
-- the old via the same PK.
CREATE TABLE IF NOT EXISTS nidp.corporate_actions (
    symbol              TEXT NOT NULL,
    series              TEXT,
    action_type         TEXT NOT NULL,               -- 'DIVIDEND' | 'SPLIT' | 'BONUS' | 'RIGHTS' | 'MERGER' | 'DEMERGER' | 'BUYBACK' | 'AGM' | 'BOARD_MEETING' | 'OTHER'
    action_subtype      TEXT,                        -- e.g. 'INTERIM' | 'FINAL' | 'SPECIAL'
    purpose             TEXT,                        -- raw "PURPOSE" string from NSE
    ratio               TEXT,                        -- '1:1' (bonus), '5:1' (split), '₹5/share' (dividend)
    face_value_pre      NUMERIC(10,4),               -- splits only
    face_value_post     NUMERIC(10,4),
    dividend_amount     NUMERIC(14,4),               -- dividends only
    record_date         DATE,
    ex_date             DATE NOT NULL,               -- the trading day adjustment kicks in
    bc_start_date       DATE,                        -- book-closure
    bc_end_date         DATE,
    announcement_date   DATE,
    source              TEXT NOT NULL,               -- 'NSE_CA'
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, action_type, ex_date, source)
);

CREATE INDEX IF NOT EXISTS idx_corp_actions_ex_date
    ON nidp.corporate_actions(ex_date);
CREATE INDEX IF NOT EXISTS idx_corp_actions_symbol
    ON nidp.corporate_actions(symbol);
CREATE INDEX IF NOT EXISTS idx_corp_actions_type
    ON nidp.corporate_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_corp_actions_announce
    ON nidp.corporate_actions(announcement_date DESC) WHERE announcement_date IS NOT NULL;


-- ── bulk_deals ──────────────────────────────────────────────────────
-- NSE bulk.csv: client_name granularity. Same client may appear
-- multiple times on the same date if multiple trades cross the bulk
-- threshold; PK includes deal sequence to keep them distinct.
CREATE TABLE IF NOT EXISTS nidp.bulk_deals (
    as_of_date      DATE NOT NULL,
    symbol          TEXT NOT NULL,
    client_name     TEXT NOT NULL,
    deal_type       TEXT NOT NULL,                   -- 'BUY' | 'SELL'
    quantity        BIGINT NOT NULL,
    avg_price       NUMERIC(14,4) NOT NULL,
    deal_seq        INTEGER NOT NULL DEFAULT 1,      -- de-dup multiple deals same client/symbol/side/day
    remarks         TEXT,
    source          TEXT NOT NULL,                   -- 'NSE_BULK'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, symbol, client_name, deal_type, deal_seq, source)
);

CREATE INDEX IF NOT EXISTS idx_bulk_date_symbol
    ON nidp.bulk_deals(as_of_date DESC, symbol);
CREATE INDEX IF NOT EXISTS idx_bulk_client
    ON nidp.bulk_deals(client_name, as_of_date DESC);


-- ── block_deals ─────────────────────────────────────────────────────
-- Same shape as bulk_deals.
CREATE TABLE IF NOT EXISTS nidp.block_deals (
    as_of_date      DATE NOT NULL,
    symbol          TEXT NOT NULL,
    client_name     TEXT NOT NULL,
    deal_type       TEXT NOT NULL,
    quantity        BIGINT NOT NULL,
    avg_price       NUMERIC(14,4) NOT NULL,
    deal_seq        INTEGER NOT NULL DEFAULT 1,
    remarks         TEXT,
    source          TEXT NOT NULL,                   -- 'NSE_BLOCK'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, symbol, client_name, deal_type, deal_seq, source)
);

CREATE INDEX IF NOT EXISTS idx_block_date_symbol
    ON nidp.block_deals(as_of_date DESC, symbol);
CREATE INDEX IF NOT EXISTS idx_block_client
    ON nidp.block_deals(client_name, as_of_date DESC);


INSERT INTO nidp.schema_migrations(filename) VALUES ('003_nidp_flows_events.sql')
    ON CONFLICT (filename) DO NOTHING;
