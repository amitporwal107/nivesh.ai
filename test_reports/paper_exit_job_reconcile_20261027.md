# Functionality Verification Report — Evening exit job hardening + paper-account reconciliation

- **Branch:** `fix/paper-exit-job-reconcile` (off origin/dev 5b6b3cfd; commits 3574cca2, 9b05f1eb, 12c0524d)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in the `nivesh/backend:staging` image (network none); staging evidence is READ-ONLY
  (`nivesh-staging-app-backend`, branch code piped in memory, every Mongo write method replaced by one that raises)
- **Changed areas:** backend routes/services: yes (`routes/risk_controls.py` one GET route; `services/job_runs.py`,
  `services/paper_reconcile.py` new; `services/paper_account.py` one new function) · frontend src: no

## Summary
Phase 0 work items 0.7 (evening exit job) and 0.9 (paper-account reconciliation), prepared for owner-approved staging
changes; nothing was applied to staging. (1) `scripts/check_desk_alerts.py` gains a Mongo lease plus `flock -n` (duplicate-run
protection), `--require-bars` (no session → exit 3, session's bars not in → exit 2, F&O structures wait for the F&O
bhavcopy), a `job_runs` heartbeat with counts, `--skip-if-done` for the retry slot, and an admin read path
`GET /api/admin/risk/jobs/check_desk_alerts` that reports `missed` when no run was recorded since the latest slot.
(2) `scripts/reconcile_paper_accounts.py` computes four invariants per account, lists every discrepancy with
evidence, proposes only derivable corrections as additive `adjust` ledger rows (idempotency key per issue and trade),
marks the rest `needs_owner_decision` with options, and can apply, re-apply (no-op), revert (additive) and check.

## Test Cases
Authored up front in `test_reports/paper_exit_job_reconcile_TESTCASES.md` (commit 3574cca2, before the code).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| EJ-1 | exit job | two runs race; expired lease taken over, live one not | unit (concurrency) | one ok, one exit 4; each trade closed once | PASS |
| EJ-2 | exit job | one stale snapshot applied twice (cash, strategy) | unit (idempotency) | second matches nothing; one release per trade | PASS |
| EJ-3 | exit job | session's bars not in | failure | exit 2, zero desk writes, `skipped_no_bars` | PASS (unit) + PASS (staging read-only, S-2b) |
| EJ-4 | exit job | NSE holiday; holiday list unreadable | edge | exit 3 / exit 2, zero writes | PASS (unit) + PASS (staging read-only, S-2c) |
| EJ-5 | exit job | expected-session rule (6 cases) | unit | dates as stated | PASS |
| EJ-6 | exit job | good run | unit | heartbeat ok + counts | PASS |
| EJ-7 | exit job | no prices / DB error / DaaS down for the session check | failure | exit 1, heartbeat `failed` | PASS |
| EJ-8 | exit job | partial run, then retry | failure + recovery | partial → retry closes once → done | PASS |
| EJ-9 | exit job | `--skip-if-done` after ok | edge | exit 0, no bar read | PASS |
| EJ-10 | exit job | dry run | unit | no lease, no heartbeat, no writes | PASS (unit) + PASS (staging read-only, S-2a) |
| EJ-11 | read path | health states incl. weekend and grace | unit | never_run/ok/ok/missed/failed/… | PASS |
| EJ-12 | read path | admin route: 403 / 200 / 404 / never_run | api (in-process) | as stated | PASS in-process; **staging endpoint NOT RUN** (branch not deployed) |
| EJ-13 | cron | cron lines vs code schedule, guards | unit | match | PASS |
| EJ-14 | exit job | F&O strategy closed once; waits without F&O marks | unit | as stated | PASS |
| RC-1 | reconcile | open cash / strategy without reservation | unit | reserve qty×entry / exposure | PASS |
| RC-2 | reconcile | P&L not in cash (before account → decision; after → proposed) | unit | as stated | PASS |
| RC-3 | reconcile | strategy closed with P&L None | unit | decision: −91.55 / 0 | PASS (in RC-12) |
| RC-4 | reconcile | reservation on a closed trade / on no trade | unit | release proposed | PASS |
| RC-5 | reconcile | duplicates | unit | review only, no entries | PASS (in RC-12) |
| RC-6 | reconcile | dry run (service + CLI, text + JSON) | unit | zero writes | PASS |
| RC-7 | reconcile | apply; trade closed after the plan | unit | exactly the plan; skipped when closed | PASS |
| RC-8 | reconcile | apply twice; crash between account write and ledger row | unit (idempotency) | no second movement; row completed | PASS |
| RC-9 | reconcile | revert; revert twice; reservation whose trade closed | unit | account restored, originals kept; no-op; skipped | PASS |
| RC-10 | reconcile | planted cash and blocked mismatch; `--check` exit codes | unit | reported, no number; 2 then 0 | PASS |
| RC-11 | reconcile | no deletes on any path | unit | 0 deletes | PASS (asserted in RC-6/7/9) |
| RC-12 | reconcile | staging-shaped golden book | unit | the known discrepancy list | PASS |
| RC-13 | reconcile | `--decide`; bad decision refused by CLI | unit | as stated; exit 3, no writes | PASS |
| RC-14 | reconcile | output hashes user ids | unit | raw id absent | PASS (in RC-6) |
| S-1 | staging | `reconcile_paper_accounts --dry-run` (+ two decision previews, `--check`) | data (read-only) | real list, counts unchanged | PASS |
| S-2 | staging | `check_desk_alerts --dry-run --require-bars` (+ 3 fixed-clock scenarios) | data (read-only) | readiness + counts, unchanged | PASS |
| REG | regression | 11 suites | unit | all pass | PASS |
| TP | staging | the staging-only test position (owner requirement) | e2e | job closes it once | **NOT RUN** — needs owner approval and a test user (approval pack) |

