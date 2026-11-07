# Functionality Verification Report — Paper Trading v2 (the owner's six-view design)

- **Branch:** `feat/paper-trading-v2` (base `dev` @ 4391cd74)
- **Date:** 2026-11-05
- **Author:** Claude (full-stack developer + QA)
- **Environment:** staging data (nivesh-staging-app-backend, Mongo), before deploy; mocked Playwright; real-body render
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Trade Desk › Paper Trading is replaced by the owner's design (5 Nov): 01 Overview, 02 Scanner opportunities,
03 Capital allocation, 04 Portfolio risk, 05 Real-time P&L, 06 Strategy analytics, under one shell (status strip,
account card with the mode chooser). Old URLs redirect (`live`/`journal` → `pnl`, `settings` → `allocation`; Risk Desk's
three SPT views → the paper views). New backend: the paper overview, ONE versioned policy over the risk profile and the
SPT config (user tightens, admin loosens with a reason), correlation, account analytics, F&O structures, named stress
scenarios, open risk per allocation bucket, and `setup_type` on P&L rows. Spec: `docs/scanner_paper_trading/UI_DESIGN_V2.md`.

Verified here: backend unit + regression; every new route on real staging data with the branch code (test users
only, restored); the six views with mocked bodies and with real staging bodies. NOT verified here: the deployed app
(needs merge + deploy), and populated F&O structures / correlation / margin on real data (the test account had none).

## Test Cases
Authored up front, after the API + UI design (spec §7) and before implementation:

| File | Ids | Result |
|---|---|---|
| `test_reports/paper_v2_backend_TESTCASES.md` | PV2-I-*, PV2-B-01 … PV2-B-33 | PASS (pytest below) |
| `test_reports/paper_v2_ui_a_TESTCASES.md` | PV2-A-01 … PV2-A-62 (+ A-38b added at integration) | PASS (Playwright below) |
| `test_reports/paper_v2_ui_b_TESTCASES.md` | PV2-B-UI-01 … PV2-B-UI-29 | PASS (Playwright below) |

Integration cases (added during integration):

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| V1 | API | every new route without a session | api (staging) | 401 | PASS |
| V2 | API | every read as the test user (18 routes + opportunities) | api (staging) | 200, bodies saved | PASS |
| V3 | API | policy defaults from the owner default profile | api (staging) | per-trade 0.5, F&O max loss 0.35 (0.7 × per-trade), margin 70 | PASS |
| V4 | API | another user's policy / correlation / analytics, read and write | api (staging) | 403 | PASS |
| V5 | API | tighten → derived F&O limit follows; stale version; loosen; out of range; unknown key; refused writes change nothing | api (staging) | 200 (0.28) / 409 / 403 admin_required / 422 / 422 / version unchanged | PASS |
| V6 | API | admin route: non-admin; admin read; PUT without reason; admin loosens; admin resets | api (staging) | 403 / 200 / 422 / 200 (0.6) / 200 (0.5) | PASS |
| V7 | API | correlation bad symbol; stress-test named scenarios present | api (staging) | 422 / `named` present | PASS |
| R | data | test-user documents before/after | data (staging) | `equal to before: True` | PASS |
| REAL-1…7 | UI | the six views on real staging bodies (empty test book; and with the 09:20 live scanner position) | e2e (real bodies) | no page error, no unexplained error block, figures from the bodies | PASS |
| A-38b | UI | a watchlists body of the wrong shape | e2e (mock) | plain words, no validator dump | PASS |

## API / Endpoint Tests (staging)
- **How:** `scratchpad/pv2_check.py` ran INSIDE nivesh-staging-app-backend in its own python process, with the branch
  code (`41435f86`) as an overlay copy of the deployed `/app/backend` (deployed files verified identical to the branch
  base by sha1 first). The running server was not touched and the copy was deleted afterwards. Test users
  `pv2chk_t1_<ts>` / `pv2chk_t2_<ts>` only.
- **Output:** `test_reports/paper_v2_staging_check.txt` (real, unedited apart from dropping library warnings). Key lines:
  ```
  PASS V3 policy fno_max_loss_pct = 0.7 × per-trade = 0.35 0.35
  PASS V5 derived fno_max_loss follows → 0.28 0.28
  PASS V5 stale expected_version → 409 {"detail":{"code":"version_conflict",...
  PASS V5 loosen per_trade 0.4→0.6 → 403 admin_required {... "loosened":["per_trade_risk_pct","fno_max_loss_pct"]}}
  PASS V6 admin PUT without reason → 422 {"detail":{"code":"reason_required",...
  AFTER (test users) {... all 0 ...}
  equal to before: True
  RESULT: PASS
  ```
