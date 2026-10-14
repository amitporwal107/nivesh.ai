# Functionality Verification Report — Smart trading desk: backend APIs for the "Not connected" parts

- **Branch:** feat/trading-desk-backend (worktree /home/deploy/nivesh-trading-desk, on top of fix/trading-desk-build → origin/dev 3f6521fd)
- **Date:** 2026-10-14
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Changed areas:** backend routes/services: yes (app routes, DaaS routers, one NIDP service + migration) · frontend src: yes (desk wiring)

## Summary
The user asked to "complete the backend api" and chose four groups (AskUserQuestion, 2026-10-14): read routes over stored data;
paper trades the user creates; price alerts; a SEBI circulars feed. Contracts: scratchpad `backend-brief.md`, copied below in short.

| Group | Endpoint | Data |
|---|---|---|
| A | GET /api/markets/sector-returns → DaaS /v1/desk/sector-returns | nidp.index_eod sectoral indices, 1D/1W/1M |
| A | GET /api/markets/deals → DaaS /v1/desk/deals | nidp.bulk_deals, nidp.block_deals |
| A | GET /api/fno/scan/buildup → DaaS /v1/desk/fno-buildup | nidp.fno_bhavcopy stock futures (prev close, change in OI) |
| A | /api/markets/home `breadth.universe`; /api/filings/feed `exchange` | existing routes |
| B | GET /api/portfolio/correlation | holdings + adjusted closes via DaaS |
| B | GET /api/portfolio/market-cap-split | NSE index membership (Nifty 100 / Midcap 150 / Smallcap 250) |
| B | /api/positional/watchlist, /picks: spark_closes, avg_traded_value_cr_20d, resistance/support | app DB stock_ohlcv |
| C | POST/GET /api/desk/paper-trades, POST …/{id}/close | MongoDB desk_paper_trades; EOD bars via DaaS |
| C | POST/GET /api/desk/alerts, DELETE …/{id}; scripts/check_desk_alerts.py + app-VM cron | MongoDB desk_price_alerts |
| D | nidp.sebi_circulars (migration 163), services/sebi_circulars, cron; DaaS /v1/circulars/sebi; GET /api/markets/circulars | SEBI RSS, circulars only |
| D | INDEX_CONSTITUENT_URLS + Nifty Midcap 150, Nifty Smallcap 250 | NSE archives |
| E | Desk tabs wired to all of the above, "Not connected" blocks replaced | frontend |

Still out of scope (not chosen / need model or new feeds): move probability beyond the next session; intraday index sparks;
one-click option paper strategies.

## Test Cases
> Authored up front — after the API design (contracts) and before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| B-1 | sector-returns | latest day, 1D/1W/1M per sectoral index | unit + data | returns = close / close N sessions back − 1, from index_eod | |
| B-2 | sector-returns | an index with < 21 sessions | edge | ret_1m_pct null | |
| B-3 | deals | days=5 kind=all; kind=bulk; symbol filter; days out of range → 422 | unit + data | rows/counts match the tables | |
| B-4 | fno-buildup | labels from price change × OI change; OI summed across expiries | unit + data | label rule holds row by row; universe = distinct STF underlyings | |
| B-5 | home / filings | breadth.universe and row exchange present | unit | as stated | |
| B-6 | correlation | 2+ holdings with prices → pairs sorted desc, values in [−1,1]; <2 usable → empty pairs + reasons | unit + data | matches numpy on the same series | |
| B-7 | market-cap split | buckets sum to equity total; funds excluded and reported; missing Midcap/Smallcap lists → available=false for those | unit | as stated | |
| B-8 | scanner fields | spark_closes length ≤ 24 oldest first; avg traded value; levels present; one batched query | unit | as stated | |
| B-9 | paper trades | create valid; reject bad symbol / stop ≥ entry / target ≤ entry / qty 0; 101st open → 409 | unit | as stated | |
| B-10 | paper trades | auto-exit at stop / target / both same session → stop; manual close; P&L figures | unit | as stated | |
| B-11 | paper trades | user A cannot read or close user B's trade | unit (security) | 404 | |
| B-12 | alerts | create/list/delete; above/below firing on the first session after creation; 51st active → 409; other user's alert → 404 | unit | as stated | |
| B-13 | evaluator | check_desk_alerts.py idempotent (second run changes nothing) | unit | as stated | |
| B-14 | SEBI ingest | parse the real feed copy; only /legal/circulars/ and /legal/master-circulars/ kept; enforcement notices (PAN) dropped; upsert idempotent | unit | as stated | |
| B-15 | circulars route | days/limit; empty table → 200 rows [] with as_of | unit | as stated | |
| B-16 | DaaS down | each backend proxy → 502/503 with a code, never an empty success | unit (failure) | as stated | |
| B-17 | staging API | every new GET on staging returns real data with the session token; POST/DELETE round-trip on a test trade/alert, then cleaned up | staging API | 200/201/204 with real figures || PENDING — session token |
| B-18 | staging data | sector-returns, deals, buildup, circulars equal direct read-only SQL on the warehouse for the same day | data | equal || PASS (staging, 2026-10-14) |
| F-1 | desk UI | Overview sector 1D/1W/1M toggle; breadth universe named | e2e (mocked) | as stated | |
| F-2 | desk UI | Intel: deals list; SEBI circulars under Regulatory; exchange from the row | e2e | as stated | |
| F-3 | desk UI | Scanner sparkline + liquid-only toggle; Chart next support/resistance | e2e | as stated | |
| F-4 | desk UI | Risk desk: Add to paper trades / Alert on trigger POST the right body; errors shown; lists in Portfolio with close/delete | e2e | as stated | |
| F-5 | desk UI | Portfolio correlation + market-cap split; F&O build-up quadrant + table | e2e | as stated | |
| F-6 | desk UI | 390px no sideways scroll on every tab; all copilot-app specs still pass | e2e + regression | as stated | |

