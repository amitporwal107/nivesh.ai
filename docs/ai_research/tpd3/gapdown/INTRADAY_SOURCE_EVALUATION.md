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

---

# ADDENDUM 3 — 2026-09-18: BACKFILL SCOPE + SYMBOL COVERAGE

## Scope: targeted, not continuous

A continuous 750-day minute backfill of the 1,647 sleeve symbols would be **315M rows /
~25 GB / ~125 min**. The app-vm had **16 GB free (81% used)**, and this disk has taken
staging Postgres down before by filling. That backfill would have caused an outage.

The sleeve only ever trades **(symbol, trade-day) pairs**, so only those days are fetched:

| | rows | size | time |
|---|---|---|---|
| continuous 750d | 315M | 25.2 GB | ~125 min |
| **targeted pairs** | **1.6M** | **~0.13 GB** | **~25 min** |

**99.5% fewer rows for exactly the data the study needs.** Compression was considered and is
unnecessary at 0.13 GB; it stays in reserve if the corpus is later widened to continuous history.

## Symbol coverage: 9.3% of sleeve symbols are not in Kite's CURRENT instrument list

Kite's `instruments("NSE")` returns names live **today** (10,130 EQ). Symbols renamed,
delisted or moved segment since 2024 are absent, so their history cannot be fetched by name.

- missing symbols: **153 of 1,647 (9.3%)**
- affected pairs: **416 of 4,313 (9.6%)**

### Survivorship check — is the gap systematic?

| cohort | n | mean intraday | median turnover |
|---|---|---|---|
| missing | 416 | **+0.767%** | Rs 404 L |
| present | 3,897 | **+0.842%** | Rs 1,367 L |

The missing names are **less liquid** (expected — delisting skews small) but their mean
intraday return is only **0.075pp lower**. Dropping them is unlikely to flip the sleeve's
sign. This is a **real but small survivorship bias**, recorded here so it is not rediscovered
later as a surprise.

**Mitigation if it ever matters:** Kite instruments can be resolved by `instrument_token`
from a historical dump rather than by current tradingsymbol. Not done now — the bias is
smaller than the effect being measured.

## Verified write path (smoke test, run smoke-002)

`{'OK': 1, 'EMPTY': 0, 'ERROR': 0, 'rows': 360}` — RELIANCE 2026-09-17, 360 minute bars,
09:15..15:14, low 1238.5 / high 1253.4 (matching the independent probe), `source_version`
stamped, ingest log row written.

Two defects were found and fixed by this smoke test before the bulk run: a Postgres index
expression needing an extra paren (migration 152), and a CSV terminator landing on the last
data row (`csv.writer` default `\r\n` -> `lineterminator="\n"`).

---

# ADDENDUM 4 — 2026-09-19: pricing correction, adjustment behaviour, display restriction

## Correction — historical data is NOT a separate add-on
Addendum 1 said the historical API is "a paid add-on, separate from Kite Connect itself". Per the Zerodha
pricing the owner cited (2026-09-19): Kite Connect is Rs 500/month per API key and **includes** real-time
and historical candle data. That claim of mine was outdated. (The subscription question was already moot:
historical calls were VERIFIED working on this app in Addendum 2.)

## Kite historical candles are BACK-ADJUSTED for splits and bonuses (verified)
Close on the session before the ex-date, bhavcopy raw vs Kite:

| symbol | action (NSE notation) | pre-ex date | bhavcopy raw | Kite | raw/Kite | expected factor |
|---|---|---|---|---|---|---|
| TDPOWERSYS | split 2:1 | 2026-08-21 | 1534.80 | 767.40 | **2.000** | 2 |
| TRENT | bonus 1:2 (1 new per 2 held) | 2026-06-03 | 4257.60 | 2838.40 | **1.500** | 1.5 |
| GOODLUCK | bonus 2:1 (2 new per 1 held) | 2026-08-20 | 1439.40 | 479.80 | **3.000** | 3 |

Rules that follow:
- **Returns** across dates: use Kite (continuous through corporate actions).
- **Rupee levels** (pivots, circuit bands, "price < Rs X" filters, round numbers): Kite history is NOT the traded
  price. Un-adjust with the corporate-action factor, or take levels from raw bhavcopy.
- **Adjusted history is rewritten** whenever a new action is ex-dated, so a stored pull goes stale for that
  symbol. Store the pull date (`fetched_at`) and re-pull a symbol after any new split/bonus.
- The G1 result (Addendum 3) is unaffected: every return there is a ratio of Kite's own same-day o/h/l/c.

## Display restriction (owner-cited Zerodha policy)
Kite Connect data may not be displayed on other platforms under exchange data-vending rules. Use is limited
to internal research / backtesting. Anything user-facing in Nivesh.ai needs an exchange-authorised vendor.
This applies to the paper-trades page's intraday chart if its source were switched to Kite.

---

# ⚠️ ADDENDUM 5 — 2026-09-19 03:30 IST: RETRACTION — the Kite minute backfill fetched the WRONG SESSION

**What was wrong.** A panel row dated *t* carries the gap of session *t+1* (`n_open/n_high/n_close` are the NEXT
session). The backfill built its pairs as `trade_day = as_of_date`, so all 1,396,641 minute bars (run
`gapdown-20260918T230903`, `nidp.intraday_bars`) are from the session **before** each gap-down, not the gap-down
session. The single-symbol cross-check (RELIANCE, Addendum 2) mapped the dates correctly; the bulk script did not,
and the join was never validated in bulk.

**Retracted:**
- "Pre-registered G1 grid re-run with a TRUE intraday low: all 4 variants FAIL (MODERATE −0.6531%, t −13.28)."
  **INVALID — measured the day before the gap.** G1 with a real intraday low is **UNTESTED**.
- The first delayed-stop timing study (same bars). It also divided bhavcopy's raw close by Kite's back-adjusted
  open, which is why it showed impossible means (+10%).

**Still valid** (they use only panel columns for the correct session): the first grid's look-ahead diagnosis
(target from the high, stop checked only at the close), the close-only result (+0.4735%/session, t = +3.70), the
abandon-condition checks, and all Phase 1 base rates.

**Fix in progress:** `/app/research/kite_history/gapdown_minute_v2/refetch.py` refetches minute bars for
`trade_day = next session after as_of_date` and validates every pair (Kite 09:15 open vs panel raw `n_open`:
equal, or an exact back-adjustment ratio > 1.05; anything else is logged as a MISMATCH).

**Rule added:** every bulk join between two price sources is validated on a shared field (open vs open) before any
result is computed from it.
