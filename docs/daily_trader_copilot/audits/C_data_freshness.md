# C. Staging data freshness: what the Copilot could answer with today

**When:** Fri 2026-10-30, 04:21–04:45 IST (VM clock: `Fri Oct 30 04:21:25 IST 2026`; warehouse `now()` = `2026-10-30 04:21:34 IST`).
The market has **not opened today**, so no "today live" data can exist yet. The latest completed session is **T-1 = Thu 2026-10-29**.
Sessions since 12 Oct, from `nidp.prices_eod`: `10-29 10-28 10-27 10-26 10-23 10-22 10-21 10-19 10-16 10-15 10-14 10-13 10-12`. 20 Oct was a holiday, so "N sessions behind" below counts from that list.

**Method:** everything was read-only.
- NIDP warehouse `nidp_staging` through `~/.config/nivesh/nidp-psql.sh`, every query wrapped in `BEGIN READ ONLY … ROLLBACK`.
- App Mongo `nivesh_staging` and app Postgres `portfolio_ingestion` from inside `nivesh-staging-app-backend` (`deps.db`; `services.pg_client.get_pool()` with `transaction(readonly=True)`).
- Yahoo Finance through the app's own `yfinance` ticker list, in a throwaway process.
- One public GET: `/api/markets/home` returned **401**, so it needs a session.

Nothing was written or restarted, and no credentials or user documents were printed. The scripts are in this folder: `mongo_enum.py`, `mongo_keys.py`, `mongo_agg.py`, `mongo_kite.py`, `pg_tables.py`, `pg_fresh.py`, `pg_more.py`, `yf_probe.py`. Raw outputs are in the `*.txt` files beside them.

Legend: **FRESH-T1** = latest row is 29 Oct. **STALE (n)** = latest row is n sessions older than T-1. **ABSENT** = no such source on staging. **EMPTY** = the table exists but has 0 rows.

## Freshness table

