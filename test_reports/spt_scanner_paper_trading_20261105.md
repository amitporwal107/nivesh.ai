# Scanner-to-Paper Trading (SPT) release 1: verification report (5 Nov 2026)

- **Branch:** `feat/spt-integration`, PR #485. It includes PR #484 (the PRD, Workflow, DESIGN and review).
- **Requirements:** `docs/prd/Nivesh_Scanner_Paper_Trading_Capital_Allocation_Risk_Management_PRD.md`,
  `docs/prd/Nivesh_Scanner_to_Paper_Trading_Workflow.md`.
- **Design:** `docs/scanner_paper_trading/DESIGN.md`.

## Test cases (authored before implementation, per slice)

| Slice | File | Ids | Result |
|---|---|---|---|
| A: signals → opportunities → validation → outcomes | `test_reports/spt_a_TESTCASES.md` | SPT-A-01 … SPT-A-41 | all implemented, unit PASS |
| B: config/modes → proposals → sizing → allocation → risk → pipeline | `test_reports/spt_b_TESTCASES.md` | SPT-B-01 … SPT-B-44 | all implemented, unit PASS |
| C: orders → execution → fills → positions → monitor → modify → reconcile | `test_reports/spt_c_TESTCASES.md` | SPT-C-01 … SPT-C-35 | all implemented, unit PASS |

**Integration cases (added during integration):**

| Id | Case | Result |
|---|---|---|
| INT-1 | `paper_reconcile` counts live SPT reservations (store `spt_orders`) as reserved (I3) and never proposes them as orphans; a desk orphan is still reported | PASS (`test_rc_spt_reservation_…`) |
| INT-2 | An opportunity flagged `conflict_after_qualified` by A is refused by B (`conflicting_signals`) | PASS (`test_spt_int_conflict_after_qualified_…`) |
| INT-3 | C's "B missing" tests still hold once B's module exists (package attribute removed) | PASS |
| INT-4 | The order-path guard: no SPT function is named like an OMS order method (`cancel_order` → `cancel_paper_order`) | PASS (`test_order_path_guard.py`) |
| INT-5 | `server.py` wires 4 routers and 3 leader-locked loops; all routes answer under `/api/v1` | PASS (staging harness below) |
| INT-6 | Staging, outside the session: backfill, validation on real data, the pipeline refuses without a fresh price, every route's auth/ownership, reads write nothing, restore | PASS (below) |
| INT-7 | Staging, in the session: proposal → risk reservation → order → fill on live quotes → exit → release → reconcile, with test users | **PENDING** (needs the market open and the morning Kite login) |

## Unit tests (real output)

```
slice A (its branch):  494 passed, 2 warnings in 13.28s
slice B (its branch):  546 passed, 5 skipped, 3 warnings in 19.57s
slice C (its branch):  476 passed, 3 warnings in 13.11s
integration (tests/test_spt_*.py + scan_builder, risk*, paper*, desk_trading*, exit_rules*, exit_watch, kite_trade_side,
market_recovery_indices):  1404 passed, 5 skipped, 2 warnings in 31.12s
after the rename (tests/test_order_path_guard.py + tests/test_spt_*.py + tests/test_paper_reconcile.py):  283 passed, 3 warnings in 19.80s
```

- The 5 skipped tests need `RISK_MONGO_URL` (the real-Mongo reservation concurrency tests).
- Full CI allowlist (342 files) before the rename: `4 failed, 9820 passed, 52 skipped`. Three of the failures are known
  and fail on a clean dev too: `test_cas_api_client` ×2 and `test_nidp_stamp_broadcast_at`. The fourth was the
  order-path guard, fixed by INT-4.
- Full CI allowlist after the rename:
  ```
  FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
  FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
  FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
  3 failed, 9821 passed, 52 skipped, 16 warnings in 255.66s (0:04:15)
  ```
  Only the three known failures remain.
- GitHub CI on PR #485, checked 04:01 IST: `Backend unit tests (allowlist): completed success`, mergeable, clean. PR #484
  is also green.

## Staging API run, outside the session (5 Nov 02:56 IST, real output)

**Setup.** The branch code was loaded ahead of the deployed copy inside nivesh-staging-app-backend, against real Mongo,
Redis, DaaS and the regime. Two synthetic TEST users were used, never a real account. The run wrote only the new
`spt_*` collections (asserted empty first) and the test users' own documents.

