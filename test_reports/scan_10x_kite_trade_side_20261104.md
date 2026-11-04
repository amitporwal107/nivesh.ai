# Functionality Verification Report — "10x volume first 5 min": trade side from Kite live ticks when TrueData is down

- **Branch:** fix/scan-10x-kite-trade-side (from origin/dev e16fe80c) · **PR:** #474
- **Date:** 2026-11-04
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER), session fffb64a1
- **Changed areas:** backend services: yes (kite_live_feed, scan_builder) · frontend src: no (applied criteria notes already render)
- **Contract:** docs/scan_builder/DESIGN.md §8 (10x volume paragraph); quote cache rows gain `ask_trades`, `bid_trades`,
  `ask_volume`, `bid_volume`, `sides_since` (cash stocks, when counted)

## Summary
Owner 4 Nov (early morning): "10x volume first 5 min This is improtant one...please fetch from kite if true data not working".
TrueData's main REST login was refused 3–4 Nov ("incorrect or subscription expired"); the WS sandbox account has no tick history.

## Test Cases
> Written 4 Nov before 08:00 IST after the design (feed counts per tick → quote cache → dashboard fallback), before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-K0 | data | 1-minute-candle tick-rule proxy vs TrueData's sides on 3 Nov's 10 stocks | data | agree on most | **4 / 10 — dropped** |
| TC-K1 | backend | trade_side.classify = tick_flow.classify (quote rule, mid, tick test) | unit | equal on a 630-case grid | passed |
| TC-K2 | backend | print = cumulative-volume rise; pre-09:15 and the first in-session tick are baselines; frozen after 15:30; new day from zero; volume going back ignored; rebase after reconnect | unit | exact counts | passed |
| TC-K3 | backend | feed: cash stocks in full mode only when switched on; counts on WS quotes; REST quotes carry counts; reconnect rebases; failure never drops a quote | unit | as rule | passed |
| TC-K4 | backend | quote cache row carries the 5 fields; as_quote adds them only when counted | unit | as rule | passed |
| TC-K5 | backend | dashboard: TrueData used when it answers; Kite counts otherwise; missing stocks requested from the feed; card says "Kite ticks to …" and the Kite note | unit | as rule | passed |
| TC-K6 | backend | existing kite live feed / quote cache / day quote / market sources / scan builder suites unchanged, with and without APP_ENV=staging | unit | all pass | passed |
| TC-K7 | staging | after merge + deploy + backend restart, in the session: cash quotes in the cache carry counts; the 10x card applies the trade side "from Kite live ticks" | live | counts + card | NOT RUN — needs the merge and the session |

## Results
- **TC-K0** (4 Nov, before 08:00 IST, offline on 3 Nov data): the 1-minute proxy agreed with TrueData's sides on 4 of the 10 stocks TrueData
  passed on 3 Nov (no better than chance) → removed; intraday.py and its tests are back to origin/dev.
- **TC-K1…K6** (4 Nov 08:10 IST, `nivesh/backend:staging` image, `--network none`, CI env values):
  `tests/test_kite_live_feed.py tests/test_kite_trade_side.py tests/test_live_quote_cache.py tests/test_kite_day_quote.py
  tests/test_copilot_market_sources.py tests/test_scan_builder_*.py` → `429 passed, 2 warnings in 11.04s` (no APP_ENV) and
  `429 passed, 2 warnings in 10.96s` (`APP_ENV=staging`). pyflakes clean on the changed files; `git diff --check` clean.
- Instrument count with the switch on (staging `kite_live_snapshot` status, 4 Nov 08:06): ~968 full-mode + 119 quote-mode tokens,
  under Kite's 3,000 per connection.

## Not verified
- TC-K7: real Kite full-mode cash ticks during a session (tick rate, how the auction volume arrives, counts vs the day's volume)
  and the card on staging. Needs the merge, the deploy and a backend restart.

## Verdict: IN PROGRESS — unit-verified; the live check runs in today's session after the merge
