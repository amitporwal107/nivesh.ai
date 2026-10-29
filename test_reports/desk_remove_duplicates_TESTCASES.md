# Desk redesign, step 6 (remove duplicate trading screens, scope A): test cases

- **Plan:** `docs/desk_redesign_20261027/PLAN.md` §4 (owner decision 27 Oct 16:40: "scenario A, trading duplicates only"),
  `docs/desk_redesign_20261027/REVIEW_current_screens.md` §4 (import-graph counts, links to repoint).
- **Branch:** `feat/desk-remove-duplicates` (from `origin/dev` 0f076b9b, after #369 shell and #370 Risk Desk).
- **Written:** 2026-10-27, before the implementation. New spec: `frontend-v5/e2e/tests/copilot-app-desk-retired.spec.ts`.
  Every API is mocked (`MOCK — not real data`). No backend change.

## What is deleted, what is kept

| Deleted | Kept (re-hosted or shared) |
|---|---|
| `/app/trader` (`Trader.tsx`, `trading/FnoAnalyser.tsx`, and files only they import) | `desk/BrokerPositions.tsx` (mounted in My portfolio), `trading/*` shared parts |
| `/app/tool/optlab` (`OptionsLab.tsx`, `trading/OptionChainViews.tsx` if nothing else imports it) | `trading/ModelViews.tsx`, `PayoffResult.tsx`, `fno.ts` (the desk F&O tab uses them) |
| `/app/tool/fnolab` frame `FnoLab.tsx` + `Replay`, `Certification`, `Shadow`, `MarketIntel`, `market-intel.ts` | `fnolab/Programs`, `LiveDesk`, `KiteSessions`, `Audit`, `governance-data.ts`, `parts.tsx` (Risk Desk imports `parts`, `Audit` `Lineage`, `governance-data`) |
| `/pro-trader` (`pages/ProTrader/*`) | — |
| the `/strategy-builder` route (the page stays: `/app/trader/strategy` mounts it) | `pages/StrategyBuilder/*` |
| `/research?screen=paper` and `?screen=lab` (the Research rail's Paper and Lab items) | `PaperTradesScreen`, `SimulationLabScreen` (mounted by `/app/page/paper`) |

## Test cases

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| RM-1 | Redirect | Open `/v5/app/trader`, in Trader mode and in Investor mode | e2e | Lands on `/v5/app/trader/desk` (Market Overview, `tab` absent or `overview`); the history entry is replaced; the old Trader landing (`screen-trader`) never renders. |
| RM-1b | Redirect | `/v5/app/trader?kite=connected` (the backend's default `KITE_LOGIN_RETURN_PATH` is `/v5/app/trader`) | e2e | Lands on the desk with `kite=connected` kept, and the "Kite connected" toast shows (the query string survives the redirect). |
| RM-2 | Redirect | `/v5/app/tool/optlab` | e2e | `/v5/app/trader/desk?tab=market&view=smartmoney&section=fno`; `screen-tool-optlab` never renders. |
| RM-3 | Redirect | `/v5/app/tool/fnolab` bare, and `?screen=mi` | e2e | `tab=market&view=smartmoney`. |
| RM-3b | Redirect | `?screen=prog`; `?screen=replay`, `?screen=shadow` | e2e | `tab=trade&view=lab&sub=build`; `tab=trade&view=lab&sub=backtest` (Trade Desk › Strategy Lab, which #377 added; a bare `tab=trade` now opens AI Scanner). |
| RM-3c | Redirect | `?screen=live`, `?screen=cert` | e2e | `tab=risk&view=controls`; the live-trading readiness block (`rd-live`) renders there. |
| RM-3d | Redirect | `?screen=audit` | e2e | `tab=risk&view=log`; the decision log (`risk-decisions`) renders. |
| RM-3e | Redirect | `?screen=zzz` (unknown) | edge | Same as bare (`tab=market&view=smartmoney`), never a blank page or the app home. |
| RM-4 | Redirect | `/v5/pro-trader` | e2e | `/v5/app/trader/desk?tab=trade&view=lab&sub=build`. |
| RM-5 | Redirect | `/v5/strategy-builder` | e2e | `/v5/app/trader/desk?tab=trade&view=lab&sub=backtest`. |
| RM-6 | Redirect | `/v5/research?screen=paper` and `/v5/research?screen=lab` (account with `move_odds` and `sim_lab`) | e2e | `/v5/app/page/paper`; `screen-page-paper` renders. |
| RM-7 | Research rail | `/v5/research` with `move_odds`, `sim_lab` and `charting` | e2e | Rail lists Feed, Alerts, Odds, Charts; no Paper (`rail-paper`) and no Lab (`rail-lab`). |
| RM-8 | Rail | Trader mode Tools | e2e | No "Trader desk", "Options lab", "F&O lab" (SH-17 already asserts it; kept green). |
| RM-9 | Links | "Backtest in the strategy builder ›" on Saved (saved screens), workspace screen watchlists and markets strategy screens | e2e / code | Points at `/v5/app/trader/strategy` (the same wizard, inside the shell), not `/strategy-builder`. |
| RM-9b | Links | Legacy `Topbar.tsx` / `CopilotDock.tsx` and admin tool templates | code | No `/pro-trader` title entry; no `trader` / `tool/optlab` tool template; `TRADER_TOOLS` has no deleted view. `grep` for the deleted views in `src/` finds only the redirect table. |
| RM-10 | Build | `npx tsc --noEmit`, `vite build` | build | Both clean. tsc proves no file imports a deleted file. |
| RM-10b | Graph | Import graph re-run after deletion | build | No unresolved import; every kept file in the table above still exists. |
| RM-11 | Regression | Broker block tests (were on `/app/trader`) | e2e | Rewritten to My portfolio (`?tab=portfolio`), the same `BrokerPositions` component: pass. |
| RM-12 | Regression | Research paper-record tests (were Research rail › Paper) | e2e | Rewritten to `/app/page/paper` › Full record (the same `PaperTradesScreen`): pass. |
| RM-13 | Regression | `copilot-app`, `-desk-shell`, `-desk`, `-desk-lab`, `-desk-strategy-builder`, `-workspace`, `-screens`, `-desk-risk-desk`, `-builder`, `-kite-login-notice`, `-desk-top10`, `-desk-smart-money`, `-desk-portfolio-fno`, `-desk-risk-controls`, `-desk-market`, `-sector-heatmap`, `-trader` (kept parts) | e2e | Pass. A failure counts only if it repeats on a re-run; a repeating failure is compared with `origin/dev`. |
| RM-14 | Specs | Specs of deleted screens | e2e | Deleted: `copilot-app-options`, `copilot-app-fnolab-mi`, `copilot-app-fnolab-kite`, `copilot-app-fnolab-governance` (every screen it opens is deleted or no longer mounted; Risk Desk RD-11 / RD-13 / RD-14 cover live readiness and the decision log); the Trader-landing parts of `copilot-app-trader`, `copilot-app-screens`, `-shots`, `-live`. |
| RM-15 | Specs | The 14 `test.skip` cases the shell left "for step 6" | e2e | Removed. `grep -rn "Superseded by the desk redesign" e2e/` returns nothing; each was already covered by a named `desk-shell` SH case. |
| RM-16 | Count | `git diff --stat origin/dev` | report | Files and lines deleted, reported. |
| RM-17 | Backend | Orphaned backend routes | report | Listed for a follow-up (none deleted here). |

## Extension (coordinator, 27 Oct): the unmounted screens and the old-Overview tests

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| RM-18 | Delete | `tradingdesk/OverviewTab.tsx`, `ScannerPulse.tsx`, `fnolab/Programs.tsx`, `LiveDesk.tsx`, `KiteSessions.tsx` | build | No importer on dev or on the open desk branches (checked with `git grep` over origin/*); tsc clean after each; the import graph has no unresolved import and no unreachable CopilotApp file. Market Overview imports nothing from them. |
| RM-19 | Prune | What only those screens used: `overview-data.ts` exports, `desk-data` `headLabel`, `fnolab/parts` `GapNote` | build | tsc clean; nothing on dev or #376 / #377 uses a removed name; `governance-data.ts` stays whole (#377's Strategy Lab imports `useStrategyTemplates`). |
| RM-20 | Tests | #373's 22 skipped cases ("deleted or re-hosted in step 6") and the 8 `copilot-app-desk.spec` cases that fail on clean dev | e2e | Removed, with only the fixtures they used. The case in their describe that still passes ("header search") stays. |
| RM-21 | Ports | Checks still meaningful and uncovered by Market Overview's spec | e2e | MO-32 the header's market-status pill (closed / live / delayed / Market open with the holiday list read / an NSE holiday); MO-33 a failed `GET /api/markets/home`; MO-34 a failed or empty `GET /api/markets/sector-returns`. Pass. |
| RM-22 | Regression | `copilot-app.spec`, `-desk.spec`, `-desk-market-overview`, `-desk-shell`, `-desk-retired`, `-desk-risk-desk`, `-desk-widgets`, plus `-desk-market`, `-desk-top10`, `-desk-scanner`, `-desk-market-desk`, `-desk-trade-desk`, `-kite-login-notice`, `-broker-paper` (`-fnolab-governance` no longer exists: this PR deletes it) | e2e | Pass; a failure counts only if it repeats. |

## Not covered here
- Staging with real data: the branch is not deployed before merge (OVERRIDE report).
- `staging-paper-trades.spec.ts` and `strategy-builder-live.spec.ts` need a real staging session; their navigation is
  rewritten but they are not run here.
