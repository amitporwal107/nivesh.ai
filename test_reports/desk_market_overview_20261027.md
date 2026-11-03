# Functionality Verification Report — Market Overview tab (desk redesign step 2)

- **Branch:** feat/desk-market-overview (merged with origin/dev after #369, the shell)
- **Date:** 2026-10-27
- **Author:** Claude (Full-stack + Design engineer + QA)
- **Environment:** mocked APIs on a production build (vite build + vite preview, Playwright 1.47 in Docker). Staging: not yet (see OVERRIDE_desk_market_overview.md)
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
Tab 01 Market Overview in the owner's design's structure (PLAN.md 1-REVISED): KPIs (paper equity, day net P/L, open risk vs
its 3% limit, candidates, feed) · Market regime (NIFTY 50, Nifty Bank, India VIX, breadth; the risk service's regime from
GET /api/risk/freshness with its as-of date, freshness and the BEAR note; last session's FII / DII; sector moves) · Top AI
candidates (Cash | F&O; Phase 3 decision-card rows with account_size, Provisional / Risk-approved, budgets left, carry-forward,
scan basis, STALE DATA, the 22:45 IST empty state; a drawer with the full card and Paper trade incl. RiskReduce; footer and
Scorecard link; See all → Trade Desk) · Paper trades (read-only, GET /api/risk/profile) · Alerts and events (today's filings
for the names on the ideas) · All scanner candidates (collapsed). The tab never calls GET /api/desk/paper-trades or
GET /api/desk/alerts (both write when listed).

## Test Cases
Authored up front: test_reports/desk_market_overview_TESTCASES.md (MO-1 … MO-31, revised for 1-REVISED). All 30 Playwright
cases of copilot-app-desk-market-overview.spec.ts PASS (output below).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| MO-1 | Layout | the design's panels in order | e2e | KPIs · regime · candidates · paper trades · alerts/events · scanner list | PASS |
| MO-2…9, 2b–2d | Market regime card | indices, breadth, BEAR/BULL/stale/failed regime, FII/DII, sectors, Kite close | e2e/edge/failure | route figures, as-of date, BEAR note | PASS |
| MO-10…22 | Top AI candidates | decision-card row, approval, budgets, carry, basis, stale, empty, toggle, drawer, reduce, block | e2e/edge | as the contract fixture | PASS |
| MO-23, 23b | Footer, See all | wording and links | e2e | Scorecard → tab=market; See all → tab=trade | PASS |
| MO-24, 24b | Alerts and events | today's filings for listed names | e2e/edge | one row; empty says so | PASS |
| MO-25…27 | KPIs + paper trades | figures, no positions, profile 500 | e2e/edge/failure | route figures; errors in words | PASS |
| MO-28 | Read-only | no GET paper-trades / alerts | e2e | zero calls | PASS |
| MO-29 | Wording | no picks / suggested / recommended | e2e | none | PASS |
| MO-30 | Phone 390 | page and drawer | e2e | no sideways scroll | PASS |
| MO-31 | Scanner list | toggle and ?tab=scanner | e2e | expands, section=scanner | PASS |

## API / Endpoint Tests (staging)
Not applicable: no backend change. Staging check deferred to after merge (OVERRIDE_desk_market_overview.md).

## UI / Playwright Tests
- **Command:** run-fe.sh (Docker): `npx tsc --noEmit`, `vite build`, `npx playwright test --config pw.copilot-app.config.ts --workers=2` on
  copilot-app-desk-market-overview, -desk-top10, -desk-decision-cards, -desk-shell, -desk-market, -desk-scanner, -ai-watchlist
- **Output (real, unedited excerpt):**
```
tsc: clean
✓ built in 42.49s
  27 skipped
  234 passed (8.9m)
exit 0
```
- Per spec: market-overview 30 passed · top10 28 passed, 8 skipped · decision-cards 29 passed · desk-shell 35 passed ·
  desk-market 13 passed, 19 skipped · desk-scanner 85 passed · ai-watchlist 14 passed.
- **Retired by this PR (22 skips, reason recorded in the specs):** desk-market's 14 old Overview-card cases + TC-7 (390, the
  same cards) + TC-3 … TC-5 (Kite close on the old tiles, PORTED as MO-2b … MO-2d), and top10's F-30 … F-34 (market pulse).
  OverviewTab.tsx and ScannerPulse.tsx are no longer mounted; their deletion or re-hosting is step 6. The other 5 skips were
  already skipped on the base.
- **Changed to follow the screen:** top10 (one board at a time, links/levels/paper trade in the row's drawer), decision-cards
  (F&O toggle always present; drawer for F&O paper trade and Strategy ›), shell SH-4/SH-7/SH-20 (no pulse; KPIs and panel
  instead of the old line; the scanner toggle instead of the old "See all").
- **Base comparison:** the shell head 7ef83ad2, same specs, under load ~30: 6 failures in these specs (ai-watchlist F-5,
  scanner SP-5/6 and 2221, shell SH-4/15/21), which the shell's final report attributes to load; all pass here at load < 6.

## Passing cases (my spec)
```
copilot-app-desk-market-overview.spec.ts:159:3 › MOCK — not real data: Market Overview · the page › MO-1 the design's panels in order: KPIs, market regime, Top AI candidates, paper trades, aler
copilot-app-desk-market-overview.spec.ts:178:3 › MOCK — not real data: Market Overview · the page › MO-31 All scanner candidates opens the list and puts section=scanner in the URL; ?tab=scanner
copilot-app-desk-market-overview.spec.ts:195:3 › MOCK — not real data: Market Overview · the market strip › MO-2 / MO-3 / MO-8 / MO-9 indices, breadth, FII / DII and sector moves from their rou
copilot-app-desk-market-overview.spec.ts:223:3 › MOCK — not real data: Market Overview · the market strip › MO-4 BEAR: the regime the risk service uses, its as-of date, and the halved size limi
copilot-app-desk-market-overview.spec.ts:235:3 › MOCK — not real data: Market Overview · the market strip › MO-5 BULL: no halving note; the line says no regime cut applies (3.4s)
copilot-app-desk-market-overview.spec.ts:245:3 › MOCK — not real data: Market Overview · the market strip › MO-6 a stale regime input says so, with the route's reason, and that new paper entrie
copilot-app-desk-market-overview.spec.ts:255:3 › MOCK — not real data: Market Overview · the market strip › MO-7 the freshness route failing leaves the rest of the strip in place (4.7s)
copilot-app-desk-market-overview.spec.ts:286:3 › MOCK — not real data: Market Overview · index cells and Kite's closing quote › MO-2b the cell already has its own 23 Oct bar: Kite's 23 Oct clos
copilot-app-desk-market-overview.spec.ts:295:3 › MOCK — not real data: Market Overview · index cells and Kite's closing quote › MO-2c the cell's own bar is older than Kite's final snapshot: Kit
copilot-app-desk-market-overview.spec.ts:303:3 › MOCK — not real data: Market Overview · index cells and Kite's closing quote › MO-2d an older backend without a cell date falls back to the page
copilot-app-desk-market-overview.spec.ts:312:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-10 / MO-11 / MO-13 a cash row is the decision-card row: the plan's levels, the risk se
copilot-app-desk-market-overview.spec.ts:338:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-12 a real allow decision reads Risk-approved, solid mint (3.8s)
copilot-app-desk-market-overview.spec.ts:348:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-14 / MO-15 the carry-forward tag, the scan basis and the stored list (3.1s)
copilot-app-desk-market-overview.spec.ts:362:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-16 a scan older than the last session is marked STALE DATA, naming both days (3.6s)
copilot-app-desk-market-overview.spec.ts:371:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-17 no stored list yet: the route's 22:45 IST words (3.3s)
copilot-app-desk-market-overview.spec.ts:380:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-18 an empty board shows the route's own reason and no rows (4.0s)
copilot-app-desk-market-overview.spec.ts:390:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-19 Cash | F&O: one board at a time, Cash first (3.9s)
copilot-app-desk-market-overview.spec.ts:410:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-20 Full card opens the drawer: every section, the levels and the links; Escape and ✕
copilot-app-desk-market-overview.spec.ts:432:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-21 Paper trade in the drawer: a 409 risk_reduce offers the allowed size and re-posts i
copilot-app-desk-market-overview.spec.ts:452:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-22 a block that still applies turns Paper trade off with the gate's reason; nothing is
copilot-app-desk-market-overview.spec.ts:465:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-23 the footer: ideas, not recommendations; no measurable ranking skill; Scorecard → 
copilot-app-desk-market-overview.spec.ts:474:3 › MOCK — not real data: Market Overview · Top AI ideas › MO-23b See all › opens Trade Desk (the AI Scanner's ranked candidates once the next nav
copilot-app-desk-market-overview.spec.ts:485:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-24 events today: only today's filing for a name on the ideas; its sy
copilot-app-desk-market-overview.spec.ts:496:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-24b a day with no filing for the listed names says so (2.6s)
copilot-app-desk-market-overview.spec.ts:502:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-25 KPIs and the paper trades panel: equity, day net P/L, open risk v
copilot-app-desk-market-overview.spec.ts:530:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-26 no open positions (3.2s)
copilot-app-desk-market-overview.spec.ts:538:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-27 the risk profile failing says so in the KPIs and the panel; the p
copilot-app-desk-market-overview.spec.ts:547:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-28 this tab never reads GET /api/desk/paper-trades (it applies exits
copilot-app-desk-market-overview.spec.ts:561:3 › MOCK — not real data: Market Overview · events and the Trade Desk line › MO-29 wording: ideas and candidates, never picks, suggestions or recomm
copilot-app-desk-market-overview.spec.ts:576:3 › MOCK — not real data: Market Overview · phone (390px) › MO-30 no sideways scroll on the page or with the drawer open (3.1s)
```

## Data Correctness (staging)
UNVERIFIED: no staging deploy before merge. After deploy: GET /api/risk/freshness market_state (expected Stale while the
regime feed is behind), real account_size on rows, the stored list's scan basis, and no paper-trades/alerts GET on this tab.

## Inputs required from user
- none

## Verdict: PASS
