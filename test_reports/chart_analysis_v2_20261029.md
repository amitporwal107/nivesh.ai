# Functionality Verification Report — Chart Analysis v2 (new chart interface) + Strategy Lab removed

- **Branch:** feat/chart-analysis-v2 (final commit 462c0b45)
- **Date:** 2026-10-29
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER)
- **Environment:** branch build (mocked APIs, Playwright) + staging READ-ONLY in-process probes (nivesh-staging-app-backend, real data); NOT deployed
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Trade Desk › Chart Analysis › Live chart is replaced by the owner's "Nivesh Chart" design (29 Oct) on real routes: header
with state and LAST (Kite close until EOD), six stats, SIGNALS ON CHART chips (+ Events), readout, one chart (candles, EMA,
walls, max pain, WATCH/READY/RVOL/✓, trade lines with draggable STOP/TGT, futures OI line, OI Δ per bar, LB/SB/SC/LU row,
strike ladder OI/OI Δ/VOLUME), option chain with B/S and OI/GREEKS, expiry pills Current/Next/Far/Consolidated, summary lines,
"Strategies that fit" (the plan engine's candidates; the design's "Recommended" is not used per the desk wording rule),
paper basket (cash/future/options, presets, stop/target, place) and strategy panel (legs + Greeks, margin + hedge benefit,
payoff today/expiry, 11-level scenario table). Backend: futures daily series and daily build-up windows (BE-1), consolidated
chain (BE-2), payoff scenario Greeks (BE-3), margin hedge benefit (BE-4). Strategy Lab is removed completely: section, Build a
trade wizard, Backtest & validation, the "From an idea" Strategy Builder screens; every lab URL and button opens Chart Analysis
with its stock and plan. Test cases and contracts: test_reports/chart_analysis_v2_TESTCASES.md (authored before implementation).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| D1–D4 | BE-1 | daily series per slot, roll keeps the contract's own OI change, consolidated sums, daily=0/251, daily windows | unit | values | PASS |
| K1–K2 | BE-2 | consolidated chain sums per strike, one-expiry strike, 404 | unit | values | PASS |
| G1–G2 | BE-3 | scenario Greeks = curve model; unpriceable leg → null + reason | unit | equal / null | PASS |
| M1–M2 | BE-4 | hedge benefit = legs alone − basket; one leg 0; failed leg → null | unit | 89,320 / 0 / null | PASS |
| S1 | staging | TVSMOTOR oi-buildup daily=60 current OI = bhavcopy | data | equal | PASS (backend report) |
| S2 | staging | TVSMOTOR consolidated 4300 CE OI = sum of 3 expiries | data | equal | PASS (backend report) |
| S3 | staging | bull call spread scenario Greeks at spot = pre_expiry.greeks | data | equal | PASS (backend report) |
| S5 | staging | margin hedge benefit on a real spread; single leg 0 | data | legs alone − basket | PASS (below) |
| S6 | staging | plan route answer for TVSMOTOR parses through the cards' code | data | cards / no-trade | PASS (below) |
| U1–U4, U10–U13, KC, TC-10 | page | header/stats, toggles, ladder, expiries + consolidated, daily OI, Kite close, drag lines, phone, not in F&O, lab URLs, no prices | e2e | text/attrs/requests | PASS |
| U3–U6, U11 (chain) | chain + cards | chain B/S, OI/GREEKS, consolidated off, live-quote rule, cards order/figures, ADD TO BASKET, states | e2e + unit | legs/text | PASS |
| U6–U9, U11 (basket) | basket + panel | presets, payoff/scenarios, margin + hedge benefit, place bodies (strategy / share trade), refusal, phone, header/leg column alignment | e2e + unit | bodies/text | PASS |
| Regression | Trade Desk | every copilot-app-desk* spec + AI watchlist + trade idea + chart specs | e2e | no failures | PASS |
| S4 | deployed | the screen on staging with real data | e2e/data | — | NOT RUN: not deployed (post-deploy check, outside this verdict) |

