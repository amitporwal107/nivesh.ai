# Scan Builder — design and API contract (v1)

Owner request (3 Nov 2026): "create a Chartink kind of dashboard … the data is from Kite or TrueData … take inspiration from
Chartink … not get the dashboard data from Chartink … work on creating this [the widget editor] first … refresh every 10 seconds
to fetch latest quotes". Owner choices the same day: it lives at **Market Desk › Scan Builder**; **daily, weekly and monthly
first**, intraday (5 min / 15 min / 1 hour) is the next step.

Reference only (never fetched at run time): Chartink public dashboard 247498 "Atlas fresh", 17 table widgets, and the owner's
three screenshots of Chartink's widget editor (Columns · Filters · Group/Sort, Design · Result, Run · Save · Copy · Cancel).

## 1. What v1 is

A scan editor in the desk. A scan = a filter tree + result columns + sort/limit. **Run** evaluates it over a universe of NSE
stocks on our own data and shows the matching stocks. While the market is open the Result view re-runs every 10 seconds with
the latest Kite quotes. Scans are saved per user (Save, Copy, delete).

Not in v1 (named so nobody assumes them): intraday timeframes; the dashboard grid of saved scans; market-statistic widgets
(advances/declines by market cap, ± volume); buyer-vs-seller-initiated trades (no data); gross profit and 3-year average ROCE
(no data); charts in the result; "save results to a watchlist".

## 2. Data — every number from our own stack, never from Chartink

| Input | Source | Notes |
|---|---|---|
| Daily OHLCV history | DaaS `POST /v1/prices/adjusted/bulk` (nidp.prices_eod_adjusted, NSE bhavcopy, split/bonus adjusted, EQ series) | From 2024-04-01; 999 symbols start 2025-10-01. Loaded once per EOD day (≤300 symbols per call, ~2 s each), kept in memory as float arrays, shared by the 4 workers through a file cache + lock. |
| Today's candle | `services/kite_live_feed/day_quote.day_quotes` (owner rule 29 Oct: market open → Kite live; after the close → saved Kite close; once the EOD file is in → EOD) + `join_bar` (joins only when Kite's previous close equals the series' last close, so a pending split/bonus never corrupts the series) | The live feed carries ~600 cash stocks (Nifty 500 + F&O). The rest of a universe gets Kite REST `quote()` through one process-wide cache: batches of 500, ≥1.1 s apart, refreshed at most every 30 s while open (10 min closed). |
| Weekly / monthly candles | Built from the daily candles (incl. today's) by calendar week (Mon–Sun) / month | The current week/month is the one in progress, as on Chartink. |
| Fundamentals | DaaS `GET /v1/stocks/screener?limit=5000` (nidp.stock_features_daily latest row) | 2,488 stocks on 2 Nov. As of the last EOD; not live. |
| Universes | DaaS `GET /v1/symbols/universe` (all symbols, F&O flag, name) and `GET /v1/indices/{name}/constituents` | Latest constituent snapshot (monthly). |

The provider switch (`backend/nidp/shared/market_data_source.py`) is respected: Kite serves live quotes today; when the switch
serves TrueData, the live feed module is what changes, not this feature.

Today-bar rule during the session: a stock whose today's candle is missing (no quote) or does not join (pending corporate
action) is **left out of the run** and counted (`counts.no_today_bar`), so every row in a result is on the same day. Before
09:15 and on holidays every stock is on its last EOD bar.

## 3. Scan definition (JSON stored and sent)

```
ScanSpec  { version: 1, name: str(1..80), description: str(0..400), filters: Group, columns: Column[1..12],
            sort: { column: <column id>, dir: "asc"|"desc" }, limit: int(1..500, default 50) }
Group     { id, kind: "group", join: "all"|"any", universe: UniverseKey | null, enabled: bool, comment: str(0..200),
            children: (Group|Filter)[0..30] }          root universe required; a child's null = its parent's
Filter    { id, kind: "filter", left: Expr, op: Op, right: Expr, enabled: bool, comment: str(0..200) }
Column    { id, alias: str(1..40), expr: Expr, enabled: bool, format: "number"|"pct"|"price"|"volume" }
Expr      { terms: Term[1..8] }       evaluated LEFT TO RIGHT as written (Chartink's rule):
                                       Close - 1 day ago Close / 1 day ago Close * 100  ==  ((C - C1) / C1) * 100
Term      { op: null (first term only) | "+" | "-" | "*" | "/", operand: Operand }
Operand   { kind: "number", value: float }
        | { kind: "measure", tf: "1d"|"1w"|"1M", offset: int(0..250), measure: MeasureKey, params: {name: number|source} }
        | { kind: "fundamental", field: FundamentalKey }
Op        "gt" | "gte" | "lt" | "lte" | "eq" | "crosses_above" | "crosses_below"
ids       client-made, [A-Za-z0-9_-]{1,24}, unique within the spec
limits    groups nested ≤ 4 deep, ≤ 40 filters in all, spec JSON ≤ 64 KB
```

