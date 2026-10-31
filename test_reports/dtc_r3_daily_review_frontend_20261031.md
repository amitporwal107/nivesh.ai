# Functionality Verification Report — Daily Trader Copilot visual answer: Q15 daily review (frontend, Release 3)

- **Branch:** feat/dtc-r3-daily-review (based on feat/dtc-r2-answers, PR #422)
- **Date:** 2026-10-31
- **Author:** Claude (DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** production build (`vite build`, base `/v5/`) served by `vite preview` in the Playwright container
  (`mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`); every `/api` call mocked except the fixture payloads,
  which are a real staging capture. Not deployed to staging.
- **Changed areas:** backend routes/services: no (see `dtc_r3_daily_review_backend_20261031.md`) · frontend src: yes, 2 lines

## Summary
`daily_review` uses only block types the renderer already draws (kpis, ranked, list, bars, notice). One addition: the
equity curve is a `bars` block in a new unit, `₹` (a signed rupee amount, `+₹1,234.50` / `−₹80.00`), because the existing
units are ₹ Cr, %, × and count and an unknown unit would have printed `-40.50 ₹`. The change is `fmtRs` and its `case "₹"`
in `src/components/chat/visual/format.ts`, and the axis tick in `blocks/Bars.tsx`. The contract doc lists the unit.

## Test Cases
> Authored up front: R2's VA-1…19 re-run against all 13 intents, plus one new case for the new unit.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| VA-1…11/16 | all blocks | each of the 13 intents' real payloads through the chat SSE widget (now incl. `daily_review`) | e2e | header, mode, headline, every block with the payload's own numbers, evidence, data-quality footer, follow-ups, no forbidden word | PASS (13/13) |
| VA-14 | phone, 390px | all 13 intents | e2e | no sideways scroll; charts at real width | PASS (13/13) |
| VA-20 | `₹` bars | a `bars` block with `unit: "₹"` (MOCK values: +95, +131, −40.5) injected into the review payload | e2e | values print `+₹95.00`, `+₹131.00`, `−₹40.50`; the block carries `data-unit="₹"`; the axis ticks carry ₹ | PASS |
| VA-7, 12, 13, 13b, 15 | plan card, follow-ups, tolerance, desk dock | unchanged | e2e | as in R1/R2 | PASS |
| VA-18 | types | `tsc --noEmit -p tsconfig.json` | unit | no errors | PASS |
| VA-17 | regression | copilot-app, -daily-trader, -desk, -desk-copilot-window, -trade-idea, -desk-decision-cards | e2e | no new failures | PASS |

## UI / Playwright Tests
- `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`
- `VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist` → `BUILD_EXIT=0`, `✓ built in 30.99s`.
  The served build was checked to contain the change (`==="₹"?\`${i}₹` found in `index-BxWKNdBO.js`) before testing.
- **Spec:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-visual-answer.spec.ts`
  - Output: `32 passed (30.6s)`, 1 skipped (VA-19 screenshots, only with `VA_SHOTS=1`). Includes
    `VA-1…11/16 daily_review: every part of the payload, with the payload's own numbers`,
    `VA-14 390 px, daily_review`, and `VA-20 a ₹ bars block … — MOCK block`. Release 2 ran 29.
- **Regression:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app.spec.ts e2e/tests/copilot-app-daily-trader.spec.ts e2e/tests/copilot-app-desk.spec.ts e2e/tests/copilot-app-desk-copilot-window.spec.ts e2e/tests/copilot-app-trade-idea.spec.ts e2e/tests/copilot-app-desk-decision-cards.spec.ts`
  - Output: `89 passed (1.2m)`
- Containers `r3review-*` were removed afterwards; no `vite preview` left running.
- **Result:** PASS

## Data Correctness (staging)
The fixture `e2e/fixtures/contract-visual-answer.json` is a real capture (see the backend report). **The real
`daily_review` payload is the empty-trades branch** (no KPI strip, no plan-vs-actual table, no curve), because the staging
account has no closed paper trade. So on real data this spec checks the review's header, fallback headline, risk-check list
and notices; the KPI strip, the plan-vs-actual table and the curve are rendered from MOCK values only in VA-20 (the curve's
unit) and are otherwise UNVERIFIED in the browser. The ranked table and KPI strip are the same components the earlier
intents already exercise on real payloads.

## Not verified / known limits
- Not deployed; no signed-in walk of the live app (`OVERRIDE_dtc_r3_daily_review.md`).
- The 390 px layout of a populated plan-vs-actual table (9 columns) is not exercised: the ranked block's card layout is
  shared with `fno_setups` (7 columns) and `top_opportunities` (9 columns), which pass VA-14, but this table itself was not seen.
- No screenshots were taken for review (`VA_SHOTS` unset).
- Light theme not looked at, as in R1/R2.

## Inputs required from user
- none

## Verdict: PASS
Scope: the frontend renders all 13 real payloads and the new `₹` unit; tsc, build, 32 spec cases and 89 regression cases
passed with the output above. The populated review in the browser on real data and a live walk are open.
