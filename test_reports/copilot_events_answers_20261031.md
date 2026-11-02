# Functionality Verification Report — Copilot answers for corporate results and market-research events

- **Branch:** feat/copilot-events-answers (from origin/dev f30c7019, which already holds #430 and #431; not stacked)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER, with the DOMAIN_EXPERT_ANALYST honesty rules for filings)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env vars); read-only in-process runs inside `nivesh-staging-app-backend` over staging's real code and data (overlay removed afterwards); Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend routes/services (services/copilot_visual, routes/copilot_prompts.py, services/suggestions): yes · frontend src (components/chat/visual): yes
- **Owner asks covered (31 Oct 2026):** (1) "Which companies report results this week?" went to the Filings analyst, which said it had no results calendar ("We do have event calendar and all results with us");
  (2) "Please provide an AI summary of each of the result and management commentary and source pdf link to download"; (3) "Users can ask any questions on the market research like order winning, Mergers and Acquisitions, Ownership" (the desk's AI Event Intelligence chips, answered from the same feed).

## Summary
Two new visual-answer intents and one new block type; every figure and every summary comes from the sources the desk itself reads.
1. **`results_calendar`** — "Which companies report results this week / today / tomorrow / yesterday / next week / last week?", optionally F&O only or one sector. Counts; up to 8 declared results as cards (the STORED AI summary verbatim, the desk's verdict "vs historical trend" or the filing analysis's band as the badge, management-commentary points on request, source-filing links to download); up to 15 companies still to report (F&O first); "Showing 8 of 494 declared results…" with **Open in Market Intelligence ›**.
2. **`event_intelligence`** — the desk's chips: announcements, results, calls and guidance, orders, M&A and actions (mna + dividend + buyback, as the chip merges them), ownership, bulk and block deals (a table), regulatory (+ SEBI circulars), exchange notices, all; optionally for one stock ("How were TCS results?", "Any order wins for L&T?"). A stock's results are ONE card: the result's stored summary, commentary, links.
3. **`briefs` block** (schema.ts, payload `_block_problems`, contract doc, `Briefs.tsx`): accessible cards, one column at any width (phone checked), commentary folded until asked for, a long summary clamped with Read more.
4. **Links**: only an attachment URL the data carries; https + an allow-list of NSE/BSE archive hosts (and SEBI for circulars) enforced in the backend (`links.py`, `validate`) AND the frontend (`safeFilingUrl`); `target=_blank rel="noopener noreferrer"`; labelled "Results filing (PDF) ›", "Source filing (PDF) ›".
5. **Honesty**: the builders never write summary text. No analysis → "Not analysed yet" (the filing link still shows); the analyses could not be read → says so (never "not analysed"). No analyst consensus is held, so a verdict is "Above / In line with / Below historical trend" and nothing is called a beat or a miss. The answer says how many were left out.

**Design decision (latency).** The desk's `build_day` (the body behind GET /api/desk/results-week) takes **14.09 s** cold on staging (~1,800 reads of financials, prices and open interest for a composite score and reaction the chat does not show). The calendar answer instead reads the same calendar (`loaders.expectations`) and the same stored analyses (`loaders.filing_analysis`) and applies the desk's OWN pure functions (`build.status_of`, `scoring.surprise`, `build.pick_analysis`, `scoring.outlook`): **0.32 s**, and the 524 rows it produced match build_day's on status, verdict, summary, band, F&O flag, sector and period for every one of the 524 companies (differences: none; see Data Correctness). This also gives next week, tomorrow and last week, which the desk's route refuses or cannot build (future date 422, no stored snapshot).

## Test Cases
> Authored before the builders: the test file was written first against the design (resolver patterns, reader shapes, block contract), the builders afterwards. The first run after implementation had 1 resolver failure ("earnings calls this week" was read as the results calendar), then 3 more ("What are the Q2 results of Reliance?" dropped by the definition guard, a `None` assertion artefact in the link test, and the suggestions/prompts wiring); all fixed. Real-data runs then found 3 more defects the mocks could not (listed under Data Correctness) and fixed them with tests.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| EV-R1 | resolver | 17 calendar phrasings (the owner's, today / tomorrow / next week / last week, F&O only, sector, "announced results today", "earnings calendar") | unit | `results_calendar` with the right period, F&O flag, sector | PASS |
| EV-R2 | resolver | 28 market-research phrasings: order wins / order book updates / contracts awarded, M&A / merger / demerger / buyback / open offer / stake sale / dividend announcements, promoter holding changes / pledge / insider / SAST, bulk and block deals, calls / guidance / concall, SEBI circulars, exchange notices, capex / QIP, "latest corporate announcements" | unit | `event_intelligence` with the chip and period | PASS |
| EV-R3 | resolver | a named stock: "How were TCS results?", "Did INFY beat estimates?", "What are the Q2 results of Reliance?", "What did Infosys management say about guidance?", "Any order wins for L&T?", bulk deals in RELIANCE, pledge change in INFY | unit | `event_intelligence` for that stock and chip | PASS |
| EV-R4 | resolver (must NOT capture) | "Is INFY a buy now?", "Is TCS a buy after results?", entry/target/stop after results, smart money, FII/DII flows, sectors, market view, F&O build-up, breakouts, unusual volume, "How did I do this week?", open trades, "Should I hold TCS after results?", trade validity, F&O setups, expected move | unit | each keeps its existing intent | PASS |
| EV-R5 | resolver (must NOT capture) | "What is the promoter holding of TCS?", dividend yield, "What is a bulk deal?", "Explain how to read quarterly results", "How do M&A deals work?", "Why did TCS fall after results?", "How did Nifty react to results this week?", order-book depth, "Place an order…", "How do I place a limit order?", news, compare, PE, chart, gainers, "Is this stock a buy now?" | unit | None (or another intent): never a calendar or event answer | PASS |
| EV-R6/R7 | wiring | INTENTS, BUILDERS, AGENT_FOR (market_analyst); every follow-up / Ask the answers offer resolves back to an answer | unit | as stated | PASS |
| EV-L1…L3 | links | https only, allow-listed hosts only; http, `javascript:`, look-alike host, user-info, port, space, backslash, `//` rejected; label says PDF/file; the reader classifies a filing by its SUBJECT line only (a newspaper ad that mentions results is not the results filing) | unit | as stated | PASS |
| EV-B1…B3 | calendar | counts, the 8 cards (analysed first, F&O favoured, then material), body is the stored text verbatim, "Not analysed yet", badge by verdict / band / not rated, basis note | unit | as stated | PASS |
| EV-B4…B6 | calendar | commentary + links from the company file (this result's window only, last quarter's deck excluded, one file once); a forged / foreign link never reaches the payload; an unreadable company file is said and the summary stays | unit | as stated | PASS |
| EV-B7 | calendar | per-company reads capped at 8 and at most 4 at a time | unit | `calls == 8`, `peak <= 4` | PASS |
| EV-B8…B12 | calendar | still-to-report list F&O first; next week (no cards, 15 of 20); each period is the date range asked for; F&O and sector filters (and the companies with no sector on record said); nothing reporting says so | unit | as stated | PASS |
| EV-B13…B17 | calendar failures | calendar unreadable (nothing invented); analyses unreadable (not "not analysed"); stale calendar flagged; partial calendar warned; Sunday "this week" = the coming week | unit | as stated | PASS |
| EV-E1…E10 | events | orders cards (stored text, impact order, link, left-out note); M&A merges mna + dividend + buyback without duplicates; ownership family + the desk's own gap; deals table with the exchange's disclosure, none / stale deals; regulatory + SEBI circulars (forged circular link dropped); calls say "no guidance tracker"; "today" keeps today's filings only; feed unreadable; one stock's feed filtered to the chip | unit | as stated | PASS |
| EV-S1…S5 | stock results | one card: summary + commentary + links; not analysed still links; no calendar row = no verdict (classifier reading, labelled), calendar down is said; no results filing says so; calls for a stock | unit | as stated | PASS |
| EV-C1 / F1 / F2 | contract, facts, wording | `validate` rejects a bad link, kind, tone, title, action; the facts block carries the cards (≤ 6,100 chars); no buy / recommend / pick wording | unit | as stated | PASS |
| EV-W1 / W2 / P1 | wiring, fixture, chat pre-step | suggestions templates + trader prompts resolve to the new intents; the Playwright mock fixture equals what the builders make today; the owner's question through `prepare` gives the widget, facts and the pinned node | unit | as stated | PASS |
| SG-T1B | suggestions | every visual intent has a template; count 16 | unit | as stated | PASS |
| EA-1…EA-11 | UI | calendar cards verbatim; links (href, `_blank`, `noopener noreferrer`, label); commentary folded / expanded with tone in words; long summary clamp; due table + Ask; Open in Market Intelligence; forged links never drawn; orders; one company; card Ask; phone 390 px (no sideways scroll, tap targets ≥ 32 px) | e2e | each value computed from the payload | PASS (11/11; EA-12 screenshots are opt-in) |
| VA | UI regression on the REAL capture | the two new intents drawn from the staging capture, with the `briefs` case in the spec | e2e | all 16 intents | PASS |
| REG | regression | fno-detail, risk-profile, fno-board, sector-rotation, visual-answer, app, desk, decision cards, positions, daily-trader, copilot window, risk-phase1, risk-desk, smart-money specs | e2e | no new failure | PASS |
| CI | regression | the full backend CI allowlist | unit | the same 13 failing names as origin/dev | PASS |

## API / Endpoint Tests (staging, read-only, in-process)
No new HTTP endpoint (the answers ride POST /api/chat/stream's existing visual pre-step). The builders were run inside `nivesh-staging-app-backend` (started 2026-10-31 16:13 UTC, dev head f30c7019) with this branch's `services/copilot_visual` first on the package path, auth stubbed, nothing written; overlay `/tmp/ov_events` removed afterwards (checked).

**BEFORE — the deployed code, the owner's phrase and its relatives (real output):**
```
14 ('market_view', 'smart_money', 'top_opportunities', 'breakouts', 'unusual_volume', 'stock_decision', 'expected_move', 'open_trades', 'fno_setups', 'trade_validity', 'exit_options', 'position_size', 'daily_review', 'sector_rotation')
'Which companies report results this week?' -> None
'Any order wins this week?' -> None
'Any M&A announcements today?' -> None
'Show promoter holding changes' -> None
'Which stocks saw bulk deals today?' -> None
'How were TCS results?' -> None
'Did INFY beat estimates?' -> None
```
None means the chat takes its usual path: the Filings analyst ("I have no results calendar"), or "trouble connecting" when the shared LLM limit is spent.

**AFTER — the overlay, same questions plus the must-not-capture ones (real output):**
```
16 ('sector_rotation', 'results_calendar', 'event_intelligence')
'Which companies report results this week?' -> ('results_calendar', None, {'period': 'this_week', 'fno_only': False, 'sector': None})
'Any order wins this week?' -> ('event_intelligence', None, {'category': 'orders', 'period': 'week'})
'Any M&A announcements today?' -> ('event_intelligence', None, {'category': 'mna', 'period': 'today'})
'Show promoter holding changes' -> ('event_intelligence', None, {'category': 'ownership', 'period': 'week'})
'Which stocks saw bulk deals today?' -> ('event_intelligence', None, {'category': 'deals', 'period': 'today'})
'How were TCS results?' -> ('event_intelligence', 'TCS', {'category': 'results', 'period': 'month'})
'Did INFY beat estimates?' -> ('event_intelligence', 'INFY', {'category': 'results', 'period': 'month'})
'Is INFY a buy now?' -> ('stock_decision', 'INFY', {})
'Where is smart money moving?' -> ('smart_money', None, {})
'What is the promoter holding of TCS?' -> None
```

**The builders over the real data (unedited; `validate=[]` is the contract check; time is the whole build, including the per-company reads):**
```
== cal_this_week: 0.56s validate=[] as_of=2026-10-31 stale=False title='Results calendar · 26–31 Oct 2026'
   headline: 524 companies report in 26–31 Oct 2026: 494 declared (113 with an AI summary), 24 awaiting figures, 6 still to report.
   blocks: [('kpis', 'counts', 6), ('briefs', 'declared', 8), ('ranked', 'due', 15), ('notice', 'more', 0)]
== cal_today: 0.25s ... 'Results calendar · Sat 31 Oct 2026'   headline: 52 companies report in Sat 31 Oct 2026: 29 declared (0 with an AI summary), 17 awaiting figures, 6 still to report.
== cal_next_week: 0.30s ... 'Results calendar · 2–7 Nov 2026'   headline: 803 companies report in 2–7 Nov 2026: 803 still to report.   blocks: kpis, ranked due (15), notice
== cal_fno_tomorrow: 0.06s ... 'Results calendar · Sun 1 Nov 2026 · F&O'   headline: 1 company reports in Sun 1 Nov 2026 (F&O names only): 1 still to report.
== cal_it: 0.44s ... 'Results calendar · 26–31 Oct 2026 · Information Technology'   headline: 9 companies report ... (Information Technology only): 7 declared (0 with an AI summary), 2 awaiting figures.   (+ the no-sector notice)
== ev_orders: 0.26s   headline: Order filings in the last 7 days: 74. All 8 shown have an AI summary.
== ev_mna: 0.20s      headline: M&A and corporate-action filings in the last 7 days: 274. All 8 shown have an AI summary.
== ev_ownership: 0.17s  headline: Ownership disclosures in the last 7 days: 1. All 1 shown has an AI summary.   (+ the desk's own gap: SAST / PIT files not loaded)
== ev_deals: 0.11s as_of=2026-10-30   headline: 389 bulk and block deals on record; the largest is SAGILITY (₹2,394.56 Cr).
== ev_regulatory: 0.28s  headline: Regulatory filings in the last 7 days: 1863. All 8 shown have an AI summary.     (SEBI circulars: the staging table returned none)
== ev_calls: 0.19s      headline: Call and guidance filings in the last 7 days: 1288. 0 of the 8 shown have an AI summary.
== ev_exchange: 0.26s   headline: Exchange notices in the last 7 days: 11. 3 of the 8 shown have an AI summary.
== ev_announcements: 0.33s / ev_all_today: 0.20s (Filings dated today: 40. 0 of the 8 shown have an AI summary.)
== res_TCS: 0.29s  title='Tata Consultancy Services Limited · results'     == res_INFY: 0.37s     == res_DELHIVERY: 0.39s     == orders_LT: 0.26s  'LT · order wins · last 30 days' (5 filings)
```
Every answer: `validate=[]`, `stale=False`, `missing: []`. **Latency: 0.06–0.56 s in-process** (the calendar with 8 company-file reads is the slowest at 0.56 s). Nothing is cached by this change.

**What a real card carries (this week, 31 Oct):** Vedanta, "Declared 28 Oct · Q2 FY27 (Jul–Sep 2026) · F&O", badge "In line with historical trend", the stored summary ("Vedanta reported record Q2 FY27 revenue of ₹25,812 crore, EBITDA of ₹9,938 crore (up 106% YoY)…"), "AI summary of the results filing, analysed 28 Oct 2026, filing read: strongly positive. Not a recommendation.", 7 commentary points (the press release's summary, the points for and against, what is unknown), 4 links (results filing, results press release, investor presentation, earnings call / investor meet). TCS: "Result filed 8 Oct 2026 · Q2 FY27 · F&O", "In line with historical trend", the stored summary of its outcome filing, 3 links. INFY: summary ends "· Assessed as routine (importance 50/100)" exactly as stored (the desk shows the same text), plus the earnings-call transcript link.

## UI / Playwright Tests
Production build (`BUILD_EXIT=0`), `pw.copilot-app.config.ts`, `--network none`; `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`.
- events-answers (new, 12 incl. the opt-in screenshot test), visual-answer (now drawing 16 intents from the real capture), fno-detail, risk-profile, fno-board, sector-rotation, copilot-app, desk, decision cards, positions, daily-trader, copilot window, risk-phase1, risk-desk, smart-money: **`238 passed, 5 skipped`** (the 5 skips are the opt-in screenshot tests EA-12, VA-19, FE-9, SE-6, FD-9).
- Looked at the EA-11 / EA-12 screenshots: cards, badge, summary, note, commentary list, buttons and link chips read correctly. The first look found the "Above · in line · below" figure wrapping onto three lines in its tile; the KPI is now `9 · 137 · 16` with the words in its label.

## Data Correctness (staging, read-only)
**Parity with the desk, all 524 companies of the week of 26–31 Oct (real run, `rd.results_rows` against `build.build_day`, same moment):**
```
mine 0.32s (524 rows) | desk build_day 14.09s (524 rows)
same symbols: True
differences: none            (status, verdict label and intensity, outlook summary and band, F&O flag, sector, period label compared per company)
desk counts: {'declared': 494, 'declared_pending': 24, 'upcoming': 6, 'above': 9, 'in_line': 137, 'below': 16, 'not_rated': 332}
mine status: {'declared': 494, 'pending': 24, 'upcoming': 6} verdicts: {None: 332, 'below': 16, 'above': 9, 'in_line': 137} analysed: 115
```
(494 now against the 425 declared the earlier probe saw at 11:56 UTC: the Saturday results and more figures landed in between; both runs are the desk's own numbers.) **Coverage the owner should know:** 381 of 494 declared results have no stored AI summary yet (the cards say "Not analysed yet"); 332 are not rated against their own trend (no reliable baseline); the call-and-guidance filings are almost all unanalysed (0 of the 8 shown); 295 of 524 companies have no sector on record, so a sector filter drops them (said in the answer).

**What the real data caught that the mocks did not (all fixed, with tests):**
1. A newspaper advertisement ("Copy of Newspaper Publication", whose text says "Unaudited Financial Results") was linked as the "Results filing" for Delhivery and Vedanta, because the desk's `kind_of` calls anything whose description says RESULT a result. The reader now classifies by the exchange's SUBJECT line only (EV-L3, EV-B4b).
2. One PDF (the press release that is also the investor presentation) was linked twice under two labels: now once.
3. A stock's answer was dated by its newest filing ("Data of 19 Oct") instead of the feed's freshness; and "M&a", "1 companies", "in the today" wording slips. Fixed.

## UNVERIFIED
- **Not seen in a real browser against staging.** The cards were exercised by Playwright on mocked APIs (the REAL builders' payload shape; the real staging capture is drawn by the visual-answer spec), not by a person on the deployed app. Needs a deploy (backend restart + frontend image) and a look.
- **The chat's written explanation** (the market analyst reading the facts block) was not run: the staging LLM shares the development login's 5-hour limit. The facts block is checked (carries the cards, ≤ 6,100 characters, no buy / recommend / pick wording); what the model writes from it is not.
- **BSE and SEBI links on real data.** Staging has only `nsearchives.nseindia.com` filings (883 of 883 sampled, 859 PDF + 24 zip) and its SEBI circulars table returned zero rows, so the BSE hosts and the circular cards are verified only on invented inputs.
- **Ownership (SAST / PIT) is thin by the desk's own admission** (`nidp.insider_sast` is empty): 1 disclosure in 7 days on staging; the answer repeats the desk's gap text. **Macro is not answered**: the desk's own chip is disabled (no macro calendar ingested).
- **Not built:** "How were its results?" using the thread's last stock (the thread-symbol hook is shared and was left alone); a stock-specific bulk-deal ranking by value beyond the route's order; BSE-only filings (none ingested on staging).
- Not deployed; the backend needs a process restart after a merge (staging-deploy-timing-trap).

## Decisions for the owner
1. **Transcripts and guidance.** "Calls & guidance" shows the companies' call and investor-meet filings, but almost none has a stored analysis (0 of 8 shown), so the answer says "Not analysed yet" and links the PDF. A guidance read per transcript is a cost / account decision (the event-AI pipeline skips the call-update subject on purpose).
2. **SEBI host in the link allow-list.** The brief named NSE and BSE; circulars link to `sebi.gov.in`, so the list also holds it (and only for what the data carries). Say if circulars should be shown without links instead.
3. **Sunday.** "This week" asked on a Sunday shows the coming week (Monday–Saturday), with the dates in the title; the desk's own week would be the one that just ended. Say if you want the desk's reading.
4. **Sector filter coverage.** 56% of the calendar has no sector on record: "Which IT companies report this week?" lists only the 9 with a sector (the answer says how many it could not place). A sector source for the rest is a data task.
5. **Warm cache** is not needed (0.3–0.6 s); the desk's own 14 s cold build is unchanged and not touched.

## Verdict: PASS
