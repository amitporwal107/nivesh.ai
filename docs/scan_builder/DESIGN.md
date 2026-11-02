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
