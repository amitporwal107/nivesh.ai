# Functionality Verification Report — Desk redesign step 6: remove the duplicate trading screens (scope A + extension)

- **Branch:** `feat/desk-remove-duplicates`. It was cut from `origin/dev` 0f076b9b, and `origin/dev` was merged in as it
  moved: #373 Market Overview, #375 Market Desk, #372/#374/#378, #377 Trade Desk, #380. Final base: **58717e28**.
- **Date:** 2026-10-27 / 28
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** offline. Checks: tsc, the production build, and Playwright against mocked APIs (`MOCK — not real
  data`), in the `mcr.microsoft.com/playwright:v1.47.0-jammy` container with `--network none`. Staging comes after the
  merge (see the OVERRIDE report).
- **Changed areas:**
  - backend routes and services: no;
  - frontend source: yes;
  - e2e specs: yes;
  - docs: `docs/API_DOCUMENTATION.md` (one line).

## Summary
**Scope A, the owner's decision of 27 Oct, 16:40.** These screens and URLs were deleted:
- the old Trader landing;
- the Options lab;
- the F&O lab frame and its Replay, Certification, Shadow and Market Intelligence screens;
- `/pro-trader`;
- the duplicate `/strategy-builder` URL;
- Research's Paper and Lab.

Every old URL now redirects to its new place in the desk, or to `/app/page/paper`.

**Extension (coordinator, 27 Oct, "no duplicate screens").** I also deleted the screens that nothing mounts any more:
- `tradingdesk/OverviewTab.tsx` and `ScannerPulse.tsx` (Market Overview replaced both);
- `fnolab/Programs.tsx`, `LiveDesk.tsx` and `KiteSessions.tsx`.

**Code pruned with them.** Code that only those screens used was removed:
- most of `overview-data.ts`;
- `headLabel`, `GapNote` and `ChartinkOnlyList`.

**Tests removed with them:**
- the old-Overview cases, all of which are skipped or failing on clean dev;
- the 14 skips the shell left "for step 6".

**Ports.** Checks that were still meaningful and covered nowhere else were ported to Market Overview's spec as MO-32, MO-33
and MO-34.

**Test cases** are in `test_reports/desk_remove_duplicates_TESTCASES.md` (RM-1 … RM-22). They were written before each
part was implemented.

## What was deleted (`git diff -M --stat origin/dev`, base 58717e28)

| | Files | Lines |
|---|---|---|
| Frontend source files deleted | **21** | **5,716** |
| Frontend source total (incl. edits and prunes) | 38 changed | +127 / −6,777 |
| e2e spec files deleted | 4 (`copilot-app-options`, `-fnolab-mi`, `-fnolab-kite`, `-fnolab-governance`) | 1,320 |
| e2e total (incl. edits, 1 rename, 1 new spec, 3 ported cases) | 26 changed | +362 / −3,312 |
| Whole branch (with these reports and one doc line) | 68 changed | +789 / −10,090 |

**Deleted source files:**
- the old Trader landing: `screens/Trader.tsx`, `trading/FnoAnalyser.tsx`;
- the Options lab: `screens/OptionsLab.tsx`, `trading/OptionChainViews.tsx`;
- the F&O lab:
  - `fnolab/FnoLab.tsx`, `Replay.tsx`, `Certification.tsx`, `Shadow.tsx`, `MarketIntel.tsx`, `market-intel.ts`;
  - `fnolab/Programs.tsx`, `LiveDesk.tsx`, `KiteSessions.tsx`;
- Pro Trader: `pages/ProTrader/*` (5 files) and `hooks/use-positional.ts`;
- the old Overview: `tradingdesk/OverviewTab.tsx` (1,917 lines) and `tradingdesk/ScannerPulse.tsx`.

**Pruned code** (used only by deleted screens):
- `tradingdesk/overview-data.ts` went from 1,027 to 316 lines. It keeps the sector returns, the index tiles and breadth,
  the IST clock, market status, `indexMode` and `stampIst`.
- `desk-data` `headLabel`.
- `fnolab/parts`: `GapNote`, plus the frame's `LAB_SCREENS`, `ModeBand` and `monoNote`.
- `chartink/ChartinkParts`: `ChartinkOnlyList` and its row.
- `ScannerTab`'s pulse line.

No name removed by the prune is used on dev or on the open desk branches (`git grep` over `origin/*`).

