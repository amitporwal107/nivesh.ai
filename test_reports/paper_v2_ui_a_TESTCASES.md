# Paper Trading v2 (builder A) — navigation, shell, Overview, Scanner opportunities, Strategy analytics — test cases

Owner decision, 5 Nov 2026 ~08:00 IST: "We need to completely replace the current paper trading dashboard." Trade Desk ›
Paper Trading becomes exactly the owner's six views (docs/scanner_paper_trading/UI_DESIGN_V2.md, the build spec).
Builder A owns: the navigation and redirects (desk-nav.ts), the Paper Trading shell (status strip, account card, mode
chooser), 01 Overview, 02 Scanner opportunities, 06 Strategy analytics, and the Trade Desk / Risk Desk wiring. Builder B
owns 03 Capital allocation, 04 Portfolio risk, 05 Real-time P&L (their own test cases: test_reports/paper_v2_ui_b_*).

Contracts: UI_DESIGN_V2.md §7 (`GET /api/v1/paper/overview`, `GET /api/v1/analytics/account/{id}?days=90`) and the existing
routes read from code: `routes/spt_accounts.py` (+ `services/paper_account.public`), `routes/spt_signals.py`,
`routes/spt_risk.py` (+ `services/spt/risk.py` risk record `checks[]`), `services/spt/outcomes/analytics.py`,
`routes/watchlists.py` (`GET /api/watchlists`, `POST /api/watchlists/{id}/symbols`).

Automated in `frontend-v5/e2e/tests/copilot-app-desk-paper-v2-a.spec.ts` with MOCK bodies (every one labelled
`// MOCK — not real data`). Mocked APIs, production build: these cases prove the screens render what the bodies say and send
the right requests; they do NOT prove the backend answers these shapes (the integrator's real-body render does that,
`copilot-app-desk-spt-real.spec.ts` with SPT_REAL_DIR).

## Navigation and redirects

