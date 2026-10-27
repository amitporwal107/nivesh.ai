# Market Overview (desk redesign step 2): test cases

Written **before** the implementation (2026-10-27), from `docs/desk_redesign_20261027/PLAN.md` §1 and
`REVIEW_workspace_vs_phases.md` §A "1 Market Overview", "What makes navigation harder" and §2 (wording, phases).

**Branch:** `feat/desk-market-overview`, built on `feat/desk-redesign-shell` (step 1, not merged yet).
**Spec:** `frontend-v5/e2e/tests/copilot-app-desk-market-overview.spec.ts` (mocked APIs, production build).
**Fixtures:** `e2e/fixtures/contract-decision-card.json` (the decision-card contract: the plans, `account_size`, the
risk profile, the stored AI watchlist day, the real allow / reduce / block answers). Anything else is an inline MOCK in
the route's real shape, labelled `MOCK — not real data`.

## Revision (owner, 27 Oct 19:40 IST, PLAN.md "1-REVISED")

The page follows the owner's design's structure: **KPIs** (paper equity, day net P/L, open risk vs 3%, candidates, feed) ·
**Market regime** · **Top AI candidates** ("See all ›" → Trade Desk) · **Paper trades** (read-only, from
`GET /api/risk/profile`) · **Alerts and events**. The one-line Trade Desk link of the first plan is replaced by the KPIs and
the panel. MO-1 and MO-25 … MO-28 below are revised accordingly (and MO-23b added); the rest are unchanged.

## The page (tab=overview), top to bottom (first plan; see the revision above)

| Panel | What it shows | Route(s) it reads |
|---|---|---|
| Trade Desk line | "N open positions · open risk x% of 3% · Trade Desk ›" | `GET /api/risk/profile` (`live.open`, `live.equity`, `profile.limits.max_open_risk_pct`) |
| Market strip | NIFTY 50, Nifty Bank, India VIX; breadth; the regime the risk service sizes with, its as-of date, its freshness, the BEAR note; last session's FII / DII; the day's leading and lagging sectors | `GET /api/markets/home`, `GET /api/risk/freshness`, `GET /api/markets/sector-returns` |
| Top AI ideas | Cash \| F&O toggle; the stored list and scan basis, STALE DATA, the 22:45 IST empty state; per row the decision-card row (+ budgets left), Provisional / Risk-approved, carry-forward; a drawer with the full card and Paper trade; the footer | `POST /api/desk/strategy/ideas {limit:10}`, `POST /api/desk/strategy/top`, `GET /api/desk/ai-watchlist`, `GET /api/desk/trade-plans/{id}`, `GET /api/risk/freshness` (`reference_session`) |
| Events today | Results and filings today for the names on today's ideas, at most 5 | `GET /api/filings/feed` (Market Intelligence's lists, `useIntelEvents`) |
| All scanner candidates | The full scanner list, collapsed | as before (`ScannerTab listOnly`) |

Removed from this page: the account KPIs, the paper-trades table, the feed KPI (the header chip has it), and the old
Overview cards and market pulse (their routes now feed the strip).

