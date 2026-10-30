# Functionality Verification Report — Daily Trader Copilot visual answer (frontend, Release 2)

- **Branch:** feat/dtc-r2-answers (based on feat/daily-trader-copilot, PR #419)
- **Date:** 2026-10-30
- **Author:** Claude (DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** production build (`vite build`, base `/v5/`) served by `vite preview` in the Playwright container;
  every `/api` call mocked except the fixture payload itself, which is a real staging capture. Not deployed to staging.
- **Changed areas:** backend routes/services: no (see `dtc_r2_visual_backend_20261030.md`) · frontend src: no new
  component code — this report's own changed files are the e2e spec and its fixture

## Summary
Release 1's block registry (`frontend-v5/src/components/chat/visual/blocks/registry.tsx`) is keyed only by block
type (kpis, candles, bars, heatmap, quadrant, ranked, trade_plan, list, notice), never by intent name. Since
Release 2's 5 new intents (`open_trades`, `fno_setups`, `trade_validity`, `exit_options`, `position_size`) only use
block types R1 already renders, no frontend component change was needed. What this report verifies is that the
existing, generic Playwright spec (`copilot-app-visual-answer.spec.ts`) — whose assertions are driven entirely by
each payload's own data, never a hardcoded expectation per intent — genuinely exercises the 5 new intents, not only
report "passed" because it silently skipped them.

## Found before any fix: the existing spec was not testing the new intents
The spec's per-intent parametrized tests loop over a hardcoded `INTENTS` constant
(`const INTENTS = ["market_view", ..., "expected_move"].filter(...)`), which listed only R1's 7 intent names. The
real 12-intent capture (`contract-visual-answer.json`) already contained the 5 new payloads, but the spec's own run
reported `19 passed, 1 skipped` without ever asserting on them — a clean-looking result that was not actually
checking the new work. Fixed by extending `INTENTS` to the full 12.

## Test Cases
> Authored up front: this report re-runs R1's VA-1…19 cases (`dtc_visual_frontend_20261030.md`), now against all 12
> intents, plus two new ones found while doing it.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| VA-1…11/16 | all blocks | each of the 12 intents' real payloads through the chat SSE widget | e2e | header, mode, headline, decision (if any), every block type with the payload's own numbers, evidence, data-quality footer, follow-ups, no forbidden word | PASS (12/12, was 7/12) |
| VA-7 | ranked→plan | a ranked row with a plan id (now `fno_setups`, not only `top_opportunities`) | e2e | opens the desk's plan card for that id | PASS |
| VA-12 | follow-ups | click a follow-up / a ranked row's Ask | e2e | sends that query as the next chat question | PASS |
| VA-13 / 13b | tolerance | unknown block, bad block, non-contract payload | e2e | graceful "not supported" / "could not be shown" / short note, thread never crashes | PASS |
| VA-14 | phone, 390px | all 12 intents | e2e | no sideways scroll; charts at real width | PASS (12/12, was 7/12) |
| VA-15 | desk dock | `stock_decision` inline in the 1440px dock | e2e | compact render, surface `trading_desk` on ask and follow-up | PASS |
| F1 | compliance | the forbidden-word check (`not /\b(buy now\|strong buy\|recommended\|pick)\b/i`) now runs against `trade_validity`'s real payload | e2e (found this session) | **FAILED first**: `trade_validity`'s follow-ups literally read `"Is PNB a buy now?"`. Root cause: 3 of the 5 new backend builders generated this exact phrase as a suggested follow-up/row-ask. Fixed in the backend (`builders.py`, see the backend report) and re-verified on a fresh real re-capture | PASS (after the backend fix) |
| T1 | test helper | the stale-banner text check with a source whose `as_of` is `null` (`fno_setups`, `position_size`) | e2e (found this session) | **FAILED first**: the test built the expected string with `fDay(null)` → `"Invalid Date"`, but the component correctly renders `"date unknown"` for a null date (it already does this correctly elsewhere, `va-source-asof` uses `"no date"`) — a gap in the test helper, not the product. Fixed the helper to match the component's own fallback text | PASS (after the test fix) |
| VA-18 | types | `tsc --noEmit -p tsconfig.json` | unit | no errors | PASS |
| VA-17 | regression | copilot-app, -daily-trader, -desk, -desk-copilot-window, -trade-idea, -desk-decision-cards | e2e | no new failures | PASS |

## UI / Playwright Tests
All runs used `mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`, a production build
(`VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist`) served by
`vite preview --outDir /tmp/cp-dist --port 5174 --strictPort`, and `pw.copilot-app.config.ts`.

- `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`
- `vite build` → `BUILD_EXIT=0`, `✓ built in 22.21s`
- **First run (before the compliance fix), extended `INTENTS`:**
  ```
  3 failed
    VA-1…11/16 fno_setups       — stale-banner text, fDay(null) ("Invalid Date" vs actual "date unknown")
    VA-1…11/16 trade_validity   — forbidden word: payload literally contains "Is PNB a buy now?"
    VA-1…11/16 position_size    — stale-banner text, same fDay(null) issue
  26 passed (22.6s)
  ```
- Backend fix applied (`builders.py`: `"Is {sym} a buy now?"` / `"Is this stock a buy now?"` → `"What's the setup for
  {sym}?"` / `"What's the setup on this stock?"`), fixture re-captured live from staging (see the backend report),
  test helper fixed (`fDay(s.as_of)` → `s.as_of ? fDay(s.as_of) : "date unknown"` in the stale-banner check).
- **Final run, spec:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-visual-answer.spec.ts`
  - Output: `29 passed (18.0s)`, 1 skipped (VA-19 screenshots, only with `VA_SHOTS=1`)
- **Final run, broader regression:** `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app.spec.ts e2e/tests/copilot-app-daily-trader.spec.ts e2e/tests/copilot-app-desk.spec.ts e2e/tests/copilot-app-desk-copilot-window.spec.ts e2e/tests/copilot-app-trade-idea.spec.ts e2e/tests/copilot-app-desk-decision-cards.spec.ts`
  - Output: `89 passed (48.2s)`
- **Result:** PASS

## Data Correctness (staging)
The fixture (`e2e/fixtures/contract-visual-answer.json`) is a real, re-captured staging read (see the backend
report's "Real staging capture" section for the exact command and output); this spec asserts the UI shows exactly
what that payload contains, nothing invented. The forbidden-word check (F1 above) is itself a data-correctness check
on the real captured text, not a synthetic one — it is what caught the "buy now" bug.

## Inputs required from user
- none

## Verdict: PASS
Scope: the frontend spec's coverage of all 12 visual-answer intents (7 from R1 + 5 from R2) against a real staging
capture, plus the regression set. Two defects were found and fixed in the course of this verification (a real
compliance-wording bug in the backend, and a test-helper gap for a null date) — both documented above with their
real before/after command output, not only described. A live signed-in staging walk (clicking through the deployed
app) remains open, same as R1 — see `dtc_visual_frontend_20261030.md`'s equivalent note.
