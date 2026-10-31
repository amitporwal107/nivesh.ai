# C. Data coverage audit for the Strategy Copilot PRD (§6, §10, §21)

Measured on 2026-10-28 against the **staging NIDP warehouse** (`nidp_staging` on 45.64.105.224, via `~/.config/nivesh/nidp-psql.sh`),
the **staging app Mongo** (`nivesh-staging-app-backend` env, read-only, no credentials printed), the **installed** cron on the data VM
(`/etc/cron.d/nidp-staging`, read with `cat`/`grep` only) and the code snapshot of `origin/dev @ 48556220` (`scratchpad/devsnap`).
Everything here was read-only. All numbers below come from the queries shown, run this session. Where something was not checked, it is marked UNVERIFIED.

Note: the data VM runs services from `/opt/nidp/dev-repo/nivesh.ai` at `5109b3f8` (2026-10-25, "Merge PR #345"), which differs from the snapshot commit 48556220. The table names and ingesters used below exist in both.

---

## Coverage table

| Dataset | Table | First date | Last date | Sessions | Symbols / contracts | Gaps / caveats (measured) | Scheduled on data VM? | Fit for the PRD |
|---|---|---|---|---|---|---|---|---|
| Equity EOD, raw | `nidp.prices_eod` (source `NSE_BHAVCOPY`) | 2024-04-01 | 2026-10-27 | 635 | 6,266 symbols (3,094 in series EQ); 2,725 EQ symbols active now, 2,215 with ≥12 mo, 1,947 with ≥24 mo | 3 weekend special sessions missing: **2024-05-18, 2025-02-01, 2026-02-01** (NSE `prev_close` ≠ stored previous close). No other missing weekday except days that look like NSE holidays (the holiday table cannot confirm 2024–25, see Q7). `avg_price` empty (memory note). Raw prices: splits/bonuses NOT adjusted. | yes: `bhavcopy` 19:00 Mon–Fri; last write 2026-10-27 19:00 | **partial**: ~2.6 years of daily OHLCV. Usable as the trading calendar and for symbol-days with no corporate action. Not usable as-is across a split or bonus. |
| Equity EOD, adjusted | `nidp.prices_eod_adjusted` (`NIDP_PRICE_ADJUSTER`) | 2024-04-01 | 2026-10-27 | 635 | 3,014 symbols; 2,725 active, 2,174 span ≥12 mo, **1,229 span ≥24 mo** | Before 2025-10-01 only **~1,180–1,285 symbols/session** (raw EQ ~1,885–2,114); from 2025-10-01 it matches raw EQ exactly. On 2025-06-02, 810 of 2,090 EQ symbols have no adjusted row (incl. YESBANK, SUZLON, PAYTM, SWIGGY). Series **break at symbol renames** (ZOMATO→ETERNAL, TATAMOTORS→TMPV, LTIM→LTM all start 2025-10-01; 101 ISINs carry >1 symbol). **Demergers not adjusted** (TATAMOTORS adj_close 660.75→395.45 on 2025-10-14). Split/bonus factors present (256/256 checked). | yes: `price_adjuster` 22:30 Mon–Fri; last write 2026-10-27 22:33 | **partial**: correct split/bonus/dividend adjustment where present. 12-month equity backtests are fine for ~2,170 symbols. 24-month backtests reach only ~1,230 symbols, unless renames and non-CA symbols are stitched from raw by ISIN. |
| Index EOD | `nidp.index_eod` (`NSE_IND_CLOSE`) | 2024-04-01 | 2026-10-27 | 635 | 173 indices; NIFTY 50, NIFTY BANK, Nifty Financial Services, Nifty Midcap Select, India VIX each 635/635 | **None**: dates match `prices_eod` exactly (0 one-sided dates); 0 flat or invalid OHLC; the 2024-09-23..2025-09-29 backfill window has 253 rows per index. Spot values for 2024-06-04 and 2025-04-07 match NSE's published closes. | yes: `index_close` 19:00 Mon–Fri; last write 2026-10-27 19:00 | **yes** for daily index signals and underlying levels. |
| F&O contracts (options + futures), EOD | `nidp.fno_bhavcopy` (`NSE_FO_BHAV`) | **2025-10-01** | 2026-10-27 | 263 (= every equity session in range) | 10,380,988 rows; index underlyings NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 (263 sessions each) + NIFTYFPI (52, from 2026-08-12); **232 stock underlyings** (211–213 live at a time) | No missing session. Per-contract O/H/L/C, settle, prev_close, OI, ΔOI, volume, value, trades, underlying price and lot size are all 100% populated. **No bid/ask.** But only **32% of index-option and 39% of stock-option rows traded** (Apr-2026). For untraded rows `close_price = prev_close_price` in 100% of cases (a stale carry-forward) and `open = 0`. No raw archives before 2025-10-01 either (`raw_archive_files` fno_bhavcopy 2025-10-01..2026-10-27). | yes: `fno_bhavcopy` 19:30 / 21:00 / 22:15 Mon–Fri; last write 2026-10-27 22:15 | **partial**: EOD option and futures backtests for **~12.9 months only**, close-to-close, with a traded/stale flag required. Too short for "24 months". Index and stock options both present. |
| Contract metadata, point-in-time | inside `nidp.fno_bhavcopy` (`expiry_date`, `actual_expiry_date`, `strike_price`, `option_type`, `new_board_lot_qty`) | 2025-10-01 | 2026-10-27 | 263 | per contract per day | Lot size is per contract and changes in the data (NIFTY 75→65, BANKNIFTY 35→30, FINNIFTY 65→60, MIDCPNIFTY 140→120 from the Jan-2026 expiry; both coexist 2025-10-29..2025-12-30); 71 of 232 stock underlyings change lot. Holiday-shifted expiries are present (5 NIFTY Monday expiries). `actual_expiry_date` records early terminations (TATAMOTORS, HINDUNILVR, VEDL demergers). Strikes are added during a contract's life (130 of 149 strikes of NIFTY 2026-06-30 appeared after 2025-10-01). **No separate expiry master or historical instrument master.** | yes (same ingester) | **yes within the F&O window**: strike, expiry and lot can be checked per historical date, as the PRD's §10.3 requires. Nothing exists before 2025-10-01. |
| Instrument / security master history | `nidp.security_reference_daily`, `ref.security_master`, `public.instrument_master` | 2026-10-12 | 2026-10-27 | 12 | 213 F&O-eligible; 20,682 securities (0 with `valid_to`); `public.instrument_master` **0 rows** | No history before 2026-10-12 | `nse_reference_snapshot` 07:30, `nse_equity_master` Sun 07:00 | **no** for history (the F&O bhavcopy is the only PIT contract list). |
| Index membership | `nidp.index_constituents` | 2026-10-12 | 2026-10-22 | 4 snapshots (NIFTY 50/100/200/500/Total Market) | 50 / 501 / 755 | No point-in-time history: an index-universe backtest has survivorship bias (the engine labels it `latest_snapshot`) | yes: monthly 1st 06:30 | **partial** |
| Intraday bars (1m/5m/15m/30m) | `nidp.intraday_bars`: **does not exist** (migration `152_kite_intraday_bars.sql` not applied; `to_regclass` null) | — | — | 0 | 0 | `tpd_paper_index_bars` exists but has 0 rows. Mongo `kite_live_minute` (last price per minute, TTL 90 d) and `kite_live_intraday` (5-min buckets with o/c/v/p, **no high/low**, TTL 180 d) hold **one session (2026-10-27)**. The live read path (`kite_live_feed/intraday.py`) fetches Kite candles on demand (≤30 sessions, raw, needs the daily Kite login). | **no**: `kite_bars` not in installed or repo cron | **no**: the PRD's "15-minute RSI" examples cannot be backtested. |
| Implied volatility history | Mongo `nivesh_staging.fno_iv_history` | 2025-10-01 | 2026-10-26 | 262 per underlying | **NIFTY and BANKNIFTY only**; 524 docs | ATM IV only (near and next month), not per contract. Model-derived (Black-76 on the forward, from bhavcopy closes of strikes where both call and put traded). All 524 docs `method=backfill`; none recorded nightly. 2026-10-27 missing. | **no**: the `record_iv_history` cron is documented in the script but not installed on the app VM | **partial**: ATM IV rank for 2 indices. No per-contract IV or Greeks history. |
| Holiday calendar | `nidp.nse_holidays` | 2026-01-01 | 2026-12-25 | — | 12 segments (FO: 20 dates) | **2024 and 2025 holidays absent**. The 2026 FO list has no conflict with stored sessions. | yes: `nse_calendar` monthly 1st 06:00; last write 2026-10-12 | **partial**: use the stored session dates (`prices_eod`) as the calendar for history. |
| Corporate actions | `nidp.corporate_actions` (`NSE_CA`) | ex 2024-03-01 | ex 2026-10-30 | — | 6,727 rows: 4,726 dividends, 184 splits, 175 bonuses, 43 demergers, 161 rights, … | Splits, bonuses and dividends are applied to `prices_eod_adjusted`. **Demergers, rights and capital reductions are not** (the adjuster loads SPLIT/BONUS/DIVIDEND/DISTRIBUTION only). | yes: `corporate_actions` daily 20:00; last write 2026-10-27 20:00 | **partial** |
| Precomputed daily features (the existing engine's signal calendar) | `nidp.stock_features_daily` (= `features.stock_features_daily`) | **2025-12-29** | 2026-10-27 | **204** | 2,124–2,494 rows/day, `rsi14` 100% filled | Shorter than the price history. `SqlMarketDataProvider` reads its signal dates from here. | yes: `technical_indicator_engine` 22:35 | **partial**: under 12 months of precomputed signals. Longer backtests need indicators recomputed from `prices_eod_adjusted`. |
| Charges / costs | none in DB; code constants `backend/services/desk_cost_card.py` (`desk-cost-v2`) | — | — | — | equity delivery, futures, options | One current rate set, no dated history. F&O rates copied from zerodha.com/charges on 2026-10-27, `effective_from = None` (UNVERIFIED in the code itself). Brokerage ₹20/side and slippage 0.05%/side are **desk assumptions**. No intraday-equity segment. | n/a | **partial**: disclosable. Historical periods are charged at today's rates. |

---

## Q1. Equity EOD

**Range, sessions, symbols**
```sql
SELECT 'prices_eod' t, min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) sessions, count(*) rows_, count(DISTINCT symbol) symbols FROM nidp.prices_eod;
SELECT 'prices_eod_adjusted' t, min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) sessions, count(*) rows_, count(DISTINCT symbol) symbols FROM nidp.prices_eod_adjusted;
SELECT source, min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) sessions, count(*) FROM nidp.prices_eod GROUP BY 1;
```
```
     t      |    min     |    max     | sessions |  rows_  | symbols
 prices_eod | 2024-04-01 | 2026-10-27 |      635 | 1977470 |    6266
          t          |    min     |    max     | sessions |  rows_  | symbols
 prices_eod_adjusted | 2024-04-01 | 2026-10-27 |      635 | 1101531 |    3014
    source    |    min     |    max     | sessions |  count
 NSE_BHAVCOPY | 2024-04-01 | 2026-10-27 |      635 | 1977470
 (adjusted: NIDP_PRICE_ADJUSTER | 2024-04-01 | 2026-10-27 | 635 | 1101531)
```
Series mix (top): EQ 1,382,792 rows / 3,094 symbols; SM 189,226 / 620; BE 147,512 / 1,224; ST, GB, GS, BZ, TB, N* (bonds/SME).

Sessions per year: 2024 → 186 (from 1 Apr), 2025 → 248, 2026 → 201 (to 27 Oct).

**History depth (adjusted table, active = has a row on or after 2026-10-20)**
```sql
WITH s AS (SELECT symbol, min(as_of_date) f, max(as_of_date) l, count(*) n FROM nidp.prices_eod_adjusted GROUP BY 1)
SELECT count(*) total_syms, count(*) FILTER (WHERE l >= '2026-10-20') active_now,
 count(*) FILTER (WHERE l >= '2026-10-20' AND f <= '2025-10-27') ge_12m_span,
 count(*) FILTER (WHERE l >= '2026-10-20' AND n >= 245) ge_245_sessions,
 count(*) FILTER (WHERE l >= '2026-10-20' AND f <= '2024-10-27') ge_24m_span,
 count(*) FILTER (WHERE l >= '2026-10-20' AND n >= 490) ge_490_sessions,
 count(*) FILTER (WHERE l >= '2026-10-20' AND f = '2024-04-01') full_span_since_start,
 count(*) FILTER (WHERE l >= '2026-10-20' AND n >= 630) ge_630_sessions FROM s;
```
```
 total_syms | active_now | ge_12m_span | ge_245_sessions | ge_24m_span | ge_490_sessions | full_span_since_start | ge_630_sessions
       3014 |       2725 |        2174 |            1978 |        1229 |            1153 |                  1134 |             937
```
Raw table for comparison (EQ series):
```
        k         | active | ge_12m | ge_24m | no_longer_trading_eq
 raw EQ by symbol |   2725 |   2215 |   1947 |                  369
 raw EQ by ISIN   |   2726 |   2210 |   1916 |                  437
```
By universe (latest constituents; F&O names from the 2026-10-27 bhavcopy), adjusted table:
```
                      u                      | members | in_adj | from_2024_04_01 | ge_24m | ge_12m | min_sessions
 FnO eligible (secref latest)                |     213 |    213 |             183 |    188 |    211 |            3
 FnO stock underlyings (bhavcopy 2026-10-27) |     213 |    213 |             183 |    188 |    211 |            3
 Nifty 50                                    |      50 |     50 |              48 |     48 |     50 |          248
 Nifty 500                                   |     501 |    497 |             375 |    390 |    476 |           24
```
(The two NIFTY 50 names that are short: ETERNAL from 2025-10-01 and TMPV from 2025-10-24, both renames.)

**Why the adjusted table is thin before 2025-10-01**: rows per session by quarter:
```
     q      | avg_raw_eq_rows | avg_adj_rows
 2024-04-01 |            1892 |         1197
 2024-07-01 |            1885 |         1183
 2024-10-01 |            1933 |         1214
 2025-01-01 |            2022 |         1246
 2025-04-01 |            2089 |         1275
 2025-07-01 |            2114 |         1285
 2025-10-01 |            2318 |         2318
 ... 2026-10-01 |          2689 |         2689
```
On 2025-06-02: `has_adj=f` 810 symbols (median turnover ₹1.17 cr, 740 still listed under the same symbol); `has_adj=t` 1,280 (median ₹9.05 cr). Missing ones include RPOWER, NIVABUPA, ETERNAL, YESBANK, SUZLON, RELINFRA, TATAMOTORS, PAYTM, SWIGGY. Reading `price_adjuster/service.py`: with `--since`, rows older than `since` are rewritten only for symbols with an action ex-dated or ingested in the window. My **inference** (not verified against run logs) is that pre-2025-10 adjusted rows exist only for symbols that went through a full-history pass.

**Renames break the series** (same ISIN, different symbol):
```
   symbol   |     isin     | min (raw EQ) | max
 TATAMOTORS | INE155A01022 | 2024-04-01 | 2025-10-23
 TMPV       | INE155A01022 | 2025-10-24 | 2026-10-27
 LTIM       | INE214T01019 | 2024-04-01 | 2026-02-26
 LTM        | INE214T01019 | 2026-02-27 | 2026-10-27
 ZOMATO     | INE758T01015 | 2024-04-01 | 2025-04-08
 ETERNAL    | INE758T01015 | 2025-04-09 | 2026-10-27
 adjusted: ETERNAL from 2025-10-01, LTIM 2025-10-01..2026-02-26, TATAMOTORS 2025-10-01..2025-10-23, TMPV from 2025-10-24
 isins_with_multiple_symbols (EQ): 101
```

**Calendar gaps**
```sql
-- weekdays with no prices_eod rows that are not in nse_holidays
WITH d AS (SELECT gs::date d FROM generate_series('2024-04-01'::date,'2026-10-27'::date,'1 day') gs WHERE extract(isodow FROM gs) < 6),
s AS (SELECT DISTINCT as_of_date FROM nidp.prices_eod), h AS (SELECT DISTINCT holiday_date FROM nidp.nse_holidays)
SELECT d.d, to_char(d.d,'Dy') FROM d LEFT JOIN s ON s.as_of_date=d.d WHERE s.as_of_date IS NULL AND d.d NOT IN (SELECT holiday_date FROM h) ORDER BY 1;
```
24 dates, all in 2024–2025 (the holiday table only covers 2026): 2024-04-11, 04-17, 05-01, 05-20, 06-17, 07-17, 08-15, 10-02, 11-15, 11-20, 12-25; 2025-02-26, 03-14, 03-31, 04-10, 04-14, 04-18, 05-01, 08-15, 08-27, 10-02, 10-22, 11-05, 12-25. These match NSE's published 2024/2025 trading holidays as I know them, **but the warehouse cannot confirm that (UNVERIFIED from data)**. No weekday gaps in 2026. 0 weekend sessions stored.

Independent check (NSE's own `prev_close` vs our previous stored close, 5 large caps):
```sql
WITH x AS (SELECT symbol, as_of_date, prev_close, lag(close_price) OVER (PARTITION BY symbol ORDER BY as_of_date) lc, lag(as_of_date) OVER (PARTITION BY symbol ORDER BY as_of_date) ld
 FROM nidp.prices_eod WHERE symbol IN ('RELIANCE','HDFCBANK','TCS','INFY','ITC') AND series='EQ')
SELECT as_of_date, ld prev_stored, string_agg(symbol||' '||prev_close||'/'||lc, '; ') FROM x WHERE lc IS NOT NULL AND abs(prev_close-lc) > 0.011 GROUP BY 1,2 ORDER BY 1;
```
```
 2024-05-21 | 2024-05-17 | RELIANCE 2869.6500/2871.4000; ITC 436.6500/436.3000; ...
 2025-02-03 | 2025-01-31 | ITC 462.5500/447.5000; HDFCBANK 1690.9500/1698.7500; ...
 2026-02-02 | 2026-01-30 | TCS 3186.9000/3123.9000; RELIANCE 1347.0000/1395.4000; ...
```
→ three **missing special sessions**: Sat 2024-05-18, Sat 2025-02-01 (Budget), Sun 2026-02-01 (Budget). No thin sessions: the lowest EQ row count per session is 1,831 (Sep-2024), against a median of 2,103.

**Adjustment factors**
```sql
SELECT count(*) rows_, count(*) FILTER (WHERE cumulative_adj_factor IS NULL) null_factor, count(*) FILTER (WHERE cumulative_adj_factor <> 1) factor_ne_1,
 count(DISTINCT symbol) FILTER (WHERE cumulative_adj_factor <> 1) syms_factor_ne_1, count(*) FILTER (WHERE adj_close IS NULL) null_adj_close, count(*) FILTER (WHERE cumulative_tret_factor <> 1) tret_ne_1
FROM nidp.prices_eod_adjusted;
```
```
  rows_  | null_factor | factor_ne_1 | syms_factor_ne_1 | null_adj_close | tret_ne_1
 1101531 |           0 |       62699 |              259 |              0 |    673917
 events by last_event_type: DIVIDEND 4178 | SPLIT 157 | BONUS 111
```
Cross-check: every split or bonus (ex-date 2024-04-15..2026-10-27) with adjusted rows in the 10 days before it has a factor ≠ 1 there: `256 | 256`. KOTAKBANK 5:1 split: 2026-01-13 raw 2132.60 → adj 426.52 (factor 0.2); 2026-01-14 raw 421.00. **Demergers are not adjusted**:
```
 TATAMOTORS | 2025-10-13 | raw 660.7500 | adj 660.750000 | factor 1
 TATAMOTORS | 2025-10-14 | raw 395.4500 | adj 395.450000 | factor 1     (demerger ex 2025-10-14 → false −40.2%)
```

## Q2. Index EOD
```sql
SELECT index_name, min(as_of_date), max(as_of_date), count(*) rows_, count(DISTINCT as_of_date) sessions, count(*) FILTER (WHERE close_price IS NULL) null_close,
 count(*) FILTER (WHERE high_price IS NULL OR low_price IS NULL OR open_price IS NULL) null_ohl, string_agg(DISTINCT source, ',') src
FROM nidp.index_eod WHERE index_name ILIKE ANY (ARRAY['nifty 50','nifty bank','nifty financial services','nifty midcap select','india vix', ...]) GROUP BY 1;
```
```
           index_name           |    min     |    max     | rows_ | sessions | null_close | null_ohl |      src
 India VIX                      | 2024-04-01 | 2026-10-27 |   635 |      635 |          0 |        0 | NSE_IND_CLOSE
 Nifty 50                       | 2024-04-01 | 2026-10-27 |   635 |      635 |          0 |        0 | NSE_IND_CLOSE
 Nifty Bank                     | 2024-04-01 | 2026-10-27 |   635 |      635 |          0 |        0 | NSE_IND_CLOSE
 Nifty Financial Services       | 2024-04-01 | 2026-10-27 |   635 |      635 |          0 |        0 | NSE_IND_CLOSE
 Nifty Midcap Select            | 2024-04-01 | 2026-10-27 |   635 |      635 |          0 |        0 | NSE_IND_CLOSE
 (173 indices in total, 635 sessions)
```
Calendar alignment: `index-only dates 0 | equity-only dates 0`. Sanity: flat OHLC 0, invalid OHLC 0, 253 rows in the 2024-09-23..2025-09-29 backfill window per index. Sample: Nifty 50 2024-06-04 close 21,884.50; 2025-04-07 close 22,161.60; India VIX 2024-06-04 close 26.75. Same three missing weekend special sessions as equity (they share the calendar).

## Q3. F&O contract-level history
```sql
SELECT min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) sessions, count(*) rows_ FROM nidp.fno_bhavcopy;
SELECT instrument_type, count(*) rows_, count(DISTINCT ticker_symbol) underlyings, min(as_of_date), max(as_of_date) FROM nidp.fno_bhavcopy GROUP BY 1;
```
```
    min     |    max     | sessions |  rows_
 2025-10-01 | 2026-10-27 |      263 | 10380988
 instrument_type |  rows_  | underlyings
 IDF             |    4101 |           6     (index futures)
 IDO             | 1351426 |           6     (index options)
 STF             |  164014 |         232     (stock futures)
 STO             | 8861447 |         232     (stock options)
 source: NSE_FO_BHAV only
```
Gaps: `eq sessions >= 2025-10-01: 263 | eq dates missing in fno: 0 | fno dates not in eq: 0`. Rows per day: min 29,088, median 37,924, max 54,042. Index underlyings: BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTY, NIFTYNXT50 have 263 sessions each; NIFTYFPI has 52 (from 2026-08-12). Raw archive: `fno_bhavcopy | 2025-10-01 | 2026-10-27 | 263 dates`, so nothing older is stored to re-parse.

**Fields** (April 2026):
```
 instrument_type | rows_  | pct_close | pct_settle | pct_oi | pct_vol | pct_undl | pct_lot | pct_traded_gt0 | pct_close_gt0 | pct_exp_ne_actual
 IDF             |    300 |     100.0 |      100.0 |  100.0 |   100.0 |    100.0 |   100.0 |           86.7 |         100.0 |  0.00
 IDO             | 128174 |     100.0 |      100.0 |  100.0 |   100.0 |    100.0 |   100.0 |           32.2 |         100.0 |  0.00
 STF             |  12610 |     100.0 |      100.0 |  100.0 |   100.0 |    100.0 |   100.0 |           98.6 |         100.0 |  0.07
 STO             | 771916 |     100.0 |      100.0 |  100.0 |   100.0 |    100.0 |   100.0 |           38.6 |         100.0 |  0.05
```
**What `close` means on untraded contracts** (2026-10-27):
```
 instrument_type | traded |   n   | pct_close_eq_settle | pct_close_eq_prev | pct_close_eq_last | pct_open_zero
 IDO             | f      |  3874 |                 0.0 |             100.0 |              11.9 |         100.0
 IDO             | t      |  2261 |                51.6 |               0.9 |              31.2 |           0.0
 STO             | f      | 14428 |                 0.1 |             100.0 |              31.3 |         100.0
 STO             | t      | 19984 |                33.2 |               8.6 |              62.8 |           0.0
```
So a "non-null close" is **not** evidence of a tradable price. For untraded rows it is the previous close, carried forward. A backtest must check `traded_volume > 0`, or knowingly use `settle_price`, which is NSE's settlement/theoretical price.

**NIFTY / BANKNIFTY chain depth at 7 dates spread across the history** (sessions #1, 45, 89, 133, 177, 221, 263):
```
 as_of_date | ticker    | expiries | expiry_strikes | contracts_nonnull_close | contracts_traded | near_exp_strikes | near_exp_traded_strikes | near_exp   | far_exp
 2025-10-01 | BANKNIFTY |        6 |            420 |                     839 |              356 |              135 |                     129 | 2025-10-28 | 2026-09-29
 2025-12-05 | BANKNIFTY |        6 |            469 |                     937 |              383 |              167 |                     167 | 2025-12-30 | 2026-09-29
 2026-02-10 | BANKNIFTY |        6 |            441 |                     882 |              372 |              134 |                     130 | 2026-02-24 | 2026-12-29
 2026-04-20 | BANKNIFTY |        6 |            676 |                    1352 |              646 |              224 |                     218 | 2026-04-28 | 2027-03-30
 2026-06-23 | BANKNIFTY |        6 |            572 |                    1144 |              550 |              194 |                     188 | 2026-06-30 | 2027-03-30
 2026-08-25 | BANKNIFTY |        6 |            481 |                     960 |              427 |              167 |                     161 | 2026-08-25 | 2027-06-29
 2026-10-27 | BANKNIFTY |        6 |            502 |                    1003 |              607 |              161 |                     155 | 2026-10-27 | 2027-09-28
 2025-10-01 | NIFTY     |       18 |            771 |                    1522 |              878 |               87 |                      87 | 2025-10-07 | 2030-06-25
 2025-12-05 | NIFTY     |       18 |            755 |                    1490 |              970 |               85 |                      85 | 2025-12-09 | 2030-06-25
 2026-02-10 | NIFTY     |       18 |            840 |                    1648 |             1115 |               98 |                      98 | 2026-02-10 | 2030-12-31
 2026-04-20 | NIFTY     |       18 |           1092 |                    2156 |             1232 |              130 |                     130 | 2026-04-21 | 2030-12-31
 2026-06-23 | NIFTY     |       18 |            921 |                    1814 |             1083 |              103 |                     103 | 2026-06-23 | 2030-12-31
 2026-08-25 | NIFTY     |       18 |            853 |                    1680 |              920 |              121 |                     121 | 2026-08-25 | 2031-06-24
 2026-10-27 | NIFTY     |       18 |            925 |                    1828 |             1167 |              144 |                     144 | 2026-10-27 | 2031-06-24
```
(`near_exp_traded_strikes` counts strikes where at least one side traded.) Liquidity by moneyness, NIFTY nearest expiry 2026-10-27: within 2% of spot, 38/38 contracts traded; 2–5%, 52/52; beyond 5%, 158/198.

**Futures per expiry** (2026-06-23): IDF 5 underlyings × 3 expiries, 13 of 15 traded; STF 211 underlyings, 1–3 expiries (avg 2.98), 628 of 629 traded. Example: NIFTY 2026-06-30 close 23,852.50, settle 23,852.50, lot 65, OI 15,876,575; 2026-07-28; 2026-08-25.

**Bid/ask**: none. A catalog search for column names matching `bid|ask|offer|spread|iv|implied|delta|gamma|vega|theta|greek` across all schemas returns only unrelated columns (`pcr_implied_pct`, `*_delta` share/weight deltas). Confirmed: **no bid/ask history and no per-contract Greeks or IV in the warehouse.**

## Q4. Contract metadata, point-in-time
**Lot size history** (index futures, by trading date):
```
 ticker_symbol | lot  | first_seen | last_seen  | expiries |  min_exp   |  max_exp
 BANKNIFTY     |   35 | 2025-10-01 | 2025-12-30 |        3 | 2025-10-28 | 2025-12-30
 BANKNIFTY     |   30 | 2025-10-29 | 2026-10-27 |       12 | 2026-01-27 | 2026-12-29
 FINNIFTY      |   65 → 60 (same pattern)
 MIDCPNIFTY    |  140 → 120 (same pattern)
 NIFTY         |   75 | 2025-10-01 | 2025-12-30 |        3 | 2025-10-28 | 2025-12-30
 NIFTY         |   65 | 2025-10-29 | 2026-10-27 |       12 | 2026-01-27 | 2026-12-29
 NIFTYFPI      | 1100 ; NIFTYNXT50 25 (no change)
```
The lot belongs to the **contract (expiry)**, not to the date: both lots coexist on the same days. Stock underlyings: `232 | 71 with_lot_change`; e.g. SUZLON, VBL, RVNL, KPITTECH have 85 dates with mixed lots across live expiries.

**Expiry calendar** (no expiry master table exists; it is derivable from `expiry_date`):
```
 NIFTY      Tue 52 expiries (2025-10-07..2026-10-27), Mon 5 (holiday shifts: 2025-10-20, 2026-03-02, 2026-03-30, 2026-04-13, 2026-10-19)
 BANKNIFTY  Tue 13 + Mon 1 (2026-03-30), monthly only
 FINNIFTY   Tue 12 + Mon 1 (monthly)      MIDCPNIFTY Tue 12 + Mon 1 (monthly)
```
NIFTY lists 18 expiries per day (weekly + monthly + quarterly/half-yearly out to 2031); BANKNIFTY lists 6. `expiry_date <> actual_expiry_date` marks early termination on corporate actions:
```
 TATAMOTORS | 2025-10-28 | 2025-10-13 | 260 ; 2025-11-25 | 2025-10-13 ; 2025-12-30 | 2025-10-13
 HINDUNILVR | 2025-12-30 | 2025-12-04 | 300 ; 2026-01-27 ; 2026-02-24
 VEDL       | 2026-05-26 | 2026-04-29 | 238 ; 2026-06-30 ; 2026-07-28
```
**Strike increments near ATM** (nearest expiry more than 3 days out):
```
 2025-10-01 | BANKNIFTY | steps within 3% of spot: 100 | all: 100,200,500
 2026-10-27 | BANKNIFTY | 100 | 100,200,500
 2025-10-01 | FINNIFTY  | 50  | 100,300,50,500      2026-10-27 | FINNIFTY | 100 | 100,400,500
 2025-10-01 | MIDCPNIFTY| 25  | 100,25              2026-10-27 | MIDCPNIFTY | 25 | 100,25
 2025-10-01 | NIFTY     | 50  | 50                  2026-10-27 | NIFTY | 50 | 50
```
FINNIFTY's ATM step changed from 50 to 100 within the window. The PRD's "ATM call and call 500 points higher" on BANKNIFTY is representable (100-point step).

**Contract additions**: NIFTY 2026-06-30 expiry has 149 strikes, of which 130 first appear after 2025-10-01 (last addition 2026-04-15). Strike existence must be checked per date.

**Historical instrument master**: none.
```
 public.instrument_master | 0 rows
 security_reference_daily | 2026-10-12 | 2026-10-27 | 12 sessions | 42937 rows (213 fno_eligible/day)
 ref.security_master      | valid_from 2026-10-12..2026-10-27 | 0 closed | 20682 (14,416 MF schemes + 6,266 equities)
 bse_scrip_master_daily   | 2026-10-06 | 2026-10-09 | 4 days
```
The F&O bhavcopy is the only point-in-time contract list.

## Q5. Intraday bars
```sql
SELECT filename, applied_at FROM nidp.schema_migrations WHERE filename ~ '^15[0-4]' ORDER BY 1;
SELECT to_regclass('nidp.intraday_bars') ib, to_regclass('nidp.intraday_ingest_log') il;
SELECT index_name, source, min(as_of_date), max(as_of_date), count(*) FROM nidp.tpd_paper_index_bars GROUP BY 1,2;
SELECT table_schema, table_name FROM information_schema.tables WHERE table_name ~* '(bar|candle|minute|intraday|tick|ohlc)';
```
```
 151_tpd_paper_trades.sql                 | 2026-10-12 15:46
 153_bse_scrip_master_daily.sql           | 2026-10-12 15:48      ← 152_kite_intraday_bars.sql NOT applied
 154_announcement_security_resolution.sql | 2026-10-12 15:48
 ib | il  →  (null) | (null)
 tpd_paper_index_bars → (0 rows)
 tables matching bar/candle/minute/intraday/tick/ohlc → nidp.tpd_paper_index_bars only
 (165 migrations applied, latest 184_scanx_mf_holdings_canonical_extension.sql)
```
Mongo (app DB), read-only:
```
 kite_live_minute   docs 358, first _id 2026-10-27T09:15, last 2026-10-27T15:29; row keys [p, s, t] (last price only); TTL 7,776,000 s (90 d)
 kite_live_intraday docs 73,  first _id 2026-10-27T09:15, last 2026-10-27T15:25; row keys [c, o, p, s, t, v] (no high/low); TTL 15,552,000 s (180 d)
 kite_live_close    docs 3 (2026-10-23..2026-10-27), daily quotes with OHLC + OI; TTL 400 d
```
Cron: `kite_bars` appears in neither the installed `/etc/cron.d/nidp-staging` nor the repo's `deploy/cloudpe/nidp/nidp-staging.cron`. The code (`kite_live_feed/intraday.py`) says: "nothing in the warehouse stores intraday bars on staging". It fetches 5m/15m/30m/60m Kite candles on demand (≤30 sessions, raw, needs the daily Kite login).
**UNVERIFIED**: whether the research VM (45.64.105.249) holds any intraday archive. I did not inspect it, because it is outside the staging warehouse scope given.

## Q6. Implied volatility / Greeks history
```python
# docker exec nivesh-staging-app-backend … motor, collection fno_iv_history, $group by underlying
```
```
fno_iv_history docs: 524
underlyings: 2
{'_id': 'NIFTY',     'n': 262, 'first': '2025-10-01', 'last': '2026-10-26', 'methods': ['backfill'], 'nonnull_atm': 262}
{'_id': 'BANKNIFTY', 'n': 262, 'first': '2025-10-01', 'last': '2026-10-26', 'methods': ['backfill'], 'nonnull_atm': 262}
```
- **Model-derived**: `services/fno_iv_history.py` reads "ATM IV by the chain route's model (routes/fno.py session_iv: Black-76 on the forward, services/option_pricing)" from bhavcopy rows. `expiry_atm_iv` needs a same-expiry future or "a strike whose call and put both traded". There are two buckets (near_month, next_month), ATM only, at a fixed rate of 5.75%.
- Not scheduled: `record_iv_history.py` says "Schedule (documented here, NOT installed …)", and `/etc/cron.d` on the app VM has no IV file (files present: ai-watchlist, cache-clear, db-snapshot, desk-alerts, positional-engine, research-watchlist). So 2026-10-27 is missing.
- No per-contract IV, no Greeks history, no IV for FINNIFTY, MIDCPNIFTY or stocks. The warehouse has no IV/Greek columns (see Q3).

## Q7. Holidays, expiry handling, corporate actions
```sql
SELECT segment, min(holiday_date), max(holiday_date), count(*) FROM nidp.nse_holidays GROUP BY 1;
```
```
 CM  | 2026-01-15 | 2026-12-25 | 20     FO | 2026-01-15 | 2026-12-25 | 20     (12 segments, all 2026 only; COM from 2026-01-01)
 last write 2026-10-12 17:27 (nse_calendar, monthly on the 1st)
```
For history, the stored session set (`prices_eod`, identical to `index_eod` and `fno_bhavcopy` in its window) is the only calendar. Expiry-day handling is covered by the data: the holiday-shifted Monday expiries and `actual_expiry_date` early terminations are in `fno_bhavcopy` (Q4). Settlement value: `settle_price` and `underlying_price` are present on expiry day.

Corporate actions:
```
    action_type    | rows_ | syms |    min     |    max     | src
 DIVIDEND          |  4726 | 1554 | 2024-03-06 | 2026-10-30 | NSE_CA
 AGM               |   980 |  975 | 2024-03-11 | 2025-07-21 | NSE_CA
 SPLIT             |   184 |  182 | 2024-03-01 | 2026-10-23 | NSE_CA
 INTEREST_PAYMENT  |   175 |   73 | …
 BONUS             |   175 |  168 | 2024-03-05 | 2026-10-15 | NSE_CA
 RIGHTS            |   161 |  143 | …
 DISTRIBUTION      |   139 |   26 | …
 BUYBACK           |    79 |   70 | …
 OTHER             |    61 |   55 | …
 DEMERGER          |    43 |   42 | 2024-04-19 | 2026-10-08 | NSE_CA
 CAPITAL_REDUCTION |     2 | MERGER 1 | EGM 1
 by year: 2024 2714 (73 splits, 63 bonus) | 2025 2021 (57, 71) | 2026 1992 (54, 41)
```
The AGM rows stop at 2025-07-21 (it looks like a feed-format change; not investigated). Demergers are recorded (TMPV 2025-10-14, HINDUNILVR 2025-12-05, VEDL 2026-04-30) but are not applied to adjusted prices (Q1).

## Q8. Charges
There is no charges or rates table in the warehouse. A column search for `brokerage|stt|stamp|gst|exchange_charge|txn_charge|sebi_fee|slippage|charges` finds only per-trade result columns: `public.strategy_trades.brokerage`, `.slippage_pct`, and `nidp.tpd_paper_trades.entry_slippage`.

Code constants in `backend/services/desk_cost_card.py` (`VERSION = "desk-cost-v2"`):
- Desk assumptions: `BROKERAGE_RS_PER_SIDE = 20.0`, `SLIPPAGE_PCT_PER_SIDE = 0.05`. Slippage doubles as the spread allowance ("the desk trades on end-of-day bars, which carry no bid or ask").
- equity_delivery: STT 0.1% buy and sell; exchange 0.00307% (start date 2026-03-01 marked UNVERIFIED in the file); SEBI ₹10/cr; stamp 0.015% buy; GST 18%.
- futures: STT 0.05% sell; exchange 0.00183%; SEBI ₹10/cr; stamp 0.002% buy; GST 18%. Source zerodha.com/charges, retrieved 2026-10-27, `effective_from=None`.
- options: STT 0.15% sell-side premium (and on exercised intrinsic value); exchange 0.03553% of premium; SEBI ₹10/cr; stamp 0.003% buy; GST 18%. Same source, no effective date.
- There is no dated rate history, so a backtest of 2025-10..2026-10 charges today's F&O rates on every date. There is no intraday-equity segment. DP charges are not charged.
- `strategy_engine/backtest.py` uses `desk-cost-v2` by default, for equity delivery only ("the desk cost card … for equity delivery per order side"). Its slippage goes into the fill prices.

## Q9. What is scheduled and when it last wrote
Installed `/etc/cron.d/nidp-staging` on 45.64.105.224 (58 active lines; `CRON_TZ=Asia/Kolkata`), relevant entries:
```
0  19 * * 1-5  bhavcopy                     30 22 * * 1-5  price_adjuster
0  19 * * 1-5  index_close                  30 7  * * 1-5  nse_reference_snapshot
30 19 * * 1-5  fno_bhavcopy                 0  7  * * 0    nse_equity_master
0  21 * * 1-5  fno_bhavcopy                 0  6  1 * *    nse_calendar
15 22 * * 1-5  fno_bhavcopy                 30 6  1 * *    index_constituents
0  20 * * *    corporate_actions            35 22 * * 1-5  technical_indicator_engine
30 10 * * 2-6  delivery                     0  22 * * 1-5  snapshot_builder
```
Not installed anywhere: `kite_bars` (also absent from the repo cron), the IV recorder (app VM), `price_adjuster` full-history backfill.

Last writes:
```
            t             |  max_date  |       last_write (IST)
 prices_eod               | 2026-10-27 | 2026-10-27 19:00:02
 index_eod                | 2026-10-27 | 2026-10-27 19:00:02
 fno_bhavcopy             | 2026-10-27 | 2026-10-27 22:15:14
 prices_eod_adjusted      | 2026-10-27 | 2026-10-27 22:33:25
 corporate_actions        | 2026-10-30 | 2026-10-27 20:00:02   (max ex_date is a future date)
 security_reference_daily | 2026-10-27 | 2026-10-27 07:30:02
 delivery_data            | 2026-10-26 | 2026-10-27 10:30:03
 nse_holidays             | 2026-12-25 | 2026-10-12 17:27:45
```
`nidp.v_feed_status`: bhavcopy, fno_bhavcopy, index_close, price_adjuster, corporate_actions, nse_reference_snapshot, nse_equity_master, nse_calendar, index_constituents all `last_run_status OK`, `consecutive_failures 0`. delivery is 1 day stale, which is expected because it lags a session.

---

## What backtests the data can honestly support today

1. **Equity, daily bars, long/short stock rules** (PRD example 1, "close above yesterday's high; 2% stop / 5% target"): adjusted OHLC **from 2025-10-01 for every EQ symbol** (~2,300–2,700 per session). **From 2024-04-01 only for ~1,200 symbols** in the adjusted table. Raw from 2024-04-01 for ~1,900–2,100 EQ symbols per session, but raw needs stitching across splits/bonuses (the factors exist), renames (by ISIN) and demergers (no factor exists). Stop/target-in-one-candle must use a documented conservative rule: no lower timeframe exists.
2. **Index daily signals** (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY underlying, India VIX): complete from 2024-04-01, 635 sessions.
3. **Index and stock options and futures, EOD, close-to-close**, **2025-10-01 → 2026-10-27 (263 sessions, ~12.9 months)**: per-contract close/settle, OI, volume and lot size, with strike, expiry and lot validation per historical date and the real expiry calendar (weekly NIFTY; monthly BANKNIFTY, FINNIFTY, MIDCPNIFTY; 232 stock underlyings). Fills must be EOD (close or settle) with an explicit **"traded that day" check**. **No bid/ask**, so spreads can only be an assumption. A "12-month backtest" barely fits. A 24-month option backtest is impossible.
4. **Multi-leg EOD structures** (verticals, straddles/strangles, iron condors, calendars, covered call/protective put on F&O stocks): data supports them in the F&O window. Far-OTM and far-dated legs are often untraded (e.g. 40 of 198 NIFTY strikes beyond 5% untraded on the nearest expiry), so expect blocked legs rather than silent stale prices.
5. **IV-based conditions**: only ATM IV for NIFTY and BANKNIFTY, model-derived (Black-76 from bhavcopy closes), 2025-10-01..2026-10-26. It must be labelled model-derived (PRD §10.3).
6. **Costs**: `desk-cost-v2` constants, disclosed as current rates applied to past dates, plus desk assumptions for brokerage and slippage.

## Data gaps that block PRD features

- **No intraday history at all** (`nidp.intraday_bars` never created; `kite_bars` not scheduled; Mongo live caches hold one session with a 90–180-day TTL). This blocks every 15-minute or intraday-RSI rule (PRD §6.3 example 2), intraday entries and exits, and lower-timeframe resolution of stop-vs-target in one candle (§10.2).
- **No bid/ask or quote history.** This blocks spread-aware fills and the partial-fill modelling of §10.2. Only an assumed slippage/spread is possible.
- **F&O history starts 2025-10-01** (no older raw archives on staging). This blocks option/futures backtests longer than ~12.9 months, walk-forward with a meaningful out-of-sample window on options (§10.4), and any 24-month option example.
- **No per-contract IV or Greeks history**, and ATM IV for only 2 underlyings, with the recorder unscheduled. This blocks delta-hedge templates (§6.2 relative value) and Greek-based entry/exit rules, except as a labelled model-derived approximation.
- **Adjusted equity history is incomplete before 2025-10-01** (~810 of ~2,090 EQ symbols missing on a sampled date). It also breaks at renames and ignores demergers. This blocks reliable 24-month stock backtests (§6.3 example 4) beyond ~1,230 symbols until the adjuster runs full-history and renames and demergers are handled.
- **No point-in-time instrument master, index membership or 2024–25 holiday calendar.** Index-universe screens carry survivorship bias. Holidays must come from the stored sessions. The 3 missing weekend special sessions (2024-05-18, 2025-02-01, 2026-02-01) are silent gaps.
- **Precomputed features only from 2025-12-29 (204 sessions).** The existing engine's signal calendar is shorter than 12 months unless indicators are computed from prices.
- **Charges have no history.** Pre-change periods cannot be charged their actual statutory rates, and the F&O rates' effective dates are UNVERIFIED in the code.
- **Margin history**: none is stored (`fno_margin.py` reads Kite live). This blocks historical margin and capital-use metrics for mixed or short-option strategies (§22 "Mixed strategies require combined exposure, margin …"). This was not measured further here.

UNVERIFIED and not checked: the research VM's files; prod (out of scope); whether NSE's 2024–25 holiday list exactly matches the 24 missing weekdays (it matches by recollection only).