## API / Endpoint Tests (staging)
- **Endpoint:** `GET /api/admin/risk/jobs/check_desk_alerts` — **NOT RUN on staging.** The branch is not deployed and
  this fix group's rules forbid a deploy, a restart or any staging write. Verified in-process only (EJ-12: 403 for a
  non-admin, 200 with `state`/`healthy`/allow-listed `last_run` for an admin, 404 for an unknown job, `never_run` when
  empty). Result: BLOCKED (needs the owner-approved deploy).
- **pytest:** `sudo docker run --rm --network none -v /home/deploy/nivesh-desk-ops:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/test_desk_exit_job.py tests/test_paper_reconcile.py tests/test_paper_account.py tests/test_desk_trading.py tests/test_desk_strategy_trades.py tests/test_order_path_guard.py tests/test_risk_controls.py tests/test_desk_alerts.py tests/test_desk_paper_sim.py tests/test_risk_gate_desk_journal.py tests/test_risk_gate.py -q -p no:cacheprovider`
  - Output (last line): `390 passed, 3 warnings in 21.46s`
  - Baseline before any change (5 of these suites): `189 passed, 3 warnings in 15.81s`
  - New tests alone (`-rA`): `40 passed, 2 warnings in 7.34s` (24 exit job, 16 reconcile)
  - Result: PASS
- **Mutation check** (scratch copy of the tree, one defect at a time, then restored):
  ```
  MUTANT lease_always_free -> 3 failed, 21 passed
  MUTANT close_without_status_filter -> 1 failed, 23 passed
  MUTANT bars_always_in -> 2 failed, 22 passed
  MUTANT ignore_holidays -> 2 failed, 22 passed
  MUTANT strategy_even_without_fno -> 1 failed, 23 passed
  MUTANT partial_counts_as_ok -> 2 failed, 22 passed
  MUTANT no_missed_detection -> 1 failed, 23 passed
  MUTANT adjust_without_key_guard -> 3 failed, 12 passed
  MUTANT stamp_any_state -> 15 passed            (survived → test RC-7b added → 1 failed, 15 passed)
  MUTANT revert_closed_too -> 2 failed, 13 passed
  MUTANT invent_pre_account_pnl -> 6 failed, 9 passed
  MUTANT swallow_ledger_failure -> 1 failed, 14 passed
  ```
