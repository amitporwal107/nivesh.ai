#!/bin/sh
# Read-only exports for the pre-registered Results-week study (docs/ai_research/EARNINGS_SURPRISE_PREREGISTRATION.md).
# Usage: research/earnings_surprise/export.sh /home/deploy/earnings-study-data [table ...]   (no table names = all)
# Runs COPY ... TO STDOUT through the staging NIDP psql wrapper; writes CSVs outside git. Nothing is written to the warehouse.
set -eu
OUT="${1:?data dir}"
shift
ONLY=" $* "
PSQL="${NIDP_PSQL:-$HOME/.config/nivesh/nidp-psql.sh}"
mkdir -p "$OUT"
q() { case "$ONLY" in "  ") ;; *" $1 "*) ;; *) return 0 ;; esac; printf '%s\n' "COPY ($2) TO STDOUT WITH CSV HEADER;" | "$PSQL" > "$OUT/$1.csv"; echo "$1: $(($(wc -l < "$OUT/$1.csv") - 1)) rows"; }

q quarters "SELECT symbol, period_end, consolidated, revenue_from_ops_cr, pat_cr, eps_basic, broadcast_at, source, ingested_at,
  ebitda_cr, other_income_cr, exceptional_items_cr, pbt_cr, tax_expense_cr
  FROM nidp.nse_financials_quarterly WHERE period_type = 'quarterly' ORDER BY symbol, period_end, consolidated, source"

q calendar "SELECT DISTINCT ON (symbol, event_date) symbol, company_name, event_date, period, purpose, intimated_at
  FROM nidp.event_calendar WHERE event_type = 'quarterly_results' ORDER BY symbol, event_date, intimated_at NULLS LAST"

q bars "SELECT a.symbol, a.as_of_date, a.adj_open, a.adj_high, a.adj_low, a.adj_close, a.adj_volume, a.raw_close, a.raw_volume, e.deliv_pct
  FROM nidp.prices_eod_adjusted a
  LEFT JOIN (SELECT DISTINCT ON (symbol, as_of_date) symbol, as_of_date, deliv_pct FROM nidp.prices_eod WHERE series = 'EQ'
              ORDER BY symbol, as_of_date, ingested_at DESC) e ON e.symbol = a.symbol AND e.as_of_date = a.as_of_date
  ORDER BY a.symbol, a.as_of_date"

q nifty50 "SELECT as_of_date, close_price FROM nidp.index_eod WHERE index_name = 'Nifty 50' ORDER BY as_of_date"

q niftybees "SELECT DISTINCT ON (as_of_date) as_of_date, close_price FROM nidp.prices_eod WHERE symbol = 'NIFTYBEES' AND series = 'EQ'
  ORDER BY as_of_date, ingested_at DESC"

# The DaaS /desk/fno-buildup aggregation (desk_market.FNO_BUILDUP_SQL, fut and g CTEs) for every session, stock futures only.
q fno "WITH fut AS (
    SELECT DISTINCT ON (as_of_date, ticker_symbol, expiry_date) as_of_date, ticker_symbol, expiry_date, close_price, prev_close_price,
           open_interest, change_in_oi, traded_value
      FROM nidp.fno_bhavcopy WHERE instrument_type = 'STF'
     ORDER BY as_of_date, ticker_symbol, expiry_date, source)
  SELECT as_of_date, ticker_symbol AS symbol,
         (ARRAY_AGG(close_price ORDER BY expiry_date))[1] AS close, (ARRAY_AGG(prev_close_price ORDER BY expiry_date))[1] AS prev_close,
         CASE WHEN COUNT(open_interest) = COUNT(*) THEN SUM(open_interest) END AS oi,
         CASE WHEN COUNT(change_in_oi) = COUNT(*) THEN SUM(change_in_oi) END AS oi_chg,
         CASE WHEN COUNT(traded_value) = COUNT(*) THEN SUM(traded_value) END AS fut_value
    FROM fut GROUP BY as_of_date, ticker_symbol ORDER BY as_of_date, ticker_symbol"

q watermark "SELECT 'nse_financials_quarterly' AS t, max(ingested_at)::text AS max_ingested, count(*) AS n FROM nidp.nse_financials_quarterly
  UNION ALL SELECT 'event_calendar', NULL, count(*) FROM nidp.event_calendar
  UNION ALL SELECT 'prices_eod_adjusted', max(ingested_at)::text, count(*) FROM nidp.prices_eod_adjusted
  UNION ALL SELECT 'index_eod', max(ingested_at)::text, count(*) FROM nidp.index_eod
  UNION ALL SELECT 'fno_bhavcopy', max(ingested_at)::text, count(*) FROM nidp.fno_bhavcopy"

# Timing check (amendment A2): every NSE 'Outcome of Board Meeting' filing (the router's exact subject match, FILING_SQL).
q outcome "SELECT ticker_symbol AS symbol, filed_at FROM nidp.corporate_announcements
  WHERE source = 'NSE_ANN' AND lower(btrim(subject)) = 'outcome of board meeting' AND filed_at >= '2025-06-01' ORDER BY 1, 2"
