# Functionality Verification Report — Desk health status route (R14)

- **Branch:** feat/autodesk-health-status-a2 (from Account 1's commit 7333ccaf; Account 1's uncommitted route and Tech Support refactor were copied read-only, then tested and finished here)
- **Date:** 2026-11-07
- **Author:** Claude (Account 2, taking over Account 1's work at the owner's request)
- **Environment:** throwaway container from the staging image + throwaway Postgres. NOT staging.
- **Changed areas:** backend routes/services: yes (new routers/health_status.py, tech_support.data_checks extracted, 2 lines in main.py) · frontend src: no

## Summary
`GET /api/v1/health/status` (public path `/autodesk/api/v1/health/status`): no sign-in, status only, six parts (database, data_api,
redis, quote_feed, scheduler, last_cycle), each OK / DEGRADED / BLOCKED with a one-sentence detail; HTTP always 200. Probes have a
3 s limit and run together; the answer is cached 15 s; the slow data check runs as a background task. `GET /api/v1/health` is
untouched. Tech Support's data rules were moved into `tech_support.data_checks`, called by both the agent and the route.
The tests (`backend/tests/autodesk/test_health_status.py`, 53) were written against `docs/autodesk/testcases_health_status.md`.

## Test Cases
| IDs | Scenario | Type | Result |
|---|---|---|---|
| AD-HS-01, 02, 80, 81 | shape, no sign-in, worst part, closed database pool | A/U | PASS |
| AD-HS-10..12 | database part, error type only, timeout | U | PASS |
| AD-HS-20..28 | data_api rules, same rules as the agent (8 scenarios), slow / old / never-finishing check, no host or port | U | PASS |
| AD-HS-40..43 | redis | U | PASS |
| AD-HS-50..57 | quote feed by market state, Kite login wording, no Kite call | U | PASS |
| AD-HS-60, 61 | scheduler | U | PASS |
| AD-HS-70..77 | last cycle on a real database (states, old session, simulations and other kinds ignored, no ids) | I | PASS (AD-HS-73 and 76 both covered; AD-HS-77 CANCELLED) |
| AD-HS-90..91, 100..102 | hung probes, probes run together, 15 s cache, single flight | U | PASS |
| AD-HS-111, 112 | exception text never shown; no advice words in details or in the module's strings | U | PASS |
| AD-HS-120, 121, 130, 131, 132 | /health unchanged and never probes; closed pool gives 503; no rows written; only SELECT in read-only transaction; no broker code | A/I/U | PASS |
| AD-HS-30 | Tech Support output, summary and market calls equal the golden values from 82e5eedd, 11 scenarios | U | PASS |
| AD-HS-31, 32 | both call the shared check; existing desk tests pass unchanged | U | PASS |
| AD-HS-110 | one JSON body with planted tenant, account, workflow, host, port, token, symbol | I | PARTIAL: hosts/ports/exception text/ids covered by AD-HS-24, 75, 111; no single combined fixture |
| AD-HS-140 | boot `autodesk.main:app` with no credentials and call the route | real boot | NOT RUN |
| AD-HS-141 | the route on staging | staging | NOT RUN (not deployed) |

Mutation check: changing the cash rule in `data_part` (BLOCKED to OK) made 6 tests fail; the file was restored.

## API / Endpoint Tests
- `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-a2-health tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `331 passed in 78.28s (0:01:18)` (278 existing + 53 new, order-path guard included)
- The route was called through FastAPI's TestClient with doubles. It was NOT called on staging.

## UI / Playwright Tests
Not applicable: no frontend change.

## Data Correctness
Last-cycle and read-only cases ran on a throwaway Postgres with rows made by the tests. UNVERIFIED against real staging data, real Redis, the real data API or a real Kite login (the Kite login read is a Mongo token document read; no Kite call is made).

## Inputs required from user
- A deploy of this branch to staging, then run AD-HS-141 and AD-HS-140.

## Verdict: BLOCKED
