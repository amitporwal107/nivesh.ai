# Exit watch: test cases (written before implementation)

Design: docs/paper_pnl_dashboard/EXIT_WATCH.md. Rule: `exit-atr-trail-v1`.

Labels: U = backend unit (pytest), S = staging API on the owner's account (real data), P = Playwright (mocked bodies are
labelled MOCK), R = the real staging bodies rendered by Playwright.

## Rule and levels (U)

| id | case | expected |
|---|---|---|
| EW-01 | ATR14 (Wilder) on 30 known bars | matches a hand-worked value to 0.01 |
| EW-02 | long candidate | close − 2 × ATR14, 2 decimals; short: close + 2 × ATR14 |
| EW-03 | first stop | stored = candidate of the latest end-of-day bar, with that day and one history entry |
| EW-04 | trail, long | a higher candidate raises the stop; a lower candidate leaves it (moved false); never loosens |
| EW-05 | trail, short | mirrored: the stop only moves down |
| EW-06 | same day again | an evening for a day not after the stored day changes nothing |
| EW-07 | series break | a 1:1 bonus (ratio 0.502) inside the window: only post-break bars used; a stop stored before the break is recomputed with reason "price series break (bonus or split)" |
| EW-08 | too few bars | fewer than 15 bars after a break, or in all → NO_STOP with the reason; no stop stored |
| EW-09 | your own stop wins | a position_levels stop → method `yours`, stop = effective_stop; rule_stop still reported |
| EW-10 | your trail | position_levels trail_pct → effective_stop from the peak, never below a fixed stop |

## Book grouping (U)

| id | case | expected |
|---|---|---|
| EW-11 | shares long | kind shares, side long, one watched position per account + underlying |
| EW-12 | future + put, put qty ≥ fut qty | kind hedged, method put_floor, stop = strike, floor loss = (fut avg − K + put avg) × qty |
| EW-13 | short future + long call | kind hedged, method call_cap, mirrored |
| EW-14 | put covers less than the future | kind future, method atr_trail, note "partly hedged (x of y)" |
| EW-15 | options only / both sides / unmapped code (an SGB code) | in not_watched with the reason each |
| EW-16 | the same underlying in two accounts | two watched positions (keys differ by account) |

## Status and loss (U)

| id | case | expected |
|---|---|---|
| EW-17 | long, price ≤ stop | HIT; price within 0.5 ATR above → NEAR; else OK |
| EW-18 | hedged, price ≤ strike | FLOOR (not HIT) |
| EW-19 | loss at stop | shares (avg − stop) × qty; futures with the basis; negative when the stop is above the average |

## Alerts (U)

| id | case | expected |
|---|---|---|
| EW-20 | STOP_HIT once | two live rounds through the same stop insert one alert; a raised stop that is hit later fires again |
| EW-21 | no fire on stale data | day_quotes why feed_not_live / no quote → nothing fires; state records feed_why |
| EW-22 | evening signals | close through stop → CLOSE_THROUGH_STOP; below the 20-session low → SUPPORT_BREAK; close < EMA20 < EMA50 newly → TREND_TURN; ratchet moved → STOP_RAISED; each once per day |
| EW-23 | evening waits for the exchange bar | latest bar older than today → no ratchet, no signals, the round retries |
| EW-24 | HEDGE_REMOVED | stored level put_floor, book now future without the put → CRITICAL alert, level switches to the trail |
| EW-25 | RESULTS_SOON | a results date within 3 calendar days → one INFO alert per event date |
| EW-26 | loop gating | outside the session no live round; not the leader → no round; EXIT_WATCH_ENABLED=0 → start() returns False |

## API (U + S)

| id | case | expected |
|---|---|---|
| EW-27 | GET /api/desk/pnl/exits without a session | 401 |
| EW-28 | GET with account=bad | 422 invalid_account |
| EW-29 | GET on the owner's real book (S) | every ICICI position listed or in not_watched; stops = the rule on real bars (checked against a hand calculation for one share position and one hedged pair); a stock with a recent bonus uses post-bonus bars only; an SGB code in not_watched |
| EW-30 | GET writes nothing (S) | exit_watch_levels / exit_alerts / position_levels unchanged by reads |
| EW-31 | POST /exits/seen (U + S) | marks only the caller's alerts; {} marks all unseen; bad body 422 |
| EW-32 | evening round on real data (S) | run the evening step once on staging for the owner after NSE's 4 Nov file: levels stored, signals as the bars say; restored afterwards if the owner's data must stay untouched |

## Screen (P + R)

| id | case | expected |
|---|---|---|
| EW-33 | section renders in ALL and LIVE, hidden in PAPER (P) | pnl-exits visible / absent |
| EW-34 | rows and chips (P) | status chips HIT/NEAR/OK/FLOOR/NO_STOP with their words; method chips; loss at stop |
| EW-35 | banner (P) | unseen > 0 → banner with the newest text; Mark seen POSTs /exits/seen and the banner goes |
| EW-36 | set my stop (P) | the input PUTs /api/positions/{U}/levels {stop}; "Use the rule" DELETEs it |
| EW-37 | phone 390 px (P) | cards, no page-level sideways scroll |
| EW-38 | real bodies (R) | the owner's real staging body renders without page errors at 1280 and 390 |