## API / Endpoint Tests (staging)
Backend changes were NOT deployed. Staging checks ran in-process inside nivesh-staging-app-backend with the branch's backend
copied to a temporary folder, a fake user, nothing written (the plan's trade-plan store step skipped), nothing restarted; the
temporary files were removed afterwards (`docker exec … ls /tmp | grep -c cav2` → 0).

- **S1–S3:** test_reports/chart_analysis_v2_backend_20261029.md (real output: TVSMOTOR current-month OI 6,787,725 = /futures;
  4300 CE consolidated OI 263,550 = 254,625 + 8,925 + 0; scenario Greeks at +0% = pre_expiry.greeks exactly).
- **S5 (margin, BE-4)** — Zerodha's calculator through the platform Kite session (a calculation; nothing placed):
  ```
  MARGIN spread {"ok": true, "required_margin": 33267.5, "initial_margin": 47075.0, "hedge_benefit": 89320.0, "hedge_benefit_basis": "the legs' margins one at a time (Zerodha's calculator, each leg alone) less the basket's margin", "as_of": "2026-10-29"}
  MARGIN short call alone {"ok": true, "required_margin": 101727.5, "initial_margin": 115535.0, "hedge_benefit": 0.0}
  ```
  Raw Kite totals: long 4300 CE alone 20,860; short 4400 CE alone final 101,727.5; spread final 33,267.5 →
  20,860 + 101,727.5 − 33,267.5 = 89,320. The first version (initial − final) was WRONG: a single sold call also showed
  13,807.5 (its premium credit). Found by this data test, fixed (commit 2afc4aca), re-probed above.
- **S6 (plan route → strategy cards)** — the plan's read path for TVSMOTOR, then the JSON through PlanSchema + reco-data:
  ```
  PLAN bullish: 6.2s status=plan preferred=combination:covered_call candidates=8 actionable=2
  PLAN bearish: 1.6s status=no_trade preferred=None candidates=5 actionable=0
  bullish: status=plan cards=2 …
    PRIMARY combination:covered_call | BUY SHARES · SELL 4500 CE | maxProfit 53611.25, maxLoss −733888.75 (price to zero, labelled), rr 3.24 after costs, breakeven 4193.65
    ALTERNATE options:bull_call_spread | BUY 4300 CE · SELL 4500 CE | maxProfit 22855, maxLoss −12145, rr 1.85 after costs, breakeven 4369.4, net debit 12145
  bearish: status=no_trade cards=0 … no trade: 3 items conflict with the bearish view against 1 that support it … / Cash plans are long only … / Short covering is a rise on falling open interest …
    1 passed (1.2s)
  ```
  (Staging's pattern engine answered 503 and nidp.security_reference_daily is missing; the plan engine already handles both.)
- **pytest** (every backend test file importing a changed module, 45 files, `nivesh/backend:staging`, no network):
  `1538 passed, 1 skipped, 3 warnings in 90.37s` — Result: PASS. Margin + payoff + leg-limit + risk gate after the BE-4 fix: `184 passed`.

## UI / Playwright Tests
Mocked APIs (labelled MOCK in every spec), production build, `pw.copilot-app.config.ts`, Playwright 1.47 container.
- `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0` (after the last code change).
- Chart specs after the last two UI fixes: copilot-app-desk-chart-analysis + copilot-app-chart-analysis-chain + copilot-app-chart-analysis-basket → `42 passed (25.0s)`.
- Full regression on the final commit 462c0b45 — every `copilot-app-desk*.spec.ts` (except strategy-graphs), the three chart
  specs, `copilot-app-ai-watchlist`, `copilot-app-trade-idea`: `BUILD_EXIT=0` · `13 skipped` · `704 passed (7.0m)` · 0 failed.
  The 13 skips are pre-existing opt-in skips (11 `test.skip` in copilot-app-desk-portfolio-fno, a screenshot folder, SCORECARD_URL).
- `copilot-app-desk-strategy-graphs.spec.ts` needs a `VITE_STRATEGY_HARNESS=1` build: `BUILD_H_EXIT=0` · `32 passed (22.6s)`
  on commit 7f4e56fb (later commits touch only StrategyPanel and AnalysisChart, which that harness does not mount).
- Design review screenshots (mocked data, e2e/.shots, not committed): desktop page with ladder/chain, desktop basket + strategy
  panel, 390 px. Two defects found and fixed from them: legs table columns shifted one place (ce4d3e46, now asserted in the
  basket spec), MAX PAIN tag crossed by an entry line at the same price (462c0b45, now asserted).

## Data Correctness (staging)
- S1–S3 (backend report) and S5–S6 above: figures equal the bhavcopy / chain routes / Zerodha's calculator; no figure is made up
  on the screen (every number is a route's; gaps show "—" with the reason, e.g. IV percentile "not recorded" until 252 sessions).

## Inputs required from user
- none

## Not verified (outside this verdict)
- S4: the deployed screen on staging with real data — the branch is not deployed (needs the PR merged and a deploy).
- Live in-session paths (Kite live LTP on the chain, 15m futures bars) were exercised with mocks only today; staging probes ran after the close.

## Verdict: PASS
