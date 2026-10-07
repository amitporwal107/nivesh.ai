-- 153_bse_scrip_master_daily.sql — point-in-time BSE scrip ↔ ISIN ↔ ticker master.
--
-- Source:   BSE SEBI-standard daily equity bhavcopy (the file nidp already fetches
--           as an NSE fallback — see nidp/shared/sources/bse_fetcher.py)
-- Cadence:  Daily, one row per scrip per trading day
-- Output:   nidp.bse_scrip_master_daily
--
-- THE PROBLEM THIS SOLVES
--
-- A BSE filing carries a 6-digit scrip code and nothing else. An NSE filing carries
-- a ticker and an ISIN. Measured on nidp_staging 2026-09-25:
--
--     nidp.corporate_announcements     rows
--     ---------------------------------------
--     total                          219,504
--     with ticker_symbol + isin      110,270   (NSE-sourced)
--     with scrip_code                109,188   (BSE-sourced)
--     with BOTH                            0   <-- the sets are disjoint
--
-- So half the announcement corpus cannot be joined to a price series at all.
-- ref.security_master (migration 041) has a `bse_code` column for exactly this,
-- and it is populated for 0 of 4,924 equities — no code path writes it. Migration
-- 129 works around the gap with a normalised-company-name join and calls itself a
-- "DOCUMENTED STOPGAP".
--
-- The cost, measured on 473 takeover/open-offer filings (2026-01-19..09-25):
--
--     resolve to a BSE scrip code      426/473   (90%)
--     scrip -> ISIN                    330/426   (77%)
--     ISIN -> NSE symbol               151/330   (46%)
--
-- THE FIX IS ALREADY HALF-WRITTEN
--
-- parse_bse_scrip_isin() in services/bhavcopy/parser.py already builds
-- {scrip_code -> ISIN} from each day's BSE bhavcopy. delivery/writer.py and
-- bhavcopy/writer.py consume it, resolve scrip -> ISIN -> NSE symbol, write only
-- the NSE symbol, and throw the map away. BSE-only scrips are dropped outright
-- ("ISIN not in NSE universe"). This migration persists what is already computed.
--
-- WHY ONE ROW PER DAY, NOT ONE PER SCRIP
--
-- sector_master is a destructive upsert, so it answers "what is this symbol today"
-- and silently rewrites history. Three things drift and matter here:
--
--   * bse_group   — a scrip moves between A / B / X / XT / T / Z / M as surveillance
--                   reclassifies it. Today's group copied onto a past event is
--                   look-ahead, and the group decides whether a fill was possible
--                   at all (X/XT/Z/T are trade-for-trade or restricted).
--   * company_name — renames break name-based joins retroactively.
--   * existence    — a scrip that stops appearing has delisted or been suspended.
--                    That absence IS the delisting signal, and it is the only
--                    survivorship-honest one available: nidp has no delisting table.
--
-- One row per (day, scrip) keeps all three point-in-time, the same argument
-- migration 138 makes for security_reference_daily.
--
-- The daily file carries ~4,999 equity scrips (measured 2026-09-24) and is
-- retrievable back to at least 2023-06-01 (HTTP 200), so the table can be
-- backfilled to the prices_eod floor of 2024-05-31 without an external source.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.bse_scrip_master_daily (
    as_of_date       DATE NOT NULL,                 -- the bhavcopy's trading date
    scrip_code       TEXT NOT NULL,                 -- BSE FinInstrmId, e.g. '500002'
    isin             TEXT,                          -- NULL only for a malformed row
    bse_ticker       TEXT,                          -- BSE TckrSymb, e.g. 'ABB'
    bse_group        TEXT,                          -- SctySrs: A|B|X|XT|T|Z|M|MT|...
    company_name     TEXT,                          -- FinInstrmNm as filed that day

    -- Provenance
    source           TEXT NOT NULL DEFAULT 'BSE_BHAVCOPY',
    source_run_id    UUID NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (as_of_date, scrip_code)
);

COMMENT ON TABLE nidp.bse_scrip_master_daily IS
    'Point-in-time BSE scrip master, one row per scrip per trading day, parsed from '
    'the BSE daily equity bhavcopy. Resolves a BSE-only filing (scrip_code) to an '
    'ISIN and thence to an NSE symbol via sector_master.isin. bse_group is the '
    'surveillance/trading group ON THAT DAY; a scrip that stops appearing has '
    'delisted or been suspended.';

COMMENT ON COLUMN nidp.bse_scrip_master_daily.bse_group IS
    'BSE SctySrs on that day. A/B trade normally; X/XT/T/Z/M are trade-for-trade '
    'or restricted, which gates executability (PRD 10.1) and is NOT recoverable '
    'from a current-state master.';