Semantics: a stock passes a group when it is in the group's universe and all (join all) / any (join any) of its ENABLED
children pass; an enabled group with no enabled children passes. A disabled node is ignored. A comparison with a missing value
(not enough history, no fundamental, division by zero) is **unknown**, which does not pass. `offset` 0 = the latest candle,
1 = one candle before it (per stock: its own candles). Crosses above at offset o: `L[o] > R[o] and L[o+1] <= R[o+1]`.
`eq` is exact equality. Arithmetic: x / 0 → missing.

Measures (params with default and bounds; `source` ∈ open, high, low, close, volume):

| key | label | params |
|---|---|---|
| open high low close volume | price fields | — |
| sma, ema | Simple / Exponential moving average | source=close, period=20 (1–500) |
| max, min | Highest / Lowest of last N | source=close, period=20 (1–500) |
| rsi | RSI (Wilder) | period=14 (2–100) |
| macd_line, macd_signal, macd_hist | MACD | slow=26, fast=12, signal=9 (1–100) |
| adx, di_plus, di_minus | ADX, +DI, −DI (Wilder) | period=14 (2–100) |
| atr | Average true range (Wilder) | period=14 (1–100) |
| supertrend | Supertrend | period=7 (1–100), multiplier=3 (0.1–10) |
| psar | Parabolic SAR | start=0.02, increment=0.02, max=0.2 (0.001–1) |
| cci | Commodity channel index | period=20 (2–100) |
| stoch_k | Fast stochastic %K | period=14 (2–100) |
| stoch_d | Fast stochastic %D (slow %K) | period=14 (2–100), smooth=3 (1–20) |
| bb_upper, bb_lower | Bollinger band | period=20 (2–100), dev=2 (0.1–5) |

Definitions (tests pin them): EMA seeded with the SMA of the first `period` values, alpha 2/(n+1); Wilder smoothing seeded with
the SMA, alpha 1/n; RSI = Wilder on gains/losses; TR uses the previous close; ADX = Wilder of DX after +DI/−DI; MACD line =
EMA(fast) − EMA(slow) of close, signal = EMA(signal) of the line; CCI = (TP − SMA(TP)) / (0.015 × mean abs deviation), TP =
(H+L+C)/3; Supertrend = the standard ATR band (HL2 ± mult × ATR, Wilder) with the final-band carry and trend flip; PSAR =
Wilder's with the given start/increment/max; Bollinger = SMA ± dev × population SD; %K = 100 (C − LL)/(HH − LL), %D = SMA(smooth)
of %K. A value needs at least the bars its definition needs (e.g. period for SMA, period+1 for RSI); before that it is missing.

Fundamentals (`field`): market_cap_cr, pe_ttm, pb, roce_pct, roe_pct, debt_to_equity, eps_growth_yoy_pct,
eps_growth_3y_cagr_pct, pat_growth_yoy_pct, revenue_growth_yoy_pct, revenue_growth_3y_cagr_pct, profit_margin_pct, ev_ebitda,
interest_coverage, dividend_yield_pct, promoter_pct, promoter_pledged_pct, fii_pct, dii_pct.

Universes: cash "All NSE stocks", fno "F&O stocks", nifty50, nifty100, nifty200, nifty500, midcap150 "Nifty Midcap 150",
smallcap250 "Nifty Smallcap 250", niftybank "Nifty Bank".

Default new scan: universe cash, no filters, columns `% Change` (Close − 1 day ago Close / 1 day ago Close × 100, pct),
`Price` (Close, price), `Volume` (Volume, volume); sort `% Change` desc; limit 50.

## 4. API (all under `/api/scan-builder`, signed-in user, behind feature flag `scan_builder`; default allowlist = owner)

