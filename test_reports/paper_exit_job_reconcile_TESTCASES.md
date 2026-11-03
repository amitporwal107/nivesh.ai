# Test cases: evening exit job hardening + paper-account reconciliation

- **Branch:** `fix/paper-exit-job-reconcile` (off origin/dev 5b6b3cfd)
- **Authored:** 2026-10-27, before implementation (VERIFICATION_PROTOCOL §1)
- **Acceptance standard:** `NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md` Phase 0 §0.2 (last two bullets), §0.3
  (reconciliation bullets), §0.4 (jobs), Phase 2 "monitored, missed or failed runs detectable", cross-phase DoD 2–4, 6.
- **Scope rule:** nothing in this branch writes to staging. Staging evidence is read-only (dry runs only).

## Design decided before the tests

### Part 1: `scripts/check_desk_alerts.py`
| Flag / behaviour | Meaning |
|---|---|
| `--require-bars` (cron) | Work out the session that should be in (IST: today from 19:00, else the previous day; walk back over weekends and NSE CM holidays from DaaS `/holidays`). Today is a weekend or NSE holiday after 19:00 → **exit 3**, nothing read or written. The session has no rows in DaaS `/prices/eod?on=` → **exit 2**, nothing written. Without the flag the job behaves as the GET does (evaluates whatever bars exist). |
| `--skip-if-done` (cron) | A run with status `ok` is already recorded for that session → exit 0, nothing evaluated. `failed`/`partial` runs are not "done", so the retry slot re-evaluates. |
| Lock | Mongo lease `job_locks/{job}` (insert, or take over only an expired lease by compare-and-set on its run id; released by expiring it, never deleted). Held → **exit 4**. The cron line also wraps the command in `flock -n -E 4`. |
| Heartbeat | `job_runs` doc per non-dry run: `{_id: run_id, job, started_at, finished_at, status, exit_code, session, counts, error}`; `status` ∈ `running, ok, partial, failed, skipped_no_bars, skipped_no_session, skipped_locked, skipped_done`. Written at start (`running`) and at the end (also on failure). |
| Counts | trades checked (cash, strategy), closed by reason (cash + strategy), alerts fired, errors (symbols failed, strategy not checked, alerts not checked), open trades behind the session. |
| Read path | `GET /api/admin/risk/jobs/{job}` (admin only): last run, last success, `state` ∈ `ok, partial, failed, running, missed, no_data, skipped, never_run`, `healthy`. **Missed** = no run recorded since the latest scheduled slot (Mon–Fri 20:45 IST) once that slot is more than 60 min old. A `running` doc older than the lease (60 min) reads as `failed` (no finish recorded). |
| Dry run | Reads only: no lock, no heartbeat, no index creation (unchanged). |
| Exit codes | 0 ran / skipped as done · 1 failed · 2 no bars for the session yet · 3 no session today (holiday/weekend) · 4 another run holds the lock |

### Part 2: `scripts/reconcile_paper_accounts.py` + `services/paper_reconcile.py`
Invariants per account: (I1) `cash − starting_capital = Σ release.net_pnl_rs + Σ adjust.cash_delta_rs`;
(I2) `blocked = Σ reserve.amount_rs − Σ release.amount_rs + Σ adjust.blocked_delta_rs`;
(I3) `blocked = Σ paper_reserved_rs over open trades`; (I4) every open trade has a reservation.
Corrections are `action: "adjust"` ledger rows (`_id` = idempotency key `reconcile:<issue>:<trade_id>`, `reason_code`,
`trade_id`, `actor: "reconcile"`, `run_id`, `cash_delta_rs`, `blocked_delta_rs`), applied through a new
`paper_account.adjust()` whose account write carries the key in its filter (`adjustment_keys $ne key` + `$push`), so the
account moves at most once per key even if the process dies between the account write and the ledger row.

