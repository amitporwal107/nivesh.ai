# Functionality Verification Report — Trader mode: the right questions, a strip that stays, and a Market pulse like the desk's regime card

- **Branch:** fix/trader-prompts-entry (from origin/dev 82580088)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** backend tests in `nivesh/backend:staging` (`--network none`); the capture ran read-only in-process inside
  `nivesh-staging-app-backend` against the real NIDP warehouse, Mongo and app Postgres; Playwright in
  `mcr.microsoft.com/playwright:v1.47.0-jammy` on a production build with mocked `/api`. Not deployed.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner's screenshots of 31 Oct showed three problems.
1. **The advisor's list in Trader mode.** The ask box listed "Which clients should I call today?" / "ranked for your client
   book" on a Trader screen. `GET /api/copilot/suggested-prompts` chose the advisor set from the account alone (it owns an
   advisory workspace) and the app sent no mode. The route now takes `mode`: the client book is for Advisor mode (or no mode,
   for older clients) only, and Trader mode gets the Daily Trader questions.
2. **The entry screen disappears after a question.** The six entry points live only in the empty state. A strip
   (`DailyQuestionBar`) now stays under a Trader's conversation (app thread and desk dock): a chip per entry point, and the
   chosen one lists its question set.
3. **Market pulse as charts with a regime outlook, like the desk's Market regime card.** `market_view` now reads: day tiles,
   a regime row (the market state the risk service sizes new paper trades with, the size-limit rule, how old the state is),
   FII/DII bars, leading and lagging sector bars, the Nifty chart, then the sector heatmap.

## Test Cases
> Authored up front, after reading the three screens and before the edits.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| PM-1 | backend | advisor-workspace owner, `mode=trader` (any case or spaces) | unit | trader list; no advisor prompt | PASS |
| PM-2 | backend | ordinary account, `mode=trader` | unit | trader list | PASS |
| PM-3 | backend | advisory account with `mode=advisor`, no mode, or an unknown mode | unit | the client book (older clients unchanged) | PASS |
| PM-4 | backend | `investor` (either account), `advisor` on an ordinary account, no mode on an ordinary account | unit | falls through to the investor's own portfolio prompts | PASS |
| PM-5 | backend | every trader question | unit | resolves to its visual-answer intent (the "avoid today" question takes the usual path); no badge; no buy-now wording | PASS |
| PM-6 | backend | the top five | unit | cover Market pulse, Opportunities, Positions, F&O, Risk | PASS |
| B-1 | backend | Market pulse payload | unit | block order: day tiles, regime, flows, sector moves, chart, heatmap | PASS |
| B-1b | backend | regime row | unit | BEAR halves, VIX 25 halves, VIX 35 defers, BULL not cut; stale state is flagged | PASS |
| B-1c | backend | market state unreadable | unit | said as missing, no regime shown, none in the headline | PASS |
| DT-8 | e2e | Trader home, ask box opened | e2e | request carries `mode=trader`; trader questions; no client-book wording | PASS |
| DT-9 | e2e | ask from the entry panel, then use the strip | e2e | panel gone, strip with the six chips; a chip lists its set; a click asks as a trader and closes the list | PASS |
| DT-10 | e2e | Investor thread | e2e | no strip | PASS |
| DT-11 | e2e | 390 px | e2e | no sideways page scroll | PASS |
| VA-1…16 | e2e | all 13 intents from the real capture, including the new Market pulse | e2e | every part of each payload with its own numbers | PASS |
| REG | e2e | seven Copilot specs | e2e | no regression | PASS (after one fix, below) |

## API / Endpoint Tests (staging)
No new route; the existing route gained a parameter. The Market pulse builder was run in-process against real staging data,
auth and writes stubbed, overlay `/tmp/ov_entry` removed afterwards.

- **pytest:** `tests/test_copilot_prompts_mode.py tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_trade_idea.py tests/test_copilot_advisor_self_mode.py`
  - Output: `221 passed` (the new file alone: `11 passed`)
