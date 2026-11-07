# Autonomous Trading Desk — health status route (R14) test cases, written before the code (7 Nov 2026)

Owner item R14: a status-only route that needs no sign-in and shows no secrets. It reports the database, data API, Redis,
quote feed, scheduler and the last cycle, each as OK, DEGRADED or BLOCKED. Done when the route answers on staging with
per-part detail and the Tech Support checks use it.

Route: `GET /api/v1/health/status` (public path `/autodesk/api/v1/health/status`). New file `routers/health_status.py`.
`GET /api/v1/health` is not touched. Tests: `backend/tests/autodesk/test_health_status.py`.

Layer: U = unit (test doubles), I = integration (throwaway Postgres), A = API (FastAPI app), R = real boot with the
dependencies absent, S = staging (needs a deploy; UNVERIFIED until run).

Part rules (decided before the code; each part is `{"status", "detail", "as_of"}`):

| Part | OK | DEGRADED | BLOCKED |
|---|---|---|---|
| database | `SELECT 1` answers | | error or no answer in 3 s |
| data_api | Tech Support's rules give READY for the session being prepared (cash and F&O end-of-day complete) | F&O not for the previous session or too few underlyings; the check has not finished yet; the last finished check is older than 5 minutes | cash older than the previous session or too few rows; data API unreadable; the check failed or did not finish in 40 s |
| redis | ping answers | not configured, error, or no answer in 3 s (the REST path remains) | never |
| quote_feed | market closed; or market open and the newest index tick in the feed cache is at most 120 s old | market open and no fresh tick, no index rows, or the cache unavailable; cannot tell whether the market is open | never |
| scheduler | never | `AUTODESK_SCHEDULER` off ("off: session cycles are started by hand"), or on (this version has no scheduler code) | never |
| last_cycle | newest non-simulation session cycle is not BLOCKED, FAILED or CANCELLED, and its session is not older than the previous session | no cycle recorded; CANCELLED; older than the previous session; cannot tell the previous session; could not be read | newest cycle is BLOCKED or FAILED |

The overall `status` is the worst part. HTTP is always 200.

## Shape, sign-in, worst part

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-01 | A | Call with no cookie, no header | 200; body has `status`, `as_of` and `parts` with exactly database, data_api, redis, quote_feed, scheduler, last_cycle; each part has status in OK/DEGRADED/BLOCKED, a non-empty one-sentence `detail`, and `as_of` an ISO time or null |
| AD-HS-02 | A | Sign-in is faked to fail (the other routes answer 401 in the same app) | this route still answers 200: it does not depend on `current_user` |
| AD-HS-80 | U | Parts all OK; one DEGRADED; DEGRADED and BLOCKED together | overall OK; DEGRADED; BLOCKED; always HTTP 200 |
| AD-HS-81 | A | The desk database is closed | 200 within the timeout; database BLOCKED; the other parts still reported |

## Parts

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-10 | U | Pool answers `SELECT 1` | database OK |
| AD-HS-11 | U | Pool raises on acquire | database BLOCKED; detail names the exception type, not its message |
| AD-HS-12 | U | Pool acquire never returns | database BLOCKED within the 3 s timeout, detail says it did not answer |
| AD-HS-20 | U | Shared data check: cash and F&O for the previous session, VIX present | data_api OK; detail has the row counts and the day |
| AD-HS-21 | U | F&O is for an older day, or too few underlyings | data_api DEGRADED (cash fine) |
| AD-HS-22 | U | India VIX missing, cash and F&O fine | data_api OK and the detail says there is no India VIX (Tech Support calls it "noted, not blocking") |
| AD-HS-23 | U | Cash older than the previous session; cash with too few rows | data_api BLOCKED |
| AD-HS-24 | U | The data API read fails with a message holding a fake hostname and port | data_api BLOCKED; the detail says the data could not be read and holds neither the hostname nor the port |
| AD-HS-25 | U | Same market inputs through `TechSupport.run` (db_ok True) and through the route, six scenarios (READY, VIX missing, F&O stale, F&O too few, cash stale, data unreadable, calendar unknown) | route data_api status equals the agent's report status (READY=OK) in each |
| AD-HS-26 | U | The data check takes longer than the wait (3 s) | the request answers within the timeout; first ever call says the first data check is still running (DEGRADED); once the background run finishes, the next uncached call reports the real result with its `as_of` |
| AD-HS-27 | U | The last finished data check is more than 5 minutes old and the new run hangs | DEGRADED saying how old the last check is, never the old OK |
| AD-HS-28 | U | The data check never finishes (deadline shortened in the test) | the stored result becomes BLOCKED, "did not finish" |
| AD-HS-40 | U | Redis client pings | redis OK |
| AD-HS-41 | U | Redis client is None (not configured) | redis DEGRADED |
| AD-HS-42 | U | Ping raises | redis DEGRADED, exception type only |
| AD-HS-43 | U | Ping or connect hangs | redis DEGRADED within the timeout |
| AD-HS-50 | U | Market open (existing `settle._market_open`), index tick received 20 s ago | quote_feed OK |
| AD-HS-51 | U | Market open, newest index tick 300 s old; tick from yesterday | DEGRADED |
| AD-HS-52 | U | Market open, cache holds no index rows | DEGRADED |
| AD-HS-53 | U | Market open, Redis cache unavailable (`read_quotes` gives None) | DEGRADED |
| AD-HS-54 | U | Market closed (evening, Saturday, a holiday), cache stale or empty | OK, detail says the market is closed; the quote cache is not read |
| AD-HS-55 | U | Weekday with no holiday list loaded | DEGRADED, "cannot tell whether the market is open"; the route calls the desk's own `settle._market_open`, no new market-hours function |
| AD-HS-56 | U | Kite login: stored and not expired / not stored / expired / the read fails / Mongo hangs | the detail says so in plain words; the status is unchanged by it; a hanging Mongo does not delay the answer past the timeout |
| AD-HS-57 | U | Market open with fresh ticks and with none | no Kite call of any kind: `KiteQuoteSource`, `_platform_kite`, `default_kite_factory` and `KiteConnect` are never called |
| AD-HS-60 | U | `AUTODESK_SCHEDULER` unset, "0" | scheduler DEGRADED, detail exactly "off: session cycles are started by hand" |
| AD-HS-61 | U | `AUTODESK_SCHEDULER` "1" | DEGRADED, detail says the setting is on but this version has no scheduler that starts cycles |
| AD-HS-70 | I | No workflow rows | last_cycle DEGRADED, "no session cycle recorded" |
| AD-HS-71 | I | Newest cycle COMPLETED for the previous session; RUNNING and WAITING_HUMAN for the session being prepared | OK |
| AD-HS-72 | I | Newest cycle BLOCKED; FAILED | BLOCKED |
| AD-HS-73 | I | Newest cycle's session is older than the previous session | DEGRADED |
| AD-HS-74 | I | A newer simulation cycle (FAILED), a newer PREMARKET_CHECK, and cycles of two tenants | simulation and other kinds are ignored; the newest non-simulation SESSION_CYCLE over all tenants decides |
| AD-HS-75 | I | Rows with planted tenant, account and workflow ids | the detail shows only state, session date and age |
| AD-HS-76 | U | The calendar cannot say which session precedes | last_cycle DEGRADED, no crash |
| AD-HS-77 | I | Newest cycle CANCELLED | DEGRADED |