| Method | Path | Body → answer |
|---|---|---|
| GET | `/catalog` | → `{measures[], fundamentals[], operators[], universes[], timeframes[], templates[], limits, refresh_seconds: 10, default_spec}`. timeframes lists 5m/15m/1h with `available: false, reason`. Also starts warming the price panel in the background. |
| POST | `/run` | `{spec}` → RunResult. One run per user per 4 s (429 `run_too_soon`, `retry_after_s`). |
| GET | `/scans` | → `{scans: [{id, name, description, created_at, updated_at}]}` newest first |
| POST | `/scans` | `{spec}` → `{scan: {id, spec, created_at, updated_at}}` (≤100 per user, 409 `too_many_scans`) |
| GET | `/scans/{id}` | → `{scan}` (404 `scan_not_found` for another user's) |
| PUT | `/scans/{id}` | `{spec}` → `{scan}` |
| POST | `/scans/{id}/copy` | → `{scan}` named "Copy of <name>" |
| DELETE | `/scans/{id}` | → `{ok: true}` |

RunResult:
```
{ ok: true, run_at, elapsed_ms,
  basis:   { mode: "live"|"kite_close"|"eod", day, eod_date, quote_as_of, text },
  sources: { prices, today, fundamentals },
  market:  { open: bool, refresh_seconds: 10 },
  universe:{ key, label, size },
  counts:  { universe, evaluated, matched, shown, no_today_bar, no_history },
  columns: [{ id, alias, format }],
  rows:    [{ symbol, name, values: (number|null)[], today: "live"|"kite_close"|"eod" }],
  nodes:   { <node id>: { passed, unknown } },          the per-filter "debug" counts
  warnings:[str] }
```
Typed errors `{detail: {code, message, path?}}`: `invalid_spec` (422, `path` = JSON path of the first problem),
`run_too_soon` (429), `data_unavailable` (503: the price panel could not be loaded), `scan_not_found` (404), `too_many_scans`
(409), `feature_disabled` (403, from the flag dependency).

## 5. UI (Market Desk › Scan Builder, `?tab=market&view=scanbuilder[&scan=<id>]`)

Left: saved scans list (+ New scan, templates). Right: the editor, as in the owner's screenshots — a rail **Columns · Filters
· Group/Sort**, a **Design · Result** switch, footer **Run · Save · Copy** … **Cancel**.

- Filters: "Stock passes [all ▾] of the below filters in [All NSE stocks ▾] segment:" then one row per filter as clickable
  tokens: `[Daily ▾] [latest ▾] [RSI(14) ▾] [Greater than ▾] [Number 55]`, each row with: operation (add + − × ÷ term),
  comment, duplicate, enable switch, debug count (after a run: how many stocks passed), delete. Under each group: + filter,
  + group. A measure picker (search) lists the catalog by group (Price, Moving averages, Momentum, Trend, Volatility,
  Fundamentals); intraday timeframes are shown disabled with "coming next".
- Columns: one row per column: tokens + "AS <alias>" + format, with the same row actions; + column.
- Group/Sort: group column Symbol (fixed in v1), sort column + direction, number of symbols (slider 1–500).
- Result: a sortable table (Symbol · Name · the columns), the basis line ("Kite live 10:15:32 IST over NSE EOD to 31 Oct …"),
  counts (universe · evaluated · matched · left out: no live quote / not enough history), warnings, and a live chip that
  re-runs every 10 s while the market is open and the tab is visible (pauses when hidden or after the close).
- Wording: no "buy", "sell", "target", "stop loss", "picks" (owner, 3 Nov). Templates are named for what they test.

## 6. Performance targets

Warm run, All NSE stocks (~2,700), ≤10 filters: < 1.5 s on the staging VM (measured in the report). Cold first run of the
day (panel load): < 60 s, with the UI saying so. REST quotes for stocks outside the feed: ≤ 6 calls per 30 s per process.

## 7. Scan dashboard (v1.1, owner 3 Nov: "chartink like scans … under the existing screener" + design `docs/Scan Dashboard Standalone (3).html`)

### 7.1 Where
Market Desk › Screener gets three sub-views (`?tab=market&view=screener&sub=…`): **Screener** (`screens`, the existing screener,
default) · **Scan dashboard** (`dashboard`) · **Scan builder** (`builder`, the editor of §5, moved here). The last two show only
with the `scan_builder` flag. The old `view=scanbuilder` URL redirects to `view=screener&sub=builder` (keeps `scan=`).

### 7.2 Grouped scans (the market-cap widgets)
`ScanSpec.group_by`: `"symbol"` (default, §3) | `"marketcap"`. When `"marketcap"`, every column carries an aggregate:

```
Column + agg:   "share" | "count" | "sum" | "avg" | "diff"      required when grouped, must be absent/null when not
         where: Filter | null       share/count/sum/avg only: the stocks counted/summed are those passing the scan's filters AND `where`
         of:    [colIdA, colIdB]    diff only: value(A) − value(B); A and B are other (non-diff) columns of the scan
share = % of the group's matched stocks passing `where` (no where → 100) · count = how many · sum / avg = of `expr` (missing skipped)
```
Groups: every stock with a market cap in the NIDP feature store (last EOD) ranked by it, largest first: 1–100 **Largecap**,
101–250 **Midcap**, 251+ **Smallcap** (the SEBI/AMFI rank rule; AMFI ranks on a 6-month average, we on the latest value — said in
`sources.groups`). A stock with no market cap is in no group. `limit` = number of groups shown (1–3). Sort is by a column, as before.
Grouped RunResult: `group_by: "marketcap"`; `rows: [{symbol: "Largecap", name: "<n> stocks", values, today}]` (symbol is the group
label, never a link); `counts.matched` = stocks in all groups. Ungrouped RunResults carry `group_by: "symbol"`.

### 7.3 F&O fields (the open-interest widgets)
Four more `fundamental` fields (catalog entries carry `group: "F&O (NSE end of day)"`; the others `group: "Fundamentals"`):
`fno_price_chg_pct` Futures price change % · `fno_oi_chg_pct` Futures OI change % · `fno_prev_price_chg_pct` and
`fno_prev_oi_chg_pct` (the session before). Source: DaaS `/v1/desk/fno-buildup` (nidp.fno_bhavcopy, stock futures: nearest expiry's
price change, OI summed over expiries) for the latest session and the one before. Used only when the latest session is today or the
previous trading session (owner rule 28 Oct); otherwise the fields are missing and a warning says why. A run that uses them adds
`sources.fno` = "NSE F&O bhavcopy, <day> …". Live intraday OI is a later step.

### 7.4 Dashboard API (signed-in user, `scan_builder` flag)
| Method | Path | Body → answer |
|---|---|---|
| GET | `/dashboard` | → `{dashboard, is_default}` (the user's saved dashboard, else the default "Fresh") |
| PUT | `/dashboard` | `{dashboard}` → `{dashboard, is_default: false}`; each widget's spec validated (422 `invalid_spec`, `path` = `widgets[i].spec.<path>`) |
| DELETE | `/dashboard` | → `{dashboard: <default>, is_default: true}` (back to the default) |
| POST | `/dashboard/run` | `{widgets?: [id]}` (default all) → DashboardRun. One per user per 4 s (429 `run_too_soon`, `retry_after_s`) |

```
Dashboard { name: str(1..60), widgets: Widget[0..20] }
Widget    { id: [A-Za-z0-9_-]{1,24} unique, title: str(1..80), size: "s"|"m"|"l" (card height 300 / 320 / 400 px),
            kind: "scan", spec: ScanSpec  |  kind: "indices", indices: [Kite index name, 1..10] (e.g. "NIFTY 50", "NIFTY BANK") }
DashboardRun { ok, run_at, elapsed_ms, market: {open, refresh_seconds: 10}, results: { <widget id>: WidgetResult } }
WidgetResult  RunResult (§4, + group_by)  |  IndexResult  |  { ok: false, error: { code, message } }   (one widget failing never fails the rest)
IndexResult { ok: true, kind: "indices", group_by: "symbol", basis: {mode: "live"|"kite_close"|"none", day, quote_as_of, text},
              columns: [{id: "ltp", alias: "LTP", format: "price"}, {id: "chg", alias: "% chg", format: "pct"}],
              rows: [{symbol: "NIFTY", name: "NIFTY 50", values: [ltp, pct], today}], counts: {matched}, warnings }
```
Index source: Kite (live in session, the saved Kite close after it — `kite_live_feed.day_quote.day_quotes`); % chg against Kite's
previous close. Short names: NIFTY 50 → NIFTY, NIFTY BANK → BANKNIFTY, NIFTY FIN SERVICE → FINNIFTY, NIFTY MID SELECT → MIDCPNIFTY.

### 7.5 The default dashboard "Fresh" (each widget is a real scan; Edit opens ITS definition)
| id | Title (design title → ours) | Definition |
|---|---|---|
| mcap_ad | Marketcap advances / declines | All NSE, by market cap; Advances = share where Close > 1 day ago Close; Declines = share where Close < 1 day ago Close |
| mcap_vol | Positive vs negative volumes | by market cap, in lakh shares; Positive = sum Volume ÷ 100000 where up; Negative = same where down; +/- vol = Positive − Negative |
| indices | Index stats | NIFTY BANK, NIFTY 50 |
| n50_gainers | Nifty 50 top gainers | Nifty 50, % change > 0, by % change |
| long_buildup | Long build-up (fresh) | F&O stocks: futures price ↑ and OI ↑ in the latest session, and NOT both ↑ the session before |
| strong_movers | "Today's top buy" → **Today's strong movers** | % change > 5, Volume ÷ 1-day-ago SMA(Volume, 20) × 100 > 200, CCI(20) > 100, ADX(14) > 25. Buy% and Dbuy are dropped: we have no buyer/seller-initiated trade data, and "buy" is barred wording (owner 3 Nov) |
| good_results | Good quarter result stocks | Net profit growth YoY > 25 %, revenue growth YoY > 15 %, market cap > ₹500 cr |
| open_interest | Open interest | F&O stocks, futures OI change ≥ 10 % in the latest session, by OI change |
| vol_10x | "10x volume first 5 min" → **10x volume (day)** | Volume > 10 × 1-day-ago SMA(Volume, 20). The first-5-minute version needs intraday candles (next step) |

### 7.6 UI (design `Scan Dashboard Standalone`, adapted)
Header: dashboard name, data badge (Kite live hh:mm:ss · Kite close · NSE EOD <day>), widget search (filters cards by title),
stock search (filters rows by symbol in every card), Auto-refresh toggle (default on: every 10 s while the market is open and the
tab visible), **Add scan** (editor with a new scan; Save adds a widget), **Reset to default** (when customised).
Card: title, basis sub-line, count pill ("50 stocks" = matched), buttons Expand (full width) · Chart (first symbol in Trade Desk ›
Chart Analysis) · Info (description, sources, counts, warnings) · Copy (rows as tab-separated text) · CSV (download) · Edit · Remove
(saved). Sortable headers (click again reverses), % columns mint/red by sign, symbols are mint links ↗ opening the chart in a new tab
(group rows and index rows: no links except index → none). Edit panel opens ABOVE the grid: rail Columns · Filters · Group/Sort,
Design · Result, Run · Save · Cancel (Cancel closes). Group/Sort adds "Group by: Symbol | Market cap"; grouped Columns rows edit
the aggregate, its "where" condition and, for a difference, the two columns.
Left out of the design on purpose (say so in the report): social share chips, Access, Copy dashboard, the premium-subscription
banner (Chartink's own), Show chart preview (no preview to show yet), Y-axis / Transpose (chart options; no charts yet).

## 8. Realtime scan dashboard (owner 3 Nov ~09:15: "a simple dashboard … real time data from Kite or TrueData … with each widget criteria … updated with today's data")
Supersedes the editable dashboard of §7.4–7.6 for now (parked): ONE fixed dashboard = the 17 widgets of Chartink dashboard 247498
(definitions only; docs/scan_builder/chartink_247498/), computed on our data, refreshed every 10 s while the market is open.

Place: Market Desk › Screener › **Scan dashboard** (`?tab=market&view=screener&sub=dashboard`; sub-views Screener · Scan dashboard ·
Scan builder, the last two behind the `scan_builder` flag; old `view=scanbuilder` → `sub=builder`).

`GET /api/scan-builder/market-dashboard` (signed in, flag) →
```
{ ok, run_at, elapsed_ms, cached,
  basis:   { mode: live|kite_close|eod, day, eod_date, quote_as_of, text },
  market:  { open, refresh_seconds: 10 },
  counts:  { cash, fno, nifty50, no_today_bar },
  sources: { prices, today, fundamentals, results, intraday, groups },
  warnings:[str],
  widgets: [ { id, chartink_id, title, universe, status: ok|partial|pending|not_computed, note,
               criteria: [ { text, level, applied, note } ],          one line per condition, nested groups indented
               columns:  [ { key, label, format: text|pct|price|volume|number } ],
               rows:     [ [cell, …] ],                                aligned to columns; null = missing
               row_kind: symbol|group|index,                           symbol rows link to the chart
               count, as_of } ] }
```
Realtime: today's candle = Kite live (feed ~1 s; REST quotes for the rest, ≤30 s) over NSE EOD bars; intraday conditions (15-minute,
1-hour) from Kite historical candles, cached across workers and rate-limited (≤1.5 calls/s for this feature), refreshed every
1–5 min, each widget saying the candle time it used. Company results (quarterly/annual net profit, EPS, PBDT) from DaaS
/v1/financials/{symbol}, loaded once a day in the background (status `pending` until loaded). One computation per ~8 s per
worker is shared by every viewer. "10x volume first 5 min" (owner 3 Nov 12:40: "fix this using kite or true data"): daily
part (volume > 10 lakh, open ≥ 50) → Kite 5-minute candles (15 sessions; today's first candle volume > 10 × SMA(volume, 1000) as
of the candle before the latest; re-read every 30 min, ~250 stocks) → for the survivors only, TrueData tick history with best
bid/ask (tick_flow.py): each print classified by the quote rule (at/above the ask = initiated at the ask, at/below the bid = at
the bid, inside the spread by the mid, at the mid by the tick test; the opening-auction print and 1-share markers skipped);
condition: ask-side prints > bid-side prints (ratio > 1). TrueData counts snapshot prints (~1 a second), not every exchange trade. When TrueData gives no ticks (owner 4 Nov: "please fetch from kite if true data not working"; the main TrueData login was refused 3–4 Nov), the same rule runs on Kite live ticks: the live feed puts the cash stocks in 'full' mode (order book) and kite_live_feed/trade_side.py sides each print (cumulative-volume rise between two ticks) against the previous tick's best bid/ask; the counts ride on each cash quote in the quote cache (ask_trades, bid_trades, ask_volume, bid_volume, sides_since). Kite keeps no tick history, so counts start when the feed first carried the stock today; the dashboard asks the feed to carry the daily-part candidates (request_symbols) on every live computation, and the card says the trade side came from Kite. Only the continuous session counts (the opening auction is a baseline); a reconnect re-baselines (the gap's volume is not sided). Switch KITE_FEED_TRADE_SIDES (default on when APP_ENV=staging). A 1-minute-candle proxy was tried and dropped: it agreed with TrueData's sides on 4 of 10 stocks. Titles/labels avoid "buy" (owner 3 Nov): TODAYS TOP BUY → Today's strong movers; BUY% → 15m pos %;
DBUY → Day pos % ((Close − Low) ÷ (High − Low) × 100); OPEN INTEREST BUY7 → Open interest 7; Copy - supertrend rsi scan →
Supertrend RSI scan.

## 9. Second dashboard tab "Day trade" = Chartink 503347 (owner 3 Nov ~17:15: "add another chartlink scan in another tab")
The owner's dashboard 225969 is private on Chartink (no definitions served); he published a copy, 503347 ("Copy day trade",
20 widgets; queries verbatim in docs/scan_builder/chartink_503347/widgets.md). Same page, same computation as §8, as a tab:
Market Desk › Screener › Scan dashboard › **Atlas fresh | Day trade** (`dash=daytrade` in the URL).

