# Functionality Verification Report — Strategy Copilot Phase 0 (run access, failed runs, one 4-leg limit)

- **Branches / PRs (base dev):**
  - 0.1 `fix/strategy-run-access` a18c6b0f → **#390**;
  - 0.2 `fix/strategy-run-failed-status` 53f72ede → **#391**;
  - 0.3 `fix/strategy-max-legs` 6d69cd52 → **#392**.
  - 0.1 and 0.2 come from dev 48556220; 0.3 from dev 5d5466c1.
- **Worktree:** /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-28 (test cases written 05:28 IST, before implementation; results filled 06:15 IST)
- **Author:** Claude (Full stack developer + QA)
- **Environment:** unit tests in the `nivesh/backend:staging` image (`--network none`); staging data read-only. Staging
  API checks need the PRs merged (a merge to dev deploys).
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
Three PRD release blockers (§19.2) in the existing Strategy Builder. None changes a screen.
- **0.1 Cross-user run access.** `GET /api/strategy-builder/runs/{run_id}` returned any run of a public template, with its trade
  ledger, to any signed-in user. Now:
  - the user who triggered the run can read it;
  - the owner of a private strategy can read its runs, and system runs;
  - everyone else gets the same 404 as for a run that does not exist, and the denial is audited;
  - a malformed id gets 404 instead of a 500.
- **0.2 Failed runs.** A no-data window was stored as `'OK'`, and an engine error stored no row at all. Now:
  - both are stored as `FAILED` with an `error_message`;
  - HTTP answers are unchanged;
  - the response gains `status` and `error`.
- **0.3 One 4-leg limit.** `services/strategy_limits.MAX_STRATEGY_LEGS = 4`:
  - the paper desk and the risk-gate default read it; values are unchanged;
  - the payoff (8) and margin (10) calculators stay analysis limits, so 5–8-leg analyses don't regress.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | 0.1 | Owner reads a run of their own private strategy | unit (route) | 200, run + trades | PASS |
| TC-2 | 0.1 | Another user reads that run | edge/unauthorized | 404 "run not found" (was 403); denial audited | PASS |
| TC-3 | 0.1 | User B reads B's own run of user A's public template | unit | 200 | PASS |
| TC-4 | 0.1 | User C reads B's run of A's public template | edge/unauthorized | 404 (was **200, the leak**); audited | PASS |
| TC-5 | 0.1 | Template owner A reads B's run of A's template | edge | 404 (was 200) | PASS |
| TC-6 | 0.1 | Template owner A reads A's own run of the template | unit | 200 | PASS |
| TC-7 | 0.1 | System run (`triggered_by` NULL) on a private strategy: owner / other | unit/edge | 200 / 404 | PASS |
| TC-8 | 0.1 | Malformed run id ("not-a-uuid") | edge/wrong-type | 404, not a 500 (asyncpg `DataError` answered as not found). Revised during implementation from "no database query": a pre-check would have broken the existing `test_tc_rp3_get_run_returns_provenance_for_an_old_run`, whose fixture id is "run-1" | PASS |
| TC-9 | 0.1 | Unknown run id (valid UUID) | edge | 404, same body as a refusal; not audited | PASS |
| TC-10 | 0.1 | No session | unauthorized | 401, no query | PASS |
| TC-11 | 0.2 | No-data result → stored row | unit (persist) | `FAILED` + "no_data…"; metrics still param 6, watermark still last | PASS |
| TC-12 | 0.2 | Normal result → stored row | unit (persist) | `OK`, error NULL | PASS |
| TC-13 | 0.2 | Route answer for a no-data window | unit (route) | 200, `status: "FAILED"`, `metrics.reason == "no_data"` kept (+ TC-13b: normal run `status: "OK"`) | PASS |
| TC-14 | 0.2 | Engine raises ValueError / CompileError | failure | FAILED row with the error text; 400 with the same detail as before | PASS |
| TC-15 | 0.2 | Engine raises an unexpected error | failure | FAILED row; 500 naming the recorded run | PASS |
| TC-16 | 0.2 | Recording the FAILED row fails too | failure | original 400 still answered; failure logged at ERROR | PASS |
| TC-17 | all | Regression: the Strategy Lab backend baseline + new tests, per branch and combined | regression | 0 failed; no existing test edited | PASS |
| TC-18 | 0.1 | Staging after merge: A's own run 200; B reading it 404; malformed id 404 | api (staging) | as stated | **PARTIAL**: A's own run 200 PASS; malformed id 404 PASS; **B reading A's run PENDING** (needs a second user's session token) |
| TC-19 | 0.2 | Staging after merge: no-data window → `status: FAILED` and a FAILED row | api + data (staging) | as stated | PASS |
| TC-20 | data | Staging today: stored runs readable by someone other than their trigger/owner | data (staging) | count | PASS (0 exposed; see below) |
| TC-21 | 0.3 | `MAX_STRATEGY_LEGS = 4`, min 1 | unit | 4 / 1 | PASS |
| TC-22 | 0.3 | Paper desk and risk-gate default ARE the constant; `POLICY_VERSION` unchanged | unit | identity holds; `fno-risk-v1` | PASS |
| TC-23 | 0.3 | Payoff (8) / margin (10) ≥ 4 and unchanged | unit/regression | holds | PASS |
| TC-24 | 0.3 | Five legs still refused by paper desk and risk gate (existing tests, unedited) | regression | pass | PASS |

