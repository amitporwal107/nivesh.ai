# Functionality Verification Report — Desk health status route (R14), Account 1

- **Branch:** feat/autodesk-health-status (stacked on origin/feat/autodesk-phase2-paper-exec @ 82e5eedd, PR #503; not rebased, dev not merged in)
- **Date:** 2026-11-07
- **Author:** Claude (full-stack developer + QA), Account 1
- **Environment:** throwaway Postgres 16 container + the `nivesh/backend:staging` image; a real boot of `autodesk.main:app` with no
  credentials. **NOT staging: the route is not deployed.**
- **Changed areas:** backend routes/services: yes (new `routers/health_status.py`, `tech_support.data_checks` extracted, 2 lines in `main.py`) · frontend src: no
- **File name:** this report is `..._a1.md` on purpose. `test_reports/autodesk_health_status_20261107.md` already exists (Account 2's report
  on branch feat/autodesk-health-status-a2, Verdict BLOCKED) and was not overwritten.

## Summary
`GET /api/v1/health/status` (public path `/autodesk/api/v1/health/status`): no sign-in, status only, six parts (database, data_api, redis,
quote_feed, scheduler, last_cycle), each OK / DEGRADED / BLOCKED with a one-sentence detail and its own `as_of`; HTTP always 200;
overall `status` = worst part. Every probe has a 3 s limit and the probes run together; the whole answer is cached in the process for 15 s
(one set of probes however many callers). `GET /api/v1/health` is not touched (`git diff origin/feat/autodesk-phase2-paper-exec --
backend/autodesk/routers/api.py` is empty). The data rules of Tech Support were moved, unchanged, into `tech_support.data_checks`; the
agent and the route both call it. Test cases AD-HS-01..141 were committed before any code (commit 7333ccaf).

Note on duplication: Account 2 built R14 from copies of my uncommitted files. Its `health_status.py`, `tech_support.py`, `main.py` and
`golden_tech_support.json` are byte-identical to mine (checked with `cmp`/`git diff`); its `test_health_status.py` (36 test functions, 53
cases) is a different file from mine (60 functions, 83 cases) with the same path, so the two branches cannot both be merged as they are.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| AD-HS-01, 02 | shape, sign-in | no cookie / bogus bearer and cookie; body shape; the same app answers 401 elsewhere; `cache-control: no-store` | api (throwaway PG) | 200, six parts, no sign-in | PASS |
| AD-HS-80, 81 | worst part, dependency down | OK / DEGRADED / BLOCKED combinations; whole path with the scheduler forced OK; closed pool; desk state missing | unit + api | worst wins; 200 | PASS |
| AD-HS-10..12 | database | OK; error shows exception type only; hang | unit | OK / BLOCKED / BLOCKED in 0.4 s (test timeout) | PASS |
| AD-HS-20..24 | data_api | OK; F&O old or short; VIX missing noted; cash old or short; unreadable with a fake host and port in the error | unit | OK / DEGRADED / OK / BLOCKED / BLOCKED, no host | PASS |
| AD-HS-25 | data_api = pre-market check | 10 database-up scenarios through `TechSupport.run` and the route | unit | same verdict (READY=OK) | PASS |
| AD-HS-26..28 | data_api timing | slow check runs in the background; old result not reported as current; check that never finishes | unit | DEGRADED then real result with its as_of; DEGRADED "N minutes old"; BLOCKED | PASS |
| AD-HS-29 | after-close window | Fri 16:00 IST, session being prepared is Monday | unit | BLOCKED with the pre-market check's own cash sentence | PASS |
| AD-HS-40..43 | redis | ok; not configured; connect error; ping error; ping False; hangs | unit | OK / DEGRADED | PASS |
| AD-HS-50..57 | quote_feed | fresh tick; old tick; yesterday's tick; no rows; cache unavailable; closed (evening, Saturday, before open, holiday); no holiday list; desk's own function followed; Kite login wording; hanging Mongo; no Kite call | unit | as in the rules | PASS |
| AD-HS-60, 61 | scheduler | env unset / 0 / false; 1 | unit | DEGRADED, exact text "off: session cycles are started by hand"; "on" says no scheduler code exists | PASS |
| AD-HS-70..77 | last_cycle | no rows; COMPLETED / RUNNING / WAITING_HUMAN / CREATED current; BLOCKED, FAILED; old session; simulations, other kinds and two tenants; no ids; CANCELLED; calendar cannot say | integration (throwaway PG) + unit | OK / BLOCKED / DEGRADED as in the rules | PASS |
| AD-HS-90, 91 | timeouts | each probe hangs in turn; five 0.5 s probes | unit | answer < 1.2 s, hung part not OK, others reported; < 1.3 s total | PASS |
| AD-HS-100..102 | cache | second call within 15 s; after 15 s; ten callers together | unit | no new probe / probes again / one set | PASS |
| AD-HS-110 | nothing private | planted host, port, token, tenant, workflow, symbol, URL: everything failing, and everything working, in one body each | unit | none in the JSON, no `://`, no dotted IP | PASS |
| AD-HS-111, 112 | exceptions, wording | every probe raises with planted text; 16 configurations x 6 details scanned for the advice words | unit | type name only; no banned word | PASS |
| AD-HS-120, 121 | /health | body keys and values; never creates the status monitor; closed pool gives 503 | api | unchanged | PASS |
| AD-HS-30 | Tech Support unchanged | 11 scenarios: output, summary and the market calls, against golden values generated from commit 82e5eedd | unit | equal | PASS |
| AD-HS-31, 32 | shared check | both call `data_checks`; the existing AD-25 and AD-FX tests | unit | pass unchanged | PASS |
| AD-HS-130..132 | read only | row counts of every autodesk table and md5 of 4 tables unchanged after 4 uncached calls; Postgres refuses a write in the route's read-only transaction; every statement is a SELECT; no broker/order import (ast) | integration + unit | no write | PASS |
| AD-HS-140 | real boot, no credentials | below | real | data_api not OK | PASS (output below) |
| AD-HS-141 | staging | `curl -s https://staging.niveshcopilot.com/autodesk/api/v1/health/status` | staging | per-part detail | **NOT RUN: UNVERIFIED until a deploy** |

## API / Endpoint Tests
Staging endpoint: NOT RUN, not deployed (see AD-HS-141). Everything below ran locally.

- **pytest, whole desk suite (+ order-path guard):**
  `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-desk-fixes tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `361 passed in 78.91s (0:01:18)`
- **Same, with the new files left out:** `... --ignore=tests/autodesk/test_health_status.py --ignore=tests/autodesk/ts_scenarios.py` → `278 passed in 73.54s (0:01:13)`
  (361 = 278 existing + 83 new; the existing tests are unchanged).
- **New module alone:** `83 passed in 11.34s`
- **py_compile:** ok for `agents/tech_support.py`, `main.py`, `routers/health_status.py`, `tests/autodesk/test_health_status.py`, `tests/autodesk/ts_scenarios.py`.
- **Mutation check on AD-HS-30:** changing `(need {MIN_FNO_UNDERLYINGS})` to `(needs …)` in `tech_support.py` gave `7 failed, 5 passed, 71 deselected in 3.90s`;
  the file was restored (`cmp` against the saved copy: identical).
- **Real boot (AD-HS-140).** A throwaway database `adboot_1794063733` on the throwaway Postgres; the container got ONLY: the throwaway database URL,
  a Mongo URL pointing at an unreachable local address, a placeholder database name and a placeholder OpenAI key. No data-API credentials, no Redis URL, no Kite
  material. `python -m uvicorn autodesk.main:app` inside the container, then three GETs. Output (unedited; the first call took 1.52 s):

```
container clock: 2026-11-07T15:02:14Z
CALL 1  HTTP 200 in 1.52 s   Cache-Control: None
{
  "status": "BLOCKED",
  "as_of": "2026-11-07T15:02:22.484821+00:00",
  "parts": {
    "database": {
      "status": "OK",
      "detail": "The desk database answers.",
      "as_of": "2026-11-07T15:02:22.484821+00:00"
    },
    "data_api": {
      "status": "BLOCKED",
      "detail": "The data check failed (CalendarUnavailable).",
      "as_of": "2026-11-07T15:02:22.504068+00:00"
    },
    "redis": {
      "status": "DEGRADED",
      "detail": "Redis is not configured or did not connect; quotes then come from the REST path.",
      "as_of": "2026-11-07T15:02:22.484821+00:00"
    },
    "quote_feed": {
      "status": "OK",
      "detail": "The market is closed, so no ticks are expected; today's Kite login could not be read in time.",
      "as_of": "2026-11-07T15:02:22.484821+00:00"
    },
    "scheduler": {
      "status": "DEGRADED",
      "detail": "off: session cycles are started by hand",
      "as_of": null
    },
    "last_cycle": {
      "status": "DEGRADED",
      "detail": "No session cycle has been recorded yet.",
      "as_of": null
    }
  }
}
CALL 2  HTTP 200 in 0.0 s   same body as call 1 (cached): True
OLD /api/v1/health  HTTP 200 in 0.01 s  keys: ['agents', 'app', 'calendar_years', 'db', 'execution', 'migrations', 'status', 'version']
```
  (`Cache-Control: None` is my client reading a lower-case header name; the header is asserted in AD-HS-01 with a case-insensitive client.)
  The throwaway database was dropped afterwards (`dropped adboot_1794063733`).

## UI / Playwright Tests
Not applicable: no frontend change.

## Data Correctness
- Last-cycle, read-only and workflow-ordering cases ran on a throwaway Postgres with rows made by the tests (AD-HS-70..77, 130).
- The boot above reads an empty throwaway database; it proves the route answers with dependencies absent, not that the figures are right on staging.
- UNVERIFIED: real Redis, real feed-cache ticks in market hours, a real Kite login document, the real data API, real workflow rows on staging.

## Rules chosen for each part, and the code each came from
- **database** — `SELECT 1` on `st.pool` (the pool `/health` uses). Failure or no answer in 3 s = BLOCKED.
- **data_api** — `tech_support.data_checks(m, sd)` (extracted from `TechSupport.run`, pure move plus 4-space dedent; `git diff -w` shows 20 added, 10 removed lines).
  `sd` = `st.next_session(now)` (the session the next cycle prepares), view = `st.market_factory(now)` (a `PitMarketView` in production). Status as the agent's
  report: no cash = BLOCKED, no F&O = DEGRADED, else OK; a missing VIX is noted and does not change it ("noted, not blocking" in the agent's docstring).
  Detail text is shown only when it matches a whitelist of count/day sentences; anything else (the data API's `not readable: …` lines carry its error text,
  including URLs) is replaced by a fixed sentence.
  **Timing:** the check makes up to 3 data reads (`day_snapshot` paged at 5000 rows, `/desk/fno-buildup`, the VIX index) plus the holiday list, each allowed 20 s by
  `daas_client`; `PitMarketView` keeps a 300 s read cache. I could not measure real latency (no credentials), so I did NOT assume it fits in 3 s: the check runs as a
  background task (registered in `st.background`, cancelled on shutdown) started when the last result is over 60 s old; a request waits 2.5 s for it, then reports
  the last finished result with that result's own `as_of`. No result yet = DEGRADED "first data check is still running"; a result over 5 minutes old = DEGRADED "N
  minutes old"; a run over 40 s = BLOCKED.
- **redis** — `quote_cache.get_client()` (the shared client `market/live_quotes.py::_feed_cache_read` reaches Redis through), then `ping()`. Not configured, error, no answer = DEGRADED.
- **quote_feed** — market hours from the desk's `execution/settle._market_open` (09:15–15:30 IST on a session day); the only addition is that a weekday with no
  holiday list loaded is DEGRADED "cannot tell" (`_market_open` would say closed). Open: `quote_cache.read_quotes(["NIFTY 50","NIFTY BANK"])` (one MGET on the feed's
  Redis cache, no Kite call), newest `received_at` via `live_quotes.from_cache_row`; today and at most `MAX_QUOTE_AGE_S` (120 s) = OK, else DEGRADED; cache unavailable or no
  index rows = DEGRADED. Closed = OK "the market is closed". `exchange_ts` is not used (it is mislabelled, per `live_quotes.py`). Index rows are used rather than
  `check_quote` because indices carry no volume and `check_quote` rejects a zero volume.
  **Kite login:** included. `platform_token.token_status(deps.db)` is a Mongo read of the token document without the token itself; no Kite call. It is bounded at 1.5 s so a dead
  Mongo cannot change this part's status or stretch the answer. It says "a Kite login is stored and has not expired" / "no unexpired Kite login is stored": the stored expiry
  (06:00 IST), not proof that Kite accepts the token.
- **scheduler** — `config.load().scheduler_enabled`. Off = DEGRADED, text exactly "off: session cycles are started by hand". **On is also DEGRADED**: nothing in the code
  reads the flag (grep: only `config.py` and the compose file), so "on" would prove nothing; the detail says so. To be revisited when R8 is built.
- **last_cycle** — `SELECT state, session_date, created_at FROM autodesk.workflows WHERE kind='SESSION_CYCLE' AND simulation_id IS NULL ORDER BY created_at DESC LIMIT 1`
  in a read-only transaction (`store.py`/migration 001 columns). No row = DEGRADED. BLOCKED or FAILED = BLOCKED. CANCELLED = DEGRADED (my call; the brief is silent and no code
  path cancels a cycle). Otherwise `session_date` against `market.previous_session(next_session)`: older = DEGRADED, else OK. Shows only state, session date, age.

## What was left out, and why
- Kite REST and any broker order data: never called (AD-HS-57, 132).
- Writing the last-cycle result anywhere, or a per-tenant view: the route is public, so only the newest cycle over all tenants and no ids.
- A new market-hours function: none written (AD-HS-55).
- The feed leader's heartbeat (`kite_live_lease` in Mongo) and the feed's own `/api/live/status`: the brief says "from the feed's Redis cache only".
- Any change to `routers/api.py` or the nginx/compose files.

## Findings for the owner
1. **The overall `status` can never be OK until R8 (scheduler) is built.** The scheduler part is always DEGRADED, and overall = worst part. A deploy check or monitor
   should look at the parts it cares about, or treat DEGRADED as healthy-enough today. The existing `/api/v1/health` stays the container healthcheck.
2. **After the close the data_api part reads BLOCKED until the cash file lands** (Friday 16:00 IST the session prepared is Monday, which needs Friday's cash file,
   published at 19:30 IST; F&O at 22:45 IST). This follows from using Tech Support's rules unchanged: the pre-market check run then would say BLOCKED too (AD-HS-29).
   If a monitor should not alert in that window, that is a rule change in the shared function, which the brief did not allow me to make.
3. Account 2's branch feat/autodesk-health-status-a2 carries the identical implementation plus its own tests and a BLOCKED report/OVERRIDE; the two branches
   have different `test_health_status.py` files at the same path.

## Inputs required from user
- A deploy of this branch to staging, then AD-HS-141: `curl -s https://staging.niveshcopilot.com/autodesk/api/v1/health/status` (and a look at the
  per-part details in market hours with a real Kite login, which no local test can show).

All 83 new and 278 existing desk tests pass and the real boot answered. PASS here does NOT mean staging-verified: AD-HS-141 is UNVERIFIED (see above).

## Verdict: PASS
