-- 141_mf_ownership_from_holdings.sql
-- stock_features_daily.mf_pct has always been NULL: it reads v_shareholding_latest.mf_pct,
-- and NEITHER shareholding source populates it (NSE_SHP 10,203 rows / screener_in 4,427 rows,
-- both 0 filled). The NSE shareholding filing simply carries no mutual-fund column.
--
-- But NIDP already ingests the AMC monthly portfolio disclosures: nidp.mf_holdings_monthly
-- holds 491,339 positions across 3,325 schemes, and sector_master carries ISIN, so MF
-- ownership is derivable in-house from a licensed source -- no scraping, and with more
-- detail than any aggregator (per-scheme holdings and month-over-month change).
--
-- Validated: implied price (market_value / quantity) matches the traded close within
-- 0.93-1.05 across RELIANCE, CHEMPLASTS, KWIL and BBOX, so the holdings themselves are sound.
--
-- The PERCENTAGE needs a share count, derived as equity_share_capital_cr * 1e7 / face_value.
-- That is exact where equity capital is current (RELIANCE 13,532 mn shares, CHEMPLASTS 158 mn)
-- but stale for some (KWIL derives 50 mn and so reports an impossible 52% MF holding).
-- mf_pct is therefore NULLed above 60% -- above that the denominator is wrong, not the company.
-- scheme count and rupee value carry no denominator and are always trustworthy.

CREATE OR REPLACE VIEW nidp.v_mf_ownership_latest AS
WITH latest AS (
    SELECT max(as_of_month) AS m FROM nidp.mf_holdings_monthly
),
agg AS (
    SELECT h.security_isin,
           sum(h.quantity)                  AS mf_shares,
           sum(h.market_value_inr) / 1e7    AS mf_value_cr,
           count(DISTINCT h.scheme_code)    AS mf_schemes
      FROM nidp.mf_holdings_monthly h, latest l
     WHERE h.as_of_month = l.m
     GROUP BY h.security_isin
),
cap AS (
    SELECT DISTINCT ON (symbol) symbol, equity_share_capital_cr
      FROM nidp.nse_financials_quarterly
     WHERE equity_share_capital_cr > 0
     ORDER BY symbol, period_end DESC
)
SELECT sm.symbol,
       (SELECT m FROM latest)                              AS as_of_month,
       a.mf_schemes,
       round(a.mf_value_cr::numeric, 2)                    AS mf_value_cr,
       a.mf_shares,
       CASE
         WHEN cap.equity_share_capital_cr > 0 AND sm.face_value > 0
              AND (a.mf_shares / (cap.equity_share_capital_cr * 1e7 / sm.face_value) * 100) <= 60
         THEN round((a.mf_shares / (cap.equity_share_capital_cr * 1e7 / sm.face_value) * 100)::numeric, 2)
         ELSE NULL
       END                                                 AS mf_pct
  FROM agg a
  JOIN nidp.sector_master sm ON sm.isin = a.security_isin
  LEFT JOIN cap ON cap.symbol = sm.symbol;

COMMENT ON VIEW nidp.v_mf_ownership_latest IS
  'Mutual-fund ownership per stock derived from AMC monthly portfolio disclosures '
  '(mf_holdings_monthly joined to sector_master on ISIN). mf_schemes and mf_value_cr are '
  'denominator-free and always valid; mf_pct is NULL where the derived share count is '
  'implausible (>60%), which indicates stale equity_share_capital_cr, not real ownership.';

-- Fills mf_pct on a given day. Called by fundamental_engine after the extended pass,
-- mirroring how migration 139's options pass is wired.
CREATE OR REPLACE FUNCTION nidp.populate_mf_ownership(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
AS $function$
DECLARE v_rows INTEGER;
BEGIN
    UPDATE nidp.stock_features_daily f
       SET mf_pct = v.mf_pct
      FROM nidp.v_mf_ownership_latest v
     WHERE f.symbol = v.symbol
       AND f.as_of_date = p_target_date
       AND v.mf_pct IS NOT NULL
       AND f.mf_pct IS DISTINCT FROM v.mf_pct;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$function$;