- **Lint:** `python -m pyflakes` on the six changed/new production files → no output, exit 0.
- **Real MongoDB 7** (throwaway local `mongo:7` container with `--network none`; the test container shares its loopback;
  database dropped and container removed afterwards; MOCK staging-shaped data from `tests/test_paper_reconcile.py`):
  `python /recon/realmongo_check.py`
  ```
  plan entries: [('ef61108b', -5154.37, 0.0), ('ffa3904e', 0.0, 124617.8)]
  concurrent applies moved: 2 already: 2 skipped: 0
  account after apply: (979392.91, 249235.6, ['reconcile:closed_pnl_not_in_cash:ef61108b-a124-49cc-a114-53b1db717b02', 'reconcile:open_trade_unreserved:ffa3904e-2245-4e60-a9d8-a37247425c62'])
  adjust rows: 2
  ICICI1 stamped: {'paper_reserved_rs': 124617.8, 'reconciliation': [{'key': 'reconcile:open_trade_unreserved:ffa3904e-2245-4e60-a9d8-a37247425c62'}]}
  check after apply: [(True, True, True, True)]
  third apply moved: [] | account: (979392.91, 249235.6)
  revert moved: 2 skipped: [] | account: (984547.28, 124617.8)
  revert again moved: [] | ledger rows: 12
  ICICI1 after revert: {'paper_reserved_rs': None} | re-plan key: 7247425c62#2
  lease winners of 20 concurrent: 1
  takeover winners of 20 concurrent after expiry: 1 | lock docs: 1
  ```
  Result: PASS. `$ne` against the account's key array, the null-or-missing stamp filter, `_id` = key and the lease's
  insert / compare-and-set all behave as the fakes model them, under real concurrency.

## UI / Playwright Tests
Not applicable: no frontend file changed.

## Data Correctness (staging)
All runs: `python make_bundle.py <worktree>/backend <mode> > bundle.py && sudo docker exec -i nivesh-staging-app-backend python - < bundle.py`
(the bundle loads `services/{paper_account,paper_reconcile,job_runs}.py` and the script from the branch in memory;
nothing is copied into the container; every motor write method raises; counts printed before and after). Container
modules the bundle relies on are byte-identical to the branch base (sha256 of `paper_account.py`, `desk_trading.py`,
`desk_strategy_trades.py`, `desk_alerts.py`, `check_desk_alerts.py`, `daas_client.py` equal to 5b6b3cfd).
Shown with `| grep -v "FutureWarning\|warnings.warn\|GSM client"` (environment noise lines only).