## API / Endpoint Tests (staging)
**Merged 2026-10-28 ~07:10 IST on the owner's "Please merge the PR's":** #390 → db459a69, #391 → 81c90937, #392 → 3a94da9b
(dev = 3a94da9b). The backend deploy run is 40616431295 for 3a94da9b.

TC-18 and TC-19 still need two signed-in staging users (session tokens); see `test_reports/OVERRIDE_strategy_phase0_runs.md`.
The post-deploy checks that need no token are below.

- Deploy: GitHub run 40616431295 "Deploy backend → CloudPe app VM [staging]" for 3a94da9b, `completed success` at 07:11:52 IST.
- The running process has the merged code:
  - `/opt/nivesh-staging/repo` is at `3a94da9b Merge pull request #392`;
  - in the container, `grep -c _can_read_run routes/strategy_builder.py` = 2, `persist_failed_run` is in `services/strategy_engine/backtest.py`, `MAX_STRATEGY_LEGS` is in `services/risk_gate/policy.py`, and `services/strategy_limits.py` exists;
  - file mtimes (01:40:17 and 01:41:04 UTC) are before the container start `2026-10-28T01:41:15Z`.
- `curl https://staging.niveshcopilot.com/api/healthz` → `200`.
- `curl https://staging.niveshcopilot.com/api/strategy-builder/runs/00000000-0000-4000-8000-000000000000` (no session) →
  `{"status":401,"error":"UNAUTHORIZED","code":"AUTH-001","message":"Not authenticated",…}` `401`. Authentication still runs first, unchanged.
- **Live run with the owner's session** (07:18:49 IST; token supplied by the owner in chat, stored in a mode-600 file, never printed, deleted after the run). Command `python3 -I staging_phase0_check.py`, real output:
  ```
  session A valid: 200 (user id not printed)
  create strategy (A): 200 {'id': '17d330d9-11b8-4b34-8532-d623e5d92501', 'strategy_id': None, 'version_no': None}
  TC-19 backtest no-data window (A): 200 {'run_id': 'c92d2f56-2cd7-4113-af13-be35b9718f17', 'status': 'FAILED', 'error': 'no_data: the window has no sessions with data to run on'} metrics.reason = no_data
  TC-18 read own run (A): 200 run.status = FAILED error_message = no_data: the window has no sessions with data to run on
  TC-18 read A's run (B): SKIPPED — no second user's session token
  TC-18 malformed id (A): 404 {'timestamp': '2026-10-28T01:48:50Z', 'status': 404, 'error': 'NOT_FOUND', 'code': 'RES-001', 'message': 'run not found', 'details': [], 'correlationId': 'c89f6c6ef19447d798c8c614ad3dd00a', 'path': '/api/strategy-builder/runs/not-a-uuid'}
  #392 risk policy (A): 200 fno-risk-v1 max_legs = 4
  archive test strategy (A): 200
  ```
- **Data (TC-19), app DB `portfolio_ingestion`, read-only:**
  ```
  id                                   | status | error_message                                           | backtest_from | backtest_to | trig_is_owner | is_archived | is_public_template | same_user_as_test_run
  bb3d0a32-…  | OK     |                                                         | 2026-04-20 | 2026-10-20 | t | f | f | t
  b2f50576-…  | OK     |                                                         | 2026-06-01 | 2026-09-18 | t | f | f | t
  9e64e0ef-…  | OK     |                                                         | 2026-04-21 | 2026-10-21 | t | f | f | t
  c92d2f56-…  | FAILED | no_data: the window has no sessions with data to run on | 2023-01-02 | 2023-01-31 | t | t | f | t
  ```
  - The new run is stored as FAILED with its reason, and the test strategy is archived. The 3 older runs are unchanged.
  - All 4 runs belong to the owner, so the cross-user read cannot be done with existing data. It needs a second user to `GET /api/strategy-builder/runs/c92d2f56-2cd7-4113-af13-be35b9718f17` (expected 404 "run not found", plus an `audit_log` row with action `strategy_run_view` and outcome `denied`).
- The script (scratchpad `prs/staging_phase0_check.py`) reads `tokens/a.txt` / `tokens/b.txt` and never prints them. It reads `tokens/a.txt` and `tokens/b.txt` and never prints them.
  - It creates one "phase0-verification" strategy for A and backtests 2023-01 (no data) → FAILED.
  - It then reads that run as A, as B and with a malformed id, and reads `/api/risk/policy`.
  - Finally it archives the strategy.

- **pytest** — all runs in `sudo docker run --rm --network none -v <tree>:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest <files> -q -p no:cacheprovider`:

| Tree | Files | Output |
|---|---|---|
| dev 48556220 (baseline, untouched) | 38 | `1701 passed, 3 warnings in 96.93s` |
| 0.1 branch (+ test_strategy_run_access) | 39 | `1711 passed, 3 warnings in 111.60s` |
| 0.1 branch, `services.audit` users (test_strategy_run_access, test_broker_native_routes) | 2 | `144 passed, 2 warnings in 9.50s` |
| 0.2 branch (+ test_strategy_failed_runs) | 39 | `1709 passed, 3 warnings in 105.07s` |
| 0.1 / 0.2 branch: test_liquid_universe | 1 | `20 passed` / `20 passed` |
| 0.1 + 0.2 merged (merge-tree 83b1d1d9), 40 + 2 files | 42 | `1873 passed, 3 warnings in 244.37s` |
| 0.3 branch on dev 5d5466c1 (+ test_strategy_leg_limit, risk_routes, risk_gate_*, fno_quotes, liquid_universe) | 44 | `1806 passed, 3 warnings in 139.19s` |
| 0.1 + 0.2 + 0.3 combined (tree 288cd722) | 44 | `1921 passed, 3 warnings in 143.25s` |

- **CI ("Backend unit tests (allowlist)", the full allowlist of about 6,800 tests on the PR merge with dev):**
  - **#391: success.**
  - **#390: success on the re-run** (job 122561433727, finished 06:18 IST).
    - The first run (job 122557300859) failed on one test outside this change: `tests/test_symbol_lookup.py::test_warm_search_is_fast_on_a_large_universe` is a timing assertion, `AssertionError: slowest query took 408 ms` against 150 ms on the CI runner. That run ended `1 failed, 6791 passed, 28 skipped`.
    - #390 changes no symbol-lookup file, and the test passes on the 0.1 branch locally (`37 passed` for test_symbol_lookup.py).
    - The token cannot re-run a job (403), so the PR was closed and reopened at 06:15 IST to trigger the new run.
  - **#392: success** (job 122560184330).
  - Final check on the combined tree from the three pushed heads (a18c6b0f, 53f72ede, 6d69cd52): the 3 new test files plus test_backtest_provenance, test_strategy_config, test_risk_gate and test_desk_strategy_trades gave `217 passed, 2 warnings in 11.93s`.
- `test_nidp_admin_iter58.py` (also imports this router) cannot be collected on untouched dev either (`RuntimeError: REACT_APP_BACKEND_URL not configured`; it is a live-server test). It is not a regression.

## UI / Playwright Tests
No frontend file changed in any of the three PRs.

The frontend Strategy Lab baseline was measured for the "no regression" floor of later phases. It ran 9 specs on dev 48556220 in the Playwright container: **271 tests, 252 passed, 3 failed, 16 skipped, 0 flaky**.
- All 3 failures are pre-existing, in `copilot-app-desk-strategy-ideas.spec.ts`:
  - SI-6 expects view "new" where the desk now uses "lab";
  - SI-7 and SI-7b look for test ids that no longer exist after the desk redesign;
  - each failed 3 of 3 times alone.
- The 16 skips are screenshot-only cases.
- Details: `docs/strategy_copilot_review_20261028/baseline_frontend_20261028.md`.

## Data Correctness (staging)
- The app backend's Postgres is the `nivesh-staging-postgres` container, database `portfolio_ingestion`, read via `POSTGRES_URL`; host and db name only were printed. It is not the NIDP warehouse, whose `public.strategy_runs` holds 0 rows.
- Read-only query, run in that container as its own user:
  ```
  SELECT r.status, s.is_public_template, (r.triggered_by IS NULL) AS system_run,
         (r.triggered_by IS NOT NULL AND r.triggered_by <> s.owner_id) AS triggered_by_non_owner,
         count(*) AS runs, count(DISTINCT r.triggered_by) AS triggerers, max(r.started_at)::date AS latest
    FROM public.strategy_runs r JOIN public.strategies s ON s.id = r.strategy_id GROUP BY 1,2,3,4;
   status | is_public_template | system_run | triggered_by_non_owner | runs | triggerers |   latest
   OK     | f                  | f          | f                      |    3 |          1 | 2026-10-21
  SELECT count(*) FROM public.strategy_runs WHERE status='OK' AND metrics->>'reason'='no_data';   →  0
  SELECT count(*) FROM public.strategies WHERE is_public_template;                               →  0
  ```
- Result: PASS (TC-20). Nothing is exposed on staging today: 3 runs, all private and all run by their owner, and no public templates. The leak would fire as soon as a template is promoted. No existing row is mislabelled OK, so no data fix is needed.
- `GET /api/risk/policy` after #392 merges should still answer `fno-risk-v1` with `max_legs: 4`. That is pending with TC-18.

## Inputs required from user
- The owner's merge of #390, #391 and #392. I cannot merge my own PRs without a per-PR go-ahead.
- Two staging session tokens: the owner's and a second test user's. They are for TC-18 (cross-user 404) and TC-19 (FAILED run). Alternatively, the owner's permission to create a disposable second test user on staging.

## Verdict: BLOCKED
