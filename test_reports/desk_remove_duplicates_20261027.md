# Functionality Verification Report — Desk redesign step 6: remove the duplicate trading screens (scope A)

- **Branch:** `feat/desk-remove-duplicates` (from `origin/dev` 0f076b9b)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** offline: tsc, the production build and Playwright against mocked APIs (`MOCK — not real data`), in
  the `mcr.microsoft.com/playwright:v1.47.0-jammy` container with `--network none`. Staging comes after merge (OVERRIDE).
- **Changed areas:** backend routes/services: no · frontend src: yes · e2e specs: yes · docs: `docs/API_DOCUMENTATION.md` (one line)

## Summary
The owner's scope A (PLAN.md §4, 27 Oct 16:40) removes the duplicate trading screens. These were deleted: the old Trader
landing, the Options lab, the F&O lab frame with its Replay, Certification, Shadow and Market Intelligence screens,
`/pro-trader`, the `/strategy-builder` duplicate URL, and Research's Paper and Lab. Every old URL now redirects to its
new home in the Smart trading desk or `/app/page/paper`. The specs of the deleted screens were deleted. Specs that only
used a moved URL were rewritten to the new place. The 14 `test.skip` cases the shell left "for step 6" were removed.
Test cases: `test_reports/desk_remove_duplicates_TESTCASES.md` (written before the implementation).

## What was deleted (`git diff -M --stat origin/dev`)

| | Files | Lines |
|---|---|---|
| Frontend source files deleted | 16 | 3,198 |
| Frontend source total (incl. edits) | 29 changed | +101 / −3,389 |
| e2e spec files deleted | 4 (`copilot-app-options`, `-fnolab-mi`, `-fnolab-kite`, `-fnolab-governance`) | 1,320 |
| e2e total (incl. edits, 1 rename, 1 new spec) | 23 changed | +260 / −2,002 |
| Whole branch before these reports | 54 changed | +416 / −5,392 |

Deleted source files: `screens/Trader.tsx`, `trading/FnoAnalyser.tsx`, `screens/OptionsLab.tsx`,
`trading/OptionChainViews.tsx`, `fnolab/FnoLab.tsx`, `Replay.tsx`, `Certification.tsx`, `Shadow.tsx`,
`MarketIntel.tsx`, `market-intel.ts`, `pages/ProTrader/*` (5) and `hooks/use-positional.ts`. The import graph shows that
only `ProTraderPage` imported the hook.

Tests removed: 48 `test()` cases in the four deleted specs, 4 in `copilot-app-screens` (Trader landing ×1, Options
lab ×2, Trader F&O card ×1), 1 in the broker spec (the journal and scanner rows of the landing), and the 14
superseded skips. `test.skip(` calls under `e2e/tests`: 39 on dev, 24 now. The 15 removed are the 14 step-6 skips and
the options spec's screenshot skip.

## Kept (re-hosted or shared), checked with the import graph
- `fnolab/parts.tsx`: imported by Risk Desk `ControlsView` / `DecisionLog` and by the kept lab screens. Only the
  frame's own exports were pruned (`LAB_SCREENS`, `isLabScreen`, `ModeBand`, the mode table and `monoNote`).
- `fnolab/Audit.tsx` (`Lineage` is used by Risk Desk › Decision log) and `governance-data.ts` (used by all three
  Risk Desk views).
- `fnolab/Programs.tsx`, `LiveDesk.tsx` and `KiteSessions.tsx` are **kept on disk, as asked, but nothing mounts them**.
  Only the frame imported them. Strategy Lab and Risk Desk have to host them; until then they are unreachable.
  KiteSessions' actions remain available elsewhere: the admin Kite login is in the shell banner (`KiteLoginNotice`) and
  the Zerodha connection is in Broker connections. Their old e2e cases are in git history: `origin/dev`
  0f076b9b `frontend-v5/e2e/tests/copilot-app-fnolab-governance.spec.ts` and `copilot-app-fnolab-kite.spec.ts`.
- `pages/StrategyBuilder/*`: the page stays mounted at `/app/trader/strategy`. `desk/BrokerPositions.tsx` stays
  mounted on My portfolio. `PaperTradesScreen` and `SimulationLabScreen` stay mounted by `/app/page/paper`.
- Kept and not touched, as instructed: the sector heatmap, `tool/screener`, `tool/research`, the `/research` chart
  workspace, `/flows`, the investor and advisor screens, the public `/watchlist` and the legacy `/markets/*`.

## Redirects (all tested, RM-1 … RM-7)

| Old URL | New URL |
|---|---|
| `/v5/app/trader` (any mode; query kept) | `/v5/app/trader/desk` (Market Overview) |
| `/v5/app/tool/optlab` | `/v5/app/trader/desk?tab=market&view=smartmoney&section=fno` |
| `/v5/app/tool/fnolab`, `?screen=mi`, unknown screen | `…/trader/desk?tab=market&view=smartmoney` |
| `…/tool/fnolab?screen=prog` · `replay` · `shadow` | `…/trader/desk?tab=trade` |
| `…/tool/fnolab?screen=live` · `cert` | `…/trader/desk?tab=risk&view=controls` |
| `…/tool/fnolab?screen=audit` | `…/trader/desk?tab=risk&view=log` |
| `/v5/pro-trader` | `/v5/app/trader/desk?tab=trade` |
| `/v5/strategy-builder` | `/v5/app/trader/desk?tab=trade` |
| `/v5/research?screen=paper` · `?screen=lab` | `/v5/app/page/paper` |

