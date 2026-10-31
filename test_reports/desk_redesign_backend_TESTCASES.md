# Test cases: four read-only backend routes for the desk redesign (2026-10-27)

Written before the implementation. Scope: `docs/desk_redesign_20261027/PLAN.md` §2c, "Small backend additions v1
needs". Each route is read-only, needs a signed-in user, and answers only for that user.

## The contracts (designed first)

| Route | Answer | Fails how |
|---|---|---|
| `GET /api/desk/idea-scorecard` | The Phase 4.3 study as committed in `research/p4_adx_rs/results_20261027/result.json`:<br>– `study`: id, registration commit, code sha, run date, signal dates;<br>– `splits[]`: name, date range, dates, coverage, `arms[]`;<br>– each arm: rank IC with its Newey-West t, the Δ vs B0 with its t and one-sided permutation p (null for B0), top-decile net return and hit rate;<br>– `decision`: the verdict "keep B0; the current ranking shows no measurable skill", the study's own verdict string, the per-arm checks;<br>– `rs63`: "promising, awaiting its pre-registered confirmation";<br>– `sources[]`: path, sha256, bytes, present. | 503 `{code: scorecard_unavailable, reason}` when `result.json` is missing, unreadable or lacks a field. 503 `scorecard_out_of_date` when the file no longer supports the served text (an arm adopted, or a B0 t ≥ 2). Never a made-up number. |
| `GET /api/desk/exit-job-status` | `status`: ok, running, late or missed; `state` (the admin route's own state); the session of the last successful check and when it ran; `expected_since`; the schedule; a trader-facing `message`. | No heartbeat: `status: missed`, `state: never_run`, `last_checked: null`. |
| `GET /api/desk/paper-account/corrections` | The caller's own `adjust` ledger rows, newest first: id, date, reason code and label, the decision (`exclude`, `void`, …, or null), trade, symbol, cash and blocked deltas, note, `in_force`, `reverts`, `reverted_by`; and counts (`excluded`, `voided`, in force). | None: an account with no corrections gets an empty list. |
| `GET /api/risk/freshness?symbol=` | `reference_session`, and for `last_close` (needs a symbol), `sector` (needs a symbol) and `market_state`: as-of, age in sessions, budget, ok, `status` (ok, stale or unknown), reason, and the value read. These are the same records `risk_gate.service.gather()` / `decide()` build. | A bad symbol is 422 `invalid_symbol`. An unreadable source is `status: unknown` with the reason. Never a guessed date. |

## Test cases

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| SC-1 | scorecard | the committed study files | api | 200; 3 splits (discovery, validation, test) with the committed bounds; arms B0, A1, A2, A3; B0 test top-decile net −0.00992, A2 test Δ IC +0.0122 (t 3.18, p 0.007), the values exactly as in the file |
| SC-2 | scorecard | B0's Δ and permutation p | unit | null for B0 (it is the baseline), not 0 |
| SC-3 | scorecard | verdict and RS63 wording | unit | "keep B0; the current ranking shows no measurable skill"; "promising, awaiting its pre-registered confirmation"; the study's own string served as well; no "pick" or "recommend" in any served text except the disclaimer "not recommendations" |
| SC-4 | scorecard | sources | unit | each path with the sha256 of the bytes on disk (checked against hashlib); `result.json` present |
| SC-5 | scorecard | `result.json` missing | failure | 503, `code: scorecard_unavailable`, the reason names the path; no numbers |
| SC-6 | scorecard | `result.json` not JSON, or a split missing | failure | 503 with the reason |
| SC-7 | scorecard | the file adopts an arm, or a B0 t ≥ 2 | failure | 503 `scorecard_out_of_date` (the fixed verdict text would be false) |
| SC-8 | scorecard | a document missing (staging mounts `research/`, not `docs/`) | edge | 200; that source has `present: false`, `sha256: null`, and a reason |
| EX-1 | exit job | the newest run is ok and covers the latest slot | unit | `status: ok`, `last_checked.session` = the run's session |
| EX-2 | exit job | the 20:45 slot has passed, no run yet, within the 60-min grace | unit | `status: late`, admin state `ok` |
| EX-3 | exit job | no run since the slot, beyond the grace | unit | `status: missed`, state `missed` (the same `job_runs.health` the admin route calls) |
| EX-4 | exit job | no heartbeat at all | edge | `status: missed`, state `never_run`, `last_checked: null` |
| EX-5 | exit job | a run in progress | unit | `status: running` |
| EX-6 | exit job | the newest run failed with an internal error text | unit | `status: missed`, state `failed`; the stored error text is NOT in the answer |
| EX-7 | exit job | agreement with the admin route | unit | `state` equals `job_runs.read_health(...)["state"]` for the same rows and clock, in every case above |
| EX-8 | exit job | projection | unit | every Mongo read names an allow-list projection; `counts`, `error` and `exit_code` are never read |
| CO-1 | corrections | an `exclude`, a `void`, a reservation and a revert, for the caller | api | 4 rows newest first; decisions `exclude`, `void`, null, null; the reverted row `in_force: false` with `reverted_by`; counts `excluded: 1`, `voided: 1` |
| CO-2 | corrections | another user's rows and non-adjust rows (reserve, release) | edge | not listed |
| CO-3 | corrections | projection | unit | the ledger read uses an allow-list (no `user_id`, `snapshot`, `stamp`, `policy_version` in the answer) |
| CO-4 | corrections | no corrections | edge | 200, empty list, counts 0 |
| FR-1 | freshness | a symbol, all inputs fresh | api | 200; `last_close`, `sector`, `market_state` each `status: ok` with as-of, age, budget 2 (sector budget null) |
| FR-2 | freshness | market state as of Fri 2026-10-23, asked Tue 2026-10-27 (reference session Mon 26th) | unit | `as_of 2026-10-23`, `age_sessions 1`, `budget 2`, `ok` |
| FR-3 | freshness | market state 3 sessions old | unit | `status: stale`, the reason states the age and the budget |
| FR-4 | freshness | sources unreadable (bars error, no sector, regime unavailable) | failure | each `status: unknown` with the source's reason; nothing invented |
| FR-5 | freshness | no symbol | edge | `market_state` judged; `last_close` and `sector` `status: not_checked` |
| FR-6 | freshness | bad symbol `IN FY;` | edge | 422 `invalid_symbol` |
| FR-7 | freshness | agreement with the risk service | unit | for the same inputs and clock, the route's three records equal `gather()`'s `last_close_freshness` and `market.freshness` and `decide()`'s `freshness.sector`, field by field |
| ALL-1 | all four | signed out | edge | 401, no database read |
| ALL-2 | all four | read-only | unit | the database fake raises on any write call; none is made |
| ALL-3 | all | the existing risk tests after the `gather()` refactor | regression | `test_risk_service.py`, `test_risk_gate*.py`, `test_risk_routes.py` pass unchanged |
| ALL-4 | all | the full CI allowlist | regression | same failures as on dev, network-only (`test_cas_api_client` ×2, `test_nidp_stamp_broadcast_at`) |
| STG-1 | staging data | the logic against staging's real rows, read-only, inside the staging backend container | data | the scorecard loads from `/app/research`; the exit job reports the real heartbeat; corrections lists the real adjust rows; freshness reports the regime as of 2026-10-23 |

MOCK data: every unit and route test uses made-up users, trades, runs and prices, labelled `MOCK` in the test files.
The scorecard tests use the real committed `result.json` for SC-1, and temporary copies for the failure cases.
