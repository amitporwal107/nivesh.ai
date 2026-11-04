# Functionality Verification Report — Scan dashboard: signal strength 0–100, strong signals ≥ 70, positional plan

- **Branch:** feat/scan-signal-strength (from origin/dev f33d0b75)
- **Date:** 2026-11-04
- **Author:** Claude (DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER), session fffb64a1
- **Changed areas:** backend services/route payload: yes · frontend src: yes
- **Contract:** docs/scan_builder/DESIGN.md §11

## Summary
Owner 4 Nov ~13:45 IST: only signals with strength > 70; fundamentally and technically good companies with a solid reason
(52-week-low reversal, momentum continuation, market events); penalise pump-and-dump; more weight to blue chips; positional, not
intraday; check SAREGAMA today. Decisions ~14:05: ATR stop + trend exit; below 70 folded away; long only.

## Test Cases
> Written 4 Nov ~14:20 IST after the design (DESIGN.md §11) and before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-S1 | backend | quality part: each band edge (ROCE/ROE/D-E/margin/consistency/promoter/institutions); financials use ROE and fixed D/E points; missing figure → 0 and named | unit | exact points | |
| TC-S2 | backend | trend part: SMA count, 50>200, 52w-high breakout / near / 52w-low reversal, RSI bands, 125-session return, cap 25 | unit | exact points | |
| TC-S3 | backend | reason part: results positive 16, orders high 12, negative −8, setup points, positional list +4, clamp 0–20 | unit | exact points | |
| TC-S4 | backend | size part: Nifty 50/100/200/Midcap/500, F&O floor 9, market-cap fallback, traded value < ₹5 cr cap 2 | unit | exact points | |
| TC-S5 | backend | participation: volume-ratio bands with/without a filing, trade sides, positional lists | unit | exact points | |
| TC-S6 | backend | penalties: each rule fires at its edge and is named; ETF / no-company symbols not scored; score clamped 0–100 | unit | exact | |
| TC-S7 | backend | long only: a stock whose lists today are all short-side is not scored (reason stated) | unit | score null | |
| TC-S8 | backend | plan v3: Entry − 2×ATR, T1 2R, T2 4R, trend exit = SMA20; no ATR / no price / stop ≤ 0 → no plan + note | unit | exact numbers | |
| TC-S9 | backend | strong record: first time ≥ 70 recorded once per (day, stock), first writer wins, frozen score/plan; below 70 never recorded; list entries keep recording without a plan | unit | exact | |
| TC-S10 | backend | dashboard payload: `strong[]`, `signals[].score`, `scores_meta`; scoring failure → dashboard still answers with a warning | unit | contract | |
| TC-S11 | backend | filings loader: paged reads, cache TTL, failure → reason part without events + warning | unit | as rule | |
| TC-D1 | data | today's real signalled stocks scored in the staging container: distribution, the ≥ 70 list, the bottom (pump-and-dump traits) | data | sensible separation, reasons true to the data | |
| TC-D2 | data | SAREGAMA 4 Nov: every input checked against its source (Q2 FY27 filing text, EOD bars, live quote, screener fundamentals) | data | equal | |
| TC-E1 | e2e | Strong signals feed: score, parts, reasons, penalties, plan (Entry, Stop loss, Target 1, Target 2, trend exit), lists | e2e | rendered | |
| TC-E2 | e2e | "Below 70 (n)" collapsed by default, opens to stock/score/reasons; no plan inside | e2e | rendered | |
| TC-E3 | e2e | browser alerts only for new strong signals (not for list entries below 70) | e2e | as rule | |
| TC-E4 | e2e | barred words outside the plan blocks (buy, sell, recommend, pick, …) absent | e2e | none | |
| TC-L1 | staging | after merge + deploy, in a session: strong signals recorded with frozen plans; payload over the route | live | as contract | |

## Results
- **TC-S1…S11** (4 Nov ~14:09 IST, `nivesh/backend:staging` image, `--network none`, CI env values):
  `tests/test_scan_builder_*.py` → `305 passed, 2 warnings in 8.96s` (new `test_scan_builder_signal_strength.py` 33 tests;
  signals tests rewritten for plan-less list entries + strong records; dashboard payload test extended). pyflakes clean.
