# Functionality Verification Report — Autonomous Trading Desk: six fixes from the 5 Nov staging walk-through

- **Branch:** fix/autodesk-desk-fixes (worktree /home/deploy/nivesh-wt-desk-fixes), based on origin/dev c2e161eb
- **Date:** 2026-11-07
- **Author:** Claude (full-stack developer + QA)
- **Environment:** local only — throwaway Postgres 16 container + the `nivesh/backend:staging` image (backend), Playwright 1.47 on the
  production build with route mocks (frontend). **Staging is NOT deployed with this branch; nothing here ran against staging or the
  real data platform.**
- **Changed areas:** backend routes/services: yes (`backend/autodesk/`) · frontend src: yes (`frontend-v5/src/autodesk/`)

## Summary
Six fixes found in the signed-in walk-through of 5 Nov (`test_reports/autodesk_staging_walkthrough_20261105.md`):
F1 data-arrival times (cash 19:30 IST, F&O 22:45 IST, still strictly point-in-time), F2 previous-session freshness in the
pre-market check (F&O not for the previous session → DEGRADED/cash only; cash older than it → BLOCKED), F3 a cycle BLOCKED before
any scan no longer uses up the session (new attempt keys `…:cycle:attempt-N`), F4 the scanner shows which pre-market checks failed,
F5 "Open full plan" links in the Simulation studio, F6 `/events`, `/simulations/{id}/timeline` and `/desk/workflows` return the
newest rows. Test cases AD-FX-01..44 were written and committed before any code (commit bddb6481). Everything below is verified by
unit / integration / API tests on a throwaway database and by mocked-API browser tests; the real-data checks are listed under
UNVERIFIED.

