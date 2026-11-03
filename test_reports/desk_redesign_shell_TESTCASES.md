# Desk redesign, step 1 (Shell): test cases

- **Plan:** `docs/desk_redesign_20261027/PLAN.md` (owner decisions of 2026-10-27), step 1 "Shell".
- **Branch:** `feat/desk-redesign-shell` (from `origin/dev` c882e64c).
- **Written:** 2026-10-27, before the implementation. The Playwright spec is
  `frontend-v5/e2e/tests/copilot-app-desk-shell.spec.ts`. Every API is mocked (`MOCK — not real data`).
- **Scope:** the frame only. Existing components are re-hosted, not rewritten. No backend change.

## The URL scheme (design decision, stated here so the cases can test it)

`/v5/app/trader/desk?tab=<tab>&view=<view>`

| Tab (`tab=`) | Number | Views (`view=`), default first |
|---|---|---|
| `overview` Market Overview | 01 | one page (no view switcher) |
| `trade` Trade Desk | 02 | `paper` Paper trades · `new` New trade |
| `market` Market Desk | 03 | `intel` Market Intelligence · `smartmoney` Smart Money · `sectors` Sector Rotation · `research` Stock Research · `screener` Screener · `watchlists` Watchlists & alerts |
| `risk` Risk Desk | 04 | `limits` Limits & budgets · `controls` Controls & profile · `log` Decision log |
| `portfolio` My portfolio | not numbered | one page (the header button, not a tab) |
| `copilot` AI Copilot | not numbered | below 1400px only (where the Copilot is not docked) |

