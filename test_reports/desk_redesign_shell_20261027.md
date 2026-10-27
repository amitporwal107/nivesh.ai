# Functionality Verification Report — Desk redesign, step 1: the shell

- **Branch:** feat/desk-redesign-shell (from origin/dev c882e64c, merged with origin/dev e832ecb1)
- **Date:** 2026-10-27
- **Author:** Claude (Design Engineer + Full Stack Developer + QA)
- **Environment:** offline: production build + Playwright with mocked APIs, in Docker with no network (`run-fe.sh`). **Not staging**: the branch is not deployed before merge (see `test_reports/OVERRIDE_desk_redesign_shell.md`).
- **Changed areas:** backend routes/services: no · frontend src: yes (`frontend-v5/src/pages/CopilotApp/...`)

## Summary
The Smart trading desk frame is rebuilt to the owner's plan of 2026-10-27 (`docs/desk_redesign_20261027/PLAN.md`, step 1):
- a persistent PAPER MODE banner;
- four numbered tabs (01 Market Overview · 02 Trade Desk · 03 Market Desk · 04 Risk Desk), each with a view switcher (at most tab → view);
- a My portfolio button that opens the real portfolio inside the frame, without the paper cards;
- a breadcrumb that shows the location;
- redirects from every old desk URL, and from the Trader rail's old tools;
- the Trader rail's Tools reduced to "Smart trading desk", and Trader mode landing on the desk.

Today's screens are re-hosted as they are, with small additive props. Test cases: `test_reports/desk_redesign_shell_TESTCASES.md` (written before the code). Spec: `frontend-v5/e2e/tests/copilot-app-desk-shell.spec.ts`.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| SH-1 | Tabs | four numbered tabs in order, no old tabs | e2e | 01–04, Market Overview selected | PASS |
| SH-2 | Tabs | each tab sets ?tab= and its default view | e2e | URL and aria-selected | PASS |
| SH-3 | Views | every view of every switcher | e2e | ?view= and aria-pressed | PASS |
| SH-4 | Views | every view mounts its re-hosted component | e2e | 11 locations, host + component | PASS |
| SH-5 | Views | bad view / bad tab | edge | tab default / Market Overview | PASS |
| SH-6 | Overview | "All scanner candidates" collapsed; pulse and Top 10 once | e2e | aria-expanded, section=scanner | PASS |
| SH-7 | Overview | open paper trades line (2 open; 0 open) | e2e | "2 open paper trades" → trade/paper; "No open paper trades" | PASS |
| SH-8 | Overview | market part only | e2e | no snapshot or risk summary | PASS |
| SH-9 | Redirects | 13 old desk URLs + scanner expanded | e2e | new tab/view/section, params kept, history replaced | PASS |
| SH-10 | Redirects | Trader-mode tool routes; Investor Screener unchanged | e2e | market/screener, sectors, research | PASS |
| SH-11 | Breadcrumb | location, not path | e2e | ▸Trading desk›Market Desk›Smart Money by any path | PASS |
| SH-12 | My portfolio | opens inside the frame | e2e | ?tab=portfolio, no tab selected, banner kept | PASS |
| SH-13 | My portfolio | no paper cards; they are on Trade Desk | e2e | record/paper lists absent; present on trade | PASS |
| SH-14 | Trade Desk | paper vs real line | e2e | exact text; link opens My portfolio | PASS |
| SH-15 | Banner | on every location | e2e | 11 locations + My portfolio + phone | PASS |
| SH-16 | Header | market pill; kill-switch pill → controls | e2e | pills shown; risk/controls | PASS |
| SH-17 | Rail | Trader Tools = Smart trading desk only | e2e | no Screener, Stock research, Sector rotation | PASS |
| SH-18 | Rail | Investor unchanged | e2e | 8 investor tools | PASS |
| SH-19 | Landing | Trader mode lands on the desk | e2e | /v5/app/trader/desk | PASS |
| SH-20 | Links | repointed links | e2e | Open the AI Scanner → scanner section | PASS |
| SH-21 | 390px | no sideways scroll, banner, every tab + My portfolio | e2e | doc and scroll overflow ≤ 1px | PASS |
| SH-22 | 390px | bottom bar reaches 01–04 + Copilot; My portfolio in header | e2e | aria-current, URL | PASS |
| SH-23 | Copilot | docked at 1440 on every tab; page Copilot below 1400 | e2e | data-variant dock/page; one ask box | PASS |
| SH-24 | Wording | no pick / recommend / suggest in the frame's text | e2e | none | PASS |
| SH-25 | Regression | every in-scope old spec, branch vs dev | e2e | no failure on the branch that passes on dev | IN PROGRESS (run 3) |
| SH-26 | Build | tsc and vite build | build | clean | PASS |