## Test Cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| EJ-1 | exit job | Two `run_job()` calls race on the same DB (fake yields between awaits) | unit (concurrency) | exactly one runs (`ok`), the other exits 4 with a `skipped_locked` heartbeat; each due trade closed once; one release per trade |
| EJ-2 | exit job | Two evaluations from the same stale snapshot of open trades (both read before either writes), cash and strategy | unit (idempotency) | second write matches nothing (`already_closed`); one `release` ledger row per trade; cash moved once |
| EJ-3 | exit job | `--require-bars`, session's bars not in DaaS | failure | exit 2; zero writes to trades/alerts/accounts/ledger; heartbeat `skipped_no_bars` with the session |
| EJ-4 | exit job | `--require-bars`, run date is an NSE holiday (after 19:00) | edge | exit 3; zero writes; heartbeat `skipped_no_session` |
| EJ-5 | exit job | Expected-session rule: before 19:00 → previous day; Monday morning → Friday; day after a holiday | unit | dates as stated |
| EJ-6 | exit job | Successful run | unit | heartbeat `ok`, `finished_at`, counts: trades checked, closed by reason, alerts fired, errors 0, open trades behind 0 |
| EJ-7 | exit job | All prices unreadable / DB error | failure | exit 1; heartbeat `failed` with the error class |
| EJ-8 | exit job | Partial failure (one symbol unreadable) then retry | failure + recovery | first run `partial` (exit 0) with the trade still open; `--skip-if-done` retry re-evaluates and closes it once; third run changes nothing |
| EJ-9 | exit job | `--skip-if-done` after an `ok` run for the same session | edge | exit 0, heartbeat `skipped_done`, no bars read |
| EJ-10 | exit job | Dry run | unit | no `job_runs`/`job_locks`/trade/ledger writes |
| EJ-11 | read path | `health()` with: no runs; ok after last slot; Monday 10:00 with Friday's run; Tuesday 22:00 with Friday's run; `running` older than lease; `failed` | unit | `never_run`; `ok`; `ok` (weekend is not a miss); `missed`; `failed`; `failed` |
| EJ-12 | read path | `GET /api/admin/risk/jobs/check_desk_alerts` as non-admin / admin; unknown job | api (in-process) | 403 / 200 with `state`, `healthy`, allow-listed `last_run`; 404 |
| EJ-13 | cron | `desk-alerts.cron` parsed | unit | 20:45 + 22:45 Mon–Fri IST, `flock -n`, `--require-bars --skip-if-done`, schedule equals the code's registry |
| EJ-14 | exit job | F&O strategy trade with a target touch, via `run_job()` | unit | closed by the job once, capital released once (existing strategy tests keep passing) |
| RC-1 | reconcile | Open cash trade with no reservation; open strategy trade with no reservation | unit | issue `open_trade_unreserved`; entry `blocked +qty×entry` / `+exposure_rs` |
| RC-2 | reconcile | Closed trade with net P&L, closed before the account existed, no release row | unit | `needs_owner_decision` with options `post_pnl` (cash Δ = net P&L) and `exclude` (Δ 0, annotated); no entry until decided |
| RC-3 | reconcile | Closed strategy trade with `net_pnl_rs: None` and no session held | unit | `needs_owner_decision`: `costs_at_entry_marks` (Δ = −round-trip costs), `void` (Δ 0); reason text says why it is None |
| RC-4 | reconcile | Reserve row for a closed trade with no release; reserve row for a missing trade | unit | `reservation_without_open_trade`; entry `blocked −amount` |
| RC-5 | reconcile | Identical trades (3 closed, 2 open) | unit | `duplicate_trades` groups listed, review only, no entries, nothing deleted |
| RC-6 | reconcile | Dry run | unit | zero writes on every collection |
| RC-7 | reconcile | `apply` | unit | ledger gains exactly the proposed `adjust` rows (keys, reason codes, run id, actor); account deltas = Σ entries; trade stamped only for reservations, with history |
| RC-8 | reconcile | `apply` twice; crash between the account write and the ledger row, then rerun | unit (idempotency) | second apply writes nothing; rerun after the crash writes the missing ledger row and does not move the account again |
| RC-9 | reconcile | `revert` | unit | reversing rows added (`revert:<key>`), account back to pre-apply values, originals still present; revert twice = no-op; a reservation whose trade has since closed is skipped with a reason |
| RC-10 | reconcile | Invariant check with a planted ₹1.00 cash mismatch and a planted blocked mismatch | unit | both reported, no number invented (`needs_owner_decision`) |
| RC-11 | reconcile | Every path (dry run, apply, revert) | unit | the fake records zero `delete_one`/`delete_many` calls |
| RC-12 | reconcile | Staging-shaped fixture (9 trades, 8 ledger rows, 1 account — MOCK copied from the 2026-10-27 read) | unit (golden) | ICICIBANK#1 reserve ₹1,24,617.80; NORTHARC −₹5,154.37 and FIXA −₹40.10 decisions; NIFTY decision (−₹91.55 / ₹0); HAL×3 and ICICIBANK×2 duplicates; I1–I3 hold before and after apply |
| RC-13 | reconcile | `--decide <trade>:<issue>=<option>` | unit | the chosen option's entry is applied; unknown option / ambiguous prefix refused |
| RC-14 | reconcile | CLI output | unit | user ids appear only hashed |
| S-1 | staging | `reconcile_paper_accounts --dry-run` piped into the staging backend | data (read-only) | real discrepancy list; no write (counts of the four collections equal before and after) |
| S-2 | staging | `check_desk_alerts --dry-run --require-bars` piped into the staging backend | data (read-only) | readiness answer and counts; no write |
| REG | regression | `test_paper_account.py`, `test_desk_trading.py`, `test_desk_strategy_trades.py`, `test_order_path_guard.py`, `test_risk_controls.py` | unit | all pass |

Not covered here (stated, not hidden): a real-Mongo concurrency test (the fakes interleave only at awaits); the
staging-only test position (owner-approved step in the approval pack); Playwright (no frontend change).