- **Full CI allowlist** (286 files; the new test file is in it):
  - Output: `20 failed, 7497 passed, 34 skipped`
  - The same 13 failing files run on a clean `origin/dev` export: `20 failed, 336 passed`; the failed test names are identical,
    so no failure is new. (dev's 20 are the cron-schedule / committed-file / fixture tests already red on dev since #416.)
- **Staging capture** (13 intents, read-only), real output for the changed answer:
```
== market_view  q='What is the market view today?'  contract_problems=[]
  headline: Nifty 50 rose 0.51% to 23,053.10; 26% of stocks advanced; India VIX 15.30; the market regime reads BEAR.
  source fresh 2026-10-30  Market state the risk service uses (regime, India VIX)
  kpis day: Nifty 50=23,053.10 (+0.51% on 30 Oct); Bank Nifty=54,686.95 (−0.41%); India VIX=15.30 (+1.22%); Breadth=847 up · 2,403 down
  kpis regime: Regime=BEAR (as of 30 Oct · India VIX 15.30); New-trade size limits=Halved (… halved in BEAR.); Market state=0 of 2 sessions old
  bars flows: FII 3598.54, DII -817.51
  bars sector_moves: IT 2.32, Healthcare 1.58, Pharma 1.55, Telecom -2.1, Capital Goods -1.91, Consumer Durables -1.78
```
  All 13 payloads: `contract_problems=[]`.

## UI / Playwright Tests
- `npx tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`; `vite build` → `BUILD_EXIT=0`
- `npx playwright test --config pw.copilot-app.config.ts` on `copilot-app.spec.ts`, `copilot-app-daily-trader.spec.ts`,
  `copilot-app-visual-answer.spec.ts`, `copilot-app-desk.spec.ts`, `copilot-app-desk-copilot-window.spec.ts`,
  `copilot-app-trade-idea.spec.ts`, `copilot-app-desk-decision-cards.spec.ts`
  - Output: `125 passed (1.6m)`, 1 skipped (VA-19 screenshots, only with `VA_SHOTS=1`)
- **A failure found and fixed on the way:** the first regression run had 4 failures in `copilot-app.spec.ts` (TC-04, TC-04c,
  TC-10, TC-14). The shared mock helper matched `**/api/copilot/suggested-prompts` exactly, so the app's new `?mode=` query
  bypassed it. The pattern is now `**/api/copilot/suggested-prompts*` (`e2e/helpers/api-mock.ts`); the rerun is the line above.

## Data Correctness (staging)
The Market pulse figures equal the desk's Market regime card rows read from the same sources: regime BEAR as of 30 Oct,
India VIX 15.30, "halved in BEAR", "0 of 2 sessions old", FII +₹3,599 Cr and DII −₹818 Cr (3,598.54 / −817.51), and the same
three leading and lagging sectors (IT +2.32, Healthcare +1.58, Pharma +1.55; Telecom −2.10, Capital Goods −1.91, Consumer
Durables −1.78). **One difference found:** in the owner's screenshot the desk card's index tiles read 22,936.75 and 23.8% breadth
(the 29 Oct close) while its regime, FII and sector rows are 30 Oct; the chat answer reads 23,053.10 (30 Oct). The desk card's
index tiles are one session behind its other rows; that is a separate defect, not changed here.

## Not verified / limits
- Not deployed. The staging backend process has not been restarted since the merge (the backend deploy was cancelled), so
  staging chat still runs the old code; nothing here has been walked through as a signed-in user. Needs the backend deploy
  re-run and a staging session token.
- A strip question that says "this stock" (the opportunities set has two) needs a stock earlier in the thread; with none it
  asks "Which stock?", as in the panel.
- Advisor mode was not changed; its client-book list is unchanged and has no new e2e case.
- Merge note: PR #426 (suggestions) also edits `views/Home.tsx`; this branch changes one line there.

## Inputs required from user
- A staging session token and the backend deploy re-run, for the signed-in walk.

## After merging origin/dev (the suggestion engine, #426, merged by the owner at 06:31 IST)
`git merge origin/dev` applied with no conflict (Home.tsx merged automatically). Re-run on the merged result: tsc `TSC_EXIT=0`, build `BUILD_EXIT=0`, eight Copilot specs (the seven above plus `copilot-app-suggestions.spec.ts`): `146 passed`, 2 skipped (screenshot cases); backend `test_copilot_prompts_mode.py`, `test_suggestions.py` and the copilot visual suites: `269 passed`.

## Verdict: PASS
Scope: the code on this branch, by unit tests, a real-data capture and mocked-API Playwright; not a deployed system.