## API / Endpoint Tests (staging)
Not applicable: no backend route or service changed. The frame reads existing routes only (`GET /api/markets/home`, `/api/risk/status`, `/api/positional/watchlist` + `picks`, `/api/desk/paper-trades`), all mocked here.

## UI / Playwright Tests
Runner: `run-fe.sh <worktree> <log> <specs…>`: tsc, `vite build`, `vite preview` and Playwright 1.47 in Docker with `--network none`, 4 workers, config `pw.copilot-app.config.ts`.

Specs run: the new `copilot-app-desk-shell.spec.ts`, `copilot-app.spec.ts` (mode pill and rail), and the 36 existing specs matching `desk|watchlist|screener|heatmap|risk|portfolio|trader|fnolab|options`. The four non-`copilot-app` specs that match that pattern (`onboarding-goal-risk`, `portfolio*`, `risk-widgets`, `watchlist-unauth`) are outside this config's `testMatch` and test legacy pages this change does not touch.

| Run | Tree | tsc | build | passed | failed | skipped |
|---|---|---|---|---|---|---|
| dev baseline | origin/dev `e832ecb1`, 36 old specs + `copilot-app.spec` (888 tests) | `tsc: clean` | `✓ built in 29.04s` | 836 | 33 | 19 |
| branch, run 2 | merged branch `3c88a21c`, the same specs + the shell spec (923 tests) | `tsc: clean` | `✓ built in 25.73s` | 843 | 47 | 33 |
| branch, run 3 | `7ef83ad2` (fixes for run 2's 15) | in progress when the PR was opened | | | | |

Real runner summary lines (unedited):
- dev: `33 failed` · `19 skipped` · `836 passed (22.0m)` · `exit 1`
- branch run 2: `47 failed` · `33 skipped` · `843 passed (19.9m)` · `exit 1`

What the failures are:
- **32 of dev's 33 and 32 of the branch's 47:** `copilot-app-desk-strategy-graphs` (SG-1 … SG-12). That spec needs a `VITE_STRATEGY_HARNESS=1` build, which this runner does not make; it fails the same way on dev.
- **Dev's 33rd:** `copilot-app-desk-widgets` TC-1 timed out at 30 s. Two other sessions' Playwright containers ran at the same time (load average 34 on 4 CPUs).
- **The new shell spec:** 35 of 35 passed in run 2 (and in run 1).
- **Run 2's other 15 failures on the branch, and their fixes (commit `7ef83ad2`):**
  - 4 URL regexes expected `tab=…&view=…` side by side, but `view` came after the scanner's params. Fixed in the product: the desk now writes canonical URLs (tab, view, section first).
  - 3 risk-controls cards are on another Risk Desk view. Fixed: the specs reach them through the view switcher.
  - 4 URL or attribute expectations still had the old names (ai-watchlist ×2, desk ×2). Fixed.
  - desk-lab TC-7 expected `view=strategy`. Fixed.
  - desk-strategy-ideas SI-7 counted the Top 10's own ideas request. Fixed.
  - desk-widgets TC-1 walked the 8 old tabs, which now load heavier combined pages, and timed out. Fixed: it walks the 6 new places with a 90 s limit.
  - desk-symbol-search SS-6: the canonical URL.

### Old specs changed (navigation and URL expectations only, unless listed as skipped)
- **URL expectations now name the new place:** Chart → `tab=market&view=research`; Strategy Builder → `tab=trade&view=new`; lab → `tab=market&view=smartmoney&section=fno`; Market Intelligence → `view=intel`; Chartink → `section=chartink`; page Copilot → `tab=copilot`; `data-tab="chart"` → `data-view="research"`.
  - Specs: desk, desk-market, desk-scanner, desk-top10, desk-lab, desk-symbol-search, desk-chartink, desk-chartink-picks, desk-strategy-ideas, desk-strategy-builder, desk-smart-money, desk-risk-controls, ai-watchlist.
- **Navigation to moved screens:**
  - paper trades: `?tab=portfolio` → `?tab=trade&view=paper` (desk-portfolio-fno, desk-decision-cards);
  - F&O paper strategies: `?tab=fno&lab=strategies` (the old URL), instead of the lab's removed sub-tab (desk-lab);
  - risk cards: the Risk Desk view that holds them (desk-risk-controls, desk-risk-phase1);
  - scanner list: Market Overview's toggle, instead of the AI Scanner tab (desk, desk-decision-cards);
  - More items: the new tab or view (desk-events, desk-strategy-builder, desk-chartink).
- **Locator scoped, assertion unchanged:**
  - Market Overview now shows both the Overview's pulse card and the scanner's pulse strip (both `desk-pulse`), so the strip is read in `desk-panel-pulse` and the card in `desk-pulse-card` (desk-top10, desk-widgets);
  - New trade also hosts the F&O lab, so the Builder's error alert is read in `desk-panel-strategy` (desk-strategy-top);
  - the ideas-request count ignores the Top 10's own `{limit:10}` request (desk-strategy-ideas).
- **Expectations changed by an owner decision** (the old requirement no longer holds):
  - `copilot-app.spec` TC-11: Trader lands on `/trader/desk`, and the rail no longer lists Screener, Stock research or Sector rotation.
  - desk-lab: the lab's view row on Smart Money has 4 entries (Paper strategies moved to New trade).
  - desk-portfolio-fno: My portfolio's phone order no longer holds the paper cards; the trust-line loop is split between My portfolio and Trade Desk.
  - desk, desk-market: Market Overview's order and trust lists no longer hold the portfolio and risk tiles.
  - desk-risk-controls RC-15: the bottom bar and view chip are 04 Risk / Controls.
  - desk TC-9: the keyboard walk uses the new bar's items.
- **Skipped (14), each with the reason and the shell case that covers the new behaviour; rewritten or deleted in step 6:**
  - desk: TC-1 (old rail and six tabs), TC-2 (old tab row and More), TC-7 (seven-item bottom bar), M1 empty tiles;
  - desk-top10: F-20, F-21/22/27, F-23/24, F-25 (click-path breadcrumb);
  - desk-market: OV-007/008 (portfolio snapshot on the Overview);
  - desk-portfolio-fno: §7 (hub beside the paper record);
  - desk-risk-controls: RC-1 (More list);
  - desk-smart-money: TC-F1 (sixth tab), TC-F20 (Flows in the bar);
  - sector-heatmap: the Trader rail item.

## Data Correctness (staging)
UNVERIFIED: no staging run. The branch is not deployed until the PR is merged, and this session does not merge. Every figure in these runs is mocked (`MOCK — not real data`). Next step after merge and deploy: open `/v5/app/trader/desk` on staging in Trader mode, check SH-1, SH-9, SH-12 and SH-15 with real data, and confirm the open-paper-trades count against `GET /api/desk/paper-trades`.

## Inputs required from user
- none

## Verdict: BLOCKED
Offline checks are not all green yet (run 3 in progress); the new shell spec passes 35/35; staging is not verified (OVERRIDE_desk_redesign_shell.md).
