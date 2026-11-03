# Functionality Verification Report — Daily Trader Copilot: the Trader home's six entry points

- **Branch:** feat/daily-trader-copilot (from origin/dev a4294830), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-30
- **Author:** Claude (DESIGN_ENGINEER + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** mocked Playwright on a production build; staging after merge
- **Changed areas:** backend routes/services: no · frontend src: yes (components/DailyTraderPanel.tsx, views/Home.tsx)

## Summary
The owner, 30 Oct, sent a screenshot of the panel and said "Please work on this". The panel reads "NIVESH COPILOT · What would
you like to know today? · Ask in plain English. Get evidence-backed insights and a clear trade plan."
- **Six entry points:** Market pulse, Find opportunities, My positions, F&O strategies, Manage risk and Daily review.
- **Question box:** picking a tile fills it with the tile's lead question, which can be edited. "this stock" is selected,
  so a typed name replaces it, with stock completion.
- **Explore this question** asks the Copilot. The tile's other questions are listed under the button.
- **Where:** the Trader-mode home (Trader mode lands on the desk; "New question" opens this home).
- **Unchanged:** the Investor and Advisor homes.

## Test Cases
> Authored before the spec ran. Spec: `frontend-v5/e2e/tests/copilot-app-daily-trader.spec.ts`.

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| DT-1 | Trader home | The panel: eyebrow, headline, sub, six tiles in the owner's order, Market pulse selected, its lead question in the box, "Explore this question"; no "Try asking" list | PASS |
| DT-2 | Each tile | Its own lead question in the box; exactly one tile selected | PASS |
| DT-3 | "More in Find opportunities" | The tile's other questions; picking "Is this stock a buy now?" selects "this stock" in the box | PASS |
| DT-4 | Type "tvs mo" over the selection | The completion shows TVSMOTOR; Tab gives "Is TVSMOTOR a buy now?" | PASS |
| DT-5 | Explore | `/api/chat/stream` gets the box's question with `persona: "trader"`; the answer shows | PASS |
| DT-6 | Investor mode | No Daily Trader panel; "Try asking" stays | PASS |
| DT-7 | 390 px | Tiles in two columns, no sideways scroll | PASS |
| DT-9 | Trading-desk Copilot dock, empty (1440 px) | The six entry points under the intro; a pick puts its lead question in the dock's box and focuses it, without sending; Send asks it with `surface: trading_desk`; the thread replaces the tiles | PASS |
| DT-8 | Staging after merge | The served bundle has the panel; a signed-in look in Trader mode | PENDING (after merge) |

## Tests run (real output, 2026-10-30)
- `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`.
- `playwright test e2e/tests/copilot-app-daily-trader.spec.ts` (production build, mocked APIs) → `7 passed (4.0s)`: DT-1 … DT-7.
- **A race, found and fixed.** A later run failed DT-4 once in 3 repeats: a name typed straight after picking a question
  could land before "this stock" was selected, because the panel selected it on the next animation frame. The selection now
  happens in the same commit (a layout effect). After the fix, `--repeat-each 5` → `35 passed (19.5s)`, with tsc 0.
- Screenshots of the panel at 1280 px and 390 px were reviewed: the two-column tile grid, the selected tile, the box and the
  button match the owner's screenshot.
- `pytest tests/test_copilot_trade_idea.py` on this branch → `35 passed` (chat path unchanged).
- After merging the visual-answer frontend (feat/dtc-visual-frontend) and adding the dock's entry points: tsc 0, and
  `playwright test copilot-app-desk-copilot-window copilot-app-daily-trader copilot-app-visual-answer copilot-app-desk`
  → `41 passed (52.5s)` (DT-9 included). A dock screenshot at 1440 px was reviewed: two columns of tiles under the intro.

## Not verified
- **DT-8:** the panel on staging. It needs the merge and the frontend deploy; the work is still in progress (the visual
  answers the questions lead to are being built on feat/dtc-visual-backend and feat/dtc-visual-frontend).

## Verdict: BLOCKED
