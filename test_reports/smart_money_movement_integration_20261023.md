# Functionality Verification Report — Smart Money Movement integration (P0+P1+P2+Evidence)

- **Branch:** `feat/smart-money-movement` (merge of `fix/mf-holdings-dedupe`, `feat/historical-ownership-reaction`,
  `study/post-disclosure-forward-returns`, `feat/evidence-validation-screen` into `feat/provider-foundations@8dc09801`)
- **Date:** 2026-10-23
- **Author:** Claude (orchestrator), re-verifying four independently-built and already individually-verified pieces
  after merging them together
- **Environment:** staging (`nivesh-staging-app-backend` container; `mcr.microsoft.com/playwright:v1.60.0-jammy` for UI)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

Four branches, each already independently verified in this session (P0: MF holdings dedupe/coverage, P1: historical
ownership-reaction panel, P2: post-disclosure forward-returns study, Evidence & Validation screen consuming P2's
result), were merged into one integration branch. Three merge conflicts occurred — all three were two branches
adding adjacent router-registration lines to the same files (`backend/nidp/services/daas_api/app.py`,
`backend/server.py`, `frontend-v5/.../SmartMoneyTab.tsx`) — resolved by keeping both additions (confirmed no logic
was dropped). This report re-verifies the combined result end-to-end, not any individual piece's own prior report.

## Test Cases

Each piece authored and passed its own test cases before this merge (see `test_reports/mf_holdings_dedupe_TESTCASES.md`,
each branch's own report). This report's scope is the merge itself: confirm all four apps' routes register together,
no test in any of the four suites regressed, and the existing (pre-existing, unrelated) Smart Money tab failure is
unchanged in count.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| M-1 | backend | `daas_api.app` imports with all four routers registered | import | no exception, route count includes ownership + evidence_validation | PASS |
| M-2 | backend | `server.py` imports with all four proxy routers registered | import | no exception | PASS |
| M-3 | backend | combined pytest across all four pieces + pre-existing desk routes | unit/api | no regressions | PASS |
| M-4 | frontend | `tsc --noEmit` on the merged `SmartMoneyTab.tsx` (both panels mounted) | typecheck | clean | PASS |
| M-5 | frontend | all three Smart Money Playwright specs run together | e2e | only the known pre-existing TC-F3 failure | PASS |

## API / Endpoint Tests (staging container)

- **Import sanity:**
  - Command: `docker exec nivesh-staging-app-backend python -c "import nidp.services.daas_api.app as a; print(len(a.app.routes)); import server as s; print(len(s.app.routes))"`
  - Output: `daas routes 187` / `server routes 732`
  - Result: PASS
- **pytest (combined):** `docker exec nivesh-staging-app-backend python -m pytest nidp/tests/services/test_daas_smart_money.py nidp/tests/services/test_mf_holdings_reconciliation.py nidp/tests/services/test_daas_evidence_validation.py tests/test_ownership_reaction.py tests/test_markets_evidence_routes.py tests/test_desk_market_routes.py -q`
  - Output: `178 passed, 1 warning in 5.43s`
  - Result: PASS

## UI / Playwright Tests

- **Specs:** `copilot-app-desk-smart-money.spec.ts` + `copilot-app-desk-ownership-reaction.spec.ts` + `copilot-app-desk-evidence-validation.spec.ts`, run together against the merged `SmartMoneyTab.tsx`
  - Command: `npx playwright test e2e/tests/copilot-app-desk-smart-money.spec.ts e2e/tests/copilot-app-desk-ownership-reaction.spec.ts e2e/tests/copilot-app-desk-evidence-validation.spec.ts --reporter=line`
  - Output: `1 failed` (`TC-F3: the disclosure date is shown, not the compute date` — pre-existing hardcoded "51d ago" date-drift assertion, unrelated to this merge, previously identified independently by both the P1 and Evidence-screen agents) · `55 passed`
  - Result: PASS (the one failure is pre-existing and out of scope for this merge)
- **tsc:** `npx tsc --noEmit -p tsconfig.json` — clean, zero diagnostics. Result: PASS

## Data Correctness (staging)

Each underlying number (HAL dedupe 25,923,551 vs 105,279,151 pre-fix vs 44,941,680 disclosed; ICICIBANK same-source
vs cross-source delta +0.89pp vs +16.65pp; the post-disclosure study's INCONCLUSIVE result at every horizon) was
already independently re-derived against the real warehouse in this session, prior to this merge, per piece. This
merge introduces no new SQL logic of its own (only router registration + a Python merge-conflict resolution that
kept both additions verbatim) — re-verified above via the combined pytest run, which includes each piece's own
data-correctness assertions.

## Known, pre-existing, out-of-scope issue

`TC-F3` in `copilot-app-desk-smart-money.spec.ts` hardcodes an elapsed-time string ("51d ago") against a fixed
`disclosureAsOf`; today's real elapsed count is 52 days. This is a time-dependent test bug unrelated to any of the
four merged pieces, first flagged independently by two different agents in this session. Not fixed here — it
belongs to whoever owns that spec file.

## Verdict: PASS
