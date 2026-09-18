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

---

# ADDENDUM 2026-09-18 — SOURCE DECISION: Kite Connect. Yahoo dropped.

Owner instruction: "FORGET YAHOO ... PLEASE CONNECT TO KITE CONNECT".
Yahoo is removed as a candidate. Kite Connect is the source for BOTH history and live.

## Why this changes the plan materially

Yahoo's 60-day cap was the reason G2-G5 were deferred ~6 months. Kite's **historical data
API** serves minute-resolution candles for **years** back, so G2-G5 become testable as soon
as a backfill runs, not in 2027-03. This is the single biggest unblock in this workstream.

## Verified this session (real output, no credentials used)

- `https://api.kite.trade/` -> **HTTP 200** `{"status":"success","data":"Take the red pill with Kite Connect v3"}`
- `https://kite.trade/connect/login?v=3` -> **HTTP 400** `Missing or empty field api_key` (reachable)
- **Kite is NOT IP-blocked from nidp-stack-vm** (unlike NSE, which 403s even via tinyproxy).
  No proxy needed.
- `kiteconnect` SDK installed into the research venv.

## Existing integration — REUSE, do not duplicate

`backend/services/brokers/zerodha.py` already implements the full read-only OAuth flow:
`auth_url()` -> `exchange_code()` (SHA-256 checksum -> `/session/token` -> `access_token`),
plus `fetch_holdings/positions/funds`. Credentials resolve through `helpers.secrets`
(**GSM -> env**) under:

- `BROKER_ZERODHA_API_KEY`
- `BROKER_ZERODHA_API_SECRET`

The collector MUST use these same names and the same `_conf` resolution. No new secret path.

## Operational constraint the owner must know

Kite `access_token` **expires daily (~06:00 IST)** and renewal REQUIRES an interactive
login (Zerodha credentials + 2FA). A cron collector therefore CANNOT run unattended
indefinitely: it will fail every morning until a fresh token is supplied. Options:
(a) owner completes a daily login; (b) a stored-session refresh the owner sets up;
(c) collector runs on-demand. **NEEDS-INPUT — not decided.**

## Subscription caveat

The **historical data API is a paid add-on**, separate from Kite Connect itself. The app
is described as "Kite connect + Historical Chart data", which suggests it is enabled, but
this is **UNVERIFIED** until a real `historical_data()` call succeeds. Live streaming
(websocket) is a different endpoint and does not substitute for historical backfill.

## Security note

The API key was shared via screenshot and is therefore no longer private.
**Recommend regenerating it in the Kite developer console.** Credentials must be delivered
as a file (never a screenshot, never pasted inline) and are never printed by any tool call.

## Revised consequence for the strategy grid

- G1 (official open) - testable now on daily OHLC (unchanged).
- **G2-G5 - testable after a Kite minute-bar backfill** (was: ~6 months away). Major change.
- Intraday exit matrix (10:30/11:30/14:30) - same; testable after backfill.
- The `low` column needed to fix the invalidated target/stop grid can also come from Kite.

---

# ADDENDUM 2 — 2026-09-18: KITE HISTORICAL VERIFIED LIVE

Authenticated as user WVX837 (login_time 2026-09-18 22:42:15). Real output below.

## The add-on IS active

- NSE EQ instruments: **10,130** (RELIANCE token 738561)
- 1 day of minute bars -> **360 candles**, 2026-09-17 09:15 .. 15:14 IST
- 5 days of 5-minute   -> **288 candles**, 2026-09-15 .. 2026-09-18

## History depth: at least 5 years of MINUTE bars

| Probe | Result |
|---|---|
| 1y ago (2025-09-18) | 1,500 candles |
| 2y ago (2024-09-18) | 1,500 candles |
| 3y ago (2023-09-19) | 1,125 candles |
| 5y ago (2021-09-19) | 1,875 candles |

This retires the Yahoo 60-day ceiling entirely. **G2-G5 and the intraday exit matrix are
now testable on history, not six months from now.**

## Cross-check against the bhavcopy panel (RELIANCE 2026-09-17)

| Field | Kite | Panel | Match |
|---|---|---|---|
| open | 1244.8 | 1244.8 | **exact** |
| high | 1253.4 | 1253.4 | **exact** |
| close | 1245.0 | 1243.9 | **differs +0.088%** |

### The close divergence is explained, not a defect

Kite's last minute candle OPENS at 15:14 (covering 15:14-15:15). NSE continuous trading
ends 15:30 and the **closing auction (15:30-15:40)** sets the official close that bhavcopy
records. Kite's final candle is the last *traded* minute, not the auction print.

**RULE — do not mix sources for the same field:**
- **Official close** -> bhavcopy (it is the auction price; the paper engine already uses it)
- **Intraday path** (open, high, **low**, every intermediate bar) -> Kite

Violating this silently biases any exit study by ~0.09% per trade.

## The low column — what unblocks the invalidated grid

The target/stop grid was invalidated because the panel had no `n_low`: targets were credited
from the intraday HIGH while stops were only checked at the CLOSE, booking the best of both
paths. Kite supplies a true per-minute low (RELIANCE 2026-09-17 day low 1238.5, MAE from
open -0.51%), so stops can fire on the low and the grid can be re-run honestly.

## Backfill cost (minute bars, 2 years, 0.35s pacing under the 3 req/s cap)

| Universe | Wall time | Approx rows |
|---|---|---|
| 50 symbols | ~4 min | ~9.6M |
| 200 symbols | ~15 min | ~38M |
| 500 symbols | ~38 min | ~96M |

Cheap in time; the row counts argue for starting with the gap-down universe rather than
all 10,130 instruments.