`replay`, `shadow` and `cert` were not in the brief. I mapped them by what they described: backtest and validation
belong to Strategy Lab, and certification to Policy & runtime (live readiness). The backend's Kite login returns to
`/v5/app/trader?kite=…` (`KITE_LOGIN_RETURN_PATH`). The redirect keeps the query (RM-1b), and the end-to-end toast
cases in `copilot-app-kite-login-notice.spec.ts` pass through it.

**Repointed links:** "Backtest in the strategy builder ›" on Saved, workspace screen watchlists and markets strategy
screens now opens `/v5/app/trader/strategy` (the same wizard, inside the shell; RM-9). I did not point it at
`?tab=trade`, because Trade Desk has no backtest view yet. `MODE_HOME.trader` was already `trader/desk` and "Open the
trading desk ›" already opened `trader/desk` (verified in the source). The legacy `Topbar` / `CopilotDock` Pro Trader
titles and the admin Trader desk / Options lab tool templates are gone.

## Orphaned backend routes (follow-up; nothing deleted here)
I ran the review's method over `origin/dev` and over this branch: the import-graph closure from `main.tsx`, the API
strings, and the service-adapter methods, matched against the 962 routes in `backend/`. Routes referenced by reachable
v5 code went from 491 to 488:

```
ORPHANED GET /api/live/option-chain routes/live_quotes.py
ORPHANED POST /api/positional/basket routes/positional.py
ORPHANED POST /api/positional/basket/simulate routes/positional.py
```
- `markets/sector-heatmap` and `flows/ledger/*` are **not** orphaned: the heatmap and `/flows` are kept.
- `positionalService.buildBasket` / `simulateBasket` (`services/adapters/positional.adapter.ts`) are now dead adapter
  methods.
- The backend default `KITE_LOGIN_RETURN_PATH = "/v5/app/trader"` could become `/v5/app/trader/desk`.
- Backend-internal callers, cron jobs and the Copilot tool layer were not checked for these routes (UNVERIFIED), as in
  the review.

## Specs changed
- **Deleted:** `copilot-app-options`, `copilot-app-fnolab-mi`, `copilot-app-fnolab-kite`, `copilot-app-fnolab-governance`.
  Every screen these specs open is deleted or no longer mounted. Risk Desk RD-11 covers live readiness and RD-13 / RD-14
  cover the decision log with lineage and replay.
- **Renamed and rewritten:** `copilot-app-trader` → `copilot-app-broker-paper`.
  - The 14 broker-block cases open My portfolio (`?tab=portfolio`, the same `BrokerPositions`).
  - One assertion changed: the "no broker account" case no longer asserts that `/api/portfolio/holdings` is uncalled,
    because My portfolio's hub card reads it. It still asserts that no broker is read.
  - The journal / watch-level / scanner case was removed with the landing.
- **Rewritten (moved URL):**
  - `research-paper-trades`, `research-paper-trade-chart` and `staging-paper-trades` open `/app/page/paper` › Full
    record. TC-P23 now asserts the Research rail has no Paper item and the redirect; TC-P27's 403 case asserts the
    paper page's own no-access state.
  - `strategy-config-bot-details` and `strategy-builder-live` open `/app/trader/strategy`.
- **Edited:** `copilot-app-screens` (Trader / Options lab entries and cases), `-shots`, `-live` (view lists), `-builder`
  (21 → 19 templates), `-kite-login-notice` (comment only).
- **New:** `copilot-app-desk-retired.spec.ts`, 19 cases (RM-1 … RM-9).
- **Skips removed (14):**
  - `desk.spec` TC-1, TC-2, TC-7, M1;
  - `desk-top10` F-20, F-21/22/27, F-23/24, F-25 (and the emptied "Desk breadcrumb" describe);
  - `desk-smart-money` TC-F1, TC-F20;
  - `desk-risk-controls` RC-1;
  - `desk-market` OV-007/008;
  - `desk-portfolio-fno` §7;
  - `sector-heatmap` rail case.

  Each one named the desk-shell SH case that covers it. Those SH cases pass in run 2 below.
  `grep -rn "Superseded by the desk redesign" e2e/` → no match.

## Evidence (real output, this session)
`run-fe-both.sh` = the scratchpad `run-fe.sh` recipe (tsc, `vite build`, `vite preview` on :5174, Playwright with no
network) plus `playwright.config.ts`'s mocked `desktop-chrome` project, for the specs outside `copilot-app*`.
`PWEXTRA="--workers=2"`.