**S-1 — reconciliation dry run (2026-10-26 20:51 UTC):**
```
READ-ONLY GUARD: read-only run: update_one refused
COUNTS BEFORE: {'desk_paper_trades': 9, 'paper_accounts': 1, 'paper_account_ledger': 8, 'desk_price_alerts': 2, 'job_runs': 0, 'job_locks': 0}
Paper-account reconciliation — DRY RUN (reads only; nothing written)   plan paper-reconcile-v1
Read: 9 trades, 8 ledger rows, 1 accounts. Issues: 6 {'needs_owner_decision': 3, 'proposed': 1, 'review_only': 2}. Entries to write: 1.

Account u=a5530afb
  now: cash 984,547.28  blocked 124,617.80  available 859,929.48  (start 1,000,000.00)
    I1 cash − start -15,452.72 = ledger cash -15,452.72  OK
    I2 blocked 124,617.80 = ledger blocked 124,617.80  OK
    I3 blocked 124,617.80 = Σ open reservations 124,617.80  OK
    I4 open trades without a reservation: 1  MISMATCH ffa3904e-2245-4e60-a9d8-a37247425c62
  after the entries: cash 984,547.28  blocked 249,235.60  available 735,311.68  (start 1,000,000.00)
    I1 cash − start -15,452.72 = ledger cash -15,452.72  OK
    I2 blocked 249,235.60 = ledger blocked 249,235.60  OK
    I3 blocked 249,235.60 = Σ open reservations 249,235.60  OK
    I4 open trades without a reservation: 0  OK

Issues

  [proposed] open_trade_unreserved  ICICIBANK  trade ffa3904e-2245-4e60-a9d8-a37247425c62  (open, u=a5530afb)
    why: Open position holding no reservation: opened before the paper account existed
    entry reconcile:open_trade_unreserved:ffa3904e-2245-4e60-a9d8-a37247425c62: cash ±0.00  blocked +124,617.80  reason open_trade_unreserved; stamps paper_reserved_rs None → 124617.8 on the trade

  [needs_owner_decision] closed_pnl_missing  NIFTY  trade 089db966-3918-4ef7-887b-1defe2b8a212  (closed, u=a5530afb)
    why: It was closed 60 s after it was opened, before any end-of-day session after its opening date had marked it: [...]
    marks: leg 1 buy 22600.0 call 2026-10-27: entry 124.4; last bhavcopy row on or before the close date (2026-10-25 IST): 2026-10-23 close 124.4 settle 124.4; first row after it: 2026-10-26 close 206.35 settle 206.35 (after the close: look-ahead, not offered)
    marks: leg 2 sell 22800.0 call 2026-10-27: entry 53.35; last bhavcopy row on or before the close date (2026-10-25 IST): 2026-10-23 close 53.35 settle 53.35; first row after it: 2026-10-26 close 77.55 settle 77.55 (after the close: look-ahead, not offered)
    option costs_at_entry_marks: cash −91.55 — [...]
    option void: cash ±0.00 — [...]
  [needs_owner_decision] closed_pnl_not_in_cash  FIXA  trade 38865edc-…  option post_pnl: cash −40.10 / option exclude: cash ±0.00
  [needs_owner_decision] closed_pnl_not_in_cash  NORTHARC  trade ef61108b-…  option post_pnl: cash −5,154.37 / option exclude: cash ±0.00
  [review_only] duplicate_trades  HAL  count=3 (all closed, net -5137.24 each, reserved None)
  [review_only] duplicate_trades  ICICIBANK  count=2 (both open; ffa3904e reserved None, 37681c72 reserved 124617.8)
EXIT CODE: 0
COUNTS AFTER: {'desk_paper_trades': 9, 'paper_accounts': 1, 'paper_account_ledger': 8, 'desk_price_alerts': 2, 'job_runs': 0, 'job_locks': 0} | unchanged: True | write calls refused: []
```
(`[...]` and the condensed last five issues shorten long lines; the full unedited output is in the approval-pack
draft and reproducible with the same command.)

Decision previews (still `--dry-run`, read-only): all three "post/charge" options → after cash **979,261.26**, blocked
249,235.60, I1–I4 OK, 4 entries; all three "exclude/void" options → after cash **984,547.28**, blocked 249,235.60,
I1–I4 OK, 4 entries (three of them zero-amount). Both: `COUNTS AFTER … unchanged: True | write calls refused: []`.

`--check` (read-only): `I4_ok: false … "ok": false`, `EXIT CODE: 2`, counts unchanged.

**Why the NIFTY spread's P&L is None (VERIFIED from stored data):** opened 2026-10-24T23:07:32Z = Sunday 2026-10-25
04:37 IST and closed 60 s later. The desk marks a structure only on sessions strictly after the IST opening date, so no
leg had an exit mark; `close_strategy_trade` stored gross, costs and net as None and released the 13,000 reservation
with `net_pnl=None`. The only marks on record at the close were the 2026-10-23 bhavcopy closes, equal to the entry
prices (124.40 / 53.35; read from DaaS `/fno/NIFTY/history`), so gross P&L at those marks is ₹0.00; the trade's cost
model gives round-trip costs ₹91.55. The 2026-10-26 marks are after the close and are not offered (look-ahead).

