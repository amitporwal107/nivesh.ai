# Functionality Verification Report — Research Watchlist: 2026-10-12 list + "also in an earlier list" marker

- **Branch:** dev
- **Date:** 2026-10-12
- **Author:** Claude (full-stack-developer + qa-engineer + domain-expert-analyst)
- **Environment:** staging (staging.niveshcopilot.com / nivesh_staging Mongo)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Publishes the 2026-10-12 list (21 growth-screen names + 20 of the day's large-cap movers, 41 in all) as a
second dated list beside the 2026-10-06 one, and marks every pick that also appeared in an earlier list:
the API returns `earlier_list_dates` per item and `meta.carried_over`, and the page shows a coloured
"also in <date> list" badge with an accent edge on the row. Closes TC-14 of
`research_watchlist_history_20261012_2355.md` (picker switching), which needed a second list.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Store | `earlier_list_dates(list_date)` with three lists | unit | maps each symbol to the dates of strictly earlier lists it was in, newest first; later lists and the list itself never count | PASS |
| TC-2 | Route | Newest list requested | unit | every item carries `earlier_list_dates` (empty list when new); `meta.carried_over` equals the number of items with a non-empty value | PASS |
| TC-3 | Route | Oldest list requested | unit | every `earlier_list_dates` is empty; `meta.carried_over == 0` | PASS |
| TC-4 | API | `GET /api/public/research-watchlist` on staging after publishing | api | `list_date 2026-10-12`, 41 items, two available dates; exactly BSE, DELHIVERY, PFC, POLICYBZR, SUZLON carry `earlier_list_dates == ["2026-10-06"]`; `meta.carried_over == 5` | PASS |
| TC-5 | API | `GET …?date=2026-10-06` on staging | api | 41 items, none marked, `meta.carried_over == 0` | PASS |
| TC-6 | Data | Staging Mongo after seeding the new list | data | 82 docs = 41 + 41; the 2026-10-06 documents are byte-identical before and after (research text and price baseline); all 41 new picks have a real `published_price`; stored screen numbers equal the screen output | PASS |
| TC-7 | E2E | Open `/v5/watchlist` (newest list) | e2e | "41 of 41 picks shown"; exactly 5 "also in 6 Oct 2026 list" badges, on the five symbols above; summary line states the count | PASS |
| TC-8 | E2E | Open `/v5/watchlist?list=2026-10-06` | e2e | no badge on any row; the pinned 41-pick cases still pass | PASS |
| TC-9 | E2E | Picker switches between the two lists (TC-14 of the history report) | e2e | list and URL switch to the chosen date and back | PASS (failed once on the first run, then passed 4 runs in a row — see UI section) |

## API / Endpoint Tests (staging)
Deployed commit `9d3eafea`. Pushing to `dev` triggers a CI deploy (`ci-deploy` SSH logins at 23:36:57 and 23:37:38 IST,
seconds after the push); my manual `deploy.sh dev` ran at the same time and exited 1 on a container-name conflict at the
frontend recreate step. CI's deploy completed: `nivesh-staging-app-frontend-v5` runs image `4d36798b106f` (built 23:37:50
IST) whose bundle contains the badge, the backend container is healthy with `earlier_list_dates` in the store, and
`GET /api/healthz` returns 200.

- **Endpoint:** `GET /api/public/research-watchlist` (TC-4)
  - Command: `curl -sS https://staging.niveshcopilot.com/api/public/research-watchlist` (summarised with python)
  - Output:
    ```
    NEWEST  list_date 2026-10-12 | count 41 | carried_over 5 | available_dates [{'list_date': '2026-10-12', 'count': 41}, {'list_date': '2026-10-06', 'count': 41}]
            marked: [('BSE', ['2026-10-06']), ('DELHIVERY', ['2026-10-06']), ('PFC', ['2026-10-06']), ('POLICYBZR', ['2026-10-06']), ('SUZLON', ['2026-10-06'])]
            live 41 | published_price null 0 | published_date ['2026-10-12'] | tiers {'high': 6, 'caveat': 17, 'speculative': 18}
    ```
  - Result: PASS
- **Endpoint:** `GET /api/public/research-watchlist?date=2026-10-06` (TC-5)
  - Output: `OLDEST  list_date 2026-10-06 | count 41 | carried_over 0 | marked 0`
  - Result: PASS