## Test Cases
Authored up front in `docs/autodesk/TESTCASES.md` ("Desk fixes from the 5 Nov walk-through"). Three rows were refined after the code
decisions (AD-FX-30/31/33: per-plan approval lookup instead of one run-wide list, because that list is capped at 1000 rows; the link
sits beside the card, not inside it; feed rows use the event's own approval id) — the doc was updated in the same commit.

| ID | Area | Scenario | Type | Test (file::name) | Result |
|----|------|----------|------|-------------------|--------|
| AD-FX-01 | F1 | `published_at` / constants: cash 19:30, F&O 22:45 IST | unit | test_market_view.py::test_adfx01_published_times_follow_the_real_loads | PASS |
| AD-FX-02 | F1 | Pit + Frozen views at 18:50, 19:29/19:30, 22:44/22:45; LookAheadError until then; Monday sees Friday (AD-10 rewritten) | unit | test_market_view.py::test_adfx02_strict_point_in_time_at_the_new_instants, ::test_ad10_publication_rule | PASS |
| AD-FX-03 | F1 | Simulations unchanged after the time change (AD-70..77, AD-72 look-ahead proof) | integration | whole suite, test_simulator.py | PASS |
| AD-FX-04 | F2 | Data for the previous session → READY, all segments | unit | test_ai_trader_ts.py::test_adfx04_previous_session_data_is_ready | PASS |
| AD-FX-05 | F2 | F&O two sessions old with enough underlyings → DEGRADED, cash only, detail names both dates | unit | ::test_adfx05_fno_two_sessions_old_is_degraded_even_with_enough_underlyings | PASS |
| AD-FX-06 | F2 | 18:50 IST case: cash older than the previous session → BLOCKED, detail names both dates | unit | ::test_adfx06_cash_older_than_the_previous_session_is_blocked | PASS |
| AD-FX-07 | F2 | Weekend (Mon needs Fri) and holiday (Wed needs Mon) | unit | ::test_adfx07_weekend_and_holiday | PASS |
| AD-FX-08 | F2 | Previous session unknown (calendar unavailable) → never READY | unit | ::test_adfx08_unknown_previous_session_never_defaults_to_ready | PASS |
| AD-FX-09 | F2 | `previous_session` on Pit (calendar only, skips holidays, no data API call, recorded) and Frozen views | unit | test_market_view.py::test_adfx09_previous_session_is_calendar_only_and_skips_holidays | PASS |
| AD-FX-10 | F3 | BLOCKED cycle then again → new workflow `…:cycle:attempt-2`, old one kept | integration | test_orchestrator.py::test_adfx10_11_blocked_cycle_can_be_asked_for_again | PASS |
| AD-FX-11 | F3 | attempt-3; a completed attempt is final (no attempt-4) | integration | same test | PASS |
| AD-FX-12 | F3 | COMPLETED and RUNNING cycles stay idempotent (AD-65 unchanged) | integration | ::test_adfx12_completed_or_running_cycle_stays_idempotent, ::test_ad65_idempotent_cycle | PASS |
| AD-FX-13 | F3 | Only BLOCKED + no scan + no proposals is re-attemptable; explicit keys (simulations) never | unit+integration | ::test_adfx13_which_cycles_may_be_attempted_again | PASS |
| AD-FX-14 | F3 | POST /desk/workflows twice over the API after a BLOCKED pre-market | API | test_api.py::test_adfx14_blocked_cycle_then_again_over_the_api | PASS |
| AD-FX-15 | F3 | Scanner: Run session cycle enabled after a blocked cycle, new attempt runs, no "already ran" | e2e (mock) | autodesk-scanner.spec.ts "AD-FX-15/21 …" | PASS |
| AD-FX-16 | F3 | POST answered with a blocked, scan-less cycle → panel, not "already ran"; COMPLETED still says already ran | e2e (mock) | "AD-FX-16/21 …" and the unchanged AD-UI-46 | PASS |
| AD-FX-20 | F4 | BLOCKED cycle lists the failed/degraded checks with their detail; READY check not listed | e2e (mock) | "AD-FX-20 …" | PASS |
| AD-FX-21 | F4 | Same panel right after a run (watch) and after a reload (list); a new blocked attempt shows its own checks | e2e (mock) | "AD-FX-15/21", "AD-FX-16/21" | PASS |
| AD-FX-22 | F4 | Pre-market with a `reason` and no checks → reason as written | e2e (mock) | "AD-FX-22 …" | PASS |
| AD-FX-23 | F4 | DEGRADED cycle → degraded note; READY cycle → no panel | e2e (mock) | "AD-FX-23 …" | PASS |
| AD-FX-24 | F4 | Tech Support details contain none of the banned narrative words (AD-92 extended) | unit | test_safety.py::test_adfx24_tech_support_details_have_no_advice_words | PASS |
| AD-FX-30 | F5 | Agent trace cards link to /autodesk/approvals/{newest approval id}; NO_TRADE / no-approval cards have none; no request for the NO_TRADE card | e2e (mock) | autodesk-studio-trace.spec.ts "AD-FX-30 …" | PASS |
| AD-FX-31 | F5 | Click → URL /autodesk/approvals/APR-…, desk approval screen asks the API for it | e2e (mock) | "AD-FX-31 …" | PASS |
| AD-FX-32 | F5 | Finished chain's outcome box carries the link | e2e (mock) | "AD-FX-32 …" | PASS |
| AD-FX-33 | F5 | Trading day feed approval rows link to the event's approval id; other rows none | e2e (mock) | autodesk-studio-day.spec.ts "AD-FX-33 …" | PASS |
| AD-FX-34 | F5 | Approvals lookup fails (500) → shown; cards and replay still work; no guessed link | e2e (mock) | trace spec "AD-FX-34 …" | PASS |
| AD-FX-35 | F5 | GET /approvals?simulation_id=&trade_id= → rows of the trade, newest first, tenant-scoped | API | test_api.py::test_adfx35_41_42_newest_rows_and_the_plan_approval_lookup | PASS |
| AD-FX-40 | F6 | `store.list_events`: no cursor = newest N ascending; after_seq=0 = first N; cursor walk reads all | integration | test_store.py::test_adfx40_list_events_cursor_and_newest | PASS |
| AD-FX-41 | F6 | GET /events: newest N / oldest N / next page | API | test_api.py::test_adfx35_41_42_… | PASS |
| AD-FX-42 | F6 | GET /simulations/{id}/timeline: same; clock rows never limited | API | same test | PASS |
| AD-FX-43 | F6 | `list_workflows(newest_first)` and GET /desk/workflows?limit=2 → two newest, newest first; children keep creation order | integration+API | test_store.py::test_adfx43_list_workflows_newest_first; test_api.py::test_adfx14_… | PASS |
| AD-FX-44 | F6 | UI consumers: existing specs unchanged; every timeline read carries after_seq (starts at 0) | e2e (mock) | studio-day spec "AD-FX-44 …" + full desk run | PASS |

## API / Endpoint Tests
Not run against staging (not deployed). The API tests above run the real FastAPI app (`autodesk.main`) with TEST-DOUBLE agents and a
throwaway Postgres (`backend/scripts/run_autodesk_tests.sh`), with a faked sign-in.

- **Backend suite** — command (from the worktree root):
  `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-desk-fixes tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output (unedited):
    ```
    ........................................................................ [ 43%]
    ........................................................................ [ 86%]
    ......................                                                   [100%]
    166 passed in 39.32s
    ```
  - Baseline on dev was 150 passed; 16 new `adfx` tests (`-k adfx` → `16 passed, 142 deselected in 6.62s`).
  - Result: PASS. `tests/test_order_path_guard.py` (no order placement) is in that run. `test_ui_request_contracts.py` (every request
    body the UI sends, posted to the real API) is in that run; no request body changed, so no fixture in `e2e/fixtures/autodesk/requests/` changed.
- **py_compile** on every changed .py (`git diff --name-only c2e161eb HEAD -- '*.py'`, 14 files): all printed `py_compile ok <file>`.

## UI / Playwright Tests
- Command (Docker, no network, from the worktree; Playwright output goes to /tmp inside the container):
  `sudo -n docker run --rm --network none -v /home/deploy/nivesh-wt-desk-fixes/frontend-v5:/app -v wl-fe-node-modules:/app/node_modules -v pw-browsers-1223:/pw -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app mcr.microsoft.com/playwright:v1.47.0-jammy bash -lc 'npx tsc --noEmit -p tsconfig.json; …; npx vite build --config vite.autodesk.config.ts --outDir /tmp/ad-dist …; npx vite preview … --port 5175 …; npx playwright test --config pw.autodesk.config.ts --output /tmp/pw-out'`
- Output lines (unedited):
  ```
  TSC_EXIT=0
  ../../tmp/ad-dist/assets/index-DBp2Nl87.js       250.38 kB │ gzip: 79.11 kB │ map: 975.53 kB
  ✓ built in 2.33s
  ...
    160 passed (1.2m)
  ```
  (baseline 149 desk specs; 11 new: scanner 5, trace 4, day 2.) The new specs, from the same run:
  ```
  ✓ autodesk-scanner.spec.ts:335 › AD-FX-20 a BLOCKED cycle lists the pre-market checks that failed or ran degraded, with their detail (427ms)
  ✓ autodesk-scanner.spec.ts:357 › AD-FX-15/21 after a blocked cycle Run session cycle opens a new attempt; no "already ran"; the old cycle is kept (2.9s)
  ✓ autodesk-scanner.spec.ts:389 › AD-FX-16/21 a request answered with a blocked, scan-less cycle says why, not "already ran"; a new attempt that is blocked again shows its own checks (3.0s)
  ✓ autodesk-scanner.spec.ts:423 › AD-FX-22 a pre-market check that did not complete: its reason is shown as written (522ms)
  ✓ autodesk-scanner.spec.ts:433 › AD-FX-23 a DEGRADED pre-market is a note on a cycle that ran; a clean one shows no panel (668ms)
  ✓ autodesk-studio-day.spec.ts:317 › AD-FX-33 approval rows of the feed link to the plan's page; other rows and folded rows do not (577ms)
  ✓ autodesk-studio-day.spec.ts:332 › AD-FX-44 the timeline is read from its first event: every request carries after_seq (393ms)
  ✓ autodesk-studio-trace.spec.ts:235 › AD-FX-30 each card that made a plan links to the plan's page via its newest approval row; no plan, no link (360ms)
  ✓ autodesk-studio-trace.spec.ts:253 › AD-FX-31 the link opens the plan's page in the desk, labelled as a simulation's (444ms)
  ✓ autodesk-studio-trace.spec.ts:262 › AD-FX-32 the finished chain's outcome box carries the same link (687ms)
  ✓ autodesk-studio-trace.spec.ts:274 › AD-FX-34 a failed approvals lookup is shown; the cards and the replay still work and no link is guessed (3.7s)
  ```
  The API in these specs is a route mock (labelled MOCK in the fixtures; bodies copy the real API's shapes). Two screenshots
  (scanner blocked panel, trace links) were looked at once for layout; they are not stored in the repo.
  Result: PASS.

## Data Correctness (staging)
**NOT RUN.** The branch is not deployed, so no real data was read. The new rules were exercised only on crafted market data
(FrozenMarketView / a fake data API). See UNVERIFIED.

## UNVERIFIED (what, why, what is needed)
- **Real data landing times.** The 19:00:04 IST (cash) and 22:15:21 IST (F&O) loads are quoted from the task and from the 5 Nov
  walk-through report; I did not query `nidp.v_feed_status` this turn. Needed: that query, and one real cycle after ~19:30 IST (cash)
  and after ~22:45 IST (F&O).
- **Real calendar in `PitMarketView.previous_session`.** Tested with holidays installed via `calendar.set_holidays`; the real
  holiday list from the data platform was not exercised. Needed: a staging run of a desk cycle after deploy.
- **Staging end-to-end** (AD-83-style cycle, a simulation run, then "Open full plan" from the real Agent trace) — needs a deploy
  (backend process restart + frontend image rebuild) and the owner's signed-in session.
- **Concurrent requests** for the same account/session: attempt keys are decided under a Postgres advisory lock inside the
  transaction; a concurrent-request test was not written.
- **Browser behaviour is on a mock.** The scanner panel and the studio links render and behave as specified against mocked API
  bodies; with the real API the same shapes are expected (the backend tests assert them), not observed.
- **Simulations on real data after F1/F2.** Unit/integration tests prove the replay is unchanged (AD-70..77); a replay on staging
  data (AD-76 style) was not re-run.

## Design choices (for review)
- F1: constants changed in `market/view.py` (single source); docs/tests/fixtures that named 18:30/19:30 updated.
- F2: new `previous_session(day)` on the market view (calendar only, no data read, recorded as a tool call; Tech Support's tool list
  has it). F&O must equal the previous session (so F&O newer than it, e.g. a past `session_date`, is also DEGRADED); cash must be at
  least that day. Unknown previous session → cash BLOCKED, F&O DEGRADED. Tech Support's `VERSION` stays `autodesk-ts-v1` (not bumped).
- F3: first attempt keeps `{account}:{session}:cycle`; later attempts `…:attempt-2`, `-3` (and `input.attempt`). Re-attempt only when the
  newest cycle is BLOCKED with no `scan` and no `proposals`. Explicit keys (simulations; the API's second call that passes the key
  it got back) are never re-attempted.
- F4: panel on the scanner shows checks with status BLOCKED/DEGRADED (plain names: Cash end-of-day data, F&O end-of-day data, India VIX,
  Desk database) and the report's `reason`; also a "ran degraded" note for DEGRADED cycles.
- F5: link beside each Agent trace card + in the chain's outcome box; approval resolved per visible card with
  `GET /approvals?simulation_id=&trade_id=&limit=20` (newest row); Trading day feed rows of APPROVAL_* events use their own approval id.
  No new backend endpoint.
- F6: `/desk/workflows` newest first (the two UI consumers sort for themselves). `/events` and `/timeline`: `after_seq` is now optional;
  absent = the newest `limit` rows (ascending), present (0 included) = the next `limit` rows after the cursor (as before). The UI
  always sends `after_seq`, so it still reads a run from its first event.
- Noted, not changed: `GET /simulations/{id}/workflows` still returns the oldest 1000 (same class of problem for runs with more than
  1000 workflows); the Trace and Run-history views read it.

## Inputs required from user
none

## Verdict: PASS