- PaperDesk cannot split open and closed trades without a rewrite, so Trade Desk has one paper view, "Paper trades".
- `section=` names a part of a view to open and scroll to: `scanner` (Market Overview's collapsed "All scanner
  candidates"), `events` (Market Intelligence), `fno` (Smart Money, New trade), `chartink` (Screener).

## Test cases

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| SH-1 | Tabs | Open `/trader/desk` | e2e | Four tabs in this order: `01 Market Overview`, `02 Trade Desk`, `03 Market Desk`, `04 Risk Desk`. Market Overview is selected (`aria-selected`). No "More" tab and no old tab names (AI Scanner, Chart Analysis, Portfolio & Risk). |
| SH-2 | Tabs | Click each tab | e2e | The URL becomes `?tab=<tab>`, plus the default `view=` for tabs that have views. That tab is selected. |
| SH-3 | Views | For every tab, the view switcher | e2e | Trade: Paper trades · New trade. Market: the six views in the order above. Risk: the three views. Overview has no switcher. Clicking a view sets `view=` and marks it `aria-pressed`. |
| SH-4 | Views | Every view mounts its re-hosted component | e2e | overview → `desk-overview` + `desk-pulse` + Top 10 + a collapsed "All scanner candidates"; trade/paper → `desk-paper-trades`; trade/new → Strategy Builder + F&O section (`desk-fno`); market/intel → `desk-intel` + Events section; market/smartmoney → Smart Money + F&O section; market/sectors → `screen-tool-sector-heatmap`; market/research → the Chart tab; market/screener → `screen-tool-screener` + "Chartink sources"; market/watchlists → `screen-page-watchlist`; risk/limits → `risk-policy`; risk/controls → `risk-status` + `risk-profile` + live-readiness; risk/log → `risk-decisions` + `risk-audit` + the F&O audit. |
| SH-5 | Views | A bad `view=` | edge | `?tab=market&view=zzz` falls back to the tab's default view (`intel`). `?tab=zzz` falls back to Market Overview. |
| SH-6 | Overview | "All scanner candidates" | e2e | Collapsed by default (`aria-expanded=false`, the scanner list not mounted). A click expands it and sets `section=scanner`; the list mounts once. The Top 10 and the pulse appear once on the page, not twice. |
| SH-7 | Overview | Open paper trades line | e2e | "N open paper trades" from `GET /api/desk/paper-trades` (N = open trades in the mock). Its "Trade Desk ›" link opens `tab=trade&view=paper`. With 0 open trades it says "No open paper trades". |
| SH-8 | Overview | Market part only | e2e | The portfolio snapshot (`desk-snapshot-card`) and the risk summary (`desk-risk-card`) are not on Market Overview. |
| SH-9 | Redirects | Every old desk URL | e2e | `?tab=scanner` → `tab=overview&section=scanner` (list expanded); `intel` → `market/intel`; `events` → `market/intel&section=events`; `chart&sym=X` → `market/research&sym=X`; `smartmoney` → `market/smartmoney`; `fno` → `market/smartmoney&section=fno`; `fno&lab=chain&lab_sym=BANKNIFTY` keeps `lab=chain&lab_sym=BANKNIFTY`; `fno&lab=strategies` → `trade/new&section=fno`; `more&view=strategy` → `trade/new` (builder params kept); `more&view=risk` → `risk/limits`; `more&view=chartink` → `market/screener&section=chartink`; `portfolio` → My portfolio. The redirect replaces the history entry. |
| SH-10 | Redirects | Trader-mode rail routes | e2e | In Trader mode, `/app/tool/screener` → `market/screener`, `/app/tool/sector-heatmap` → `market/sectors`, `/app/tool/research` → `market/research`. In Investor mode `/app/tool/screener` stays the standalone Screener. |
| SH-11 | Breadcrumb | Location, not click path | e2e | `Trading desk › Market Desk › Smart Money` on `market/smartmoney`; reaching the same view by another path (a link from Market Overview) shows the same crumbs. `Trading desk › Market Overview` on the overview; `Trading desk › My portfolio` on My portfolio. The last crumb is `aria-current="page"`. "Trading desk" opens Market Overview; the tab crumb opens the tab's default view. |
| SH-12 | My portfolio | Header button | e2e | A "My portfolio" button right of the tabs, with no number. It opens `?tab=portfolio` inside the desk frame: the four tabs and the banner stay, no tab is selected, the button is `aria-pressed`. The broker hub (`desk-portfolio`) renders. |
| SH-13 | My portfolio | No paper cards | e2e | On My portfolio, `desk-portfolio-record` ("Paper trades · predicted vs actual") and `desk-portfolio-paper` (the paper-trade and alert lists) are absent. Both are on Trade Desk › Paper trades. |
| SH-14 | Trade Desk | Paper vs real line | e2e | Trade Desk shows "These are paper trades. Your real holdings and F&O positions (read-only): My portfolio"; the link opens `?tab=portfolio`. |
| SH-15 | Banner | PAPER MODE on every view | e2e | `desk-paper-banner` reads "Paper mode · simulated execution only · no broker orders" on all 11 tab/view locations, My portfolio, and on a phone. |
| SH-16 | Header | Pills kept | e2e | The market-status pill (`desk-market-status`) shows. With `GET /api/risk/status` kill switch on, `desk-risk-pill` shows and opens `risk/controls`. |
| SH-17 | Rail | Trader TOOLS | e2e | Trader mode lists only "Smart trading desk" under Tools (no Screener, Stock research, Sector rotation, Trader desk, Options lab). |
| SH-18 | Rail | Investor unchanged | e2e | Investor mode still lists Portfolio analysis, Recommendations, Risk, Goals, Tax, Stock & fund research, Screener, Markets. |
| SH-19 | Landing | Trader mode lands on the desk | e2e | Switching the mode pill to Trader goes to `/v5/app/trader/desk` (Market Overview), not `/v5/app/trader`. |
| SH-20 | Links | Repointed links | e2e | The AI-watchlist's desk links and "Open the trading desk ›" (`SetupsToWatch`) open the new URLs; the Top 10's "View trades" opens `trade/paper`; the Overview's "Open the AI Scanner" expands the scanner section. |
| SH-21 | Phone 390px | No sideways scroll | e2e | On every tab and on My portfolio: `scrollWidth <= clientWidth` for the page. The banner wraps rather than overflowing. |
| SH-22 | Phone 390px | Tabs reachable | e2e | The bottom bar holds 01–04 and Copilot; each opens its tab. The view switcher scrolls inside itself. My portfolio is in the phone header. |
| SH-23 | Copilot | Dock kept | e2e | At 1440px the docked Copilot (`desk-copilot-dock`) shows on every tab. Below 1400px the header's Copilot button opens `?tab=copilot` with the page Copilot, and the app's own ask box is hidden there. |
| SH-24 | Wording | No picks/recommended/suggested | e2e | The header, tabs, view switcher, breadcrumb, banner, overview trades line and the Trade Desk line contain none of "pick", "recommend", "suggest" (case-insensitive). |
| SH-25 | Regression | Every existing desk / watchlist / screener / heatmap / risk / portfolio / trader / F&O-lab / options spec | e2e | Pass as on origin/dev, through the redirects. A spec that needs a change gets its URL changed, not its assertion; every such change is listed in the report. |
| SH-26 | Build | `tsc --noEmit` and `vite build` | build | Clean. |

## Not covered here (later steps or not testable offline)
- Staging with real data: the branch is not deployed before merge (OVERRIDE report).
- Content redesign of each tab (steps 2–5), the Idea scorecard view (its endpoint is being built), the paper-account
  strip (no component reads `GET /api/desk/paper-account` yet), and deleting old screens (step 6).
