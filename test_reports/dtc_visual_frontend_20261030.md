# Functionality Verification Report — Daily Trader Copilot visual answer (frontend)

- **Branch:** feat/dtc-visual-frontend
- **Date:** 2026-10-30
- **Author:** Claude (DESIGN_ENGINEER + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** production build (`vite build`, base /v5/) served by `vite preview` in the Playwright container; every
  /api call mocked. Not deployed to staging.
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
The chat renders the `visual_answer` widget (contract `docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md`,
`visual-answer-v1`) as a visual decision dashboard. That covers the app's thread view (ChatWidget) and inline in the
trading-desk Copilot dock. The backend builder is a separate agent's work. Until its real capture
(`e2e/fixtures/contract-visual-answer.json`) exists, the spec reads `e2e/fixtures/visual-answer.mock.json`, which is
labelled MOCK — not real data.

## Test Cases
> Authored up front (after the contract and the UI design, before the implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| VA-1 | header | each of the 7 intents' payloads through the real chat (SSE widget frame) | e2e | title, "Data of <as_of>" with the mode (Live / End of day / Mixed) and the headline are the payload's own | PASS |
| VA-2 | kpis | a kpis block | e2e | one tile per item; label and value from the payload | PASS |
| VA-3 | candles | a candles block | e2e | the desk's CandleChart: one candle per bar, every level as a dashed line with its price, the band's low and high, EMA lines drawn; the levels and band also listed as text | PASS |
| VA-4 | bars | h and v bars, ₹ Cr and × units, signed values, baseline | e2e | one bar per item; each value printed in the block's unit; a negative bar is drawn below zero in the danger colour; the baseline line is drawn when given | PASS |
| VA-5 | heatmap | a sector heatmap | e2e | one tile per cell with its label and signed %; up tiles mint, down tiles danger | PASS |
| VA-6 | quadrant | an F&O buildup quadrant | e2e | one point per point; the four quadrant names; a text table lists each point with x and y | PASS |
| VA-7 | ranked | a ranked table with ask and plan_id rows | e2e | one row per row, cells in their format; "Ask" sends the row's question; a plan_id row opens that plan (DecisionCard by id) | PASS |
| VA-8 | trade_plan | a trade_plan block | e2e | the desk's compact DecisionCard row for that plan id | PASS |
| VA-9 | list / notice | warnings list and a warn notice | e2e | every item's text; a warn notice is shown as a warning | PASS |
| VA-10 | decision | stock_decision payload | e2e | the decision label, reason, each condition with met / not met, the invalidation | PASS |
| VA-11 | data quality | a payload with a stale source and a missing item | e2e | each source with its date and fresh / stale / missing; a stale payload shows a loud warning at the top; missing items listed | PASS |
| VA-12 | follow-ups | click a follow-up button | e2e | the chat sends that follow-up's query as the next question | PASS |
| VA-13 | tolerance | unknown block type; a known type with bad data; a payload that is not visual-answer-v1 | e2e | "not supported yet" note for the unknown one, "could not be shown" for the bad one, the rest renders; a bad payload shows a short note and does not crash the thread | PASS |
| VA-14 | phone | every intent at 390 px | e2e | no sideways scroll on the page; charts drawn at their real width | PASS |
| VA-15 | desk dock | ask in the trading-desk dock at 1440 px | e2e | the visual answer renders inline in the dock (compact), not "open the full thread"; its follow-up asks again with surface trading_desk | PASS |
| VA-16 | evidence / caveat | any payload | e2e | each evidence row (label, value, source, date) and the caveat | PASS |
| VA-17 | regression | copilot-app-trade-idea, -desk, -desk-copilot-window, -desk-decision-cards | e2e | no new failures against the baseline taken before the change | PASS |
| VA-18 | types | `tsc --noEmit -p tsconfig.json` | unit | no errors | PASS |
| VA-19 | visual | element screenshots at 1440 and 390 px, read by eye | manual | legible, nothing clipped or overflowing | PASS |

## API / Endpoint Tests (staging)
Not applicable: no backend change in this branch. The backend payload is another agent's branch.

## UI / Playwright Tests

All runs used `mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`, a production build
(`VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build`) served by `vite preview` on :5174, and `pw.copilot-app.config.ts`.

- **Baseline, before any change to a shared file** (the four regression specs, untouched branch at 21c8ae13):
  - Output: `53 passed (30.0s)`
- **Final run** (the commit's code; one build, then both test sets):
  - `npx tsc --noEmit -p tsconfig.json` → `TSC-EXIT=0` (no error lines)
  - `vite build` → `BUILD-EXIT=0`, `✓ built in 24.30s` (only the usual chunk-size advice)
  - **Spec:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-visual-answer.spec.ts --reporter=list`
    (with `VA_SHOTS=run4`, which also writes the review screenshots). Output (spec path shortened):
```
Running 20 tests using 3 workers

  ✓   2 [copilot-app] VA-1…11/16 market_view: every part of the payload, with the payload's own numbers (1.9s)
  ✓   3 [copilot-app] VA-1…11/16 top_opportunities: every part of the payload, with the payload's own numbers (2.1s)
  ✓   1 [copilot-app] VA-1…11/16 smart_money: every part of the payload, with the payload's own numbers (2.3s)
  ✓   4 [copilot-app] VA-1…11/16 breakouts: every part of the payload, with the payload's own numbers (2.0s)
  ✓   5 [copilot-app] VA-1…11/16 unusual_volume: every part of the payload, with the payload's own numbers (1.9s)
  ✓   6 [copilot-app] VA-1…11/16 stock_decision: every part of the payload, with the payload's own numbers (2.0s)
  ✓   7 [copilot-app] VA-1…11/16 expected_move: every part of the payload, with the payload's own numbers (1.7s)
  ✓   9 [copilot-app] VA-7 a ranked row with a plan id opens the desk's plan card for that id (1.7s)
  ✓   8 [copilot-app] VA-12 a follow-up button asks its question; a ranked row's Ask asks the row's question (2.4s)
  ✓  10 [copilot-app] VA-13 an unknown block says 'not supported yet', a bad one says it could not be shown, and the rest still renders (1.6s)
  ✓  11 [copilot-app] VA-13b a payload that is not visual-answer-v1 shows a short note; the written answer still shows (1.4s)
  ✓  12 [copilot-app] VA-14 390 px, market_view: no sideways scroll; charts drawn at their real width (2.6s)
  ✓  14 [copilot-app] VA-14 390 px, top_opportunities: no sideways scroll; charts drawn at their real width (2.0s)
  ✓  13 [copilot-app] VA-14 390 px, smart_money: no sideways scroll; charts drawn at their real width (2.6s)
  ✓  15 [copilot-app] VA-14 390 px, breakouts: no sideways scroll; charts drawn at their real width (2.1s)
  ✓  16 [copilot-app] VA-14 390 px, unusual_volume: no sideways scroll; charts drawn at their real width (2.1s)
  ✓  17 [copilot-app] VA-14 390 px, stock_decision: no sideways scroll; charts drawn at their real width (2.3s)
  ✓  18 [copilot-app] VA-14 390 px, expected_move: no sideways scroll; charts drawn at their real width (1.9s)
  ✓  19 [copilot-app] VA-15 on the trading desk the Copilot dock shows the visual answer inline, compact; its follow-up asks again from the desk (2.5s)
  ✓  20 [copilot-app] VA-19 screenshots at 1440 px (only with VA_SHOTS=1) (8.2s)

  20 passed (21.6s)
```
  - **Regression:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-trade-idea.spec.ts e2e/tests/copilot-app-desk.spec.ts e2e/tests/copilot-app-desk-copilot-window.spec.ts e2e/tests/copilot-app-desk-decision-cards.spec.ts --reporter=list`
    - Output: `53 passed (33.8s)`. Same count as the baseline; no new failures.
- **Earlier runs, same session:**
  - Run 1: spec 20 passed and regression 53 passed, but tsc reported 2 type errors (`PeriodKey` imported from the wrong
    module; a span given a div's ref). Fixed.
  - Run 2: tsc clean, spec 20 passed. Its screenshots were clipped by the thread's scroll container, so the screenshots
    were changed to one per part.
  - Run 3: tsc clean, spec 20 passed, per-part screenshots, reviewed below.
- **Result:** PASS

### Visual review (VA-19)
Element screenshots, one per part of each answer: header, stale banner, decision, every block, data-quality footer.
They cover the thread at 1440 px and 390 px and the desk dock at 1440 px. The 83 PNGs are in
`frontend-v5/e2e/.shots/visual-answer-run4/` (git-ignored) and copied to
`/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad/va-shots-run4/`.

Read by eye. Fixed after run 3, then checked again in run 4:
- **Phone ranked cards:** a column name was cut to "Buil…" and the words wrapped. Text columns now take the full card
  width, figures sit two to a line, and the rank is in the heading ("#1 ICICIBANK").
- **Quadrant:** a point near a corner overlapped that corner's quadrant name. The plot now has ×1.35 headroom.
- **MOCK fixture:** it contradicted itself. The FII bars put −₹943.60 Cr on 16 Oct while the KPI says it was 29 Oct's.
  The series are now oldest first.

Left as is (legible, minor): at 1440 px the value list under vertical bars has a tight 12 px gap between columns.

## Data Correctness (staging)
UNVERIFIED. No real payload exists yet: the backend builder (`backend/services/copilot_visual/`) is another agent's
branch, and its capture `e2e/fixtures/contract-visual-answer.json` was not written. Every number this report shows
rendered comes from `e2e/fixtures/visual-answer.mock.json` (MOCK — not real data, generated by
`e2e/tools/make_visual_answer_mock.py`). Checking the data needs:
1. The backend's real capture. The spec switches to it automatically when the file exists, and it must be
   `{ about, payloads: { <intent>: payload } }` or an array of payloads.
2. A deploy of both branches to staging, then one question per intent asked there, comparing the dashboard's numbers
   with the sources named in its data-quality footer.

## Not verified / known limits
- Not deployed; nothing was checked on staging (see above).
- The candle chart's band is drawn across the whole price pane, as the desk's CandleChart draws it. "Shaded band" is
  named in the legend and its range is printed under the chart with the payload's label (e.g. "Expected move to
  4 Nov"). History (the candles) and that range are told apart in words, not by drawing the band only to the right of
  the last candle; that would need a CandleChart change, which the contract did not require.
- Light theme not screenshotted (the config runs dark). Every colour is a house token, but light mode was not looked at.
- `bars.baseline` is read as a reference line (bars still start at zero); the contract does not say which.

## Inputs required from user
- none

## Verdict: PASS
Scope: the frontend, on the MOCK fixture, in a production build with mocked APIs. All 19 test cases passed with the
output above. The data check on staging is open (UNVERIFIED above) until the backend capture and a deploy exist.
