# Functionality Verification Report — Trade Desk (desk redesign step 3), PR A: nav v2 + Paper Trading + Strategy Lab + Watchlists

- **Branch:** feat/desk-trade-desk (merged with origin/dev at 0f076b9b: shell #369, Risk Desk #370)
- **Date:** 2026-10-27
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** Playwright on a production build with mocked APIs (Docker, no network). Staging: not deployable before merge (OVERRIDE_desk_trade_desk.md).
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Trade Desk follows the owner's workbench (PLAN.md "1-REVISED"):
- five sections with sub-views, a section row, sub-view chips, and a breadcrumb that goes to the sub-view;
- **Paper Trading › Live desk:** the header strip (paper account; "Open risk x% of 3%"; the exit-job line from `/api/desk/exit-job-status`; corrections), pending entries, open positions, F&O structures with every leg and Roll, and recent exits;
- **Paper Trading › Trade journal:** the timeline, fills, the desk-cost-v2 bridge "net, before income tax", stop history and the stop-first flags, plus every closed trade;
- **Strategy Lab › Build a trade:** the ticket sized by `account_size` (no slider and no size field), the F&O builder limited to the backend catalog, and the Strategy Builder;
- **Strategy Lab › Backtest & validation:** the backtest with its provenance;
- **Watchlists:** the Watchlist page, moved from Market Desk.

AI Scanner and Chart Analysis host today's scanner list, Chartink sources, the F&O forward test and the chart until PR B builds them.

`?tab=trade` opens Paper Trading › Live desk until PR B. Old URLs redirect: `view=paper`/`open` → Live desk; `closed` → Trade journal; `new` and the strategy / F&O-lab URLs → Build a trade; Market Desk's `watchlists` → Trade Desk › Watchlists.

## Test Cases
Authored first: `test_reports/desk_trade_desk_TESTCASES.md`:
- TD-1 … TD-36 were committed before the first implementation;
- NV-1 … NV-5 were committed in abd24615, before the spec changes for this layout.

| ID | Area | Result |
|----|------|--------|
| NV-1 … NV-5 | sections, sub-views, four-deep crumb, old URLs, Watchlists moved, journal picker | PASS (NV-3 failed once on a race in the spec, which read `sub` without polling; it was fixed and passed) |
| TD-1 … TD-6, TD-42 | header strip: account, open risk vs 3%, exit job ok / missed / late / error, equity unknown, corrections | PASS |
| TD-8 … TD-13 | Live desk: pending rule and validity, open positions, F&O legs and payoff-v2 figures, roll, missing marks, empty | PASS |
| TD-14 … TD-23 | Trade journal: timeline, fills, the cost bridge (net, before income tax), stop history, the stop-first flags (no AMBIGUOUS), links, the closed list | PASS |
| TD-24 … TD-33 | Strategy Lab: the account_size ticket, allow / reduce "Accept 83?" / block / duplicate / impossible fill, the catalog-limited builder with Greeks, backtest provenance and the survivorship warning | PASS |
| TD-34 | one GET /api/desk/paper-trades per load across sections and sub-views | PASS |
| TD-35 | 390 px | PASS |
| TD-36 | wording | PASS |
| TD-37 … TD-41 | close, refused close, 502 / 403, contract error, flat-cost bridge | PASS |
| REG-1 | affected specs (shell, portfolio-fno, decision-cards, strategy-builder, lab, risk-phase1, top10, widgets) | PASS after the fixes below; a failure counts only if it repeats |
| STG-1 | staging after merge | NOT RUN (OVERRIDE) |

## UI / Playwright Tests
- **Command:** `PWEXTRA="--workers=2" run-fe.sh <worktree> <log> copilot-app-desk-trade-desk copilot-app-desk-shell copilot-app-desk-portfolio-fno copilot-app-desk-decision-cards copilot-app-desk-strategy-builder copilot-app-desk-lab copilot-app-desk-risk-phase1 copilot-app-desk-top10 copilot-app-desk-widgets`
  (tsc, a production vite build, vite preview, Playwright `pw.copilot-app.config.ts`).

Run 1 (all affected specs), real output:
```
== tsc
tsc: clean
== build
✓ built in 29.39s
  10 failed
  32 skipped
  290 passed (7.6m)
```
The 10 failures were:
- the 5 F&O forward-test cases: the panel lived in the old PaperLists, and now lives on AI Scanner › Scorecard;
- SB-1, top10 F-3 and top10 F-14: they expected `view=new`;
- NV-3: the race in the spec;
- lab TC-7 at 390 px: it did not repeat. It passed in run 2 and run 3.

Run 2 (the failed tests, after the fixes):
```
== tsc
tsc: clean
== build
✓ built in 28.62s
  2 failed
  10 passed (22.0s)
```
The two failures were second assertions in the same specs (SB-1 `desk-view-new` aria-pressed; forward-test TC-8 expected `desk-paper-trades`). Both were fixed.

Run 3:
```
== tsc
tsc: clean
== build
✓ built in 28.30s
  7 passed (7.6s)
```
The skipped tests include 11 PaperDesk-only cases in `copilot-app-desk-portfolio-fno.spec.ts`. They are marked `test.skip`, each naming the TD case that now covers it. PaperDesk is no longer mounted, and step 6 deletes it.

## API / Endpoint Tests (staging)
No backend change. A read-only check that the routes the tab reads are live on staging (401 without a session, 404 for a route that does not exist):
```
/api/desk/exit-job-status 401
/api/desk/paper-account 401
/api/desk/paper-trades 401
/api/risk/profile 401
/api/desk/strategy/templates 401
/api/desk/does-not-exist 404
```

## Data Correctness (staging)
NOT RUN. This needs the merged frontend on staging and a signed-in session (OVERRIDE_desk_trade_desk.md).

## Inputs required from user
- none for this PR. Staging verification after merge needs a signed-in staging session.

## Verdict: BLOCKED
Staging verification is deferred to after merge (OVERRIDE). Every mocked test case above passed.

---

# PR B: AI Scanner and Chart Analysis (branch feat/desk-trade-desk-b)

Built on PR A (#376), with #373 (Market Overview) and #375 (Market Desk) merged in, because both merge before this PR.

**What changed:**
- `?tab=trade` opens **AI Scanner › Ranked candidates**: the Top 10 decision cards and "All scanner candidates", moved off Market Overview. `?tab=scanner` and `?tab=overview&section=scanner` land there.
- **Signal library & sources:** the scanner's signal categories, each with the rule the route sent, and the Chartink sources.
- **Scorecard:** #375's IdeaScorecard (`GET /api/desk/idea-scorecard`), then the F&O forward test.
- **Live chart:** ChartTab, with the `account_size` paper ticket in place of the capital × risk-% calculator. The plan comes from `?tp=` or today's Top 10 idea; a stock with no idea gets no ticket, and the page says so.
- **Signal record:** "not available yet", because no route serves the signal history.
- **Market Overview:** "See all ›" opens Ranked candidates; "Scorecard →" opens Scorecard.
- **#375's spec:** `SCORECARD_URL` is set to the Scorecard, so its SC-* cases run.

## Test Cases
AS-1 … AS-4 and CH-1 … CH-3 are in `desk_trade_desk_TESTCASES.md` (commit 40f43be7, before the PR B spec changes). All PASS.

## UI / Playwright Tests
Run 1: tsc, build, and the affected specs at `--workers=2` (trade-desk, shell, market-overview, market-desk, top10, decision-cards, scanner, portfolio-fno, strategy-builder, lab, risk-phase1, widgets). Real output:
```
== tsc
tsc: clean
== build
✓ built in 55.12s
  12 failed
  36 skipped
  427 passed (12.0m)
```
The 12 failures:
- **4 were mine:**
  - MD-10, the forward-test TC-8, SH-12/13 and SH-14 expected the old default or the old Scorecard note.
  - The four specs were fixed. Run 2:
```
== tsc
tsc: clean
== build
✓ built in 45.59s
  8 passed (15.8s)
```
- **8 were the widgets spec:** its `beforeEach` waits for the old Overview's pulse card, which #373 removed. It fails the same way on #373's own branch (53371071):
```
== tsc
tsc: clean
== build
✓ built in 50.46s
  8 failed
```
  - Not caused by this PR. #373 or a follow-up should fix it.

## Verdict: BLOCKED
Staging verification is deferred to after merge (OVERRIDE_desk_trade_desk.md). Every mocked case above passed.

---

# PR B follow-up (review of 27 Oct): chart links, Chartink in one place, desk-widgets, merged with dev

dev was merged in: #373, #375, and #378 (the Top 10 timeout hotfix, which merged without conflict).

**What changed:**
- **Chart links** open Trade Desk › Chart Analysis › Live chart. This covers `openChart` (scanner rows, idea cards, the journal's Chart, the header search), the AI watchlist's desk links, and the old `?tab=chart`. Market Desk › Stock Research stays reachable from its switcher.
- **Chartink sources** live only in AI Scanner › Signal library. Market Desk › Screener links there; its old `section=chartink` URL and `?tab=more&view=chartink` redirect there.
- **The desk-widgets spec** runs on Market Overview's panels (`mo-strip`, `mo-paper`). Only navigation and locators changed.
- **New cases:** CH-4, AS-5 and WG-1, added to the test-case file before the spec changes.

## Runs (`--workers=2`; a failure counts only if it repeats)
**Run 3.** The coordinator's list (trade-desk, widgets, shell, market-overview, market-desk, top10, decision-cards, lab, portfolio-fno, strategy-builder, ai-watchlist, watchlists) plus the five older specs I edited (scanner, symbol-search, desk, chartink, chartink-picks):
```
== tsc
tsc: clean
== build
✓ built in 27.85s
  46 failed
  59 skipped
  510 passed (15.0m)
```
**In the coordinator's list,** everything passed except two:
- MO-24 expected the old chart place. Updated.
- top10 F-3 read `?cand=` after the Strategy Builder had consumed it (a race that always lost on this branch). Fixed: it now reads the URL the click produced.

**The 44 failures in the older specs:** 16 also fail on dev. They test the old Overview that #373 removed. The same four specs on dev:
```
== tsc
tsc: clean
== build
✓ built in 24.39s
  16 failed
  4 skipped
  128 passed (3.1m)
```
The other 28 were mine:
- 26 scanner chart/risk-desk cases opened `?tab=chart`. They now open Stock Research, which keeps the full ChartTab with its risk desk.
- 2 desk.spec cases used Market Overview's scanner toggle. They now use the Trade Desk tab.

**Run 4:** scanner, desk, market-overview and top10, after the fixes.
```
== tsc
tsc: clean
== build
✓ built in 30.58s
  10 failed
  12 skipped
  149 passed (2.6m)
```
- 8 of these are dev's own desk.spec failures (the same tests, each one line lower).
- 2 were the scanner chart screenshots. Fixed.

**Run 7:** F-3 and the chart screenshots, `--repeat-each=3`.
```
== tsc
tsc: clean
== build
✓ built in 29.94s
  18 passed (29.5s)
```

## Verdict: BLOCKED
Staging verification is deferred to after merge (OVERRIDE_desk_trade_desk.md). Every mocked case on this branch passed. The 16 older-spec failures are dev's own (#373).