**tsc and the build (both runs):**
```
== tsc
tsc: clean
== build
✓ built in 24.65s
```
A standalone `npx tsc --noEmit -p tsconfig.json` after the deletions also printed `tsc: clean`. The import graph after the
deletion: `664 files 155566 lines; unresolved: []`.

**Run 1: new and rewritten specs.** copilot-app: `copilot-app-desk-retired`, `-broker-paper`, `-kite-login-notice`,
`-builder`, `-screens`. Main: `research-paper-trades`, `research-paper-trade-chart`, `strategy-config-bot-details`.
```
== playwright copilot-app
  79 passed (1.6m)
== playwright main (desktop-chrome)
  33 passed (30.8s)
exit 0
```

**Run 2: full regression.**
- copilot-app specs: `copilot-app.spec`, `-desk-shell`, `-desk.spec`, `-desk-lab`, `-desk-strategy-builder`,
  `-workspace`, `-desk-risk-desk`, `-desk-top10`, `-desk-smart-money`, `-desk-portfolio-fno`, `-desk-risk-controls`,
  `-desk-market`, `-sector-heatmap`, `-research`, `-screener`, `-shots`, `-live`, `-ops`, `-desk-retired`,
  `-broker-paper`, `-screens`, `-builder`, `-kite-login-notice`.
- Main-config specs: `research-access`, `research-move-odds`, `research-charts.spec` (it also matches
  `staging-research-charts`), `filings-intelligence`, `research-paper-trades`, `research-paper-trade-chart`,
  `strategy-config-bot-details`.
```
== playwright copilot-app
  34 skipped
  575 passed (8.5m)
== playwright main (desktop-chrome)
  5 skipped
  152 passed (3.3m)
exit 0
```
`grep -c '✘' run2.log` → `0`. No failures, so nothing needed a re-run.

The 39 skips are all environment-gated or pre-existing:
- `-shots` 7 (`SHOT_DIR`);
- `-live` 6 (`LIVE_TOKEN_FILE` / `REPLAY_DIR`);
- `-desk-strategy-builder` 14 (`SHOTS_DIR` screenshots);
- `-desk-lab` 2, `-ops` 2, `-research` 2 and `-sector-heatmap` 1 (screenshot dirs);
- `staging-research-charts` 4 (`STAGING_SESSION_FILE`);
- `research-access` 1 (an existing `test.skip`).

**Code check (RM-9b):** in `src/`, the deleted views and names appear only in the redirect tables:
```
routes.tsx:148:      <Route path="/pro-trader" element={<Navigate to="/app/trader/desk?tab=trade" replace />} />
pages/CopilotApp/lib/retired-views.ts:38:    case "tool/optlab":
pages/CopilotApp/lib/retired-views.ts:41:    case "tool/fnolab":
```

## Test case results

| ID | Result | Evidence |
|---|---|---|
| RM-1, RM-1b | PASS | desk-retired RM-1 ×2, RM-1b; kite-login-notice toast cases through `/v5/app/trader?kite=…` |
| RM-2, RM-3 … RM-3e | PASS | desk-retired RM-2, RM-3 ×9 (`rd-live` / `risk-decisions` render on the redirected places) |
| RM-4, RM-5 | PASS | desk-retired ×2 |
| RM-6, RM-7 | PASS | desk-retired ×3; research-paper-trades TC-P23 |
| RM-8 | PASS | desk-shell SH-17 / SH-19 (run 2) |
| RM-9, RM-9b | PASS | desk-retired RM-9; the grep above |
| RM-10, RM-10b | PASS | tsc clean, build OK, graph has no unresolved import; the kept files are present |
| RM-11 | PASS | copilot-app-broker-paper (run 1 and run 2) |
| RM-12 | PASS | research-paper-trades, research-paper-trade-chart (run 1 and run 2) |
| RM-13 | PASS | run 2: 575 + 152 passed, 0 failed |
| RM-14, RM-15 | PASS | specs deleted; `test.skip(` 39 → 24; no "Superseded" comment left |
| RM-16, RM-17 | DONE (report) | the counts and the orphaned routes above |

## UNVERIFIED
- **Staging:** the branch is not deployed (staging deploys after merge; this session does not merge). No redirect has
  run against the real app or real data. After the merge and deploy, open the URLs in the redirect table on
  https://staging.niveshcopilot.com and do one real Kite login. That login should land on the desk with the
  "Kite connected" toast.
- `staging-paper-trades.spec.ts` and `strategy-builder-live.spec.ts` (real-session specs) were rewritten but not run.
- Whether any account on prod is research-only. `research_only`'s default allowlist is empty
  (`backend/feature_flags.py`); the runtime allowlist was not read. Such a user loses Paper and Lab, because `/app` is
  closed to them and the redirect bounces them back to the `/research` feed.
- Whether the Strategy Lab and Risk Desk branches in progress will mount `Programs`, `LiveDesk` and `KiteSessions`.

## Verdict
Offline verification passes. Staging is pending the merge; see `test_reports/OVERRIDE_desk_remove_duplicates.md`.