**Tests removed: 104.**
- 48 in the four deleted spec files.
- 4 in `-screens` and 1 in `-broker-paper`: Trader-landing and Options-lab cases.
- The shell's 14 step-6 skips.
- #373's 22 skipped old-Overview and pulse cases: `-desk-market` ×18 (including two `describe.skip`), `-desk-top10` F-30 … F-34.
- 8 `copilot-app-desk.spec` cases that fail on clean dev.
- 7 Chartink cases that fail on clean dev, plus CK-16's Overview tail.

**Tests added: 22.** That is 19 in `copilot-app-desk-retired` and the 3 ports MO-32 … MO-34.

**Skip counts:** `test.skip(` went from 70 on dev to 37; `describe.skip(` from 2 to 0.

## Kept (re-hosted or shared), checked with the import graph and `git grep` over the open branches
- `fnolab/parts.tsx`. Risk Desk `ControlsView` and `DecisionLog`, and `Audit.tsx`, import it.
- `fnolab/Audit.tsx`. Risk Desk › Decision log uses its `Lineage`.
- `fnolab/governance-data.ts`, whole. All three Risk Desk views use it, and #377's Strategy Lab (`NewTrade.tsx`) imports
  `useStrategyTemplates`.
- `pages/StrategyBuilder/*` stays mounted at `/app/trader/strategy`.
- `desk/BrokerPositions.tsx` stays mounted on My portfolio.
- `PaperTradesScreen` and `SimulationLabScreen` stay mounted by `/app/page/paper`.
- `ScannerTop10`, `ResultsWeekIdeas`, and `ChartinkPicks` `variant="full"` are mounted elsewhere.
- `ScannerTab`'s full mode (Top 10, results week, list) has no caller, but #377's AI Scanner may still use it, so it
  stays. Only the pulse line was removed from it.
- `ChartinkPicks` `variant="top"` is dead since the old Overview went. It is threaded through a live component, so it
  is left for its owner.
- Untouched, as instructed:
  - the sector heatmap, `tool/screener`, `tool/research`, the `/research` chart workspace and `/flows`;
  - the investor and advisor screens;
  - the public `/watchlist` and the legacy `/markets/*`.
- The "Backtest in the strategy builder" links point to `/app/trader/strategy` and stay that way, as the coordinator
  instructed: #377's agent repoints them.

After the merges, the import graph on the final commit reads `685 files 157866 lines; unresolved: []`. No CopilotApp
file is unreachable.

## Redirects (all e2e-tested, RM-1 … RM-7)

| Old URL | New URL |
|---|---|
| `/v5/app/trader` (any mode; query kept) | `/v5/app/trader/desk` (Market Overview) |
| `/v5/app/tool/optlab` | `…/trader/desk?tab=market&view=smartmoney&section=fno` |
| `/v5/app/tool/fnolab`, `?screen=mi`, unknown screen | `…/trader/desk?tab=market&view=smartmoney` |
| `…/tool/fnolab?screen=prog` | `…/trader/desk?tab=trade&view=lab&sub=build` (Strategy Lab › Build a trade) |
| `…/tool/fnolab?screen=replay` · `shadow` | `…/trader/desk?tab=trade&view=lab&sub=backtest` (Strategy Lab › Backtest & validation) |
| `…/tool/fnolab?screen=live` · `cert` | `…/trader/desk?tab=risk&view=controls` |
| `…/tool/fnolab?screen=audit` | `…/trader/desk?tab=risk&view=log` |
| `/v5/pro-trader` | `/v5/app/trader/desk?tab=trade&view=lab&sub=build` |
| `/v5/strategy-builder` | `/v5/app/trader/desk?tab=trade&view=lab&sub=backtest` |
| `/v5/research?screen=paper` · `?screen=lab` | `/v5/app/page/paper` |

**Strategy Lab targets.** The brief said `?tab=trade` for programs, `/pro-trader` and `/strategy-builder`, "the Strategy Lab
section will take it". Since #377, a bare `?tab=trade` opens AI Scanner. So these URLs now name Strategy Lab and its
sub-view.

**URLs not in the brief.** I mapped `replay`, `shadow` and `cert` by what they described.

**Kite login.** The backend's Kite login returns to `/v5/app/trader?kite=…` (`KITE_LOGIN_RETURN_PATH`). The redirect keeps
the query (RM-1b). The end-to-end toast cases in `copilot-app-kite-login-notice.spec.ts` pass through it.

## Orphaned backend routes (follow-up; nothing deleted here)
I used the review's method: the import-graph closure from `main.tsx`, the API strings, and the service-adapter methods,
matched against the 964 routes in `backend/`. Routes referenced by reachable v5 code go from 496 (dev 58717e28) to 490:

```
ORPHANED GET /api/live/option-chain routes/live_quotes.py
ORPHANED GET /api/markets/sector-constituents routes/markets_desk.py
ORPHANED GET /api/macro/today routes/macro.py
ORPHANED GET /api/positional/market-dashboard routes/positional.py
ORPHANED POST /api/positional/basket routes/positional.py
ORPHANED POST /api/positional/basket/simulate routes/positional.py
```
- **Orphaned for v5 only.** `macro/today` (5 files) and `positional/market-dashboard` (3 files) are still called by the v2
  app (`frontend/src`), so they stay.
- **No caller in either app:** `live/option-chain`, `markets/sector-constituents` and `positional/basket(+/simulate)`.
- **Not orphaned:** `markets/sector-heatmap` and `flows/ledger/*`. The heatmap and `/flows` are kept.
- **Dead adapter methods:** `positionalService.buildBasket` and `simulateBasket`.
- **Suggested change:** the backend default `KITE_LOGIN_RETURN_PATH = "/v5/app/trader"` could become `/v5/app/trader/desk`.
- **UNVERIFIED:** backend-internal callers, cron jobs and the Copilot tool layer were not checked.

## Specs changed
- **Deleted:** `copilot-app-options`, `-fnolab-mi`, `-fnolab-kite`, `-fnolab-governance`. Risk Desk RD-11 covers live
  readiness, and RD-13 / RD-14 cover the decision log with lineage and replay.
- **Renamed:** `copilot-app-trader` → `copilot-app-broker-paper`.
  - The broker-block cases open My portfolio, which mounts the same `BrokerPositions`.
  - The journal case was removed.
- **Moved URL:**
  - the paper-record specs open `/app/page/paper` › Full record;
  - the strategy-builder specs open `/app/trader/strategy`.
- **Old Overview (extension):**
  - `-desk-market`: the 18 skipped cases and their fixtures were removed. One case still runs (the desk search asks the
    Copilot).
  - `-desk-top10`: F-30 … F-34 were removed. F-35 still runs.
  - `copilot-app-desk.spec`: the 8 failing cases and their fixtures were removed. "header search" stays; it carries #377's
    `view=chart`.
  - `-desk-chartink-picks`: PK-6 and PK-6b were removed, and PK-8's overview run. Its settings and ideas runs stay.
  - `-desk-chartink`: CK-7, CK-8, CK-8b and CK-9 were removed, and CK-16's Overview tail. CK-16's settings checks stay.
- **Ported to `copilot-app-desk-market-overview.spec.ts`:**
  - MO-32: the header's market-status pill (from desk.spec's header-row case);
  - MO-33: a failed `GET /api/markets/home` (was TC-12);
  - MO-34: a failed or empty `GET /api/markets/sector-returns` (was TC-11).
- **New:** `copilot-app-desk-retired.spec.ts`, 19 cases.
- `-fnolab-governance` from the coordinator's run list no longer exists, because this PR deletes it.

## Evidence (real output, this session)

### Final commit 661cc92b (base 58717e28)
`run-fe.sh`, `PWEXTRA="--workers=2"`. Specs:
- `copilot-app.spec`, `-desk.spec`, `-desk-market-overview`, `-desk-shell`, `-desk-retired`, `-desk-risk-desk`,
  `-desk-widgets`;
- `-desk-market.spec`, `-desk-top10`, `-desk-chartink*`, `-desk-results*`, `copilot-app-results-week*`,
  `-desk-trade-desk`, `-desk-market-desk`.

```
tsc: clean
✓ built in 26.54s
  1 failed
  2 skipped
  304 passed (4.4m)
```
- The one failure is `copilot-app-desk-results-signal` RS-1/2/3. It fails identically on clean `origin/dev` 7b926d9c (the
  comparison below) and is not caused by this branch.
- The 2 skips are env-gated.
- Every old-Overview Chartink case left in the specs passes: `-desk-chartink` 20, `-desk-chartink-picks` 17.

### Requested set on 428065a8 (after the #377 merge; same frontend as the final commit except the Chartink cleanup)
Specs:
- `copilot-app.spec`, `-desk.spec`, `-desk-market-overview`, `-desk-shell`, `-desk-retired`, `-desk-risk-desk`,
  `-desk-widgets`;
- `-desk-market.spec`, `-desk-top10`, `-desk-scanner`, `-desk-market-desk`, `-desk-trade-desk`, `-kite-login-notice`,
  `-broker-paper`.
```
tsc: clean
✓ built in 23.45s
  367 passed (5.3m)
exit 0
```
- The 367 include MO-32, MO-33 and MO-34.
- They include all 19 `copilot-app-desk-retired` cases, with the Strategy Lab redirects RM-3 prog / replay / shadow and
  RM-4 / RM-5.

