# Functionality Verification Report — Research Watchlist: dated lists + historical view

- **Branch:** dev
- **Date:** 2026-10-12
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (staging.niveshcopilot.com / nivesh_staging Mongo)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The public `/watchlist` page held one undated list keyed by symbol, so publishing a new list
would overwrite the old one. This change makes every list a dated snapshot
(`list_date` + `symbol` is the key), stamps the existing 41 picks as the `2026-10-06` list
(the date that list was first published, commit `fb67ce55`), adds `?date=` to the public API
with the available dates in `meta`, and adds a list picker to the page (`?list=YYYY-MM-DD`
in the URL so a historical list is linkable). The live-quote overlay now asks for the union
of every list's symbols, because its cache is global and would otherwise mark a second
list's stocks as not live.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | API | `GET /api/public/research-watchlist` with no `date` | api | 200; items are the newest list only; `meta.list_date` set; `meta.available_dates` newest-first, each `{list_date, count}`; every item carries `list_date == meta.list_date` | PASS |
| TC-2 | API | `GET …?date=<existing list date>` | api | 200; only that list's items; `meta.list_date` equals the requested date | PASS |
| TC-3 | API | `GET …?date=2020-01-01` (no such list) | edge | 404 with a `detail` naming the date; no empty-200 | PASS (envelope field is `message`, see note) |
| TC-4 | API | `GET …?date=not-a-date` | edge | 422 | PASS |
| TC-5 | Store | Two lists share a symbol | unit | two separate documents; seeding the second list leaves the first list's research text and price baseline untouched; `list_picks()` returns only the newest | PASS |
| TC-6 | Store | Re-seed an existing `(list_date, symbol)` | unit | research text updated; `published_price` / `published_date` not reset | PASS |
| TC-7 | Store | `backfill_list_date` on legacy docs with no `list_date` | unit | only undated docs stamped; second run changes nothing | PASS |
| TC-8 | Store | Daily price refresh with two lists | unit | every `(list_date, symbol)` doc gets the new price; each `change_since_published_pct` uses its own baseline | PASS |
| TC-9 | Route | Live quotes requested while viewing an older list | unit | quotes are requested for the union of all lists' symbols | PASS |
| TC-10 | Data | Staging Mongo after the one-off backfill | data | 41 docs, all `list_date = 2026-10-06`, unique index on `(list_date, symbol)`, `published_price` values unchanged by the backfill | PASS |
| TC-11 | E2E | Open `/v5/watchlist` cold, no session | e2e | no redirect to `/login`; newest list renders; list picker shows the available dates | PASS |
| TC-12 | E2E | Open `/v5/watchlist?list=2026-10-06` | e2e | "41 of 41 picks shown", CUMMINSIND visible, LIVE badge, row expands, tier filter narrows (the pre-existing TC-5/6/8, pinned to that list) | PASS |
| TC-13 | E2E | Open `/v5/watchlist?list=2020-01-01` | edge | a clear "no list for that date" message with a way back to the latest list; no crash, no blank page | PASS |
| TC-14 | E2E | Pick a different date in the list picker (needs two lists on staging) | e2e | list and URL switch to the chosen date; switching back restores the newest | PASS — run after the 2026-10-12 list was published; see research_watchlist_list_20261012_carryover.md (TC-9), including one unexplained first-run failure |

## API / Endpoint Tests (staging)
Deployed commit `73498f48` (`sudo bash /opt/nivesh-staging/repo/deploy/cloudpe/app/deploy.sh dev`). The deploy
pulled and built the commit, then its frontend recreate step printed a container-name conflict
(`/9182ce073e3e_nivesh-staging-app-frontend-v5 is already in use`), which looks like a second deploy running at
the same moment. Checked afterwards: repo at `73498f48`, `nivesh-staging-app-frontend-v5` runs the image built
at 23:25:30 IST and its bundle contains the new picker, backend container healthy with the new store code.

- **Endpoint:** `GET /api/public/research-watchlist` (TC-1)
  - Command: `curl -s https://staging.niveshcopilot.com/api/public/research-watchlist` (summarised with python)
  - Output: `meta.count 41 | meta.list_date 2026-10-06 | available_dates [{'list_date': '2026-10-06', 'count': 41}]`
    `item list_dates ['2026-10-06'] | live 41 | first 1 CUMMINSIND 4835.0`
  - Result: PASS