-- The join this table exists to serve: scrip_code -> ISIN -> sector_master.symbol.
CREATE INDEX IF NOT EXISTS idx_bse_scrip_master_isin
    ON nidp.bse_scrip_master_daily (isin, as_of_date DESC) WHERE isin IS NOT NULL;

-- "What was this scrip on date D", and the per-scrip history scan behind
-- v_bse_scrip_coverage below.
CREATE INDEX IF NOT EXISTS idx_bse_scrip_master_scrip
    ON nidp.bse_scrip_master_daily (scrip_code, as_of_date DESC);

-- Per-scrip lifetime: first/last trading day, and how many distinct groups and
-- names it has carried. last_seen materially before the table's max date is the
-- delisting / suspension proxy.
CREATE OR REPLACE VIEW nidp.v_bse_scrip_coverage AS
SELECT
    scrip_code,
    min(as_of_date)                              AS first_seen,
    max(as_of_date)                              AS last_seen,
    count(*)                                     AS sessions,
    count(DISTINCT isin)                         AS distinct_isins,
    count(DISTINCT bse_group)                    AS distinct_groups,
    count(DISTINCT company_name)                 AS distinct_names,
    (array_agg(isin         ORDER BY as_of_date DESC))[1] AS latest_isin,
    (array_agg(bse_ticker   ORDER BY as_of_date DESC))[1] AS latest_ticker,
    (array_agg(bse_group    ORDER BY as_of_date DESC))[1] AS latest_group,
    (array_agg(company_name ORDER BY as_of_date DESC))[1] AS latest_name
FROM nidp.bse_scrip_master_daily
GROUP BY scrip_code;

COMMENT ON VIEW nidp.v_bse_scrip_coverage IS
    'Per-scrip lifetime from the daily master. last_seen well before the table max '
    'means delisted or suspended. distinct_isins > 1 means an ISIN change (face-value '
    'split or scheme) — those break naive ISIN joins and must be resolved as-of-date.';

-- ── Resolver ────────────────────────────────────────────────────────────────
--
-- scrip_code -> NSE symbol is not quite a 1:1 join. Measured on nidp_staging
-- 2026-09-25, 7 ISINs in sector_master carry two symbols each:
--
--     INE142K01011  LYPSAGEMS/EQ, AURUS/EQ
--     INE203Y01012  SILLYMONKS/EQ, CRESTO/EQ
--     INE844O01030  GUJGASLTD/EQ, GUJENERGY/EQ
--     INE094B01013  ASHIKA/EQ, ASHIKAG/BE
--     ... 3 more
--
-- These are company renames (plus one EQ/BE pair). sector_master is a
-- destructive upsert keyed on symbol and never deletes, so the retired name
-- stays forever and a naive ISIN join silently doubles those rows.
--
-- Tie-break, in order: the symbol that actually traded most recently in
-- prices_eod, then EQ over other series, then the symbol alphabetically so the
-- result is deterministic when a stock has no recent price at all.

CREATE OR REPLACE VIEW nidp.v_bse_scrip_to_nse AS
WITH last_traded AS (
    SELECT symbol, max(as_of_date) AS last_seen
    FROM nidp.prices_eod
    GROUP BY symbol
),
ranked AS (
    SELECT
        sm.isin,
        sm.symbol,
        sm.series,
        row_number() OVER (
            PARTITION BY sm.isin
            ORDER BY lt.last_seen DESC NULLS LAST,
                     (sm.series = 'EQ') DESC,
                     sm.symbol
        ) AS rn
    FROM nidp.sector_master sm
    LEFT JOIN last_traded lt ON lt.symbol = sm.symbol
    WHERE sm.isin IS NOT NULL
)
SELECT
    b.as_of_date,
    b.scrip_code,
    b.isin,
    b.bse_ticker,
    b.bse_group,
    b.company_name,
    r.symbol      AS nse_symbol,
    r.series      AS nse_series,
    (r.symbol IS NOT NULL) AS nse_listed
FROM nidp.bse_scrip_master_daily b
LEFT JOIN ranked r ON r.isin = b.isin AND r.rn = 1;

COMMENT ON VIEW nidp.v_bse_scrip_to_nse IS
    'Deterministic scrip_code -> NSE symbol resolution, as of each trading day. '
    'Exactly one row per (as_of_date, scrip_code): where an ISIN carries several '
    'sector_master symbols (company renames, EQ/BE pairs) it picks the one that '
    'traded most recently. nse_listed = false means BSE-only, so no NSE price '
    'series exists and the filing is outside an NSE-traded universe.';
