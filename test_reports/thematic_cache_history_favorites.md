# Functionality Verification Report — Thematic daily cache + history + favourites

- **Branch:** feat/filings-intelligence-design (shipped to `dev`)
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack + QA)
- **Environment:** staging (DaaS 8084 · /v5/research :8443 · nidp_staging)
- **Changed areas:** backend routes/services: **yes** (daas_api thematic_search.py + intelligence.py) · frontend src: **yes** (hooks/useThematicQueries.ts, pages/Research/index.tsx)

## Summary
Three asks: (1) cache thematic results for the day, refresh next day; (2) history of queries
fired; (3) favourite queries. (1) is server-side in the DaaS (shared, market-wide results);
(2)+(3) are per-device on /v5/research (localStorage) as tabs on the starters card.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | cache | 1st call computes + stores | api | cached:false, slow | PASS |
| TC-2 | cache | 2nd identical call | api | cached:true, instant | PASS |
| TC-3 | cache | pagination from cache | api | cached:true across offset | PASS |
| TC-4 | cache | row keyed by CURRENT_DATE | data | day=today | PASS |
| TC-5 | ui | 3 tabs Curated/History/Favorites render | e2e | all present | PASS |
| TC-6 | ui | curated shows 5 by default | e2e | 5 | PASS |
| TC-7 | favourites | bookmark a theme → Favorites tab | e2e | 1 item | PASS |
| TC-8 | history | fire a query → History tab logs it | e2e | 1 item, correct text | PASS |
| TC-9 | build | tsc + vite build | build | exit 0 | PASS |

## API / Endpoint Tests (staging DaaS 8084) — REAL output
```
call 1 (miss):  cached: False | matches: 1 | time=21.582472s
call 2 (hit):   cached: True  | matches: 1 | time=0.014714s
page 2 (hit):   cached: True  | next_offset=... | time=0.011607s
cache table:    1 row | day 2026-07-21 .. 2026-07-21
```
21.6s → 0.015s on repeat; a new day is a cache miss (day-keyed) → recompute ("refresh next
day"). Rows older than 7 days pruned on write. Best-effort: any cache error → live compute.

## Playwright (staging /v5/research, session_token cookie) — REAL output
```
tab present [tab-curated]: true
tab present [tab-history]: true
tab present [tab-favorites]: true
curated starters (default): 5
favorites after 1 bookmark: 1
history items after firing 1 query: 1
  first history: Biggest order wins this fortnight — by value, sector, and counterparty
VERDICT: PASS
```
Screenshot: scratchpad/research_tabs.png (tabs Curated · History (1) · Favorites (1), the
logged query with bookmark + remove + Clear).

## Build
- `tsc --noEmit` exit 0; `vite build` exit 0 (✓ built in 46.22s)
- Frontend-v5 rebuilt + `nivesh-staging-app-frontend-v5` recreated @ dev f1f7cf84
- DaaS thematic cache @ dev 4f25ce60 (deployed, verified)

## Notes / risks (honest)
- History + favourites are **per-device (localStorage)** — not synced across devices. Can be
  promoted to a server store (Mongo) later without changing callers (the hook is the seam).
- **Staging DB capacity risk**: during cache testing the staging Postgres crash-looped on
  `No space left on device` (WAL) — its data volume is on a prod-shared NFS at ~97-99%. It
  self-recovered (437s checkpoint). Not caused by this change; flagged for an infra fix
  (prune staging-raw-archives / expand NFS). No shared-NFS data was deleted.
- prod untouched.

## Verdict: PASS