- **TC-D1** (4 Nov 14:08 IST, staging backend container, read-only — the branch's signal_strength.py loaded from a copy, live
  Kite prices, nothing recorded): 300 list entries today → 218 stocks; 183 scored in 2.1 s, **22 at 70 or more**, 161 below,
  35 not scored (18 ETFs, 17 with under 60 sessions). Top: BOSCHLTD 90 (52-week-high breakout, quality 30/30, Nifty 100),
  ANTHEM 86 (results filed 3 Nov, positive), ADANIPORTS 81 (Nifty 50 breakout), EMCURE 80, METROPOLIS 79, ALIVUS 77, IOC 76 and
  BHARTIARTL 76 (turning up from the 52-week low), … SAREGAMA 74. Bottom 10 all penny / micro caps with named penalties
  (e.g. ATALREAL: market cap ₹135 cr −25, price ₹14.61 −10, NSE 5 % band −15). Sources read: screener fundamentals
  2026-11-03, snapshot 2026-11-03, filings to 14:08 IST; no source warnings.
  Found and fixed from this run: "other" filings read "Filing filing" → "Exchange filing"; CORONA reached exactly 70 with a
  negative litigation filing → a negative filing is now also a −10 penalty (DESIGN §11, test added).
- **TC-D2 SAREGAMA** (14:08 IST, price ₹644.05): 74 = quality 26 + trend 21 + reason 20 + size 5 + participation 7 − 5,
  recomputed by hand from the sources:
  - quality: ROCE 16.41 → 6, ROE 13.09 → 3, D/E 0.04 → 5, margin 21.19 % → 3, earnings consistency 100 → 4, promoter
    60.84 % → 3, FII 11.88 + DII 9.36 → 2 (DaaS /stocks/screener, as of 3 Nov);
  - trend: above all 8 averages (SMA5 543.34 … SMA200 427.29 = the owner's screenshot) 8, SMA50 501.77 > SMA200 4,
    52-week-high breakout over ₹574.50 (5 Aug) 6, RSI(14) with today's price > 80 → 0, 125-session return 63 % → 3;
  - reason: Q2 FY27 results filed 12:29–12:36 IST, classified earnings / positive — the filing's text (NSE archive PDF) says
    revenue ₹3,143 Mn +37 % YoY, adjusted EBITDA +39 %, PBT +43 % — 16, breakout 10, positional lists 4 → capped 20;
  - size: outside Nifty 500 (constituents 1 Nov), not F&O, market cap ₹9,600 cr → 5;
  - participation: volume 53× its usual by now with a filing 3, Kite trade sides above 1.1 (13:51 read: ask 1,577 ÷ bid
    1,299 = 1.21) 2, three
    positional lists 2;
  - penalty: 26 % above its 20-day average (₹510.65) → −5 (chasing).
  ATR(14) 18.99 = the screenshot's Day ATR; plan at ₹644.05 would be Stop loss 606.07, Target 1 720.01, Target 2 795.97,
  trend exit below the 20-day average.

- **Wording on real data** (14:11 IST, the branch module on today's real scores): 1,264 reason / penalty / note texts, **0** with a
  barred word (buy, sell, recommend, pick, target, stop loss, entry, exit). Guard added after the frontend half flagged it:
  "Buyback" filings read "Share repurchase", and a filing subject carrying a barred word is not quoted (test added → backend
  `306 passed`). The list-mark rules text was reworded ("list entry" → "list mark").
- **Payload:** today's `scores` ≈ 134 KB raw (responses are gzip-encoded on staging); stocks below 70 now send 3 reasons.
- **TC-E1…E4 + TC-E5** (14:19 IST, `mcr.microsoft.com/playwright:v1.47.0-jammy`, mocked API — MOCK fixtures, SAREGAMA 83 → 84,
  a penalised SAKUMA, a long-only and an ETF row): `tsc exit: 0`, `build exit: 0`, Playwright scan dashboard + scan builder +
  screener **`68 passed (32.7s)`**. Frontend choices: an answer without `scores_meta` (an older backend) keeps the §10 feed; a
  stock at 70+ outside the session (nothing recorded) is listed apart with "no plan" rather than under Below 70.
- **TC-RE2 REAL replay** (in the 68): `e2e/fixtures/scan-dashboard-real/dashboard_20261104_scores.json` = the 3 Nov widgets +
  today's REAL 300 list marks, scores, 19 strong signals and scores_meta captured at 14:15 IST from the branch module in the
  staging container; the page renders the strong cards (SAREGAMA 74/100 with its plan and trend exit), Below 70 (197) folded
  then open with no plan inside, no page error, no barred word outside the plan blocks.

## Not verified yet
- TC-L1: after the merge and deploy, in a market session — strong signals recorded once with frozen plans by the signal loop,
  the payload over the route, browser alerts on the owner's device (needs his session token for a browser check).

## Verdict: IN PROGRESS — verified up to deployment (backend 306, frontend 68 incl. a real-data replay); live check after merge