### Supplementary batch on 428065a8
Specs: `-desk-lab`, `-desk-strategy-builder`, `-workspace`, `-screens`, `-builder`, `-desk-portfolio-fno`,
`-desk-smart-money`, `-desk-risk-controls`, `-desk-events`, `-desk-chartink*`, `-desk-results-*`, `-sector-heatmap`.
```
tsc: clean
✓ built in 31.33s
  9 failed
  28 skipped
  334 passed (5.9m)
```
I compared the 3 specs with failures on a clean `origin/dev` 7b926d9c worktree and on the branch, one after the other:
```
origin/dev 7b926d9c:  9 failed · 38 passed   (tsc: clean)
branch:               9 failed · 38 passed   (tsc: clean)
```
- **The 9 failures are the same on both, so none is caused by this branch.**
- 8 are old-Overview Chartink cases. They were then deleted (commit ac551243).
- 1 is `copilot-app-desk-results-signal` RS-1/2/3, the order of the scanner list. It fails on dev too, it is unrelated to
  this PR, and it is left for its owner.
- The 28 skips are env-gated screenshot suites.

### Earlier history (the scope-A part, before the extension)
- Run 1 on the 0f076b9b base: 79 + 33 passed.
- Run 2 on the 0f076b9b base: 575 + 152 passed, 0 failed.
- After #373 and #375, on 329a3647:
  - run 4: 477 + 152 passed, 0 failed;
  - a base comparison showed the same 8 `desk.spec` failures on dev and on the branch. The extension then deleted those
    8 cases.
- Run 5 on 739aabda: 103 passed.

### Spec integrity
- `tsc --noEmit` over the edited specs reports no undefined name (TS2304 / TS2552) and no syntax error.
- `playwright test --list` loads them all (101 tests in the 5 desk specs).

### Code check (RM-9b)
The deleted views and names appear in `src/` only in the redirect tables (`routes.tsx`, `lib/retired-views.ts`).

## Test case results

| ID | Result | Evidence |
|---|---|---|
| RM-1, RM-1b | PASS | desk-retired RM-1 ×2 and RM-1b; the kite-login-notice toast cases through `/v5/app/trader?kite=…` |
| RM-2, RM-3 … RM-3e | PASS | desk-retired RM-2 and RM-3 ×9 (Strategy Lab build / backtest; `rd-live` / `risk-decisions` render) |
| RM-4, RM-5 | PASS | desk-retired ×2 (Strategy Lab build / backtest) |
| RM-6, RM-7 | PASS | desk-retired ×3; research-paper-trades TC-P23 |
| RM-8 | PASS | desk-shell SH-17 / SH-19 |
| RM-9, RM-9b | PASS | desk-retired RM-9; the grep |
| RM-10, RM-10b | PASS | tsc clean after every step; the build passes; the graph has no unresolved import |
| RM-11, RM-12 | PASS | `-broker-paper`; research-paper-trades and research-paper-trade-chart |
| RM-13 | PASS | every run; each failure seen was identical on clean dev |
| RM-14, RM-15 | PASS | specs deleted; `test.skip(` 70 → 37; no "Superseded" or "step 6" skip left |
| RM-16, RM-17 | DONE (report) | the counts and the orphaned routes above |
| RM-18 | PASS | five files deleted; no importer on dev or any open branch; tsc clean |
| RM-19 | PASS | prunes; tsc clean; no removed name used anywhere (`git grep` over `origin/*`) |
| RM-20 | PASS | 22 + 8 (+7 Chartink, same class) cases removed; header search kept |
| RM-21 | PASS | MO-32, MO-33 and MO-34 pass |
| RM-22 | PASS | the final runs above |

## UNVERIFIED
- **Staging.** The branch is not deployed: staging deploys after the merge, and this session does not merge. No redirect
  has run against the real app or real data. After the merge and deploy:
  - open each URL in the redirect table on https://staging.niveshcopilot.com;
  - do one real Kite login, which should land on the desk with the "Kite connected" toast.
- **Real-session specs.** `staging-paper-trades.spec.ts` and `strategy-builder-live.spec.ts` were rewritten but not run.
- **Research-only users.** The coordinator reports that staging has none, because the `research_only` flag has no stored
  allowlist. I did not re-check that myself, and **production was not checked**. A research-only user would lose Paper
  and Lab, because `/app` is closed to them and the redirect bounces them back to the `/research` feed.

## Verdict
Offline verification passes. Every failure seen also fails on clean dev, and none is caused by this branch. Staging is
pending the merge: see `test_reports/OVERRIDE_desk_remove_duplicates.md`.
