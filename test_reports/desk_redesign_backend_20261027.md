# Functionality Verification Report: four read-only routes for the desk redesign

- **Branch:** feat/desk-redesign-backend (from origin/dev c882e64c)
- **Date:** 2026-10-27
- **Author:** Claude (full stack developer + QA)
- **Environment:** unit and route tests in the `nivesh/backend:staging` image with `--network none`. The branch's
  handlers were also run against staging's real data, inside the staging backend container, read-only. They are not
  deployed, so no HTTP call to staging has been made (see the OVERRIDE).
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
Four routes from `docs/desk_redesign_20261027/PLAN.md` §2c, "Small backend additions v1 needs". Each one is read-only,
needs a signed-in user, and is scoped to that user:

| Route | Code |
|---|---|
| `GET /api/desk/idea-scorecard` | `services/idea_scorecard.py`. Serves the committed `research/p4_adx_rs/results_20261027/result.json` as it is. Answers 503 with the reason when the file is missing, incomplete or no longer supports the fixed verdict. |
| `GET /api/desk/exit-job-status` | `services/job_runs.trader_status`. Gives `ok | running | late | missed` by the admin route's own `health()`, plus the session last checked. |
| `GET /api/desk/paper-account/corrections` | `services/paper_reconcile.corrections`. The user's `adjust` ledger rows, with the decision, the reason, the date and whether each is in force. |
| `GET /api/risk/freshness?symbol=` | `routes/risk_controls.freshness`. Judges the inputs with `risk_service.last_close_freshness / sector_freshness / market_freshness`, which `gather()` and `decide()` now call too; their behaviour is unchanged. |

`GET /api/desk/paper-trades` is untouched and is not called: it applies exits.

## Test Cases
Authored first: `test_reports/desk_redesign_backend_TESTCASES.md` (commit d2795a42, before the implementation commit
1096531c). Tests: `backend/tests/test_desk_redesign_routes.py`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| SC-1 | scorecard | committed study, every split and arm | api | values equal the file; B0 test −0.00992; A2 test Δ 0.0122 t 3.18 p 0.007 | PASS |
| SC-2 | scorecard | B0 Δ and permutation p | unit | null | PASS |
| SC-3 | scorecard | verdict, RS63 status, wording | unit | the fixed sentences; no pick, recommend or suggest outside the disclaimer | PASS |
| SC-4 | scorecard | sources | unit | sha256 of the bytes on disk | PASS |
| SC-5 | scorecard | `result.json` missing | failure | 503 `scorecard_unavailable` with the path | PASS |
| SC-6 | scorecard | not JSON, no test split, no B0 | failure | 503 with the reason | PASS |
| SC-7 | scorecard | the file adopts an arm, or B0 t ≥ 2 | failure | 503 `scorecard_out_of_date` | PASS |
| SC-8 | scorecard | documents missing | edge | 200, `present: false` | PASS (also seen on staging) |
| EX-1…EX-6 | exit job | ok, late, missed, never run, running, failed | unit+api | ok, late, missed, missed, running, missed | PASS |
| EX-7 | exit job | agreement with the admin route | unit | same `state` in all six cases | PASS (also on staging: both `never_run`) |
| EX-8 | exit job | allow-list projection | unit | only started_at, finished_at, status, session | PASS |
| CO-1…CO-4 | corrections | decisions, reverts, isolation, projection, empty | api+edge | as stated | PASS |
| FR-1…FR-6 | freshness | fresh, one session old, stale, unreadable, no symbol, bad symbol | api+edge | as stated | PASS |
| FR-7 | freshness | agreement with `gather()`/`decide()` | unit | field-by-field equal in 3 variants | PASS (also on staging: all three True) |
| ALL-1 | all | signed out | edge | 401 and no database call | PASS |
| ALL-2 | all | read-only | unit | the fake raises on any write; none was made | PASS |
| ALL-3 | regression | existing risk, desk, job and reconcile suites | regression | unchanged | PASS (407 passed) |
| ALL-4 | regression | full CI allowlist, branch vs dev | regression | the same 3 network-only failures | PASS |
| STG-1 | staging data | the branch's handlers on staging rows, read-only | data | real rows read, nothing written | PASS (in the container; HTTP after deploy: see OVERRIDE) |

