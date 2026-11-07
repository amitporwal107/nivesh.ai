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
| INT-7 | Staging, in the session: proposal → risk reservation → order → fill on live quotes → exit → release → reconcile, with test users | **PASS** (5 Nov 09:20–09:23 IST, deployed code, below) |

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

## Staging in-session run, INT-7 (5 Nov 09:20–09:23 IST, real output)

- **Code:** the DEPLOYED staging backend (#485 + #486 merged; the harness asserts every module is under `/app/backend`, no overlay).
- **Data:** two synthetic test users `spt_int7_t1_<ts>` / `spt_int7_t2_<ts>` only. The deployed B and C loops did the work; the
  harness only switched the test users on through the routes and read the results. Kite feed `live`, 1,098 instruments.
- **Harness:** `scratchpad/spt_int7.py` run by `scratchpad/int7_run.sh` (`docker exec -e LIVE=1 … python /tmp/spt_int7.py`).

Selected lines, verbatim (long lines cut at 260 characters):

```
# INT-7 live run, started 2026-11-05 09:20:20 IST
feed: live open regular_session 1098 2026-11-05T03:50:06.804804+00:00
deployed code: config v2 = True | LIVE = True | now 2026-11-05T03:50:28.460565+00:00
BEFORE (test users) {"spt_account_config": 0, "spt_account_config_versions": 0, "spt_proposals": 0, "spt_orders": 0, "spt_fills": 0, "spt_positions": 0, "spt_events": 0, "paper_accounts": 0, "paper_account_ledger": 0, "risk_decisions": 0, "risk_profiles": 0, "
market-wide (info only, not touched) {"spt_signal_events": 3924, "spt_opportunities": 1207, "spt_signal_outcomes": 0}
QUALIFIED opportunities at start: 119
R1 no session /api/v1/scanner/signals → 401
R1 no session /api/v1/opportunities → 401
R1 no session /api/v1/paper/accounts → 401
R1 no session /api/v1/proposals → 401
R1 no session /api/v1/paper/orders → 401
R2 opportunities QUALIFIED → 200 119 items
R3 PUT another user's config → 403 {"detail":{"code":"not_your_account","message":"You can only use your own paper account."}}
R3 PUT bad mode → 422 {"detail":{"code":"invalid_mode","message":"mode must be one of off, tracking, approval, auto","field":"mode"}}
A1 non-admin GET admin settings → 403
A1 non-admin GET admin user config → 403
A2 user loosens max_new_per_day 5→10 → 403 {"detail":{"code":"admin_required","message":"Only an admin can loosen an SPT limit (max_new_per_day). You can tighten any limit yourself.","loosened":["max_new_per_day"]}}
A2 user tightens →3 → 200 {'max_new_per_day': 3}
A2 user resets (null) → 403 {"detail":{"code":"admin_required","message":"Only an admin can loosen an SPT limit (max_new_per_day). You can tighten any limit yourself.","loosened":["max_new_per_day"]}}
A4 admin loosens T1 max_chase_pct →2 → 200 2.0
R4 /api/v1/risk/account/<T2> → 403 {"detail":{"code":"not_your_account","message":"You can only use your own paper account."}}
R4 validate-trade (dry run) → 200 {"dry_run":true,"writes":"none: no risk_decisions row, no reservation, no proposal","symbol":"DABUR","entry":{"type":"MARKET","price":394.5,"basis":"live ask","chase_bound":404.808,"plan_entry":400.8,"limit_price":null,"time_i
R4 ENTRY without an approved proposal → 422 {"detail":{"code":"entry_requires_approved_proposal","message":"A paper entry is created only from your own proposal that has passed the risk checks and is read
L1 T1 mode=auto → 200
L1 T2 mode=approval → 200
  waited 20 s for a deployed B round after opt-in
  waited 0 s for a second deployed B round
L1 deployed B round → {"at": "2026-11-05T03:51:17.475604+00:00", "users": 3, "qualified": 119, "proposals": 0, "refused": 0, "orders": 0, "orders_rejected": 0, "awaiting_approval": 0, "expired_approvals": 0, "skipped": {"price_unavailable": 63}, "errors": []} 
L1 proposals T1 → 200 50 | [('ANTHEM', 'BLOCKED_BY_RISK', 'BLOCKED', 80, []), ('LTM', 'BLOCKED_BY_RISK', 'BLOCKED', 14, []), ('INFY', 'BLOCKED_BY_RISK', 'BLOCKED', 51, []), ('PVRINOX', 'BLOCKED_BY_RISK', 'BLOCKED', 43, []), ('INDUSTOWER', 'BLOCKED_BY_RISK', 'B
L1 proposals T2 → 200 50 | [('ANTHEM', 'BLOCKED_BY_RISK', 'BLOCKED', 80, []), ('LTM', 'BLOCKED_BY_RISK', 'BLOCKED', 14, []), ('INFY', 'BLOCKED_BY_RISK', 'BLOCKED', 51, []), ('PVRINOX', 'BLOCKED_BY_RISK', 'BLOCKED', 43, []), ('INDUSTOWER', 'BLOCKED_BY_RISK', 'B
L2 T2 approve ZYDUSLIFE → 200 {"proposal":{"template":"cash_long_positional_v1","symbol":"ZYDUSLIFE","exchange":"NSE","direction":"long","horizon":"positional","instrument":"cash","opportunity":{"opportunity_id":"dc369778-5e84-4f28-863a-69785e21924b","state_at
  waited 0 s for a fill by the deployed C loop
L3 orders T1 → [('ZYDUSLIFE', 'ENTRY', 'MARKET', 'FILLED', 81, 81, 1178.2246, None), ('SAREGAMA', 'ENTRY', 'LIMIT', 'PENDING', 108, 0, None, 628.75), ('BOSCHLTD', 'ENTRY', 'LIMIT', 'PENDING', 1, 0, None, 50650.0)]
L3 positions T1 → [('ZYDUSLIFE', 'MONITORING', 81, 1178.2245, None)]
L3 fill T1 ZYDUSLIFE BUY 2 @ 1179.79 ref 1179.2 basis top_of_book depth_unknown False quote_age_s 0.9 | fill at 2026-11-05T03:51:22.633824+00:00 quote at None
L3 fill T1 ZYDUSLIFE BUY 14 @ 1179.09 ref 1178.5 basis top_of_book depth_unknown False quote_age_s 0.3 | fill at 2026-11-05T03:51:07.562833+00:00 quote at None
L3 fill T1 ZYDUSLIFE BUY 65 @ 1177.99 ref 1177.4 basis top_of_book depth_unknown False quote_age_s 1.0 | fill at 2026-11-05T03:50:52.504695+00:00 quote at None
L3 orders T2 → [('ZYDUSLIFE', 'ENTRY', 'MARKET', 'PARTIALLY_FILLED', 80, 26, 1179.7477, None)]
L3 positions T2 → [('ZYDUSLIFE', 'MONITORING', 26, 1179.7477, None)]
L3 fill T2 ZYDUSLIFE BUY 15 @ 1179.79 ref 1179.2 basis top_of_book depth_unknown False quote_age_s 0.5 | fill at 2026-11-05T03:51:52.739476+00:00 quote at None
L3 fill T2 ZYDUSLIFE BUY 11 @ 1179.69 ref 1179.1 basis top_of_book depth_unknown False quote_age_s 1.4 | fill at 2026-11-05T03:51:37.678916+00:00 quote at None
P pnl_paper → 200 positions 1 scanner rows 1 by_source {'desk': 0, 'scanner': 1, 'broker': 0} mismatches 0
P pnl_all → 200 positions 1 scanner rows 1 by_source {'desk': 0, 'scanner': 1, 'broker': 0} mismatches 0
L4 exit ZYDUSLIFE → 200 {"order":{"_id":"2b73cad4-2d59-4990-a3cc-10594c5a92f4","user_id":"spt_int7_t1_1793850628","account_id":"spt_int7_t1_1793850628","proposal_id":"dd766ddb-13cc-4a75-9d8a-59fee9f6de5a","opportunity_id":"dc369778-5e84-4f28-863a-69785e21924b"
  waited 45 s for the exit fill + close
L4 position after exit → 200 CLOSED 0 net -131.27 release done
L4 account blocked_rs 213956.8 → 118554.99999999999 | cash_rs 1000000.0 → 999868.73 | reservations 3 → 2
L4 trades → 200 [('ZYDUSLIFE', -131.27, 'manual', 'done')]
L5 reconcile T1 → 200 {"version":"spt-reconcile-v1","at":"2026-11-05T03:52:40.728749+00:00","ok":true,"user_id":"spt_int7_t1_1793850628","counts":{"orders":4,"fills":6,"positions":1,"mismatches":0,"by_code":{}},"mismatches":[]}
L5 reconcile T2 → 200 {"version":"spt-reconcile-v1","at":"2026-11-05T03:52:40.732997+00:00","ok":true,"user_id":"spt_int7_t2_1793850628","counts":{"orders":1,"fills":3,"positions":1,"mismatches":0,"by_code":{}},"mismatches":[]}
RESTORE mode off T1 → 200
RESTORE cancel SAREGAMA ENTRY → 200
RESTORE cancel BOSCHLTD ENTRY → 200
RESTORE mode off T2 → 200
RESTORE spt_settings put back ( 0 docs ); harness version rows removed: 1
RESTORE settings equal to snapshot: True
RESTORE purge pass 0 removed 1277
RESTORE purge pass 1 removed 0
RESTORE purge pass 2 removed 0
AFTER RESTORE (test users) {"spt_account_config": 0, "spt_account_config_versions": 0, "spt_proposals": 0, "spt_orders": 0, "spt_fills": 0, "spt_positions": 0, "spt_events": 0, "paper_accounts": 0, "paper_account_ledger": 0, "risk_decisions": 0, "risk_profiles
Opportunities QUALIFIED at start that changed state during the run (market facts, not reverted): 0 {}
EXIT=0
# finished 09:23:22 IST
```

**What this shows**
- L1: the deployed B loop picked up both test users within 20 s and proposed against the 119 QUALIFIED opportunities.
- L2/L3: T2's approval became a MARKET order; T1 (auto) got orders without asking. The deployed C loop filled them on
  live top-of-book quotes (quote age 0.3–1.4 s), in slices, including a partial fill (T2: 26 of 80).
- L4: a manual exit closed T1's ZYDUSLIFE position (net −₹131.27 after costs), released its reservation and moved
  cash 10,00,000 → 9,99,868.73.
- L5: reconcile `ok: true`, 0 mismatches for both users. The P&L dashboard showed the scanner row (`by_source scanner 1`).
- Restore: every test-user document removed (1,277), 0 left after two more passes, settings equal to the snapshot,
  **`equal to before: True`**; no QUALIFIED opportunity changed state during the run.

**Observations (not failures)**
- 63 of the 119 QUALIFIED opportunities were skipped as `price_unavailable` in that B round: their symbols are not in
  the Kite live-feed universe (1,098 instruments), so no proposal is made for them.
- 49 of T1's 50 proposals were `BLOCKED_BY_RISK` with reason `max_new_per_day`. The harness had tightened T1's cap to 3
  (A2) and a user's reset back to the default (5) is a loosening, so it needs an admin (403, by design). T1 got exactly
  3 orders.
- The deployed C state doc has no `round`/`counts` keys (L3 line shows null); the fills prove the loop ran.

### The deployed SPT screens (PR #488) on these live bodies (Playwright, real bodies, no mocks for SPT routes)

First run, the spec as merged (verbatim):
```
  ✘  1 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:99:3 › SPT screens on real staging bodies › REAL-3 Settings shows the real config (mode and limits) (1.5s)
  ✘  3 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:76:3 › SPT screens on real staging bodies › REAL-1 Opportunities lists the real opportunities (1.8s)
    ../out/results/copilot-app-desk-spt-real--cd165-ists-the-real-opportunities-copilot-app/test-failed-1.png
    ../out/results/copilot-app-desk-spt-real--9e44a-eal-config-mode-and-limits--copilot-app/test-failed-1.png
  2 failed
  4 passed (6.6s)
PW_EXIT=1
```
Both failures were the spec's safe-mode assumptions, not the screens: REAL-1's symbol set left out the proposals body
(ROLEXRINGS is a proposal whose opportunity is outside the first 200; the screen lists proposals too), and REAL-3
expected mode `off` from `accounts.json`, saved after the switch to auto, while the Settings screen reads
`account_t1.json` (mode off; the screen showed "Off · current"). With both checks reading the body the screen
reads (scratch copy of the spec; the fix goes into the Paper Trading v2 branch's spec):
```
BUILD_EXIT=0
  ✓  3 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:91:3 › SPT screens on real staging bodies › REAL-2 Analytics renders the real outcome body (3.4s)
  ✓  2 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:99:3 › SPT screens on real staging bodies › REAL-3 Settings shows the real config (mode and limits) (3.4s)
  ✓  1 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:76:3 › SPT screens on real staging bodies › REAL-1 Opportunities lists the real opportunities (4.9s)
  ✓  4 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:110:3 › SPT screens on real staging bodies › REAL-4 Trading overview shows the real paper equity (2.8s)
  ✓  5 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:120:3 › SPT screens on real staging bodies › REAL-5 Capital allocation ranks the real opportunities (2.8s)
  ✓  6 [copilot-app] › e2e/tests/copilot-app-desk-spt-real.spec.ts:130:3 › SPT screens on real staging bodies › REAL-6 Portfolio risk renders the real (empty) book (2.2s)
  6 passed (8.4s)
PW_EXIT=0
```
Screenshots: `scratchpad/pw-real-live3/shots/real-{opportunities,analytics,settings,overview,allocation,portfolio}.png` (session scratchpad, not committed: they hold staging data).

## Playwright

- **PR #488 (the first SPT screens), mocked bodies:** `TSC_EXIT=0`, `BUILD_EXIT=0`, `188 passed, 2 skipped` (5 Nov, before merge;
  `test_reports` of PR #488).
- **PR #488 on real staging bodies:** the 07:35 safe-mode bodies `6 passed`; the INT-7 live bodies `6 passed` with the two
  body-driven checks (above).
- **Exit watch (PR #483):** `test_reports/exit_watch_20261104_2145.md` (Verdict PASS).

## Not verified yet

- **Real-Mongo concurrency** (the 5 skipped tests): two loop replicas racing on one document. Staging runs one
  leader-locked replica, so it did not arise here.
- **A full trading day** of the loops (targets/stops hit by the monitor on their own, end-of-day jobs). INT-7 proved
  one manual exit, not an automatic one.

Release 1 as merged (#485, #486, #488) works end to end on staging during market hours, with the gaps above stated.

## Verdict: PASS
