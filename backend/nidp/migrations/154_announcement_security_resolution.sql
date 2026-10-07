-- 154_announcement_security_resolution.sql — resolve every announcement to a
-- security, as of the day it was filed.
--
-- Depends on: 153_bse_scrip_master_daily.sql
--
-- WHY A VIEW AND NOT AN UPDATE
--
-- nidp.corporate_announcements is the raw record — migration 030 says so:
-- "The crawler ships the raw record; the classifier enriches it." ticker_symbol
-- and scrip_code are what the EXCHANGE sent. Overwriting ticker_symbol with a
-- value we derived would destroy that distinction and make the resolution
-- unauditable: nobody could later tell an NSE-supplied symbol from one nidp
-- inferred through an ISIN two hops away.
--
-- So resolution is a view. It also stays correct for free as the scrip master
-- backfills further — an UPDATE would freeze whatever the master knew on the
-- day it ran.
--
-- THE AS-OF RULE
--
-- A filing is resolved against the scrip master row for the latest trading day
-- ON OR BEFORE filed_at. Never a later one. Measured on nidp_staging over
-- 2024-06-03..2026-09-24, using the newest row instead would be wrong for a
-- large minority of scrips:
--
--     scrips that changed BSE group   2,024 of 7,274   (28%)
--     scrips renamed                    357
--     scrips whose ISIN changed         249
--
-- bse_group decides whether a fill was possible at all (X/XT/T/Z are
-- trade-for-trade or restricted), so today's group applied to a 2024 filing is
-- look-ahead on the single field that gates executability.
--
-- WHAT "UNRESOLVED" MEANS
--
-- resolution = 'none' is mostly NOT a defect. Of 4,999 scrips on 2026-09-24,
-- 2,405 map to an NSE symbol and 2,594 do not — the rest are BSE-only companies
-- with no NSE listing and therefore no NSE price series. They are outside an
-- NSE-traded universe by construction. Consumers should filter on
-- nse_symbol IS NOT NULL rather than treat the gap as missing data.

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_announcement_security AS
WITH last_traded AS (
    SELECT symbol, max(as_of_date) AS last_seen
    FROM nidp.prices_eod
    GROUP BY symbol
),
-- One NSE symbol per ISIN. sector_master is a destructive upsert keyed on
-- symbol and never deletes, so a renamed company keeps both names against the
-- same ISIN (7 such ISINs on 2026-09-25). Same tie-break as v_bse_scrip_to_nse.
ranked_symbol AS (
    SELECT sm.isin, sm.symbol, sm.series,
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
    ca.announcement_id,
    ca.source,
    ca.filed_at,
    ca.subject,
    ca.scrip_code,
    ca.ticker_symbol                                   AS exchange_ticker,
    -- Resolution, NSE-supplied first, then the BSE bridge.
    COALESCE(ca.ticker_symbol, rs.symbol)              AS nse_symbol,
    COALESCE(ca.isin, m.isin)                          AS isin,
    m.bse_ticker,
    m.bse_group,                                       -- as of the filing date
    m.as_of_date                                       AS resolved_as_of,
    CASE
        WHEN ca.ticker_symbol IS NOT NULL THEN 'exchange_symbol'
        WHEN rs.symbol        IS NOT NULL THEN 'bse_scrip_isin_bridge'
        WHEN m.scrip_code     IS NOT NULL THEN 'bse_only_no_nse_listing'
        WHEN ca.scrip_code    IS NOT NULL THEN 'scrip_not_in_master'
        ELSE 'no_identifier'
    END                                                AS resolution
FROM nidp.corporate_announcements ca
LEFT JOIN LATERAL (
    SELECT b.scrip_code, b.isin, b.bse_ticker, b.bse_group, b.as_of_date
    FROM nidp.bse_scrip_master_daily b
    WHERE ca.scrip_code IS NOT NULL
      AND b.scrip_code  = ca.scrip_code
      AND b.as_of_date <= ca.filed_at::date
    ORDER BY b.as_of_date DESC
    LIMIT 1
) m ON TRUE
LEFT JOIN ranked_symbol rs ON rs.isin = m.isin AND rs.rn = 1;

COMMENT ON VIEW nidp.v_announcement_security IS
    'Every corporate announcement resolved to an NSE symbol and ISIN as of the '
    'day it was filed. Non-destructive: corporate_announcements keeps the raw '
    'exchange record. bse_group is the trading group ON THE FILING DATE, which '
    'is what gates executability. resolution = bse_only_no_nse_listing is not a '
    'defect — that company has no NSE price series.';