- **pytest (TC-1..TC-3 and the seven earlier cases):**
  - Command: `sudo docker run --rm --network none -v /home/deploy/nivesh-dev-worktree:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_research_watchlist_history.py -q -p no:cacheprovider`
  - Output: `9 passed, 1 warning in 5.47s`
  - Result: PASS

## UI / Playwright Tests
- **Typecheck:** `npx tsc --noEmit` in a Node 20 container → `tsc exit 0 | error lines: 0`.
- **Spec:** `frontend-v5/e2e/tests/watchlist-unauth.spec.ts` (byte-identical to the repo copy), run in
  `mcr.microsoft.com/playwright:v1.47.0-jammy` against staging.
  - First run, a few minutes after the deploy: `1 failed … TC-14 the picker switches between lists` /
    `8 passed (24.5s)` (the 9th test was a throwaway screenshot helper). The failure was
    `expect.toHaveValue with timeout 15000ms — waiting for getByLabel('Watchlist date')`: the picker did not appear
    within 15 s on that page load. **Cause not identified.** The API answered in 55–87 ms in six timed calls made
    right after, and backend logs show 10–14 ms responses. It came shortly after the CI deploy restarted the
    frontend containers, which may be related; that is a guess, not a finding.
  - Re-run of that case alone: `1 passed (2.7s)`.
  - Three further full runs, each:
    ```
      ✓  1 … TC-5 renders unauthenticated with all picks
      ✓  2 … TC-8 shows the LIVE badge and a row expands into the deep-dive
      ✓  3 … TC-6 tier filter narrows the visible cards
      ✓  4 … TC-11 opens on the newest list with a list picker
      ✓  5 … TC-13 unknown list date shows a message and a way back
      ✓  6 … TC-14 the picker switches between lists
      ✓  7 … carry-over badge marks exactly the picks from an earlier list
      ✓  8 … the first list shows no carry-over badge
      8 passed (9.2s)   /   8 passed (8.9s)   /   8 passed (8.4s)
    ```
  - Result: PASS for TC-7, TC-8, TC-9, with the one unexplained first-run failure recorded above.
- Screenshot of the newest list checked by eye: BSE (rank 4) shows the "also in 6 Oct 2026 list" badge and the
  summary line reads "41 of 41 picks shown · 5 also in an earlier list".

## Data Correctness (staging)
- Seed: `docker exec nivesh-staging-app-backend python -m scripts.seed_research_watchlist --file scripts/data/research_watchlist_20261012.json --list-date 2026-10-12`
  → `done: {'list_date': '2026-10-12', 'seeded': 41, 'priced': 41, 'unpriced': 0, 'symbols_unpriced': []}`
- 2026-10-06 list untouched (SHA-256 over its research text and price baseline, 41 docs):
  before `docs by list {'2026-10-06': 41} | fingerprint 23752e2a956cd31b`,
  after `docs by list {'2026-10-06': 41, '2026-10-12': 41} | fingerprint 23752e2a956cd31b`.
- Stored numbers vs the screen output (ROCE, market cap, PE, latest-quarter profit, distance from high, baseline price,
  for all 41): `order matches screen: True | field mismatches vs screen output: []`.
- Source data checks made before publishing: all 41 picks' 12 Oct close and day change in NIDP equal Yahoo Finance
  (`NIDP vs Yahoo disagreements: []`); Trendlyne 3Y growth converted from cumulative to CAGR reproduces the stored
  2026-10-06 figures (Cummins profit 92.3% → 24.35%/yr); NIDP's unadjusted distance-from-high was replaced with
  Trendlyne's split-adjusted figure (as of the previous close).
- Result: PASS (TC-6)

## Known limits of the published content (not test failures)
- Per-stock notes are generated from the screen numbers and say so; there is no analyst deep-dive for this list.
- Tier is rule-based (stated on every pick), not an analyst judgement.
- Fundamentals are Trendlyne's latest values and are not point-in-time validated.
- The page header still says "quant-filtered from real NIDP filing data"; for this list the fundamentals came from
  Trendlyne because staging NIDP has one quarter of financials per company.

## Inputs required from user
- none

## Verdict: PASS