| # | Source | Where | Latest date | Rows on latest | Fresh? | Notes |
|---|---|---|---|---|---|---|
| 1 | Feed health | `nidp.v_feed_status` (60 feeds) | ran 04:21 IST | 60 | n/a | Core market feeds (bhavcopy, F&O bhavcopy, index close, FII/DII, corp actions, bulk deals, NSE announcements, technicals) are OK for 29 Oct. **STALE (feed's own flag):** smart_money_scores, sensibull_fii_dii, mf_holdings*, scanx_*, trendlyne_*, fpi_sector_auc, event_calendar_backfill, amfi_nav_history. **FAILED:** BSE announcements (HTTP 403, 69 failures in a row since 13 Oct), amc_urls_drift_check. **NEVER_SUCCEEDED:** FRED_MACRO, NSE_FINANCIALS, 3 portfolio_*_sync (GCP credentials). |
| 2 | Validation findings | `nidp.validation_findings` (no open/closed column; "open" here = detected in the last 3 days) | 30 Oct 01:04 IST | 15 in 3 days | n/a | The 22:30 quality_gate on **29 Oct raised 7 CRITICAL + 3 ERROR, all first-time rules**. Checked against the data, the CRITICALs are **validator/schema mismatches, not data defects**: it says `fno_bhavcopy.ticker_symbol` is 100% null, but the table has 32,621/32,621 filled and 0 duplicate keys. It says 99% of `bhavcopy.isin` fail the regex, but 3,581/3,697 are valid. FII category 'FII' ≠ 'FII/FPI'. The index_close ERROR is real but minor: 25 thematic indices have no OHL. |
| 3 | Equity bhavcopy (OHLCV) | `nidp.prices_eod` | 2026-10-29 | 3,697 (2,712 EQ) | **FRESH-T1** | Ingested 29 Oct 19:00. The adjusted series `prices_eod_adjusted` is also 29 Oct (2,712 rows, 22:33). |
| 4 | Delivery qty / % | `prices_eod.deliv_*`, `nidp.delivery_data` | **2026-10-28** | 3,269 / 3,512 | **STALE (1)** | 0 of 3,697 rows on 29 Oct have delivery. The NSE_DELIVERY feed fills the previous session at 10:30 IST, so 29 Oct delivery arrives today about 10:30. This lag is by design and every day. |
| 5 | F&O bhavcopy | `nidp.fno_bhavcopy` | 2026-10-29 | 32,621 (666 futures, 31,955 options, 224 underlyings) | **FRESH-T1** | Ingested 29 Oct 22:15. |
| 6 | Option chain metrics (PCR, max pain, OI walls) | computed per request from `fno_bhavcopy` (DaaS `/fno/*`, `routes/fno.py`) or the live Kite chain; `nidp.v_options_chain_latest` | 2026-10-29 | 16,452 strike rows, 224 underlyings | **FRESH-T1** | Real check: NIFTY/BANKNIFTY OI-PCR is computable from the 29 Oct chain (BANKNIFTY 23-Nov expiry PCR 0.970, spot 54,909.65). No stored PCR/max-pain table; they are computed on request. |
| 7 | IV (ATM, near/next month) | Mongo `fno_iv_history` | **2026-10-26** | 1 per underlying | **STALE (3)** | NIFTY and BANKNIFTY only; all 524 docs are `method=backfill`. The `record_iv_history` cron is **not installed** (`/etc/cron.d` has no entry). No per-contract IV or Greeks history. |
| 8 | Index closes (NIFTY, BANKNIFTY, INDIA VIX) | `nidp.index_eod` | 2026-10-29 | 151 indices | **FRESH-T1** | 29 Oct: Nifty 50 22,936.75 (+1.05%), Nifty Bank 54,909.65 (+1.18%), India VIX 15.12 (−6.94%). |
| 9 | Sector indices (relative strength) | `nidp.index_eod` sectoral rows | 2026-10-29 | 56 sector-like of 151 | **FRESH-T1** | IT, Auto, Pharma, Metal, FMCG, Realty, PSU Bank, Energy, etc. are all present. App Postgres `sector_macro_scores` 29 Oct (21 rows) and `market_index_data` 29 Oct (8). `rel_strength_90d` / `vol_z20` are in `stock_features_daily` on 29 Oct. |
| 10 | Sector analytics (precomputed) | `analytics.sector_snapshot`, `analytics.mv_sector_heatmap`, Mongo `market_sector_analysis` | **2026-10-12** | 22 / 22 / 8 | **STALE (12)** | Frozen: see the analytics_refresh defect below. |
| 11 | Stock card / top movers / delivery surge | `analytics.stock_card`, `analytics.mv_top_momentum`, `analytics.mv_delivery_surge` | **2026-10-12** | 2,696 / 494 / 493 | **STALE (12)** | `/api/markets/home` takes top gainers/losers from `mv_top_momentum`, so **Market Overview movers are 12 Oct data**. |
| 12 | Stock features: 52-week high/low, RSI, relative volume, 20-day delivery average | `nidp.stock_features_daily` (read by Copilot `get_technical_analysis` via DaaS) | 2026-10-29 | 2,493 (52w 2,493/2,493; vol_z20 2,493; sector 545) | **FRESH-T1** | Real check: RELIANCE `dist_52w_high_pct` −27.5717 matches my recompute from 252 adjusted sessions (−27.57). Its `deliv_pct_avg_20` ends at 28 Oct delivery (row 4). Sector tags are sparse (545/2,493). |
| 13 | Stock daily snapshot | `nidp.stock_daily_snapshot`, `nidp.daily_snapshot` | 2026-10-29 | 3,339; status READY | **FRESH-T1** | |
| 14 | Market snapshot / regime | `nidp.market_daily_snapshot`, `analytics.market_snapshot` (warehouse); app PG `macro_state`, `macro_daily` | 2026-10-29 | 1 each | **FRESH-T1** | The app-Postgres copy of `analytics.market_snapshot` is EMPTY (0 rows); the warehouse copy is fresh. |
| 15 | FII/DII cash | `nidp.fii_dii_flows` source NSE_FII_DII | 2026-10-29 | 2 (FII −943.60 Cr, DII +1,924.41 Cr) | **FRESH-T1** | Ingested 19:30. |
| 16 | FII/DII F&O (index futures/options OI) | `nidp.fii_dii_flows` source SENSIBULL | **2026-10-21** | 1 per segment | **STALE (6)** | The `sensibull_fii_dii` feed's last success was 22 Oct. `market_daily_snapshot` has `fii_fno_index_net_cr` columns, but their source is this stale feed. |
| 17 | Corporate actions | `nidp.corporate_actions` | ingested 29 Oct 20:00 | ex 30 Oct: 11 dividends, 2 distributions, 1 buyback, 1 other | **FRESH-T1** | The CRITICAL "ex_date null 5/5" finding: 0 recent rows actually have a null ex_date. |
| 18 | Results / events calendar | `nidp.event_calendar` | fetched 29 Oct 20:30 | **30 Oct: 120 quarterly results**; 31 Oct: 52; 2 Nov: 133; 3 Nov: 174 | **FRESH-T1** | Furthest event is 5 Dec. Memory note: Sep-26 quarter is labelled "Q2 FY26" (should be FY27). |
| 19 | Corporate announcements | `nidp.corporate_announcements` | NSE: 29 Oct 23:26 IST; **BSE: 13 Oct** | 917 NSE on 29 Oct; 0 BSE | NSE **FRESH**, BSE **STALE (12)** | BSE returns HTTP 403 every run. |
| 20 | Post-event AI signals (Market Overview news) | `nidp.corporate_event_signals` | none | **EMPTY** | **EMPTY** | Market Overview "market news headlines" reads this table. |
| 21 | Event AI analysis | Mongo `event_ai_analysis` | event_ts 29 Oct 15:36, analysed 29 Oct 16:04 (stored UTC) | 577 events on 29 Oct IST, 60 included | **FRESH-T1** | 33,167 docs in total. |
| 22 | Bulk / block deals | `nidp.bulk_deals`, `nidp.block_deals` | 29 Oct / 28 Oct | 71 / 2 | bulk **FRESH-T1**; block "no rows in source" for 29 Oct | |
| 23 | Insider / SAST | `nidp.insider_sast` | none | **EMPTY** | **EMPTY** | |
| 24 | Macro / economic calendar | `nidp.macro_releases` | latest fetch 29 Oct 20:30 | **0 events for 30 Oct–3 Nov**; India rows: 42 in total (next CPI 12 Nov) | partial | Only IN (42) and US (333) rows. The macro_calendar feed is PARTIAL. `nidp.fred_macro` is EMPTY (NEVER_SUCCEEDED). |
| 25 | Global cues: US/Europe indices, Brent/WTI, gold, USD/INR, US 10Y, S&P futures | Yahoo via `positional_engine.nse_live.get_global_snapshot` (60 s in-process cache, not stored anywhere) | US/EU/commodities/INR=X: 2026-10-29 bar | 21 tickers | US/EU/FX **FRESH (29 Oct)** | Probed this session: `^GSPC`, `^DJI`, `^IXIC`, `BZ=F`, `INR=X` (95.21), `ES=F`, `^TNX` all have a 29 Oct bar. |
| 26 | Asian indices (Nikkei, Hang Seng, Kospi, STI, Shanghai) | same Yahoo call | **2026-10-28 bar** | 4 bars in a 5-day window | **STALE (1)** at 04:30 IST | Yahoo had no 29 Oct daily bar for any of the 5 Asian tickers (ASX did). The app's 2-day logic would show a 28-vs-27 change as "latest". Payload has `fetched_at` but **no bar date**, so the UI cannot tell. |
| 27 | GIFT Nifty | — | — | — | **ABSENT** | Not fetched by design (code comment: "no reliable free Yahoo feed"). Not in Kite universe either. `nidp.international_etf_price` is EMPTY. |
| 28 | MF monthly holdings | `nidp.mf_holdings_monthly`, `nidp.scanx_mf_holdings` | **2026-09 month** | 193,756 rows / 3,031 schemes (13 sources) | current month-end (Oct disclosures are due ~10 Nov) | Feed status STALE (last run 13/22 Oct, "missing=10/14" AMCs on the direct path). App PG `mutual_fund_holdings` 15,286 rows, written 29 Oct 03:01. |
| 29 | MF flows | AMFI category net-flow table: **ABSENT**. Stock-level flow `nidp.v_mf_stock_flow_monthly` | — | **0 rows** | ABSENT / EMPTY | `mf_holdings_deltas` last ran 22 Oct (target 2026-09). |
| 30 | MF NAV | `nidp.mf_nav_daily` | 29 Oct has 11 rows; **28 Oct has 8,655** | 11 / 8,655 | **STALE (1) for most schemes** | AMFI's full 29 Oct NAV list publishes late, after the 20:00 ingest. The 11-row load also raised the scheme_name-null CRITICAL. |
| 31 | Smart-money scores | `nidp.smart_money_scores_daily` | **2026-10-21** | 1,960 | **STALE (6)** | Feed last success 22 Oct. It is built from monthly holdings, so its daily-proxy fields (delivery, vol z) are 6 sessions old. |
| 32 | Shareholding pattern | `nidp.shareholding_pattern` | period_end 2026-09-30 | 2,370 symbols | current quarter | nse_shareholding ran 30 Oct 01:04, 1,960 rows. One WARN (promoter+public ≠ 100). |
| 33 | AI scanner watchlist (Top 10 cash + F&O) | Mongo `ai_watchlist_days` | list_date **2026-10-29** | cash 10, F&O 10; `fno_chain_as_of` 2026-10-29 | **FRESH-T1** | Built 29 Oct 22:45 IST, after the 22:15 F&O bhavcopy. Installed cron is now 22:45 / 23:30 / 23:55, so the earlier chain-date defect is fixed on staging. 4 days stored (26–29 Oct). |
| 34 | Positional engine (AI scanner signals) | app PG `positional_signals`, `stock_ohlcv`, `stock_technical_features` | 2026-10-29 | 766 signals (ACCUMULATION 695, EARLY_BREAKOUT 66, BREAKOUT 5) / 2,927 bars / 2,203 | **FRESH-T1** | `job_runs`: positional_engine ok 29 Oct 19:45 IST. `stock_scores` / `stock_primitives` end 28 Oct (98 rows): **STALE (1)**. |
| 35 | Trade plans | Mongo `trade_plans` | created_at 29 Oct 22:44 UTC (= 30 Oct 04:14 IST) | 14 created today IST; 157 on 29 Oct IST; 639 in total | **FRESH-T1** | Newest 50 all have `data_as_of.price` = 2026-10-29, `mode=end_of_day`. |
| 36 | Kite close (after-hours price) | Mongo `kite_live_close` | 2026-10-29 (saved 15:31 IST, `final=True`) | 1,087 quotes: 615 equities/indices, 224 near-month futures, 124 NIFTY + 124 BANKNIFTY options | **FRESH-T1** | No stock options and no next/far futures, as the memory note says. Superseded by the exchange EOD for 29 Oct, which is already loaded. |
| 37 | Kite live feed / platform login | Mongo `kite_live_snapshot/status`, `kite_platform_token` (dates only) | status updated 04:26 IST: `market_closed / before_open`; token obtained **29 Oct 09:41 IST**, expires **30 Oct 06:00 IST** | 1,087 instruments in the universe, 13 unresolved | not live yet (pre-open) | **Today's live data needs a fresh admin Kite login after 06:00 IST.** `token_alert` for 30 Oct: count 0, not confirmed. Last intraday data: `kite_live_minute` 29 Oct (348 rows, last 15:29 IST), `kite_live_intraday` 29 Oct (70). |
| 38 | Desk paper trades | Mongo `desk_paper_trades`, `paper_accounts` | updated 29 Oct 13:30 UTC | 3 open (2 TRADE_ELIGIBLE awaiting entry, 1 POSITION_OPEN); 0 closed | active | 1 paper account, 3 ledger rows. |
| 39 | Desk price alerts | Mongo `desk_price_alerts` | updated 29 Oct 09:42 UTC | 2, both `fired`; 0 active | active | Alert job `check_desk_alerts` ok 29 Oct 20:45 IST. |
| 40 | Idea scorecard / signal hit rate | `services/idea_scorecard.py` reads committed `research/p4_adx_rs/results_20261027/result.json`; app PG `positional_outcomes` | study run_date **2026-10-27** (static) | 385 signal dates / 634 sessions in the study; `positional_outcomes` **0 rows** | static study, **no live hit rate** | The file loads OK in the container. Verdict: "the current ranking shows no measurable skill". There are no live outcomes for issued ideas. |
| 41 | Move-odds model | `nidp.tpd_preview_runs` / `tpd_preview_estimates` (written by the research VM's nightly job) | target_session **2026-10-30**, data_as_of 2026-10-29 | 1,434 scored of 1,457; 5,736 estimates | **FRESH-T1 (preview only)** | Created 29 Oct 20:40 IST. `nidp.tpd_runs` has **0** published runs, so `/api/move-odds/latest` says "not published". I did not SSH to the research VM; the warehouse holds its outputs. |
| 42 | Strategies (Strategy Lab / AI Trader) | app PG `strategies`, `strategy_versions`, `strategy_runs`, `strategy_trades`, `strategy_signals`, `strategy_alerts`; Mongo `ai_trader_strategies` | versions 28 Oct 01:48; trades entry_date 2026-10-19 | 6 / 6 / 4 / 151 / 0 / 0; Mongo 2 | STALE (no runs since 28 Oct; last trade entry 19 Oct) | `strategy_signals` and `strategy_alerts` are EMPTY. |
| 43 | Trade journal / review | Mongo `trade_journal`; app PG `positional_signals_history`, `positional_backtest_labels` | — | **0 / 0 / 0** | **EMPTY** | No journal data exists. |
| 44 | Risk profile and limits | Mongo `user_profiles` (risk_profile field), `risk_controls`, `risk_decisions`; limits are code constants (`ai_trader/risk_governor.py LIMITS_VERSION="gov-v1"`) | profiles updated 29 Oct; decisions to 29 Oct 22:58 IST | 2 of 4 profiles carry a risk field; 2 kill-switch docs (0 on); 29 decisions (6 allowed, 22 blocked, 1 reduced) | n/a | There is no `risk_profiles` collection. 4 users on staging. |
| 45 | Daily market brief / dashboard snapshot / Closing Bell | Mongo `market_daily_brief`, `dashboard_daily_snapshot`, `closing_bell_runs` | 21 Oct / 24 Oct / **29 Oct** | 1 / 1 / 1 (published) | brief **STALE (6)**, dashboard **STALE (4)**, Closing Bell **FRESH-T1** | |
| 46 | Research watchlist | Mongo `research_watchlist_picks` | list 2026-10-23 (prices refreshed to 29 Oct) | 16 | list is 4 sessions old; prices FRESH-T1 | |
| 47 | Chartink hits | Mongo `desk_chartink_hits`; app PG `chartink_scan_hits` | 2026-10-27 / none | 351 / 0 | **STALE (2)** / EMPTY | The desk Chartink refresh is manual. |
| 48 | Chat | Mongo `chat_messages`, `chat_sessions` | 29 Oct 22:46 UTC (= 30 Oct 04:16 IST) | 132 / 41 in total | live | Latest message time only. |

## Queries run (exact SQL or calls, no secrets) and output excerpts

**NIDP feed status**
```sql
SELECT source_name, ingester, expected_freq, last_success_at, last_failure_at, consecutive_failures, last_run_status, last_target_date,
 last_rows_inserted, last_snapshot_date, last_snapshot_rows, staleness_days, staleness_budget_days, effective_status, last_dq_status, last_dq_findings, last_error_message
FROM nidp.v_feed_status ORDER BY effective_status, source_name;
```
```
 NSE_BHAVCOPY     | bhavcopy     | daily | 10-29 19:00 | ... | OK | 2026-10-29 | 3697  | ... | OK
 NSE_FNO_BHAVCOPY | fno_bhavcopy | daily | 10-29 22:15 | ... | OK | 2026-10-29 | 32621 | ... | OK
 NSE_DELIVERY     | delivery     | daily | 10-29 10:30 | ... | OK | 2026-10-28 | 3512  | ... | OK
 BSE_CORPORATE_ANNOUNCEMENTS | ... | 10-13 09:13 | 10-29 06:30 | 69 | FAILED | ... HTTP 403 Access Denied
 analytics_refresh | ... | 10-30 00:10 | ... | OK | 0 rows
 sensibull_fii_dii | ... | 10-22 08:05 | ... | STALE (8 days, budget 4)
 smart_money_scores| ... | 10-22 04:52 | target 2026-10-12 | STALE
 mf_holdings       | ... | 10-13 08:19 | PARTIAL missing=10/14 | STALE
 FRED_MACRO, NSE_FINANCIALS, portfolio_*_sync | NEVER_SUCCEEDED
(60 rows; full output: nidp_feed_status.txt)
```

**Validation findings (last 3 days) and a cross-check against the data**
```sql
SELECT ingester, severity, failure_class, count(*), max(target_date), max(detected_at) FROM nidp.validation_findings
 WHERE detected_at >= now() - interval '3 days' GROUP BY 1,2,3;
SELECT as_of_date, count(*), count(ticker_symbol), count(DISTINCT ticker_symbol) ... FROM nidp.fno_bhavcopy WHERE as_of_date >= '2026-10-27' GROUP BY 1;
SELECT count(*) FROM (SELECT ticker_symbol, instrument_type, expiry_date, strike_price, option_type FROM nidp.fno_bhavcopy WHERE as_of_date='2026-10-29' GROUP BY 1,2,3,4,5 HAVING count(*)>1) d;
```
```
 fno_bhavcopy | CRITICAL | FIX | 2 | 2026-10-29   ("ticker_symbol 32621/32621 null", "compound key not unique")
 bhavcopy     | CRITICAL | FIX | 1 | 2026-10-29   ("isin regex 3668/3697 failed")
 index_close  | ERROR    | FIX | 3 | 2026-10-29   (open/high/low null 25/151)
 -- data says:
 2026-10-29 | 32621 rows | 32621 ticker_nonnull | 224 underlyings      dup_groups = 0
 prices_eod 2026-10-29: isin_nonnull 3697, isin_valid (^IN[A-Z][0-9A-Z]{9}$) 3581
```
All 29-Oct CRITICAL rules have `n_days = 1, first_td = 2026-10-29`. They are new expectations, not recurring defects.

**Equity / delivery / adjusted**
```sql
SELECT as_of_date, count(*), count(*) FILTER (WHERE series='EQ'), count(deliv_qty), count(deliv_pct), max(ingested_at) FROM nidp.prices_eod WHERE as_of_date >= '2026-10-26' GROUP BY 1;
```
```
 2026-10-29 | 3697 | 2712 | 0    | 0    | 10-29 19:00
 2026-10-28 | 3682 | 2711 | 3269 | 3269 | 10-28 19:00
 prices_eod_adjusted 2026-10-29 | 2712 | ingested 2026-10-29 22:33
 delivery_data max 2026-10-28 | 3512
```

**Index / sector / FII-DII**
```sql
SELECT as_of_date, index_name, open_price, high_price, low_price, close_price, pct_change FROM nidp.index_eod WHERE as_of_date >= '2026-10-28' AND index_name IN (...);
SELECT source, segment, min(as_of_date), max(as_of_date), count(*) FROM nidp.fii_dii_flows GROUP BY 1,2;
```
```
 2026-10-29 | India VIX | ... | 15.1200 | -6.94      2026-10-29 | Nifty 50 | ... | 22936.75 | 1.05
 2026-10-29 | Nifty Bank | ... | 54909.65 | 1.18     (IT, Auto, Pharma, Metal, FMCG, Realty, PSU Bank, Energy all 29 Oct)
 2026-10-29 | FII | EQUITY_CASH | 13400.29 | 14343.89 | -943.60 | NSE_FII_DII
 2026-10-29 | DII | EQUITY_CASH | 18458.64 | 16534.23 | 1924.41 | NSE_FII_DII
 SENSIBULL | FUT_NIFTY / INDEX_FUTURES / INDEX_OPTIONS ... | 2026-04-01 | 2026-10-21
```

**Derived warehouse tables** (`max(date)` plus row count on that date, one UNION query; full output in nidp_derived.txt)
```
 features.stock_features_daily 2026-10-29 2493 | nidp.stock_daily_snapshot 2026-10-29 3339 | nidp.market_daily_snapshot 2026-10-29 1
 analytics.market_snapshot 2026-10-29 1 | analytics.sector_snapshot 2026-10-12 22 | analytics.stock_card 2026-10-12 2696
 nidp.smart_money_scores_daily 2026-10-21 1960 | nidp.mf_holdings_monthly 2026-09-01 193756 | nidp.v_options_chain_latest 2026-10-29 16452
 nidp.insider_sast 0 | nidp.fred_macro 0 | nidp.international_etf_price 0 | nidp.tpd_runs 0 | nidp.earnings_estimates 0
 nidp.tpd_preview_runs target 2026-10-30, last created 2026-10-29 20:40 | nidp.sector_master 550 of 2630 with sector
 analytics.mv_top_momentum 2026-10-12 494 | mv_delivery_surge 2026-10-12 493 | mv_sector_heatmap 2026-10-12 22
 nidp.corporate_event_signals: 0 rows
```

**analytics_refresh: why the analytics layer is frozen**
```sql
SELECT started_at, status, target_date, rows_inserted FROM nidp.job_log WHERE ingester='analytics_refresh' ORDER BY started_at DESC LIMIT 8;
```
```
 10-30 00:10 | OK | | 0
 10-29 00:10 | OK | | 0   ... (same for 10-28, 10-27, 10-24, 10-23, 10-22, 10-21)
```
The repo cron is `10 0 * * 2-6 … analytics_refresh`, and `service.run()` defaults `target_date = date.today()`. **Likely cause (UNVERIFIED):** at 00:10 IST, `date.today()` is already the next calendar day, which has no prices, so `analytics.refresh_all()` writes 0 rows. The job still reports OK.

**52-week check**
```sql
SELECT as_of_date, count(*), count(dist_52w_high_pct), count(dist_52w_low_pct), count(rsi14) FROM nidp.stock_features_daily WHERE as_of_date >= '2026-10-28' GROUP BY 1;
WITH w AS (SELECT adj_close, adj_high FROM nidp.prices_eod_adjusted WHERE symbol='RELIANCE' AND as_of_date <= '2026-10-29' ORDER BY as_of_date DESC LIMIT 252) SELECT max(adj_high), ... FROM w;
```
```
 2026-10-29 | 2493 | 2493 | 2493 | 2493
 RELIANCE | 2026-10-29 | 1167.40 | dist_52w_high_pct -27.5717      recompute: hi_252 1611.80, dist -27.57
```

**Option chain / PCR**
```sql
SELECT as_of_date, ticker_symbol, expiry_date, count(*), sum(ce_oi), sum(pe_oi), round(sum(pe_oi)::numeric/nullif(sum(ce_oi),0),3), max(underlying_price)
FROM nidp.v_options_chain_latest WHERE ticker_symbol IN ('NIFTY','BANKNIFTY') GROUP BY 1,2,3 ORDER BY 2,3 LIMIT 6;
```
```
 2026-10-29 | BANKNIFTY | 2026-11-23 | 154 | 12481350 | 12104430 | 0.970 | 54909.65
 underlyings_in_chain_view = 224
```

**Events / corporate actions / macro / MF**
```sql
SELECT event_date, event_type, count(*) FROM nidp.event_calendar WHERE event_date BETWEEN '2026-10-29' AND '2026-11-03' GROUP BY 1,2;
SELECT ex_date, action_type, count(*) FROM nidp.corporate_actions WHERE ex_date BETWEEN '2026-10-30' AND '2026-11-03' GROUP BY 1,2;
SELECT release_date, country, count(*) FROM nidp.macro_releases WHERE release_date BETWEEN '2026-10-29' AND '2026-11-03' GROUP BY 1,2;
SELECT as_of_month, count(DISTINCT scheme_code), count(*) FROM nidp.mf_holdings_monthly WHERE as_of_month >= '2026-07-01' GROUP BY 1;
SELECT nav_date, count(*) FROM nidp.mf_nav_daily WHERE nav_date >= '2026-10-26' GROUP BY 1;
```
```
 2026-10-30 | quarterly_results | 120     2026-10-31 | quarterly_results | 52     2026-11-02 | quarterly_results | 133
 2026-10-30 | DIVIDEND | 11   DISTRIBUTION | 2   BUYBACK | 1   OTHER | 1
 macro_releases 29 Oct–3 Nov: only 2026-10-29 | US | 3      countries: IN 42, US 333
 2026-09-01 | 3031 schemes | 193756    2026-08-01 | 2847 | 185918
 nav 2026-10-29 | 11     2026-10-28 | 8655
 v_mf_stock_flow_monthly: 0 rows      shareholding_pattern period_end 2026-09-30 | 2370 symbols
 tpd_preview_runs: 15 | REBUILT-WAREHOUSE PREVIEW | target 2026-10-30 | data_as_of 2026-10-29 | 1457 | 1434 | 10-29 20:40 ; tpd_runs = 0
```

**Global cues** (`yf_probe.py`: `yf.download(<app's 21 tickers>, period="5d")`, then the last non-null bar date per ticker)
```
 ^GSPC last_bar=2026-10-29 7720.39 | ^DJI 2026-10-29 | ^IXIC 2026-10-29 | ES=F 2026-10-29 | INR=X 2026-10-29 95.21
 BZ=F 2026-10-29 111.51 | CL=F 2026-10-29 | ^TNX 2026-10-29 | ^FTSE/^GDAXI/^FCHI/^STOXX50E 2026-10-29
 ^N225 last_bar=2026-10-28 | ^HSI 2026-10-28 | ^KS11 2026-10-28 | ^STI 2026-10-28 | 000001.SS 2026-10-28 | ^AXJO 2026-10-29
```
`GET https://staging.niveshcopilot.com/api/markets/home` → `HTTP 401` (needs a session).

**App Mongo** (`mongo_enum.py`, `mongo_agg.py`, `mongo_kite.py`; aggregates only)
```
 ai_watchlist_days 2026-10-29 built_at 2026-10-29T17:15:05Z cash=10 fno=10 fno_chain_as_of=2026-10-29 fno_chain_dates=['2026-10-29']
 trade_plans by created day (UTC string): 2026-10-29 171 | 2026-10-28 40 | 2026-10-27 428 ; created today IST 14 ; on 29 Oct IST 157
 trade_plans newest 50: cash 35 + 7, options 7, futures 1 — all data_as_of.price 2026-10-29, mode end_of_day, status proposed
 kite_live_close 2026-10-29 as_of 10:01:02Z final=True count=1087 ; by kind: equity/index 615, future 224, NIFTY opt 124, BANKNIFTY opt 124
 kite_live_snapshot/status: state market_closed, reason before_open, instrument_count 1087, unresolved_count 13, updated 22:56Z
 kite_platform_token obtained_at 2026-10-29 04:11:55Z  expires_at 2026-10-30 00:30:00Z   (06:00 IST today)
 kite_live_minute 2026-10-29 348 (last 09:59Z) ; kite_live_intraday 2026-10-29 70
 desk_paper_trades: open/TRADE_ELIGIBLE 2, open/POSITION_OPEN 1 ; desk_price_alerts: fired 2
 event_ai_analysis n=33167 last_event 2026-10-29 15:36 ; 29 Oct IST 577 (included 60)
 risk_controls 2 (kill_switch_on 0) ; risk_decisions allowed 6 / blocked 22 (last 2026-10-29T17:28Z) / reduced 1 ; risk_profiles collection: absent ; user_profiles 4, with risk field 2
 fno_iv_history NIFTY/BANKNIFTY last 2026-10-26 method backfill ; market_daily_brief 2026-10-21 ; dashboard_daily_snapshot 2026-10-24
 market_sector_analysis 2026-10-12 (8) ; research_watchlist_picks 2026-10-23 (16) ; closing_bell_runs 2026-10-29 published ; desk_chartink_hits 2026-10-27 (351)
 job_runs: positional_engine ok 2026-10-29T14:15Z ; check_desk_alerts ok 2026-10-29T15:15Z ; trade_journal 0
```

**App Postgres** (`pg_fresh.py`, `pg_more.py`, read-only transaction, db `portfolio_ingestion`)
```
 positional_signals max(signal_date)=2026-10-29 rows=766 (ACCUMULATION 695, EARLY_BREAKOUT 66, BREAKOUT 5)
 stock_ohlcv max(bar_date)=2026-10-29 rows=2927 ; stock_technical_features 2026-10-29 2203
 positional_outcomes 0 ; positional_signals_history 0 ; positional_backtest_labels 0 ; chartink_scan_hits 0
 strategies 6 (2026-10-28) ; strategy_versions 6 ; strategy_runs 4 ; strategy_trades 151 (max entry_date 2026-10-19) ; strategy_signals 0 ; strategy_alerts 0
 market_index_data 2026-10-29 8 ; macro_daily / macro_state 2026-10-29 ; sector_macro_scores 2026-10-29 21 ; stock_scores 2026-10-28 98
 analytics.market_snapshot (app copy) 0 ; features.stock_features_daily (app copy) 0 ; user_universes 0
```

## What would make a Copilot answer wrong today (30 Oct)

1. **Market Overview movers, sector heatmap, delivery surge and stock cards are 12 Oct data.** `analytics_refresh` has inserted 0 rows on every nightly run while reporting OK. Its likely cause is `date.today()` at 00:10 IST (UNVERIFIED). Any answer drawn from `analytics.*` (top gainers/losers, sector snapshot, `stock_card` 52-week/vol_ratio) is 12 sessions stale. Use `nidp.stock_features_daily` (fresh) instead.
2. **No live data until someone logs in to Kite.** The platform token expires 06:00 IST today, and the feed reports `before_open`. Without a fresh admin login after 06:00, intraday and "now" questions fall back to the 29 Oct close.
3. **Delivery % for 29 Oct is not loaded until ~10:30 IST.** Before then, delivery-based answers (accumulation, delivery spikes) use 28 Oct (T-2). Join on the latest session that has delivery data.
4. **F&O participant flows (FII index futures/options OI) stop at 21 Oct.** The Sensibull feed is stale, so FII F&O positioning answers would be 6 sessions old. FII/DII *cash* is fine (29 Oct).
5. **IV / IV-rank stops at 26 Oct.** The `record_iv_history` cron is not installed. PCR, max pain and OI walls are fine, computed from the 29 Oct bhavcopy.
6. **Smart-money scores stop at 21 Oct**, and `v_mf_stock_flow_monthly` is empty. "Which funds are buying X" can use September holdings (latest month) but not the derived flow view.
7. **GIFT Nifty is absent, and Yahoo's Asian indices stop at 28 Oct.** Global-cue answers lack the single most-asked pre-open number. Asian moves would be one session old, and the payload carries no bar date to warn the user.
8. **Market Overview news headlines are empty** (`nidp.corporate_event_signals` 0 rows), and **BSE announcements have been blocked since 13 Oct** (HTTP 403). NSE announcements and `event_ai_analysis` are fresh.
9. **No live signal hit-rate.** `positional_outcomes` has 0 rows, and the idea scorecard is a static 27-Oct backtest ("no measurable skill"). The Move-odds model is preview-only (`tpd_runs` = 0, so the API says "not published").
10. **The macro calendar shows nothing for 30 Oct–3 Nov**, and `fred_macro` has never succeeded. An "events this week" answer would list only company results (120 today), with no macro events.
11. **Last night's 7 CRITICAL validation findings would mislead a data-health answer.** Checked against the tables, they are new validator rules that mis-read the schema (e.g. "ticker_symbol 100% null" when it is 100% filled). They do not reflect bad data.
12. **Empty sources:** journal/trade review (`trade_journal`, history and labels tables), `strategy_signals`/`strategy_alerts`, `insider_sast`, `earnings_estimates` (so no consensus or surprise data). Strategy runs stop at 28 Oct.

Not reached or not checked: I did not SSH to the research VM (45.64.105.249); its outputs were read from `nidp.tpd_preview_*` in the warehouse. Authenticated app endpoints (401) were not called with a session.