`GET /api/scan-builder/market-dashboard?dashboard=atlas|daytrade` (default atlas; another key → 422 `unknown_dashboard`).
The §8 payload plus `dashboard {key, title, chartink_id}` and `dashboards [...]` (the tabs). One computation per dashboard per
CACHE_S per worker. The frontend never shows an answer whose `dashboard.key` is not the tab asked for (an old backend
ignores the parameter and answers atlas).

Mapping: {33489} = F&O stocks; "earning per share[eps]" = EPS, latest year; "prev year eps" = EPS, previous year;
"yearly pe ratio" = Close ÷ EPS, latest year; net profit[quarter] / [yearly] = latest quarter / latest year; "N months /
weeks ago" = monthly / weekly candles; max(N, x) = highest of the last N candles including the latest (so "High = Highest
high of 260" means a 52-week high today). Columns: % Change, Price, Volume (Chartink's extra display columns — VWAP, Stoch
RSI, VWMA, RSI, MACD, market cap — are not shown yet).
Honest limits (each said on screen): 12 Year High Breakout needs 3,000 sessions, our history starts April 2024 (~640) →
not computed; Multiyear breakout: the 780–2,600-session legs cannot be checked but cannot add a stock the 520-session leg
misses → computed (the max/min period cap is 1,000); Stocks Under 300: 200-week SMA not computable → Partial, that line not
applied; High Momentum Stocks: "RSI(14) > highest RSI(14) of 3" can never hold → always empty, on Chartink too.
Intraday (Kite 15-minute candles, fresh ≤ 60 s, shared cache with §8): RSI VWAP intraday = close > 1 day ago high, then
30-minute RSI(14) > 60 (pairs of 15-minute candles, intraday.py `bucket`) and today's VWAP (Σ typical price × volume ÷ Σ
volume over today's 15-minute candles, intraday.py `vwap`) < the latest close; 15 minute stock breakouts = on F&O stocks
(owner: {57960} is not published), latest 15-minute close > highest 15-minute close of 20 as of the candle before, and
latest 15-minute volume > SMA(volume, 20). While the tab is open, the 218 F&O stocks' 15-minute reads share Kite's budget
(≤ 1.5 calls/s for this feature), so candles may be 2–3 minutes old (the widget's as-of says so). 10x volume first 5 min =
the §8 widget's rule. Renamed for the wording rule: RSI VWAP INTRADAY BUY → RSI VWAP intraday; Swing trade breakout strategy
10-20% gains → Swing trade breakout; Copy - Strong stocks → Strong stocks.
A list cut at the 500-row limit says how many stocks passed (both tabs).

## 10. Early signals, alerts and trading plans (owner 3 Nov evening: "The whole idea is to give early alerts and signals and trading plan for those stocks")
Owner choices (AskUserQuestion, same time): alerts **in-app + browser**; plan words **Entry · Stop loss · Target 1 · Target 2**
(an explicit exception to the 3 Nov wording rule, for this screen's plans only); plan basis **live rules + the strategy
builder's options idea** beside it.

**Signal** = a stock entering a widget's list (symbol widgets with status ok or partial) during the session, recorded once
per (day, widget, stock) with the time first seen and the live price then. Recorded only while the market is open and the
basis is Kite live. Stored in Redis (`nivesh:sb:signals:<day>:…`, TTL 3 days, first writer wins across workers). So that
alerts are early even when nobody has the page open, one worker (Redis lock) computes the dashboard every 15 s from
09:15 to 15:30 on staging (`APP_ENV=staging`; `SCAN_SIGNALS_ENABLED=0` turns it off, `=1` turns it on elsewhere).
Signals from the session's first computation carry `at_open: true`.

**Plan** (rules `scan-plan-v2`, frozen at the moment of the signal; owner 3 Nov ~20:50 IST after the early-signals study, whose
flags were followed by a median further rise of ~1.0–1.5 % and a dip of ~0.6 %): Entry = the live price when first seen;
Stop loss = Entry − 1 %; Target 1 = Entry + 1.5 %; Target 2 = Entry + 3 % (reward : risk 1.5 and 3.0). A falling F&O stock in
"Open interest" / "Open interest 7" gets the short mirror. (v1 — ATR / 2R / 3R — was replaced the same evening: its targets sat
4–12 % away, beyond what the study saw after a flag; a first v2 wording with "the lower of today's low and Entry − 0.5 × ATR"
was impossible for early movers, which are ≥ 2 % over the open, and was corrected before it was built.)

**Early movers** (tab `early`, services/scan_builder/early_movers.py): the study's top early indicator as a list — volume so
far ≥ 5 × its usual by now (20-session average daily volume × the share of a day's volume usually traded by then, from the
study's 20 training sessions) and price ≥ 2 % over today's open; NSE stocks with a 20-session average volume ≥ 50,000 and price
≥ 20; from 09:30 (the study's first step). Its entries raise signals like every other list. The background loop computes
every tab.

API: GET /api/scan-builder/market-dashboard adds
```
signals: [ { id, widget_id, widget_title, symbol, first_seen (ISO, IST), at_open, direction: long|short, entry, stop_loss,
             target_1, target_2, risk_per_share, rr_1, rr_2, stop_basis, target_1_basis, plan_ok, plan_note,
             price_now, move_since_pct } ]        today's, newest first, at most 300
signals_meta: { day, count, recording, rules, caveat }
```
UI: a "New signals" feed above the widgets (newest first: time, stock, scan, Entry / Stop loss / Target 1 / Target 2, R:R,
the options idea when one exists, price now and move since); an "Enable browser alerts" button (Notification API) that, while the
page is open, notifies each signal newer than the last one this browser saw (grouped when several arrive at once); stock rows
with a signal today carry a "New hh:mm" badge.

## 11. Signal strength 0–100 — positional, long only (owner 4 Nov ~13:45 IST)

Owner: "hundreds of signals … process only those signals where signal strength is above 70% … companies fundamentally and
technically good and some solid reasons to have such strong movements … reduce the signal quality for pump and dump stocks and
promote … trend reversal from 52 week low, momentum continuation, some market events … not intraday but positional … more
weightage to blue chip". Decisions 4 Nov ~14:05 (asked): plan = ATR stop + trend exit; below 70 = folded away (no alert, no
plan, shown with score and reasons); long only.

**What is scored:** a STOCK that entered at least one list today (a list entry is still recorded per (day, list, stock) as in
§10, now without a plan). The score is recomputed on every refresh from the data then; a stock whose long score first reaches
70 becomes a STRONG SIGNAL: recorded once per (day, stock) — first writer wins across workers — with the score and its parts
at that moment and the positional plan frozen at the live price then. Only strong signals raise alerts and carry a plan. A
stock whose lists today are all short-side (falling F&O stock in the Open interest lists) is not scored ("long only").

**Score = quality (30) + trend (25) + reason (20) + size (15) + participation (10) − penalties, clamped to 0–100.**
Rule-based weights set by hand (not fitted or back-tested; stated on screen). Inputs and their dates travel with the score.
- Quality (DaaS /stocks/screener, the NIDP feature store; as of its date): ROCE (ROE for banks/financial companies) ≥ 20 → 8,
  ≥ 15 → 6, ≥ 10 → 3; ROE ≥ 18 → 5, ≥ 12 → 3, ≥ 8 → 1; debt/equity ≤ 0.3 → 5, ≤ 1 → 3, ≤ 2 → 1 (financials: 3); profit
  margin ≥ 10 % → 3, > 0 → 1; earnings consistency ≥ 75 → 4, ≥ 50 → 2; promoter ≥ 50 % → 3, ≥ 30 % → 2; FII + DII ≥ 15 % → 2,
  ≥ 5 % → 1. A missing figure scores 0 and is named.
- Trend (EOD bars to the last session + the live price): price above each of the 5/10/20/30/50/100/150/200-day averages → 1
  each; 50-day above 200-day → 4; setup: 52-week-high breakout (price ≥ the prior 250-session high) → 6, within 5 % of it → 4,
  reversal from a 52-week low (price ≤ 1.3 × the 250-session low, above its 50-day average, 20-day average rising) → 6;
  RSI(14) 50–72 → 4, 72–80 → 2, < 50 → 1, > 80 → 0; 125-session return > 10 % → 3, > 0 → 1. Capped at 25.
- Reason (exchange filings since the previous session, DaaS /announcements, classified by category/sentiment/impact): results
  filed with positive sentiment → 16; orders / M&A / capex / buyback, positive, high or medium impact → 12 (low: 8); other
  positive high/medium → 8; results otherwise → 6; negative high/medium → −8. Plus the setup: 52-week-high breakout or
  52-week-low reversal → 10, near the 52-week high → 6; plus 4 when one of today's lists is a positional pattern (52-week,
  multi-year, cup and handle, consolidation, triple bottom, long build-up, swing/volume breakouts, results lists). Capped 0–20.
- Size — blue chips weigh more: Nifty 50 → 15, Nifty 100 → 13, Nifty 200 / Midcap 150 → 10, other Nifty 500 → 7; an F&O stock
  at least 9; outside these, market cap ≥ ₹5,000 cr → 5, ≥ ₹2,000 cr → 3; 20-day average traded value < ₹5 cr caps it at 2.
- Participation: volume so far ÷ its usual by now (20-day average × the time-of-day share, §10 Early movers): 1.5–8× → 6;
  8–20× → 4 with a filing, else 2; > 20× → 3 with a filing, else 0; below 1.5× → 2. Trade sides (Kite ticks) ask ÷ bid
  > 1.1 → 2. In ≥ 2 positional lists → 2.
- Penalties (pump-and-dump risk; each named on the card): market cap < ₹500 cr −25, < ₹1,000 cr −15; no market cap and in no
  index −10; price < ₹20 −10; volume > 10× usual with no filing and outside Nifty 500 −15; parabolic (> 50 % in 21 sessions or
  > 100 % in 63) without PAT growth > 25 % or a filing −15; loss-making −10; promoter pledge > 50 % −20, > 25 % −10; promoter
  < 25 % and FII + DII < 5 % −5; 1-year volatility > 70 % −5; more than 25 % above the 20-day average (chasing) −5; exchange
  negative filing since the last session −10 (on top of the reason part's −8); NSE price band 2 % −30, 5 % −15, 10 % −5
  (the platform does not ingest NSE's ASM/GSM lists; 5 % and 2 % bands are what surveillance and illiquid stocks get);
  locked at the upper band today (band ≤ 10 %) −10; the exchange queried the company about a volume spurt or a price
  movement in the last 30 days (its reply filed, DaaS /desk/filings?family=exchange) −10. ETFs are not scored.

**Plan (rules `scan-plan-v3`, strong signals only):** Entry = the live price when the score first reached 70; Stop loss =
Entry − 2 × ATR(14) (ATR to the last session), judged on daily closes; Target 1 = Entry + 2 × risk; Target 2 = Entry + 4 ×
risk; trend exit = a daily close below the 20-day average (its value shown, it rises as the trend runs). No stop below zero:
without ATR or price → no plan and the reason.

**API (GET /market-dashboard, additive):**
- `scores`: {SYMBOL: {score: int | null, parts: {quality, trend, reason, size, participation, penalty}, reasons: [str],
  penalties: [{text, points}], lists: [{id, title}], note: str | null}} for every stock with a list entry today (score null
  with a note when not scored: long only, ETF, no price history).
- `strong`: newest first, one per stock — {symbol, name, first_strong, score_at, parts_at, reasons_at, score_now, rules
  "scan-plan-v3", entry, stop_loss, target_1, target_2, risk_per_share, rr_1 2, rr_2 4, atr, sma20, trend_exit, plan_ok,
  plan_note, lists_at, price_now, move_since_pct}.
- `signals[]` (list entries) gain `score` (the stock's score now or null); their plan fields are null with plan_ok false and
  plan_note "Plans go to strong signals only (score ≥ 70)".
- `scores_meta`: {threshold 70, weights {quality 30, trend 25, reason 20, size 15, participation 10}, as_of {fundamentals,
  eod, snapshot, filings}, rules, plan_rules, caveat, counts {scored, strong, below, not_scored}, warnings[]}.
UI: a "Strong signals (score ≥ 70)" feed (score, parts, reasons, penalties, plan with trend exit, lists, price now and move
since), a collapsed "Below 70 (n)" list (stock, score, lists, main reasons and penalties); browser alerts only for new strong
signals.
Price band, ETF flag and traded value come from the feature-store snapshot (DaaS /features/scan-snapshot, one call).
