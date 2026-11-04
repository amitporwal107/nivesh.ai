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
| TC-K7 | staging | after merge + deploy + backend restart, in the session: cash quotes in the cache carry counts; the 10x card applies the trade side "from Kite live ticks" | live | counts + card | passed (09:21 IST) |

## Results
- **TC-K0** (4 Nov, before 08:00 IST, offline on 3 Nov data): the 1-minute proxy agreed with TrueData's sides on 4 of the 10 stocks TrueData
  passed on 3 Nov (no better than chance) → removed; intraday.py and its tests are back to origin/dev.
- **TC-K1…K6** (4 Nov 08:10 IST, `nivesh/backend:staging` image, `--network none`, CI env values):
  `tests/test_kite_live_feed.py tests/test_kite_trade_side.py tests/test_live_quote_cache.py tests/test_kite_day_quote.py
  tests/test_copilot_market_sources.py tests/test_scan_builder_*.py` → `429 passed, 2 warnings in 11.04s` (no APP_ENV) and
  `429 passed, 2 warnings in 10.96s` (`APP_ENV=staging`). pyflakes clean on the changed files; `git diff --check` clean.
- Instrument count with the switch on (staging `kite_live_snapshot` status, 4 Nov 08:06): ~968 full-mode + 119 quote-mode tokens,
  under Kite's 3,000 per connection.

- **Merge + deploy:** owner "merge #474" → merged 08:19 IST (b041face); "Deploy backend → CloudPe app VM [staging]" success;
  container restarted 08:19:25 IST (trade_side.py on disk 08:19:13), healthy; `APP_ENV=staging`, `trade_side.enabled()` = True.
- **TC-K7** (4 Nov 09:21 IST, staging backend container, read-only, `k7_check.py`):
  - Quote cache: **20 of 20** sample stocks counted, all `sides_since 09:15:06` (the first in-session tick after the auction
    baseline), last update 09:21:06–09:21:10. Sided volume = 71–96 % of the day's volume (the rest is the opening-auction volume,
    which is never sided). Examples: RELIANCE ask 172 / bid 168 prints (78 % of 1,036,109 sided); ITC 198 / 143 (96 %);
    COALINDIA 64 / 30; GRSE 142 / 79; small caps outside Nifty 500 counted too: KITEX 88 / 90, JAINREC 28 / 12.
  - 10x card (16 s): status ok; as_of "Kite live 09:21:06 IST · 5-minute candles to 09:20 · Kite ticks to 09:21:27 IST"; every
    criterion applied; trade-side note "from Kite live ticks (each trade against the bid/ask before it), while TrueData is
    unavailable …"; 9 stocks: AWFIS, SANDUMA, HEGAM, ITC, PASHUPATI, SBIN, SHAREINDIA, ZEEL, KEC. TrueData still answers
    AUTH_EXPIRED (logged), so the Kite path was used.
  - No trade-side or feed warnings in the backend log since 09:00.
- **Signals** (09:22 IST, `signals.today`, read-only): 300 signals recorded today from 09:15:58 (leader 1 worker); the 10x list,
  which could not record before (its trade side was never applied), now records: vol_10x_5min 12 (first PASHUPATI 09:16:59,
  then WELSPUNLIV, SBIN, ITC, HEGAM, KEC, SHAREINDIA, IOC, AWFIS, SANDUMA, ZEEL, EBGNG), Day trade copy dt_vol_10x_5min 10,
  all with plans (plan_ok). This also covers the earlier report's TC-P7 (live recording from the open).

## Not verified
- Accuracy of the Kite sides against exchange trade data: no independent trade-side source while TrueData's login is refused.
  The rule equals tick_flow's (unit grid); Kite ticks are ~1-a-second snapshots, so counts are prints, not exchange trades.
- The page in a browser (needs the owner's staging session token).

Changed areas are backend only; they are merged, deployed and verified live on staging in the 4 Nov session (counts + card).

## Verdict: PASS
