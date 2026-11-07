# Functionality Verification Report — The trade plan card in plain words, why a plan is blocked, and the payoff today and at expiry

- **Branch:** feat/plain-trade-plan-card (stacked on feat/copilot-floating-window #405 and feat/copilot-stock-autocomplete
  #404), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-29
- **Author:** Claude (DESIGN_ENGINEER + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** mocked Playwright on a production build; the payoff calculation in-process in the staging backend
  container (read only); the served bundle after merge
- **Changed areas:** backend routes/services: no (a backend contract test only) · frontend src: yes

## Summary
The owner's three asks of 29 Oct:
1. "We need to display the trade plan in compact way same as we do today in AI recommendations please remove all
   technicals jargon from full card view".
2. "Also if the trade plan is rejected because of risk and margin issues and guardrails please provide the details and
   way's to override it".
3. "Also we need to show the payoff graph/table with today's date and expiry date".

What was built:
- **Plain card (1).** The trade plan card in plain words: Enter, Exit if wrong, Targets, Size, Max loss, Charges, Hold for.
  The method (ATR, R multiples, order types, rule versions, the plan id) moves to a closed "Technical details".
- **Compact chat card (1).** The Copilot's chat card is the compact row the AI recommendations use. "Full card ›" opens
  the whole card.
- **Top 10 drawer (1).** The drawer's paper-trade lines are in plain words. The scanner's and the structure's own levels
  go under a closed "Technical details".
- **Why not, and what you can do (2).** Every reason a plan is blocked or cut, in plain words, taken from three sources:
  the account sizing, the last limits check, and the plan's own rules. Each reason comes with the allowed ways forward:
  - a smaller size or a closer exit;
  - another structure;
  - closing other trades, or waiting;
  - asking an admin to loosen a limit.

  "Override" is never a way around the check. Users can tighten their own limits, but only an admin can loosen one
  (backend services/risk_profile.py set_limits: admin_required). Every trade is checked again when it is placed.
- **Payoff today and at expiry (3).** An options plan's full card gets a new section, "Profit or loss: today and at
  expiry":
  - **Chart:** two lines, one dated today (estimated) and one dated at the expiry.
  - **Table:** the profit or loss at set moves of the underlying, on both dates.
  - **Source:** one request to the existing payoff calculation (POST /api/desk/strategy/payoff) for the plan's own legs
    and entry prices, at your size. The expiry values are exact. Today's value is the calculation's own estimate
    (Black-76, each option's volatility implied by its entry price), on the same price grid. Every table row is a point
    the calculation priced; nothing is interpolated.

## Test Cases
> Authored UP FRONT. PC/WF cases before the plain-card build; PO cases after the payoff ask and before its
> implementation. Specs: copilot-app-desk-decision-cards, copilot-app-desk-market-overview, copilot-app-desk-top10,
> copilot-app-trade-idea, copilot-app-desk-plan-payoff (new); backend tests/test_plan_payoff_contract.py (new).

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| PC-1 | Top 10 cash row (compact) | Enter / Exit if wrong / Targets / Size / Max loss / Charges in plain words; no ATR, no R multiples, no plan id | PASS |
| PC-2 | Full card | Sections The idea, When to enter, When the idea is wrong, Targets, Money at risk, Charges, Why this idea, Things to watch, How it ends; the method only under a closed "Technical details" | PASS |
| PC-3 | Statuses and limit chips | "Ready to enter", "Not tradeable", "Not yet checked against your limits", "Fits your limits", "Allowed at a smaller size", "Not allowed by your limits" | PASS |
| PC-4 | Copilot chat trade idea | The compact row by default; "Full card ›" opens every section and back; "Paper trade ›" opens the ticket; no jargon in either | PASS |
| PC-5 | Top 10 drawer | Paper-trade line in plain words (the card's own entry/exit/targets); the scanner's and the structure's levels closed under "Technical details" | PASS |
| WF-1 | Plan turned down by its own rules (reward : risk 0.9) | Compact: "Why not: The possible gain is too small for the risk taken. · What you can do: Wait for a better (lower) entry price"; full card: the plan's own message, three options, the last "Ask an admin to loosen…", and the link to Risk Desk › Controls & profile | PASS |
| WF-2 | Kill switch on | "Why not: The kill switch is on… · What you can do: Only an admin can switch trading back on" | PASS |
| WF-3 | Smallest lot above the one-trade limit (min_lot_exceeds_budget) | "Why not: Even the smallest size (one lot) would risk more than your limit for one trade." | PASS |
| WF-4 | A plan sized within the limits (a limit set the size) | No "Why not" line: the size shown is already allowed | PASS |
| PO-1 | Options plan, full card | Section "Profit or loss: today and at expiry" with a chart and a table; the compact row has none; a cash plan's full card has none | PASS |
| PO-2 | The request | Exactly the contract body: the plan's legs at your lots per leg, the reference close, as_of = the chain date, a grid in 0.125% steps covering the strikes, exit and targets, `pre_expiry.date` = today (IST) | PASS |
| PO-2b | A Strategy Builder / Copilot plan (an `fno` date, no `chain` date; found on staging after the merge) | The same request; "Option prices of 21 Oct 2026" names its day | PASS |
| PO-3 | The chart | Two lines named with their dates: "Today, 22 Oct 2026 (estimated)" and "At expiry, 27 Oct 2026"; the price now, the exit and the targets marked | PASS |
| PO-4 | The table | One row per set move (0 = now); the Today and At expiry cells equal the answer's after-charges values at those exact grid points | PASS |
| PO-5 | Today on or after the expiry | No estimate is asked for; the expiry line and column only, with "These options expire(d) on …" | PASS |
| PO-6 | Estimate unavailable for a leg | The expiry line and column, and why there is no estimate today, in plain words | PASS |
| PO-7 | The calculation fails | "The profit or loss could not be worked out just now: …" with Try again; no empty chart | PASS |
| PO-8 | No jargon in the section | No Greeks, Δ/Θ, Black-76, gross/net, R multiples | PASS |
| PO-9 | 390 px | No sideways page scroll; the table scrolls inside itself | PASS |
| PO-10 | Backend contract | The body the card sends is accepted by the real compute_payoff: valid, an estimate grid for today, the grid points at the set moves; the response fixture the spec answers with is compute_payoff's own output | PASS |
| PO-11 | Staging | compute_payoff in the staging backend container on the contract body: valid, today line present (read only, in-process) | PASS |
| RG-1 | Regression: desk decision cards, market overview, top 10, trade desk, live chart, risk desk, lab, scanner, strategy builder, watchlists, AI watchlist, trade idea, stock complete, Copilot window | No new failure | PASS |
| RG-2 | `tsc --noEmit` | exit 0 | PASS |
| ST-1 | Staging after merge | The served bundle has the plain card, the "Why not" line and the payoff section; a manual look with a session at a live F&O plan's full card | PENDING (after merge) |

## Tests run (real output, 2026-10-29)
- **tsc:** `tsc --noEmit` → `TSC_EXIT=0`.
- **Full regression, 17 specs:** decision-cards, market-overview, top10, trade-desk, live-chart, risk-desk, desk-lab,
  scanner, strategy-builder, audit-wave1, ai-watchlist, watchlists, trade-idea, strategy-builder-live, watchlist-unauth,
  stock-complete and copilot-window, on a production build with mocked APIs.
  - **Before the last edits:** `441 passed (4.6m)`, 16 skipped, 0 failed.
  - **After the last edits** (plain "Wrong if", table cells that don't wrap): `439 passed`, 16 skipped, and 2 failed. Both
    failures were my new "Wrong if" assertions: the row's label and value are separate spans, so the text has no space.
    They now match the value alone.
  - **Final run of that spec:** `copilot-app-desk-decision-cards.spec.ts` → `35 passed (37.2s)`. This includes UI-2,
    UI-8c (WF-1), UI-8f2 (WF-2), UI-16 and PO-1 … PO-9.
  - **The 16 skipped** were skipped before this work too: 2 opt-in lab screenshot tests and 14 gated strategy-builder tests.
- **Earlier runs:**
  - TI-13b (PC-4) passed in `40 passed (37.1s)` with market-overview.
  - The Top 10 and market-overview drawer cases (PC-5, MO-20, L-1, UI-1) passed in `62 passed (42.5s)`.
- **Backend contract (PO-10):**
  - `pytest tests/test_plan_payoff_contract.py tests/test_strategy_payoff.py tests/test_decision_card_contract.py
    tests/test_trade_plan_contract.py tests/test_payoff_cost_card.py` → `113 passed, 1 skipped`, in the backend image
    with no network.
  - `contract-plan-payoff.json` is the real route's output (written by the test with CONTRACT_FIXTURES_OUT). The
    hand-worked bounds hold: at expiry the most it makes is (900 − 292.30) × 30 = ₹18,231, and the most it loses
    292.30 × 30 = ₹8,769.
- **Staging (PO-11):**
  - `compute_payoff` ran in-process in the running `nivesh-staging-app-backend` container on the contract body (read
    only). Output: `staging engine payoff-v2 | valid True | problems [] | pre_expiry date 2026-10-22 model Black-76
    unavailable []`, `grid points 65 | today points 65`.
  - At −2%: today +10,054.89, expiry +18,025.73. Now: today −375.96, expiry −8,171.49.
  - `identical to the fixture (before expiry): True | on the expiry day: True | on-expiry pre_expiry: None`.
- **Visual check:** screenshots of the payoff section at 1440 and 390 px and of the "why not" section, reviewed.
  - The first phone version had unreadable axis text and pushed the expiry column out of view. Fixed: the chart is
    drawn at its real width, and the move sits inside the price cell. PO-9 now checks that both columns fit.

## Staging after the merge (real output, 2026-10-29)
- **The merged code, tested before the merge** (dev 9 commits ahead, including #406 and #407; a local merge, since
  removed):
  - `tsc` → `TSC_EXIT=0`.
  - 18 specs, the 17 above plus portfolio-fno: `473 passed`, 0 failed, 27 skipped. All 27 skips were skipped before:
    hard-coded `test.skip` or opt-in.
  - Backend: `204 passed, 1 skipped`, including test_kite_day_quote, test_desk_live_chart, test_copilot_trade_idea and
    the payoff and contract suites.
  - GitHub CI "Backend unit tests (allowlist)" on #408: success.
- **Merge:** #408 merged at the owner's request (`dev` be0ba7de). GitHub then marked #404 and #405 as merged too, since
  their commits came with it.
- **Deploys:** backend, frontend and Android all succeeded. The backend container restarted at
  `2026-10-29T13:09:54Z`.
- **Served bundle:** `grep -rlF` finds 2 files each for "Profit or loss: today and at expiry", "What you can do",
  "Why a smaller size", "Not yet checked against your limits" and "Technical details · the scanner", and 4 files for
  "Full card ›". `/api/healthz` returns 200. POST /api/desk/strategy/payoff signed out returns 401.
- **Live plans, today's date (read only):** the three newest options plans still before expiry in staging's
  `trade_plans` were ADANIPORTS covered call, long call and bull call spread, expiry 23 Nov 2026. For each, the card's
  request with today (2026-10-29) went through the deployed calculation in-process: `valid True`, today estimate
  `2026-10-29`, no leg unavailable, 321 points, and every table move on the grid (`on-grid=True`). For example, the
  bull call spread now: today −215.84, at expiry −7,798.18. At +10%: today +8,689.74, at expiry +10,296.19.
- **The F&O-date fix (PO-2b):** these live plans showed one gap. 15 of staging's 315 options plans (the Strategy
  Builder's and the Copilot's) date their prices as `fno`, with no `chain`. The request already used `fno`, but the
  label only read `chain`, so it would have said "the plan's day". Fixed in fix/plan-payoff-fno-date: tsc 0, decision-cards
  + trade-idea `42 passed`, backend payoff tests `69 passed`.

## Not verified
- **ST-1 (the rest):** a signed-in look at a live F&O plan's full card. The bundle and the calculation on live plans are
  checked above; the rendered screen with a session is not.

## Inputs required from user
- A signed-in look at a Copilot or Top 10 options plan's full card.

## Verdict: BLOCKED
