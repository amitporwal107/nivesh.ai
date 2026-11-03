# Functionality Verification Report — Scan dashboard: "10x volume first 5 min" on Kite + TrueData, and per-stock strategy ideas

- **Branch:** feat/scan-dashboard-10x-volume (from origin/dev 6d30a7f7, after PR #464)
- **Date:** 2026-11-03
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER), session fffb64a1
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Contract:** docs/scan_builder/DESIGN.md §8 (10x volume paragraph); strategy ideas: `ideas` / `ideas_meta` on GET /api/scan-builder/market-dashboard

## Summary
Owner 3 Nov ~12:40 IST (screenshot of the "Not computed" card): "Please fix this using kite or true data". Then ~12:58: "provide
the best AI recommended strategies for each of the stocks wherever the risk reward are favorable" — built as STRATEGY IDEAS from
the existing strategy builder (owner's compliance wording rules of 25 Oct and 3 Nov), only where its reward : risk rule passes.

## Test Cases
> Written 3 Nov ~12:58 IST, after the design and DURING implementation (the owner's requests arrived mid-session, market open).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-V1 | backend | first_volume = volume of the latest session's first candle; 5-minute candles read as ("5m", 15 sessions); 5-minute cache TTL 1 day | unit | exact | |
| TC-V2 | backend | 10x widget: daily part → 5-minute test (first volume > 10 × SMA(volume, 1000) as of the candle before) → TrueData only for survivors | unit | calls + rows | |
| TC-V3 | backend | no ticks / no TrueData login → Partial, trade-side line not applied with the reason | unit | as rule | |
| TC-V4 | backend | 5-minute candles not in yet → TrueData never asked; Partial | unit | no call | |
| TC-V5 | backend | candles read but < 1,000 of them → not Partial, note "too little history" | unit | as rule | |
| TC-T1 | backend | tick classification (quote rule, mid, tick test, auction print, 1-share markers), incremental reads, cross-worker cache, spacing | unit | exact | |
| TC-T2 | data | SBIN ticks 09:15–12:50 classified by tick_flow vs independent code on the same rows | data | equal | |
| TC-K1 | data | a stock's first 5-minute candle volume and 1,000-candle mean vs Kite's own 5-minute candles | data | equal | |
| TC-L1 | staging | the 10x widget end to end on today's live data (staging backend container, process-local caches) | data | rows + all criteria applied | |
| TC-I1 | backend | attach_ideas: every shown stock once, symbol rows only; None = not favorable; absent = being built; plan_inputs not sent | unit | exact | |
| TC-I2 | backend | ideas failing → dashboard still answers | unit | isolation | |
| TC-I3 | backend | strategy_ideas: favorable kept / unfavorable None / failure None; cache across workers; staleness; wording | unit | per rule | |
| TC-I4 | staging | ideas for 8 of today's dashboard stocks with the real builder (read-only) | data | ideas or None with reasons | |
| TC-E1 | e2e | idea column: favorable / none / being built states and tooltip; header line + caveat; no column on group/index widgets | e2e | rendered | |
| TC-E2 | e2e | no barred words (buy, sell, target, stop loss, pick, recommend, entry, exit) on the page | e2e | none | |
| TC-S1 | staging | after merge + deploy: the route answers with `ideas`; the page in a browser with the owner's session | api/e2e | live | |

## Results
(filled in as each step runs)
- **TC-V1…V5, TC-T1, TC-I1, TC-I2** (12:55–13:00): backend scan-builder suite `228 passed`; touched files
  (market_dashboard, tick_flow, intraday) `54 passed` — staging image, --network none.
- **TC-K1** (12:49, staging backend container, Kite live): MONEYVIEW first 5-minute candle volume 1,805,375 = Kite's own
  5-minute candle; 1,000-candle mean before the latest 1,078,054 (ours) vs 1,077,908 (Kite, read ~1 min later). Of the 90
  highest-volume of 252 daily-part stocks, 21 passed the 10× test (ITI 81×, TRIVENI 72×, KITEX 70×, VRLLOG 63×, MARICO 54× …).
- **TC-T2** (fork T, 12:51–12:53): SBIN 09:15–12:50, 7,645 TrueData rows; tick_flow 4,293 at the ask / 2,912 at the bid /
  0 unclassified = an independent recount on the same rows; 3 auction rows and 439 volume ≤ 1 rows skipped.
- **TC-L1** (12:55–12:58 IST, staging backend container, the branch's modules, process-local caches): the 10x widget end to
  end — 258–262 stocks in the daily part; 5-minute candles filled in 202 s (263 Kite calls); TrueData asked only for the
  5-minute survivors (85 calls); final at "Kite live 12:58:23 IST · 5-minute candles to 12:55 · ticks to 12:58:31 IST":
  status ok, every criterion applied, 10 stocks — GRSE (ask 4,116 / bid 3,348 prints), WELSPUNLIV (5,890 / 4,771),
  ASIANPAINT (3,829 / 2,738), IOC (2,441 / 1,928), JAINREC (742 / 699), ZEEL (1,583 / 835), ITI (4,326 / 3,369),
  SYRMA (4,089 / 2,508), NATIONALUM (2,180 / 910), KEC (4,368 / 2,428).
- **Infrastructure note:** right after 12:58 the app VM stalled (load average ~150 on 4 cores, 1.2 GB free memory; other
  sessions' Playwright/tsc/OCR runs): Redis, Mongo and Kite calls timed out in the backend container for ~2 h; staging
  containers stayed up (backend healthy). Not caused by this change; noted because it delayed the remaining checks.
- **TC-I3** (fork S): `tests/test_scan_builder_strategy_ideas.py` 14 passed; full scan-builder backend suite with it: `242 passed`.
- **TC-I4** (fork S, 16:46 IST, staging backend container, read-only, process-local cache): 8 stocks built in 21.8 s at
  concurrency 3, 216 data-platform calls, 0 failures; HDFCBANK long futures (net R:R 8.1), IOC covered call (R:R 1.5, max loss
  ₹8,374); MARICO, ITI, RELIANCE, VRLLOG, COALINDIA, KITEX no favorable structure (builder verdicts wait / no_trade with reasons).
- **TC-I4 through the route function** (16:53 IST, Kite close, the branch's modules): dashboard rows of two widgets (17 stocks)
  then attach_ideas with the real builder: built 3 → 17 in 30 s; TATACONSUM bull call spread (debit) R:R 1.92 max loss ₹7,397.50
  "Long 1 lot 1030 CE + Short 1 lot 1070 CE, 23 Nov"; HDFCBANK long futures R:R 8.1; DRREDDY covered call R:R 3.41; INDHOTEL bull
  call spread R:R 1.57; the other 13 "–"; data 2026-11-02 (T-1, end of day); payload 6,241 bytes.
- **TC-E1, TC-E2** (16:50 IST): `tsc exit: 0`, `build exit: 0` (NODE_OPTIONS=--max-old-space-size=2560; an unlimited build was
  OOM-killed while the VM was loaded), Playwright dashboard + scan builder + screener `45 passed (1.2m)` — mocked API, MOCK.

## Owner decisions surfaced (not blocking)
1. Ideas are end-of-day (the builder's inputs: bhavcopy chains, futures, scanner, filings), rebuilt every 3 h — not real time.
2. One bullish, positional view for every stock (as the desk's AI-scanner ideas); a bearish view per widget is possible later.
3. Not sized per user (the builder's defaults: one lot / unsized); ~300 dashboard stocks take ~10 min and ~8,000 DaaS calls to fill.

## Not verified
- TC-S1: after merge + deploy, the route with `ideas` over HTTP and the page in a browser (needs the owner's staging session token).

## Verdict: IN PROGRESS — verified up to deployment; staging HTTP/browser check pending merge and the owner's session token

### Early signals, alerts and trading plans (DESIGN.md §9, owner decisions 3 Nov ~17:15 IST) — branch feat/scan-dashboard-signals
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-P1 | backend | plan: long stop = lower of day low / entry − ATR; T1 2R capped at the 20-session high; T2 3R; R:R1 < 1.5 → no plan with the reason; short mirror; no price / no room | unit | exact numbers | 12 passed (signals suite) |
| TC-P2 | backend | plan inputs = engine's ATR(14) at offset 1 and the previous 20 sessions' high/low | unit | equal to indicators.py | passed |
| TC-P3 | backend | record only fully applied stock lists; once per (day, widget, stock); first writer wins across workers; at open ≤ 09:20; falling OI stock short | unit | exact | passed |
| TC-P4 | backend | today(): newest first, price now, move since; unreadable store → empty list + reason; dashboard carries signals + signals_meta (recording false outside the session) | unit | exact | passed |
| TC-P5 | backend | leader loop: one worker, session only (09:15–15:30 IST weekdays); enabled on APP_ENV=staging, SCAN_SIGNALS_ENABLED switch | unit | exact | passed |
| TC-P6 | data | plans on today's real lists (staging container, Kite close, local stores) | data | levels by the rule | 180 signals, 107 with plans; MARICO entry 878.40 / stop loss 826.05 (today's low) / T1 983.10 / T2 1,035.45; ANGELONE no plan (20-session high only 0.63 × risk away) |
| TC-P7 | staging | live recording at the open on 4 Nov (after merge + deploy) | live | signals with first_seen from 09:15 | NOT RUN — needs the merge and a market session |

- Backend scan-builder suite on this branch: `255 passed` (20:23 IST); pyflakes clean; `import server` ok.

### Merged with dev (#468 merged by the twin window, #470 Day trade tab, #469 wording) + Early movers + plan rule v2 (owner 3 Nov ~20:50 IST)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-M1 | backend | plan v2: Stop loss = Entry − 1 %, Target 1 +1.5 %, Target 2 +3 %, R:R 1.5/3.0; short mirror; no price → no plan | unit | exact | passed |
| TC-M2 | backend | Early movers: curve (75 cumulative shares, monotonic), usual share by time (linear in a candle, none before 09:30, 1.0 after the close), rule (≥ 5× usual, ≥ 2 % over open, ADV ≥ 50,000, price ≥ 20, ≥ 10 sessions), criteria text | unit | exact | passed |
| TC-M3 | backend | three tabs atlas / daytrade / early; the signal loop computes every tab; Day trade tests kept green | unit | as contract | passed |
| TC-M4 | e2e | merged UI: Day trade tabs + signals feed + ideas; wording checks exclude only the plan blocks | e2e | 62 passed | passed |
| TC-M5 | data | Early movers on real data after the close (whole-day version) + v2 plans | data | rows + levels | 25 stocks (TRIDENT 76.6× usual, +3.43 %; KITEX 47.6×; KRBL 31.7× …); KITEX Entry 133.23 / Stop loss 131.90 / T1 135.23 / T2 137.23 |

- Backend scan-builder suite on the merged branch: `269 passed` (incl. dev's Day trade tests); pyflakes clean.
- Frontend: `tsc exit: 0`, `build exit: 0`, Playwright dashboard + scan builder + screener `62 passed (44.1s)` (mocked API + the REAL snapshot replay).

## Not verified (needs the merge, a deploy and a market session)
- TC-P7 / TC-S1: live recording from 09:15 on 4 Nov on staging (signals with first_seen in the session, browser alerts), the
  route over HTTP and the page in a browser (owner's session token).

## Verdict: IN PROGRESS — verified up to deployment; the live session check runs at the 4 Nov open after the merge