## Unit tests (local, staging backend image, no network)
New and touched backend tests together (desk market, F&O build-up, home breadth, portfolio correlation and market-cap
split, scanner fields, paper trades and alerts, circulars route, DaaS desk + circulars routers, SEBI parser/service,
existing DaaS API tests):
```
435 passed, 8 warnings in 11.77s
```
Test isolation fix: `test_daas_desk_market.py` imported the full DaaS app, which made `test_daas_api.py` fail when it ran
afterwards (its fake pool must be in place at the app's first import). The desk test now mounts only its router;
both orders pass (`58 passed` each). The feed-registry drift test fails identically on a clean origin/dev copy
(`corporate_announcements` not in nidp.cron) — not this branch.

## UI / Playwright Tests (route-mocked — MOCK, not real data)
Playwright 1.47, production build, `--network none`; four desk specs + Trader + screens regression:
```
TSC CLEAN
vite build ok
✓ built in 22.48s
  114 passed (1.5m)
```
Covers F-1…F-6 as wired (sector 1D/1W/1M, deals, circulars, exchange, scanner sparkline + liquid-only, levels,
paper-trade and alert POST bodies and errors, correlation, market-cap split, F&O build-up, 390px).
**Design-fidelity pass** (4 agents; desktop tab order follows the PRD, docs/smart_trader §3.1). Re-run by me on the combined tree, 2026-10-14 ~16:50 IST:
- `desk-run.sh tsc` → `TSC CLEAN`.
- `desk-run.sh pw` over every `e2e/tests/copilot-app*.spec.ts` except the shots and live specs (21 files: production build, then `npx playwright test`, all /api calls route-mocked):
```
vite build ok
  14 skipped
  436 passed (4.8m)
```
- The 14 skipped tests are all opt-in screenshot captures (account, contract-chart, desk-lab, ops, options, research and statements "shots"/"pictures").

## API / Endpoint Tests (staging)
**What is deployed (2026-10-14):**
- **App VM:** PR #220 merged to dev and auto-deployed. The backend container has `routes/desk_trading.py`, `markets_desk.py` and `portfolio_desk.py`, dated 10:02 UTC.
- **Warehouse (NIDP) VM:** deployed with migrations, the step the user approved: `deploy/cloudpe/nidp/deploy.sh dev --migrate`, with no cron change. Log, verbatim:
```
[nidp-deploy] Deploying 801d0000 Merge pull request #220 from amitporwal107/feat/trading-desk-backend
  ✅ 162_sourced_fundamentals.sql applied
  ✅ 163_sebi_circulars.sql applied
[nidp-deploy] OK  DaaS API :8084/health
[nidp-deploy] OK  nginx /daas/health
[nidp-deploy] Done.
```

**App routes without a session (backend container, 172.18.0.5:8001).** Auth is enforced:
```
/api/desk/paper-trades -> 401
/api/desk/alerts       -> 401
/api/broker/positions  -> 401
```

**Desk DaaS routes on the warehouse VM (internal key, read on the VM, never printed):**
```
GET /v1/desk/sector-returns    HTTP 200  as_of 2026-10-13  sectors list[20]  first: Nifty Auto close 25391.85 ret_1d 1.23 ret_1w -0.59 ret_1m -7.8
GET /v1/desk/deals?days=10     HTTP 200  as_of 2026-10-13  from 2026-10-04  count 431
GET /v1/desk/fno-buildup       HTTP 200  as_of 2026-10-13  universe 213  long_buildup 116 short_buildup 20 short_covering 73 long_unwinding 4 neutral 0 no_data 0
GET /v1/circulars/sebi?days=60 HTTP 200  count 0 (table created by 163; the SEBI ingest job is not installed — not approved)
```

**B-17 (the /api/desk/* user routes with a real session: GET, then a POST/DELETE round-trip) is still pending.** It needs a staging session token from the user.

## Data Correctness (staging)
Read-only checks done during the build (agents' reports): sector returns vs NSE pct_change (Nifty IT 5.22%),
build-up counts, deal values, correlation vs Postgres corr(), paper-trade/alert price read vs direct SQL, SEBI
listing parse. **B-18 on staging, 2026-10-14: each route figure equals direct read-only SQL on the warehouse:**
```
deals_10d (bulk + block, 2026-10-04..13)            SQL 431            route count 431
STF underlyings 2026-10-13                          SQL 213            route universe 213
build-up long/short/covering/unwinding              SQL 116/20/73/4    route 116/20/73/4
Nifty Auto 1d / 1m (index_eod, own series)          SQL 1.23 / -7.80   route 1.23 / -7.8
nidp.sebi_circulars rows                            SQL 0              route count 0
```

## Inputs required from user
- **Done:**
  - Merged to dev (PR #220).
  - Migrations 162 and 163 applied with the user's approval.
- **Still needed:**
  - A staging session token for B-17. The user was asked to save it to /home/deploy/.nivesh-staging-session (mode 600).
  - Cron entries (SEBI ingest and desk alerts): the user did not select them on 2026-10-14, so they are not installed.

## Verdict: BLOCKED