## Cases

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| MO-1 | Layout | Open `/app/trader/desk` | e2e | The panels in order: Trade Desk line, market strip, Top AI ideas, events today, "All scanner candidates" (collapsed). No `desk-overview` (old Overview cards), no market pulse, no account KPIs, no paper-trades table, no feed KPI. |
| MO-2 | Strip · indices | `/api/markets/home` answers | e2e | NIFTY 50, Nifty Bank and India VIX tiles show the route's value and change %, with the tape mode (End of day / Live) and stamp. |
| MO-3 | Strip · breadth | breadth in the answer | e2e | "{adv} advancing · {dec} declining", the % advancing worked out from the route's counts. |
| MO-4 | Strip · regime BEAR | freshness `market_state.regime = BEAR`, `as_of` 2026-10-23, `status ok` | e2e | "BEAR · as of 23 Oct" and "New-trade size limits are halved in BEAR." |
| MO-5 | Strip · regime BULL | `regime = BULL` | e2e | "BULL · as of …", no "halved" note; the text says no regime cut applies. |
| MO-6 | Strip · regime stale | `status stale`, `age_sessions 3`, a reason | edge | A "Stale" pill and the line that new paper entries are blocked while the regime input is stale, with the route's reason. |
| MO-7 | Strip · regime unreadable | freshness 500 | failure | "Regime unavailable" with the reason; the rest of the strip still shows. |
| MO-8 | Strip · FII / DII | `fii_dii` in `/api/markets/home` | e2e | Signed ₹ crore for FII and DII and the session date. |
| MO-9 | Strip · sectors | `/api/markets/sector-returns` | e2e | The day's top 3 and bottom 3 sectors by 1-day return, with signs; "Sector Rotation ›" opens `tab=market&view=sectors`. |
| MO-10 | Ideas · rows | the contract's cash idea (ICICIBANK) | e2e | The row's decision card shows entry and order type, stop and method, targets in R, size = `account_size.quantity`, ₹ risk and % of equity, costs, plan id; the figures are worked out from the fixture, never copied from the screen. |
| MO-11 | Ideas · Provisional | `risk_decision: null` | e2e | Amber dashed "Provisional · no risk decision yet". |
| MO-12 | Ideas · Risk-approved | the contract's `allowed.trade_plan_response` (a real allow) | e2e | Mint "Risk-approved". |
| MO-13 | Ideas · budgets | `account_size.portfolio.remaining` | e2e | "May be reduced by portfolio limits at submission" and the budgets left (open risk ₹, positions) on the row. |
| MO-14 | Ideas · carry-forward | stored day with `carried` {sessions 3, from 2026-10-15} on the row's symbol | e2e | "On the list 3 sessions · carried from 15 Oct" on that row. |
| MO-15 | Ideas · scan basis | the board's `selection.scan_date` and the stored day's `notes.scan_basis` | e2e | "From the {date} close" and the stored list's date. |
| MO-16 | Ideas · STALE DATA | scan date older than freshness `reference_session` | edge | A "Stale data" pill in the header naming both dates; absent when the scan is current. |
| MO-17 | Ideas · empty at 22:45 | `/api/desk/ai-watchlist` answers `list_date: null` + `empty_reason` | edge | "No list is stored yet. The job runs each weekday at 22:45 IST…" (the route's words). |
| MO-18 | Ideas · empty board | the ideas route answers no ideas | edge | The board's own empty reason; no rows. |
| MO-19 | Ideas · Cash \| F&O | click F&O | e2e | One board at a time: the F&O rows (BANKNIFTY …) with their decision cards; Cash hides. Default Cash. |
| MO-20 | Ideas · drawer | click "Full card" on a row | e2e | A dialog with the full decision card (every section), the levels and links, Paper trade; Escape and ✕ close it. |
| MO-21 | Ideas · Paper trade | Paper trade in the drawer, risk service answers 409 `risk_reduce` (the contract's real `reduced` answer) | e2e | The route's reason and "Paper trade 83 shares instead" (RiskReduce); accepting re-posts with quantity 83 and plan_ref. |
| MO-22 | Ideas · action gate | a blocked plan (the contract's real `blocked` decision, kill switch on) | e2e | Paper trade is off with the gate's reason; nothing is posted. |
| MO-23 | Ideas · footer | always | e2e | "Ideas, not recommendations. The rank orders ideas; our test found no measurable ranking skill. Scorecard →"; the link opens `tab=market`. |
| MO-24 | Events today | filings feed with a result for a listed name today, one for another name, one from yesterday | e2e | Only today's filing for the listed name shows (≤ 5); its symbol opens the chart; an empty day says so. |
| MO-25 | Trade Desk line | risk profile: 3 open positions, risk ₹12,000 on ₹10,00,000, limit 3% | e2e | "3 open positions · open risk 1.2% of 3%"; the link opens `tab=trade&view=paper`. |
| MO-26 | Trade Desk line · none | 0 open positions | edge | "No open positions · open risk 0% of 3%". |
| MO-27 | Trade Desk line · unreadable | `/api/risk/profile` 500 | failure | "Open positions and open risk didn't load" and the link still works. |
| MO-28 | Read-only | load the page, open a drawer | e2e | No `GET /api/desk/paper-trades` request is made from this tab (it applies exits). |
| MO-29 | Wording | the whole page | e2e | No "pick", "recommended", "suggested", "recommendation" except inside "not recommendations"; the cards' "not a prediction" caveat is present. |
| MO-30 | Phone 390 px | the page and an open drawer | e2e | No horizontal page scroll (`scrollWidth <= innerWidth`); the strip stacks; the drawer fits the screen. |
| MO-31 | All scanner candidates | click the toggle | e2e | Expands, `section=scanner` in the URL, the scanner list mounts; `?tab=scanner` opens it expanded. |

## Regression set (run on this branch AND on the base `feat/desk-redesign-shell`)

Every `copilot-app-desk*.spec.ts`, `copilot-app-ai-watchlist.spec.ts`, `copilot-app-watchlists.spec.ts` and
`watchlist-unauth.spec.ts`. A failure on this branch only is fixed, or (where this step removes a screen from the page by
the plan) the case is moved to the new panel or retired with the reason recorded in the report.

## Gates

tsc clean · production build · the new spec green · no new failure against the base · `test_reports/OVERRIDE_desk_market_overview.md`
(staging deploys only after merge).
