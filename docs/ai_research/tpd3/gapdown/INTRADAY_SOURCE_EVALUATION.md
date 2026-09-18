# Intraday bar source evaluation — 2026-09-18

Decision input for the 5-minute collector (owner priority 2). Every figure below was
probed live this session; nothing is quoted from memory or vendor marketing.

## Priority 1 result — does NIDP already hold intraday bars?

**No.** Verified by schema inspection (no GCP token needed):

- Migration grep for `intraday|_5m|minute_bar|tick_data|vwap` matched 2 files, neither a bar table:
  - `002_nidp_market_data.sql:30` — `avg_price NUMERIC(14,4) -- VWAP / AvgPric`, a *daily* column on an EOD table.
  - `088_monitoring_environment_overview.sql` — cron *schedule strings* ("every 5m IST"), not data.
- `CREATE TABLE ... (intraday|minute|_5m|tick)` → **zero matches**.
- `analytics.market_snapshot` is `as_of_date DATE NOT NULL UNIQUE` — one row per day, market-level
  breadth/FII/DII/index closes. Not per-symbol, not intraday.
- `event_day_poller` runs `*/5 9-16` but its service polls for **results announcements**
  (`_check_nse_for_result`, `_ingest_result`); it persists no prices.

**Conclusion: no duplication risk. A new collector is required.**

UNVERIFIED: row counts / live coverage were not queried — the GCP token expired this session
(`Request had invalid authentication credentials`). The schema evidence is conclusive on its own
(a table that does not exist cannot hold rows), so this does not block the decision.

## Source candidates

| Source | 5m history | Live/delayed | Universe | Adjusted | Verdict |
|---|---|---|---|---|---|
| Yahoo `v8/finance/chart` | **60 days (hard cap)** | ~15m delayed | 7/8 probed OK | **No** (`adjclose=False` on 5m) | Use for forward collection |
| NSE `chart-databyindex` | today only (intraday) | live | — | no | **Blocked from this VM** |
| NSE `quote-equity` | — | — | — | — | **HTTP 403 even with cookies** |
| Paid vendor | — | — | — | — | Not evaluated; needs owner budget decision |

### Yahoo — probe detail
- `5m`/`1mo` → 1,725 bars from 2026-08-19 ✓; `3mo`,`6mo`,`1y`,`2y` → **HTTP 422**
- Explicit `period1`/`period2` 6-month window → **HTTP 422** (hard cap, not a parameter problem)
- `15m` → same 60-day wall; `60m`/`2y` → 3,498 bars back to 2024-09-19 ✓
- Scale: 300 bars per symbol per 5 sessions ≈ **75 bars/symbol/day**; a 1,000-symbol universe
  ≈ **75,000 rows/day** (~19M rows/year). Sizeable but ordinary for Postgres.
- Reliability: 1 of 8 symbols (`TATAMOTORS.NS`) returned HTTPError on a single probe → the
  collector must retry and must record per-symbol fetch status, not assume completeness.

### NSE — probe detail
Warm-up against `get-quotes/equity` acquired 5 cookies, but `quote-equity` still returned
**403** through the tinyproxy route that fixes the EOD feeds. Consistent with the known
blanket NSE block on this VM. NSE also serves only *today's* intraday chart, so even if
unblocked it is a forward-collection source, not a history source.

## Licensing / redistribution — OPEN

Yahoo's terms do not grant redistribution rights. That is acceptable for **internal research
and model training**, which is the present use. It is **not** settled for anything user-facing.
NEEDS-INPUT before any intraday-derived number is shown to users or sold.

## Consequence for the strategy grid

- **G1 (official open)** — testable today on 501 sessions of bhavcopy daily OHLC.
- **G2–G5** (5m close / 15m high / VWAP reclaim / first-hour) — **~20 usable sessions**.
  Not walk-forward testable. Testable ~6 months after collection starts.
- Intraday exit matrix (10:30/11:30/14:30) at 5m resolution — same constraint.
  A coarse 60-minute version is possible back to 2024-09-19 and is worth a separate look.

## Recommendation

Start the Yahoo 5m collector now for forward accumulation (every day of delay is
unrecoverable), build G1 on daily OHLC in parallel, and keep the vendor decision open —
`source_version` on every row makes a later switch non-contaminating.