```
BEFORE {"spt_signal_events": 0, "spt_opportunities": 0, … all 0}
S1 backfill exit 0 | {"consolidate": {"attached": 811, "conflicts": 59, "created": 996, "events": 1807, "failed": 0, …}, "day": "2026-11-04",
   "ingest": {"duplicate": 0, "errors": 0, "inserted": 2367, "normalized": 1807, "quarantined": 560, "reasons": {"stale": 560}, "seen": 2367}, "mode": "write"}
S1 counts 2367 events, 996 opportunities
S1 second run (idempotent) → 2367 events, 996 opportunities
S2 A round 5.0 s → {… "validate": {"due": 996, "validated": 60, "skipped": 0, "errors": 0, "QUALIFIED": 58, "CONDITIONAL": 2},
   "expire": {"window_ended": 0, "closed_below_stop": 0, "series_break_after_signal": 0, "checked": 86, "errors": 0, "expected_bar_day": "2026-11-04"}}, "errors": []}
S2 opportunities by state {'CREATED': 936, 'QUALIFIED': 58, 'CONDITIONAL': 2}
S3 no session /api/v1/scanner/signals → 401   (and /opportunities, /paper/accounts, /proposals, /paper/orders → 401)
S3 signals day=2026-11-04 → 200 items 5
S3 opportunities QUALIFIED → 200 {"ok":true,"count":58,…}
S3 unknown signal → 404 {"detail":"signal_not_found"}
S4 GET accounts → 200 (₹10,00,000 paper account for the test user)
S4 PUT config mode=approval → 200 (version 1)
S4 PUT another user's config → 403 {"detail":{"code":"not_your_account",…}}
S4 PUT bad mode → 422 {"detail":{"code":"invalid_mode",…}}
S5 B round → {"users": 1, "qualified": 58, "proposals": 0, "orders": 0, "skipped": {"price_unavailable": 58}, "errors": []}
S6 /api/v1/risk/account/<T1> → 200 (equity 1000000.0, basis stated)    /risk/exposures → 200    /allocation/recommendations → 200
S6 /api/v1/risk/stress-test/<T1> → 200 (spt-stress-v1)    /risk/account/<T2> as T1 → 403
S6 calculate-position-size (PRD §8.4 example inputs) → 200 (pure, writes none)
S6 validate-trade (dry run) → 200 {"dry_run":true,"outcome":"rejected","reason_codes":["price_unavailable"],…} | risk_decisions written: 0
S6 approve now (outside the session) → 404 {"detail":{"code":"proposal_not_found",…}}
S7 C live round → {"ran": true, "round": "housekeeping", "counts": {"expired": 0}, "errors": []}
S7 /api/v1/paper/orders → 200 {"orders":[],"count":0}   /positions → 200 []   /trades → 200 []
S7 /api/v1/paper/reconcile → 200 {"version":"spt-reconcile-v1","ok":true,…,"mismatches":[]}
S7 ENTRY without an approved proposal → 422 {"detail":{"code":"entry_requires_approved_proposal",…}}
S8 analytics/scanners → 200 {"ok":true,…,"min_sample":30,…}
S9 paper_reconcile issues for test users: []
S10 events by type {'OPPORTUNITY_QUALIFIED': 58, 'OPPORTUNITY_VALIDATED': 60, 'SIGNAL_CONFLICT_DETECTED': 59, 'SCANNER_SIGNAL_NORMALIZED': 1807,
    'OPPORTUNITY_UPDATED': 811, 'OPPORTUNITY_CREATED': 996, 'SCANNER_SIGNAL_RECEIVED': 2367}
S10 spt_state [('spt_a', []), ('spt_b', []), ('spt_c', None)]
AFTER RESTORE {… all 0} | equal to before: True
```

**What this shows:**
- Ingest is idempotent and quarantines rather than drops.
- 4 Nov's real strong signals produce 58 QUALIFIED opportunities on real prices and the real regime.
- The pipeline makes **no proposal without a fresh live price**, which is right outside the session.
- Auth and ownership hold on every route.
- The dry run writes nothing.
- The paper side is clean.
- Every document was removed.
- The scratch copy in the container was deleted afterwards (`ls`: No such file or directory).

**One fix on the harness side:** the "opportunity detail" line printed `signals 0 / validation null` because the
harness read the top level of the response instead of its `opportunity` key. The harness is fixed for the in-session
run; the route was correct.

## Playwright

No frontend code is changed by SPT: the release is APIs only, because the owner is designing the screens. The session's
earlier frontend edits (Exit watch, PR #483) were verified with Playwright: 54 passed plus a 2-test real render, in
`test_reports/exit_watch_20261104_2145.md` (Verdict PASS).

## Not verified yet

- **INT-7**, the in-session chain on live quotes: proposal → reservation → order → fill → exit → release → reconcile.
  The harness `LIVE=1` mode is ready, to run after 09:15 IST on 5 Nov. It needs the morning Kite login.
- **Real-Mongo concurrency** (the 5 skipped tests).
- **The scan-loop hook and the three loops running inside the deployed app.** Before a merge and deploy they only run in
  the harness.

## Verdict: PENDING (INT-7 in-session run)
