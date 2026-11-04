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
(filled in as each step runs)

## Verdict: IN PROGRESS