## API / Endpoint Tests (staging)
**Not run over HTTP: the routes are not deployed until the PR is merged.** Instead, the branch's six changed modules
were loaded by path into a one-off Python process inside `nivesh-staging-app-backend`. Nothing in `/app` was changed.
The four route handlers were then called against staging's real Mongo and data platform. Every Mongo collection was
wrapped so that any write raises. The session user was set to the one account with corrections; the hash is printed,
not the id. Trade ids are shortened to 8 characters. The script was deleted from the container afterwards.

- Command: `sudo docker cp …/desk_check nivesh-staging-app-backend:/tmp/desk_check && sudo docker exec -w /app/backend nivesh-staging-app-backend python /tmp/desk_check/check.py`
- Output (real, abridged only where marked `[…]`):
```
now (UTC): 2026-10-27T11:14:17.545778+00:00
users with adjust rows: ['a5530afb'] | paper accounts: ['a5530afb']

===== GET /api/desk/idea-scorecard (abridged: study, decision, rs63, sources, test split B0/A2)
 "study": {"id": "p4_adx_rs", "phase": "4.3", […] "run_date": "2026-10-27", "registration_commit": "4c408401",
  "code_sha": "4c408401+run_study(uncommitted)", "signal_dates": 385, "sessions": 634,
  "input_hash": "65483cfc3d3d077b65ab3cbcb0dee2caf65b72bce169e584840d3c34ff473365", "bar_rows": 1098819, […]}
 "decision": {"verdict": "keep B0; the current ranking shows no measurable skill",
  "study_verdict": "keep B0 (no arm met every pre-registered condition)", "adopted": null}
 "rs63": {"arm": "A2", […] "status": "promising, awaiting its pre-registered confirmation", "adopted": false, […]}
 "sources": [{"path": "research/p4_adx_rs/results_20261027/result.json", […] "present": true,
   "sha256": "4b3eff97d09f854397fe4ca11a0895d159920b3ce093d6063b2b9d6d6426ebd8", "bytes": 7927, "reason": null},
  {"path": "docs/ai_research/P4_ADX_RS_PREREGISTRATION.md", […] "present": false, "sha256": null, "bytes": null,
   "reason": "not readable here (FileNotFoundError)"}, […the other two docs: the same…]
 "test.B0": {"arm": "B0", […] "rank_ic": {"mean": 0.0075, "nw_t": 0.41, "se": 0.0182, "n": 81}, "vs_b0": null,
  "permutation_p": null, "top_decile_net_mean": -0.00992, "top_decile_hit_rate": 0.4494, "top_minus_median": 0.00555}
 "test.A2": {[…] "rank_ic": {"mean": 0.0197, "nw_t": 0.98, […]}, "vs_b0": {"delta_ic": 0.0122, "nw_t": 3.18, "se": 0.0038,
  "n": 81, "permutation_p": 0.007, "by_regime": {"up": {"n": 0, "delta_ic": null, "nw_t": null},
  "down": {"n": 81, "delta_ic": 0.0122, "nw_t": 3.18}}}, […] "top_decile_net_mean": -0.00885, "top_decile_hit_rate": 0.4572, […]}
 "coverage": {"discovery": {"top_movers_outside_universe": 0.6673, […]}, "validation": {[…] 0.7741 […]},
  "test": {[…] 0.7331 […]}}

===== GET /api/desk/exit-job-status
 "job": "check_desk_alerts", "status": "missed", "state": "never_run",
 "message": "No evening exit check has been recorded.", "last_checked": null, "latest_run": null,
 "expected_since": "2026-10-26T17:15:00+00:00", "schedule": "Mon–Fri 20:45 IST, retry 22:45 IST", "grace_minutes": 60, […]
admin route state for the same job: never_run | healthy: False

===== GET /api/desk/paper-account/corrections (user a5530afb; ids shortened)
 {"id": "reconcile:closed_pnl_missing:089db966…", "at": "2026-10-27T01:22:00.199891+00:00", "reason_code": "closed_pnl_missing",
  "reason": "A closed trade had no P&L on record", "decision": "void", "kind": "owner_decision", "symbol": "NIFTY",
  "cash_delta_rs": 0.0, […] "in_force": true, "run_id": "phase0-reconcile-20261027", "actor": "reconcile"}
 {"id": "reconcile:closed_pnl_not_in_cash:38865edc…", […] "decision": "exclude", […] "symbol": "FIXA", […] "in_force": true, […]}
 {"id": "reconcile:open_trade_unreserved:ffa3904e…", […] "decision": null, "kind": "proposed", "symbol": "ICICIBANK",
  "blocked_delta_rs": 124617.8, […] "in_force": true, […]}
 {"id": "reconcile:closed_pnl_not_in_cash:ef61108b…", […] "decision": "exclude", […] "symbol": "NORTHARC", […]}
 "count": 4, "truncated": false,
 "counts": {"in_force": 4, "excluded": 2, "voided": 1, "reverted": 0,
  "by_reason_code": {"closed_pnl_missing": 1, "closed_pnl_not_in_cash": 2, "open_trade_unreserved": 1}}, […]

===== GET /api/risk/freshness
 "market_state": {"source": "macro_engine.classify_desk_regime (services/strategy_plan/regime_fit.read_regime)",
  "as_of": "2026-10-26", "age_sessions": 0, "budget": 2, "ok": true, "reason": null, […] "status": "ok",
  "regime": "BEAR", "vix": 17.16, "key": "mixed"},
 "last_close": {"status": "not_checked", […]}, "sector": {"status": "not_checked", […]},
 "all_ok": true, "reference_session": "2026-10-26", […]

===== GET /api/risk/freshness?symbol=INFY
 "market_state": {[…] "as_of": "2026-10-26", "age_sessions": 0, "budget": 2, "ok": true, […] "regime": "BEAR", "vix": 17.16 […]},
 "last_close": {"source": "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform)",
  "as_of": "2026-10-26", "age_sessions": 0, "budget": 2, "ok": true, […] "status": "ok", "value": 1166.0},
 "sector": {"source": "NSE industry classification, nidp.index_constituents (DaaS /v1/indices/{index}/constituents), Nifty Total Market",
  "as_of": "2026-10-22", "age_sessions": null, "budget": null, "ok": true, […] "status": "ok", "value": "Information Technology"},
 "all_ok": true, "reference_session": "2026-10-26", […]

agreement with gather()/decide() at 2026-10-27T11:14:17.568595+00:00 : last_close True | sector True | market True

Mongo reads made (collection, op, filter keys, projection keys):
   ('job_runs', 'find', ['job'], ['finished_at', 'session', 'started_at', 'status'])
   ('job_runs', 'find', ['job', 'status'], ['finished_at', 'session', 'started_at', 'status'])
   ('job_runs', 'find', ['job'], None)                 <- the ADMIN read_health, called only for the comparison
   ('job_runs', 'find', ['job', 'status'], None)       <- the same
   ('paper_account_ledger', 'find', ['action', 'user_id'], ['_id', 'action', 'actor', 'at', 'blocked_delta_rs', 'cash_delta_rs', 'note', 'reason_code', 'reverts', 'run_id', 'symbol', 'trade_id'])
write guard: WRITE BLOCKED: insert_one on paper_account_ledger
```
(The two `<-` notes are added here; they are not script output.) The `gather()` agreement run stubbed the book and
the controls, because `risk_book.read` can write the equity peak. The market, last close and sector reads were real.