- **Endpoint:** `GET /api/public/research-watchlist?date=2026-10-06` (TC-2)
  - Output: `http=200` · `meta.list_date 2026-10-06 | count 41 | items 41`
  - Result: PASS
- **Endpoint:** `GET /api/public/research-watchlist?date=2020-01-01` (TC-3)
  - Output: `{"timestamp":"2026-10-12T17:56:24Z","status":404,"error":"NOT_FOUND","code":"RES-001","message":"No research watchlist was published for 2020-01-01","details":[],"correlationId":"3146a113fb4b495d8ef07988b6d105ac","path":"/api/public/research-watchlist"}` · `http=404`
  - Result: PASS. Note: the app's error envelope carries the text in `message`, not `detail` as the test case was worded.
- **Endpoint:** `GET /api/public/research-watchlist?date=not-a-date` (TC-4)
  - Output: `{"timestamp":"2026-10-12T17:56:24Z","status":422,"error":"VALIDATION_ERROR","code":"VAL-001","message":"Request validation failed","details":[{"field":"query.date","message":"Input should be a valid date or datetime, invalid character in year"}],…` · `http=422`
  - Result: PASS
- **pytest (TC-5..TC-9, plus route date handling):** throwaway container from the staging backend image, worktree mounted read-only
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-dev-worktree:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_research_watchlist_history.py -q -p no:cacheprovider`
  - Output: `7 passed, 1 warning in 5.50s`
  - Result: PASS

## UI / Playwright Tests
- **Typecheck:** `npx tsc --noEmit` in a Node 20 container over the worktree's `frontend-v5` → `tsc total error lines: 0`.
- **Spec:** `frontend-v5/e2e/tests/watchlist-unauth.spec.ts` (TC-11, TC-12 = the three pinned cases, TC-13, TC-14)
  - Command: `npx playwright test` in `mcr.microsoft.com/playwright:v1.47.0-jammy` with `@playwright/test@1.47.0` and a
    minimal config (this VM has no Node; the repo config would start a local Vite server the spec does not use — it
    targets staging by absolute URL). The spec file was byte-identical to the repo copy (`cmp`).
  - Output:
    ```
    Running 6 tests using 1 worker
      ✓  1 watchlist-unauth.spec.ts:20:7 › Research Watchlist public page › TC-5 renders unauthenticated with all picks (839ms)
      ✓  2 watchlist-unauth.spec.ts:30:7 › Research Watchlist public page › TC-8 shows the LIVE badge and a row expands into the deep-dive (887ms)
      ✓  3 watchlist-unauth.spec.ts:41:7 › Research Watchlist public page › TC-6 tier filter narrows the visible cards (4.5s)
      ✓  4 watchlist-unauth.spec.ts:55:7 › Research Watchlist dated lists › TC-11 opens on the newest list with a list picker (2.7s)
      ✓  5 watchlist-unauth.spec.ts:67:7 › Research Watchlist dated lists › TC-13 unknown list date shows a message and a way back (804ms)
      -  6 watchlist-unauth.spec.ts:76:7 › Research Watchlist dated lists › TC-14 the picker switches between lists
      1 skipped
      5 passed (10.7s)
    ```
  - Result: PASS for TC-11/12/13. TC-14 NOT RUN (skips itself while staging has fewer than two lists).

## Data Correctness (staging)
- One-off backfill, run in `nivesh-staging-app-backend` before the deploy so the page never showed an empty list
  (same operation as `store.backfill_list_date` + `store.ensure_indexes`):
  `stamped 41 | index list_date_1_symbol_1 | docs 41 | dated 2026-10-06 41 | baselines unchanged True`
- Result: PASS (TC-10) — 41 documents, all dated 2026-10-06, unique index present, every `published_price` identical before and after.

## Inputs required from user
- Approval of the 2026-10-12 candidate list (given; the list is published).

## Verdict: PASS
TC-14 was run once the second list existed; evidence is in `research_watchlist_list_20261012_carryover.md`.