**S-2 — exit job dry run, `--require-bars` (2026-10-26 20:41 UTC = 2026-10-27 02:11 IST):**
```
READ-ONLY GUARD: read-only run: update_one refused
COUNTS BEFORE: {'desk_paper_trades': 9, 'paper_accounts': 1, 'paper_account_ledger': 8, 'desk_price_alerts': 2, 'job_runs': 0, 'job_locks': 0}
… GET https://staging-data.niveshcopilot.com/daas/v1/holidays?segment=CM&from=2026-10-06&to=2026-10-27&limit=100&offset=0 "HTTP/1.1 200 OK"
… GET https://staging-data.niveshcopilot.com/daas/v1/prices/eod?on=2026-10-26&limit=1&offset=0 "HTTP/1.1 200 OK"
… GET https://staging-data.niveshcopilot.com/daas/v1/fno/NIFTY?on=2026-10-26&limit=1&offset=0 "HTTP/1.1 200 OK"
… GET https://staging-data.niveshcopilot.com/daas/v1/prices/eod/ICICIBANK?start=2026-10-06&limit=5000&offset=0 "HTTP/1.1 200 OK"
2026-10-26 20:41:26,330 [INFO] desk check (dry run): users=1 open_trades=2 active_alerts=1 symbols=1 failed=0 no_prices=0 | exits stop=0 target=0 already=0 | strategy open=0 exits={} not_checked=0 waiting_for_fno=0 | alerts fired=0 already=0 | latest_session=2026-10-26 session=2026-10-26 trades_checked=2 closed={} errors=0 behind=0
2026-10-26 20:41:26,330 [INFO] desk check ok (run None, session 2026-10-26)
EXIT CODE: 0
COUNTS AFTER: {... same ...} | unchanged: True | write calls refused: []
```
Both open ICICIBANK trades are checked through 2026-10-26 (`behind=0`) and neither exits, which agrees with the study's
bar check (lowest low 1375.10 > stop 1363.26; highest high 1409.70 < target 1474.07).

Fixed-clock scenarios (dry run, real DaaS answers):
```
SCENARIO 2026-10-27 20:45 IST (session not ingested yet) -> exit 2 | status skipped_no_bars | session 2026-10-27 | error the 2026-10-27 end-of-day bars are not in the data platform yet | trades_checked None | behind None
SCENARIO 2026-11-10 20:45 IST (NSE CM holiday) -> exit 3 | status skipped_no_session | session None | error 2026-11-10 is an NSE holiday: no session | trades_checked None | behind None
SCENARIO 2026-10-27 10:00 IST (morning: previous session) -> exit 0 | status ok | session 2026-10-26 | error None | trades_checked 2 | behind 0
COUNTS AFTER: {'desk_paper_trades': 9, 'paper_accounts': 1, 'paper_account_ledger': 8, 'desk_price_alerts': 2, 'job_runs': 0, 'job_locks': 0} | unchanged: True | write calls refused: []
```
(S-2b = first line, S-2c = second line. The first scenario only shows that the 2026-10-27 bars were not yet in at
02:xx IST, when the run happened; it says nothing about 20:45 IST that day.)

Snapshot scripts (read-only, summary line only): `snapshot_staging.py` → `{"desk_paper_trades": 9, "paper_accounts": 1,
"paper_account_ledger": 8, "risk_decisions": 7, "risk_controls": 2, "risk_control_audit": 13, ...}`;
`snapshot_staging_desk.py` additionally `"desk_price_alerts": 2, "job_runs": "absent", "job_locks": "absent"`.

## Findings outside this fix (noted, not changed)
- **Strategy exits on the GET path can use stale leg marks.** Between the 19:00 cash bhavcopy and the 19:30 F&O
  bhavcopy (or longer if the F&O ingest fails), a list read that sees the underlying's new bar can close a structure
  while each leg "keeps its last mark" (previous session). The job now waits for the F&O bhavcopy; the GET
  (`routes/desk_trading.py`, `services/desk_strategy_trades.py`, another agent's files) does not.
- **FIXA / FIXC are E2E fixtures in the real user's paper account.** FIXC's −₹41.00 is in cash; FIXA's −₹40.10 is
  one of the decisions. Whether fixtures belong in that account is an owner question.
- **Staging has no dedicated test user** (3 users: `a5530afb` admin with the trades, `96422aa4` admin without trades,
  `18744d0c` non-admin without trades; hashed).

## Inputs required from user
- Approval to deploy the branch to staging (needed for the endpoint test and before any apply or cron install).
- The three owner decisions (NORTHARC, FIXA, NIFTY) and which user holds the staging-only test position, plus that
  user's session token for creating it through the API. All in the approval-pack draft.

## Verdict: BLOCKED
Unit, mutation and read-only staging checks pass. The staging endpoint test, the staging test position, the
reconciliation apply and the cron install all need the owner's approval and a deploy, which this fix group must not do.
See `test_reports/OVERRIDE_paper_exit_job_reconcile.md`.
