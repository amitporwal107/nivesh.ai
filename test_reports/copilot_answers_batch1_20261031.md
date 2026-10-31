# Functionality Verification Report — Copilot answer fixes, batch 1: F&O setups board and sector rotation

- **Branch:** fix/copilot-answers-batch (from origin/dev 25c61610 = after #427/#428), 2 commits
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER, with the DOMAIN_EXPERT_ANALYST's F&O checks)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env vars); read-only in-process runs inside
  `nivesh-staging-app-backend` over staging's real warehouse; Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend services (copilot_visual, suggestions catalog, copilot_prompts): yes · frontend src: yes
- **Owner asks covered (31 Oct 2026):** the F&O setups answer (max profit not a to-zero figure, lots, margin, stocks, latest EOD or live
  data), the sector rotation answer (heatmap, top five stocks per sector, not a market overview), the `₹-14,406.00` format.

## Summary
1. **F&O setups.** Two sections (Index options, Stock F&O), one row per underlying, its other structures folded under "+N more ›".
   A bought option's profit reads "Not capped" with the profit at the expected move beside it (the to-zero figure only in a tooltip);
   losses print `−₹14,406.00`; each row shows its lots (`1 lot × 30`) and Zerodha's margin: the platform's Kite login, else the user's
   own Zerodha session, else "Needs login" with a notice offering Log in to Kite (admins) and Connect a broker. In the session the
   premiums are live from Kite REST quotes (only contracts that traded today); the ranking stays the close's; row badge "Live", mode "mixed".
2. **Sector rotation.** New intent: leaders/laggards strip, the sector heatmap (1-week return, best first), each tile selectable with its
   five strongest stocks by the day's move; the leading sector is open to begin with. `sector rotation` is no longer a smart-money phrase.

## Test Cases
> Authored before the builder wiring and the frontend. **Honest note:** the helper module `fno_board.py` was written before its tests
> (the protocol says tests first); the builder, readers, validator and every frontend change came after the tests, which were run
> failing first (`16 failed, 2 passed` for FB; `8 failed, 4 passed, 5 errors` for SR) and then made to pass.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| FB-1 | F&O | the owner's shape (both index leads carry two alternatives + stock leads): two sections, leads only, alternatives folded | unit | no stock lost to the row cap; BANKNIFTY, NIFTY / RELIANCE, TCS | PASS |
| FB-2 | F&O | stock class empty | unit | a notice naming the reason, no stock table | PASS |
| FB-3/4 | F&O | long put / long call / spread | unit | "Not capped" + profit at move; to-zero figure only in `tips`; spread keeps its real maximum | PASS |
| FB-5 | F&O | lots | unit | `1 lot × 30` / `× 65` / `× 175`; mixed lot sizes → none, never a guess | PASS |
| FB-6…10 | margin | calculator ok · none · user's Zerodha ended · own Zerodha fallback · one structure fails | unit | figure / "Needs login" + actions / "sign in again" / own source / "—" + reason | PASS |
| FB-11…14 | live | in session repriced by the board engine (oracle = `metrics_for` on the same legs) · no live spot · market closed · live unavailable | unit | live row = oracle; ranking untouched; mode mixed; no live read when closed; reason + login ask | PASS |
| FB-15 | contract | validator covers alternatives, tips, badge, notice actions | unit | accepts good, rejects malformed | PASS |
| FB-16…18 | fno_board | margin = one basket call in lots × lot size, cached; refused session falls to the next calculator; live quotes only for contracts traded today | unit (fake Kite) | as stated | PASS |
| FB-19/20 | regression | found on staging data: real regime has `as_of` not `date`; all calculators refusing → one login notice | unit | no false stale notice; one notice, no per-row noise | PASS |
| SR-1 | resolver | 10 questions | unit | sector questions → sector_rotation; smart money / FII-DII / build-up unchanged | PASS |
| SR-2…8 | sector | wiring; leaders first + five per sector + no padding; unread sector keeps its tile; no data; stale members; contract; DaaS reader | unit | as stated | PASS |
| C-2 | contract | the REAL staging capture holds a payload for every builder (existing guard) | unit | fails until `sector_rotation` is captured; PASS after the capture | PASS |
| FE-1…10 | F&O UI | sections/rows from the payload · "+N more" fold · lots, "Not capped" + tooltip · true minus · "Needs login" + actions · non-admin sees no platform login · live badge + margin · phone cards · wide table (forced 1300 px) | e2e | each value computed from the payload | PASS (10/10; FE-9 is the opt-in screenshot run) |
| SE-1…6 | sector UI | heatmap first · leader open · switch/hide/keyboard · member Ask › asks its plan · plain tile · phone | e2e | as stated | PASS |
| REG | regression | visual-answer (now incl. the real capture's new fno_setups + sector_rotation), app, desk, decision cards, positions, daily-trader, copilot window | e2e | no new failure | PASS |
| CI | regression | the full backend CI allowlist, baseline vs branch | unit | no new failure | PASS |

## API / Endpoint Tests
**No new HTTP endpoint** is added; the change is the Copilot chat's pre-step builders (`routes/chat.py` calls `services/copilot_visual`).
There is no staging deploy of this branch, so the builders were exercised in-process inside `nivesh-staging-app-backend` on staging's
real data (below), and the chat route's own tests ran in the suite.

- `pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_prompts_mode.py tests/test_copilot_trade_idea.py tests/test_suggestions.py` (full-layout tree, CI env):
  **`306 passed`** (baseline on origin/dev before the change: `196 passed, 1 skipped` on the first four files).
- **Full CI allowlist, baseline measured on a clean `git archive origin/dev` with the same layout:**
  - origin/dev: `13 failed, 7619 passed, 34 skipped in 273.46s`
  - this branch: `13 failed, 7656 passed, 34 skipped in 267.07s`
  - FAILED names compared (`comm -13` and `comm -23` on the sorted lists): **both empty — identical lists**. +37 passed = the new tests.
  - The first branch run showed one extra failure, `test_c2_the_staging_capture_matches_the_contract`: the existing guard that the real
    staging capture has a payload for every builder. It had been skipped in all my earlier runs (the sparse worktree mounted no
    fixtures) and ran only once the full layout existed. Fixed by capturing `sector_rotation` and the new `fno_setups` from staging (below).

## UI / Playwright Tests
Production build (`VITE_USE_MOCK_API=false VITE_BASE=/v5/ vite build`, `BUILD_EXIT=0`) served by `vite preview`, `pw.copilot-app.config.ts`, `--network none`.
- `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0` (re-run after the last frontend source change).
- Regression set (fno-board, sector-rotation, visual-answer, app, desk, desk-decision-cards, positions): **`128 passed, 3 skipped`** (the 3 skips are the three opt-in screenshot tests: VA-19, FE-9, SE-6).
- daily-trader + desk-copilot-window: **`19 passed`**.
- After the real captures were merged into the fixture and `sector_rotation` added to the spec's intent list (the trap in `daily-trader-copilot-program`): fno-board + sector-rotation + visual-answer: **`48 passed, 3 skipped`**.
- **What the runs found (fixed, not hidden):** (1) the old visual-answer spec asserted the format `₹-14,406.00` that the owner reported as a defect; its
  expectation and the contract doc now say `−₹14,406.00`. (2) A ten-column table overflowed and clipped inside the ~800 px thread column and broke a loss across two lines
  (seen in the screenshots): a table now needs 560 px + 110 px per column beyond seven (cards below that), figures never wrap, and a wide board's card cells are wider.
  (3) Two of my own tests assumed the table layout and the tooltip on the row; both made layout-independent (the tooltip is now on the figure in both layouts).

## Data Correctness (staging, read-only, in-process)
Overlay of this branch's `services/copilot_visual` over the deployed tree inside `nivesh-staging-app-backend` (`/tmp/ov_fnoboard`), auth stubbed to a
probe identity, **no storage write** (`regime_fit.build_top` alone replaced the route's store-and-return; no broker call for any user).

**F&O board — BEFORE (deployed code), the owner's screenshot reproduced from real data:** 5 rows under one block, `BANKNIFTY` ×3 and `NIFTY` ×2;
Long put 54700 max profit 1618186.5 (= 54,700 × 30 − 22,813.50, the payoff with the index at zero); Long put 23050 max profit 1489975.5 (= 23,050 × 65 − 8,274.50); a
"stale, unknown date" notice on the answer; no stock row.

**F&O board — AFTER (this branch), unedited output:**
```
validate: []
builder file: /tmp/ov_fnoboard/copilot_visual/builders.py
as_of 2026-10-30 mode eod | headline: 7 F&O setups fit today's regime (Bearish): 2 index, 5 stock.
== fno_index Index options · 2 setups | rows 2
   BANKNIFTY | Bear put spread 53100/54700 | 1 lot × 30 | loss -14406.0 | profit 33594.0 | atmove 33337.54 | rr 2.31 | margin Needs login | badge 30 Oct close | alts 2
   NIFTY | Bear put spread 22800/23050 | 1 lot × 65 | loss -5450.25 | profit 10799.75 | atmove 9254.87 | rr 1.7 | margin Needs login | badge 30 Oct close | alts 2
== fno_stock Stock F&O · 5 setups | rows 5
   PERSISTENT | Bear put spread 5800/6000 | 1 lot × 125 | loss -10106.25 | profit 14893.75 | atmove 14641.86 | rr 1.45 | margin Needs login | badge 30 Oct close | alts 2
   PNB | Bear put spread 120/123 | 1 lot × 8000 | loss -9760.0 | profit 14240.0 | atmove 13927.46 | rr 1.43 | margin Needs login | badge 30 Oct close | alts 2
   ZYDUSLIFE | Bear put spread 1200/1250 | 1 lot × 450 | loss -9270.0 | profit 13230.0 | atmove 12980.0 | rr 1.4 | margin Needs login | badge 30 Oct close | alts 2
   ANANDRATHI | Bear put spread 2200/2260 | 1 lot × 250 | loss -6312.5 | profit 8687.5 | atmove 8499.01 | rr 1.35 | margin Needs login | badge 30 Oct close | alts 2
   INDIANB | Bear put spread 850/870 | 1 lot × 1000 | loss -9850.0 | profit 10150.0 | atmove 9834.79 | rr 1.0 | margin Needs login | badge 30 Oct close | alts 2
== notice login | Margin need a Kite login: ask an admin to log in to Kite for the day (the header's Log in to Kite), or connect your own Zerodha account in Brokers. | actions ['kite_login', 'connect_broker']
== trade_plan first |  | actions []
sources: [("Desk F&O board (StrategyPlan, fit to today's regim", '2026-10-30', 'fresh')]
missing: ['Margin: every Zerodha calculator session was refused (the Kite login has expired)']
```
Real findings: the stock class **does** build ideas (5 of them: PERSISTENT, PNB, ZYDUSLIFE, ANANDRATHI, INDIANB) that the old five-row cap hid; the real regime carries
`as_of`, not `date`, so every F&O answer carried a false stale notice (fixed, FB-19); the platform calculator object exists but its token is refused, which printed 21
per-row lines and no login prompt (fixed, FB-20).

**Sector rotation — real data, unedited output:**
```
builder file: /tmp/ov_fnoboard/copilot_visual/builders.py
'Which sectors are leading and lagging?' -> sector_rotation
'Show sector rotation today' -> sector_rotation
'Where is smart money moving?' -> smart_money
validate: []
as_of 2026-10-30 mode eod | headline: Pharma leads the week (+7.09%) and Cement lags (−1.79%).
blocks: [('kpis', 'summary'), ('heatmap', 'rotation')]
kpis: [('Leading', 'Pharma', '+7.09% over 1 week'), ('Lagging', 'Cement', '−1.79% over 1 week'), ('Sectors up today', '5 of 20', "by the sector index's 1-day move")]
tiles: 20
   Pharma 7.09 | 1d +1.55% · 1m +0.71% | members: [('LAURUSLABS', 7.2, None), ('ZYDUSLIFE', 5.16, None), ('SAILIFE', 4.13, None), ('PPLPHARMA', 3.52, None), ('CIPLA', 1.54, None)]
   Healthcare 6.91 | 1d +1.58% · 1m −0.68% | members: [('LAURUSLABS', 7.2, None), ('ZYDUSLIFE', 5.16, None), ('APOLLOHOSP', 3.02, None), ('FORTIS', 1.76, None), ('CIPLA', 1.54, None)]
   Power 5.9 | 1d +0.22% · 1m −1.76% | members: [('VEDPOWER', 14.72, None), ('POWERGRID', 1.92, None), ('SJVN', 1.89, None), ('NTPC', 1.85, None), ('NHPC', 0.7, None)]
   Media 4.34 | 1d −1.46% · 1m +5.86% | members: [('SAREGAMA', 2.36, None), ('PVRINOX', 0.32, None), ('TIPSMUSIC', -1.18, None), ('MPSLTD', -1.3, None), ('PFOCUS', -1.55, None)]
   Oil & Gas -0.74 | 1d −0.47% · 1m −2.50% | members: [('GAIL', 1.66, None), ('CASTROLIND', 0.2, None), ('PETRONET', 0.12, None), ('CHENNPETRO', -0.02, None), ('OIL', -0.11, None)]
   Cement -1.79 | 1d −1.26% · 1m −3.32% | members: [('INDIACEM', 3.95, None), ('GRASIM', 1.66, None), ('JSWCEMENT', -0.27, None), ('SHREECEM', -0.54, None), ('ULTRACEMCO', -1.16, None)]
tiles without members: []
sources: [('NSE sector indices (desk sector returns)', '2026-10-30', 'fresh'), ('NSE index lists with bhavcopy closes (stocks of ', '2026-10-30', 'fresh')]
missing: []
```
The leaders match the owner's screenshot (Pharma +7.09%, Healthcare +6.91%, Power +5.90%, Media +4.34%). The real constituent rows carry no index weight, so none is shown (nothing invented).

## UNVERIFIED (see OVERRIDE_copilot_live_margin_real_data.md)
- **Live repricing and a real margin figure** have never run on real Kite data: it was Saturday 31 Oct and the platform Kite token had expired, so staging answered "Needs login" (that path IS verified on real data).
  Verified on constructed inputs only: the repricing against the board's own engine (FB-11), the calculator calls against a fake Kite (FB-16/17), and the quote filter against a fake Kite (FB-18).
- **Stock option quotes live:** the live feed carries index options only; this reads Kite REST `quote()` for the named contracts, including stock options. Not run for real.
- **TrueData** is a shadow feed in dev ("serves nobody"), so Kite is the only live source wired. The reader seam is `readers.py` (`fno_live_quotes`, `live_spots`).
- **The wide-table layout** (a box of 890 px or more) cannot be reached in the mocked thread column (about 800 px at any window width); it is exercised by forcing the box to 1300 px (FE-10), not seen in a real wide window.
- **Not deployed.** A merge to dev rebuilds the frontend; the backend needs a process restart (staging-deploy-timing-trap). Disk is 6.9 GB free against the 6 GB a deploy needs.

## Decisions for the owner
1. **LLM capacity** (found while investigating the runtime error): the staging chat's LLM runs through `/opt/claude-gateway` under the VM's own Claude login, so dev sessions and agents exhaust the same 5-hour limit ("trouble connecting"). A dedicated API key or a separate login for the gateway is needed.
2. "Top 5 stocks of a sector" is ranked **by the day's move** (the constituent read carries only that); say if you want it by weight or by a one-week return.
3. FII/DII flows are no longer in the sector answer; they stay under smart money.

## Not built yet (the rest of the owner's list)
Open trades from the broker book with a 5-second refresh, the F&O buildup popup, broker trades in the daily review, "Plan a bearish trade for X" and the graceful LLM-down message, risk-profile capture; and the two plans (Risk Management, Screener/Watchlist).

## Cleanup
Containers `docker run --rm`; no leftover test containers. The staging overlay `/tmp/ov_fnoboard` was removed from `nivesh-staging-app-backend` (checked: the directory is gone). Scratch under the session scratchpad.

## Verdict: PASS
Scope: the backend (306 in the copilot suites; the allowlist has the same 13 failures as origin/dev), the screens against MOCK payloads built by the real builder and against the
real staging capture, and the read-only staging runs on real data. The live-quote and margin figures on real Kite data are open and covered by `OVERRIDE_copilot_live_margin_real_data.md`.