- **pytest (docker, mock fixtures):** `test_reports/paper_v2_backend_pytest.txt`, 09:28 IST:
  - `tests/test_paper_v2_*.py tests/test_paper_pnl*.py` → `147 passed, 2 warnings in 9.68s` (exit 0)
  - regression set → `1488 passed, 5 skipped, 3 warnings in 42.27s` (exit 0)
- Result: PASS

## UI / Playwright Tests
- **Affected specs, mocked (final, after the integration fixes):** `test_reports/paper_v2_final_mocked_pw.txt`
  ```
  TSC_EXIT=0
  BUILD_EXIT=0
    59 skipped
    176 passed (2.0m)
  PW_EXIT=0
  ```
  (paper-v2-a, paper-v2-b, pnl, pnl-exits, risk-controls, compliance-wording, spt-paper, spt-risk, trade-desk, shell,
  risk-desk, hedge. The 59 skips are the old dashboard's retired cases, each marked RETIRED in its spec.)
- **Wider desk regression (59 specs, on 118d96e9):** `995 passed, 94 skipped`; the 32 failures were
  `copilot-app-desk-strategy-graphs.spec.ts`, which fails under the standard recipe by design. On its own harness
  build (`e2e/fe-run-stgraph.sh`): `32 passed (20.3s)`, exit 0.
- **Real staging bodies (`copilot-app-desk-spt-real.spec.ts`, SPT_REAL_DIR):** `test_reports/paper_v2_real_render_pw.txt`
  - set A (staging check bodies + real `/api/risk/policy|status`): `7 passed (7.4s)`, `PW_EXIT=0`
  - set B (set A + the 09:20 live run's P&L and proposals, a real scanner position): `7 passed (7.8s)`, `PW_EXIT=0`
- Result: PASS

## Fixes made at integration (found on real data)
- **P&L total.** It is net of estimated charges while the Unrealized tile is gross (real case: +₹70.91 gross,
  ₹259.63 estimated charges, total −₹188.72). The sub-line now says "net of estimated charges".
- **Risk headline, empty book.** It said one limit was "the nearest to a breach" when nothing was in use. It now says
  "Within every limit: nothing is in use yet."
- **Error text.** A body of the wrong shape showed the validator's raw dump to the user. `sptProblem` now says
  "unexpected response shape (fields)".
- **Real-body spec.**
  - REAL-1 waits for its rows before deciding which branch to take.
  - REAL-5 and REAL-6 now check for error blocks.
  - REAL-7 (P&L) is new.
  - The caps card reads real `/api/risk/policy` and `/api/risk/status` bodies.
  - Watchlists are answered as "not part of this check". A first GET creates a starter list, which would be a write
    outside the test-user cleanup.

## Data Correctness (staging)
- Policy defaults read from the real risk-profile store for a fresh user: 0.5 / 3 / 2 / 4 / 10 / 10 / 25 (owner
  default), F&O max loss 0.35, margin 70, buckets 45 / 25 / 20, reserve 10. All match the owner's 5 Nov decisions and
  PRD §9.4.
- Bucket open risk sums to `open_risk.rs` (0 for the empty test book: `{"equity_positional": {"used_rs": 0.0,
  "cap_rs": 450000.0, "risk_rs": 0.0}, …}`).
- Overview on real data: 1,842 scanner signals consolidated into 291 opportunities, feed `live`, last tick 1.2 s.
- Result: PASS for what an empty test account can show. Populated buckets, correlation and F&O structures are
  verified on mocked bodies only.

## Not verified (state plainly)
- **The deployed app.** This report verifies the branch before merge. After merge and deploy, open
  `/v5/app/trader/desk?tab=trade&view=paper` on staging and run the same check against the deployed code.
- **Real F&O margin.** `margin_rs` comes from Zerodha's read-only calculator and is null without a Kite session.
- **Real correlation and F&O structures with positions.** The test account had none.

## Owner decisions open
1. **Roll and the plan card.** Roll on F&O structures, and the plan card on a paper trade's record, have no place in the
   design (both lived on the old Live desk / journal).
2. **Bucket capital vs bucket risk.** `used_rs` per bucket counts SPT reservations only, while `risk_rs` counts every
   paper position. A desk F&O structure therefore shows risk in `fno` with ₹0 capital used.
3. **Margin-use cap.** The 70% default comes from the design; the PRD has no figure. It is configurable.
4. **Old dashboard code.** The old components are still in the tree but unrouted. Delete them in a follow-up?

## Inputs required from user
- none

## Verdict: PASS