- **pytest (new tests):** `sudo docker run --rm --network none -v /home/deploy/nivesh-desk-backend:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_desk_redesign_routes.py -q -p no:cacheprovider`
  - Output: `43 passed, 2 warnings in 6.74s`
- **pytest (existing suites the change touches):** `… python -m pytest tests/test_risk_service.py tests/test_risk_gate.py tests/test_risk_gate_ai_trader.py tests/test_risk_gate_desk_journal.py tests/test_risk_routes.py tests/test_risk_route_inventory.py tests/test_risk_entry_paths.py tests/test_risk_replay.py tests/test_desk_exit_job.py tests/test_paper_reconcile.py tests/test_desk_trading.py tests/test_paper_account.py -q -p no:cacheprovider`
  - Output: `407 passed, 2 warnings in 18.90s`
- **pytest (full CI allowlist, the file list in `.github/workflows/backend-tests.yml`):**
  - branch (248 files): `3 failed, 6563 passed, 28 skipped, 15 warnings in 206.38s (0:03:26)`
  - origin/dev c882e64c (247 files, from `git archive`): `3 failed, 6520 passed, 28 skipped, 15 warnings in 208.96s (0:03:28)`
  - Both fail the same three: `test_cas_api_client.py::test_sandbox_parse_and_map`, `::test_convenience_helper_returns_list`
    ("Sandbox call failed — check network / keys") and `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`
    ("Cannot connect to host www.nseindia.com:443 … Temporary failure in name resolution"). These are network-only
    under `--network none`. The difference, 6563 − 6520 = 43, is the new file.