## Timeout, concurrency, cache

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-90 | U | Each probe hangs in turn (database, redis, quote cache, last cycle, data check) | response within about 3.5 s; the hung part is not OK and says it did not answer; every other part is reported |
| AD-HS-91 | U | Five probes that each take 1 s | the whole answer takes under 2.5 s (they run together) |
| AD-HS-100 | U | Second call within 15 s | identical body (same `as_of`); no new pool acquire, ping, cache read or data check |
| AD-HS-101 | U | A call after the 15 s are over (clock moved) | the probes run again; new `as_of` |
| AD-HS-102 | U | Ten calls together on an empty cache | one set of probes (single flight) |

## Nothing private, wording

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-110 | I | Fixtures hold a fake hostname, a fake token, a tenant id, an account id, a workflow id, a symbol, and a URL with a port, in exception messages, rows, env and the Redis rows | the whole JSON body holds none of them, no `://` and no host:port pattern |
| AD-HS-111 | U | Every probe raises `RuntimeError("<planted secret>")` | each detail names `RuntimeError` and never the message |
| AD-HS-112 | U | Every detail text across all states above | holds none of: buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit, upside, price target, recommend, pick |

## Existing behaviour that must not change

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-120 | A | `GET /api/v1/health` with the new route present | same keys and values as before (status ok, app, version, db, migrations, agents, calendar_years, execution); it never touches the status route's probes (spy) |
| AD-HS-121 | A | `/health` with the pool closed | 503 `{"status":"degraded","db":false,"error":…}` as before |
| AD-HS-30 | U | Tech Support run on eight scenarios, output and summary and the market calls it made | byte-for-byte equal to the output the code before the change gave (golden values taken from commit 82e5eedd) |
| AD-HS-31 | U | Spy on `tech_support.data_checks` | `TechSupport.run` and the status route both call it |
| AD-HS-32 | U | The existing AD-25 and AD-FX-04..08 tests | pass unchanged |

## Read only

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-130 | I | Row counts of every autodesk table, and `n_tup_ins/upd/del`, before and after several uncached calls on a database holding workflows | identical |
| AD-HS-131 | U | A recording pool | every statement the route sends starts with SELECT and runs in a read-only transaction or a plain read |
| AD-HS-132 | U | The route's source and a run with the market open | no import of a broker, `ReadOnlyKite` or order module; no broker order data read |

## Real boot and staging

| ID | Layer | Case | Expected |
|---|---|---|---|
| AD-HS-140 | R | Boot `autodesk.main:app` on a throwaway database with no data-API credentials, no Redis, no Mongo; call the route | a real 200 body; database OK; data_api not OK; redis DEGRADED; scheduler DEGRADED |
| AD-HS-141 | S | After the deploy: `curl -s https://staging.niveshcopilot.com/autodesk/api/v1/health/status` | per-part detail on staging. UNVERIFIED until a deploy |