| ID | Case | Expected |
|---|---|---|
| PV2-A-01 | Paper Trading sub-views | Chips, in order: 01 Overview · 02 Scanner opportunities · 03 Capital allocation · 04 Portfolio risk · 05 Real-time P&L · 06 Strategy analytics; each number is a separate small mono span before its label |
| PV2-A-02 | Default | `?tab=trade&view=paper` (no sub) lands on `sub=overview`; the Overview chip is pressed; the breadcrumb ends "Paper Trading›Overview" |
| PV2-A-03 | Each chip | Clicking each chip sets `sub=` to overview / opportunities / allocation / risk / pnl / analytics and mounts that view (`pv2-overview`, `pv2-opps`, B's Allocation, B's Risk, B's P&L, `pv2-analytics`) |
| PV2-A-04 | Old Paper Trading keys | `sub=live` → `sub=pnl`; `sub=journal` (with `&trade=<id>`) → `sub=pnl` keeping `trade=`; `sub=settings` → `sub=allocation`; `sub=opportunities` and `sub=analytics` stay; an unknown sub → `overview` |
| PV2-A-05 | Old Trade Desk views | `?tab=trade&view=open` → `view=paper&sub=pnl`; `?tab=trade&view=closed` → `view=paper&sub=pnl` |
| PV2-A-06 | Old Risk Desk SPT views | `?tab=risk&view=overview` → `tab=trade&view=paper&sub=overview`; `view=allocation` → `sub=allocation`; `view=portfolio` → `sub=risk` |
| PV2-A-07 | Risk Desk views | The Risk Desk switcher reads Exposure & limits · Policy & runtime · Decision log (· Portfolio hedge last, with its flag); no Trading overview / Capital allocation / Portfolio risk |
| PV2-A-08 | Opportunities badge | A mono amber count on the 02 chip = `count` of `GET /api/v1/proposals?state=AWAITING_USER_APPROVAL`; hidden when 0 |

## Shell (every Paper Trading view)

| ID | Case | Expected |
|---|---|---|
| PV2-A-10 | Status strip, live | From `GET /api/v1/paper/overview` `status`: "● Live · paper" (mint), "Market open · HH:MM IST", "Data fresh · 1.2s" (mint), "Policy v7", right-aligned "Kill switch · ACTIVE" (mint) |
| PV2-A-11 | Status strip, stale / down / halted / closed | `last_tick_age_s` 42 → "Data stale · 42s" amber; `feed_state` down → "Feed down" danger; `kill_switch.entries_blocked` true → "Trading halted" danger with the text as its title; `feed_state` closed → "Feed closed · last tick 1h 06m ago" plain and "Market closed · HH:MM IST" (a closed market's old tick is not an alarm) |
| PV2-A-12 | Status strip, unreadable | Overview read fails → the strip says the status could not be read (the error) and shows no invented state |
| PV2-A-13 | Shell on every view | The strip and the account card are shown on all six sub-views |
| PV2-A-14 | Account card | "Account · Mode", "Paper account", the starting capital from `account.starting_capital_rs` (₹10.00 L), and the mode pill (e.g. APPROVAL MODE) |
| PV2-A-15 | Mode chooser | Clicking the pill opens off / tracking / approval / auto with one-line meanings; Tracking PUTs `/api/v1/paper/accounts/{id}/config` `{mode:"tracking", expected_version}` |
| PV2-A-16 | Auto confirm | Auto first asks to confirm; Cancel sends nothing; Confirm PUTs `{mode:"auto"}` |
| PV2-A-17 | Mode refused | A 409 `concurrent_change` or 403 is shown in words, nothing claimed as saved |

## 01 Overview

| ID | Case | Expected |
|---|---|---|
| PV2-A-20 | Synthesis with a concentration | `headline` {setups_cleared 3, worst_concentration {name "Banks", pct 42}} → "3 setups cleared the risk engine today — but Banks already carry 42% of open risk." with the concentration in an amber span |
| PV2-A-21 | Synthesis without | `worst_concentration` null → "3 setups cleared the risk engine today." (no amber span); 1 → "1 setup cleared …" |
| PV2-A-22 | Prose line | "{signals} scanner signals consolidated into {opps} opportunities. {blocked} … blocked by the risk engine and {reduced} … reduced to fit the risk budget." from `headline` |
| PV2-A-23 | KPI tiles | Six tiles: Account equity "start ₹X"; Daily P&L mint/danger "limit -X% · used Y%"; Capital deployed "N% · cash ₹"; Open planned risk amber when > 80% of the budget, "of X% budget"; Drawdown "warning at X%"; Positions "n / max", "k pending orders" — all from `kpis` |
| PV2-A-24 | Null KPI | A null KPI reads "—", never 0 |
| PV2-A-25 | Pipeline | Six rows Scanner signals → Opportunities → Qualified → Risk approved → Orders filled → Open positions with counts; bar widths relative to scanner signals; the footnote "A scanner signal is not a trade. Each stage can reject, expire or reduce." |
| PV2-A-26 | Risk warnings | Each warning: dot coloured by level, title, mono meta "CODE · HH:MM"; mint items (e.g. "All feeds healthy") last |
| PV2-A-27 | Empty states | No warning → "No risk warning was raised today."; empty pipeline → says the counts were not sent; overview read fails → the problem with Retry, no figures |

## 02 Scanner opportunities

| ID | Case | Expected |
|---|---|---|
| PV2-A-30 | Header and table | Eyebrow "Scanner opportunities", h1 "Consolidated setups, ranked after the risk engine has spoken."; table columns Symbol (+ "LONG · EQ") · Signals ("N sources") · Opp score · Entry · R:R ("2.0:1") · Risk ₹ · Decision |
| PV2-A-31 | Decision pills | APPROVE mint · APPROVE REDUCED amber · CONDITIONAL indigo · BLOCKED danger · WATCHLIST plain · TRACKED plain (F&O idea, NOT_TRADABLE) · ORDER CREATED mint |
| PV2-A-32 | Ranking | Awaiting your approval first, then by opportunity score |
| PV2-A-33 | Detail | Selecting a row highlights it (bg-3) and fills the detail: "{id} · AWAITING USER APPROVAL", serif symbol, decision pill, the reason sentence, "Supporting signals · N" tiles (scanner · time · score), Strategy plan Entry / Stop / T1 / T2 tiles, sizing (Quantity "full size" / "reduced from N" / "would be N", Capital, Planned risk), every risk check from `risk.checks[]` with ✓ / ! / × |
| PV2-A-34 | Approve | "Approve paper trade" POSTs `/api/v1/opportunities/{id}/approve`; the pill turns "ORDER CREATED" (mint) and the button reads "Done · order created" (disabled) |
| PV2-A-35 | Approve refused | A 409 with code / message / reason codes is shown; no success claimed |
| PV2-A-36 | Conditional | A CONDITIONAL proposal awaiting approval reads "Arm conditional order" |
| PV2-A-37 | Reject | "Reject" asks for a one-line reason; empty sends nothing; with a reason POSTs `/reject {reason}`; the pill reads "USER REJECTED" |
| PV2-A-38 | Add to watchlist | POSTs `/api/watchlists/{first list id}/symbols {symbol}`; the pill reads "WATCHLISTED"; with no list it says to make one in Watchlists |
| PV2-A-39 | Disabled states | Approve is disabled (opacity .35) for BLOCKED, WATCHLIST, TRACKED and after an action; a BLOCKED item shows "The risk engine has the final say. User approval cannot override a hard limit."; others "Approval expires if price leaves the entry range, data goes stale or policy changes." |
| PV2-A-40 | Empty / error | No opportunities and no proposals → says none yet and why; a failing read → the problem with Retry |

## 06 Strategy analytics

| ID | Case | Expected |
|---|---|---|
| PV2-A-50 | Header and synthesis | Eyebrow "Strategy analytics · last 90 days"; "{best} earn the edge. {weakest} lack sample size to scale." from `by_setup` (best = highest positive expectancy; weakest = fewer than 30 trades) |
| PV2-A-51 | KPI tiles | Trades "closed"; Win rate "avg win xR"; Expectancy "+0.31R net of costs"; Profit factor; Max drawdown "peak to trough"; Sharpe / Sortino |
| PV2-A-52 | Null Sharpe | `sharpe`/`sortino` null → "—" with `ratio_reason` shown |
| PV2-A-53 | Scanner attribution | From `GET /api/v1/analytics/scanners`: Scanner · Signals · T+5 · T+20 · MFE / MAE · Evidence (Sufficient mint n ≥ 30, Building amber, Low sample danger n < 15) |
| PV2-A-54 | Certification | "Certification · {setup}": each criterion with ✓ / ! / × and its value; not measured → amber "!" and "not measured"; the note "Risk allocation increases only after every criterion passes. A winning streak alone does not qualify." |
| PV2-A-55 | Expectancy by regime | Uptrend / Sideways / Downtrend rows with a bar and "+0.52R" |
| PV2-A-56 | Empty | 0 trades → the synthesis says there is nothing to measure yet; no metric invented |

## Cross-cutting

| ID | Case | Expected |
|---|---|---|
| PV2-A-60 | Compliance lint | No "recommend", "pick" or "suggest" in the text, labels or titles of the shell, Overview, Scanner opportunities, Strategy analytics |
| PV2-A-61 | 390 px | Each of the three views and the shell: no sideways page scroll; the opportunities table scrolls inside its card; the 06 chip reads "Analytics" (the chip row overflows at 390 px, §1) |
| PV2-A-62 | No sample figures | Every figure on screen comes from the mocked bodies (spot-checked against them) |