- **Mutation check:** each mutant was run on a scratch copy against `tests/test_desk_redesign_routes.py`:
```
MUTANT market_budget_3 -> 4 failed, 39 passed, 2 warnings in 7.75s
MUTANT no_late -> 2 failed, 41 passed, 2 warnings in 7.02s
MUTANT corrections_all_users -> 3 failed, 40 passed, 2 warnings in 6.93s
MUTANT scorecard_no_text_guard -> 4 failed, 39 passed, 2 warnings in 7.50s
MUTANT exit_reads_error -> 1 failed, 42 passed, 2 warnings in 6.80s
```

## UI / Playwright Tests
Not applicable: no frontend file changed.

## Data Correctness (staging)
- **Scorecard:** staging's backend container mounts `/app/research`, so `result.json` is there and its sha256
  `4b3eff97…6ebd8` is served. `docs/` is not mounted, so the three write-ups show `present: false` with the reason.
  The prod compose (`deploy/nivesh-app`) mounts neither. There the route would answer 503 `scorecard_unavailable`,
  the same way `/api/ai-trader` answers 503 without `research/`.
- **Exit job:** staging's `job_runs` holds no `check_desk_alerts` run, so the admin rule says `never_run`. The
  trader route says `missed`: "No evening exit check has been recorded." This is a real staging finding, not a test
  artefact. The heartbeat code is on dev, but staging has recorded no run under it.
- **Corrections:** 4 real `adjust` rows from run `phase0-reconcile-20261027` (2026-10-27 01:22 UTC): 2 `exclude`,
  1 `void`, 1 proposed reservation (ICICIBANK, blocked +124,617.80); none reverted.
- **Regime:** at 2026-10-27 11:14 UTC, `market_state()` reads the regime **as of 2026-10-26** (BEAR, VIX 17.16).
  That is age 0 against the reference session 2026-10-26, within the budget of 2. A direct read-only check gave the
  same date: `macro_engine.latest_state()` has `date: 2026-10-26` and `read_regime()` has `as_of: 2026-10-26`. The
  earlier observation that it read 2026-10-23 no longer holds at this time. The route reports whatever
  `market_state()` returns, so it shows the older date whenever the ingest lags. FR-2 covers exactly that case
  (Friday 23 Oct seen on Tuesday 27 Oct: age 1, budget 2, ok). The macro ingest was not changed.

## Inputs required from user
- none for this report. HTTP verification on staging needs the PR merged and deployed, then a signed-in session.

## Verdict: BLOCKED
Every unit, route and regression case passed, and the logic was checked against staging's real data. The staging HTTP
check waits for the merge and deploy; see `test_reports/OVERRIDE_desk_redesign_backend.md`.
