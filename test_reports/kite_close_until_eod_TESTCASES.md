# Test cases — Kite close until EOD (stocks and F&O), 2026-10-29

Owner rule (29 Oct 2026): while the market is live show live data; after the close show the Kite closing data until the
EOD jobs load the exchange's prices; then the exchange's prices.

Shared reader: `backend/services/kite_live_feed/day_quote.py`
- `day_quotes(symbols, now)` → today's quotes: live (session open, fresh feed) or the saved Kite close (`kite_live_close`)
- `join_bar(bars, quote, day, holidays)` → the end-of-day series with today's provisional bar appended, or unchanged + why
- `extend_daily(bars, symbol, now)` → both, plus the holiday read only when a weekday sits between the two days

## Unit (pure, no I/O)
| id | case | expected |
|---|---|---|
| U1 | after close, EOD last day T-1, Kite close for T, prev close == EOD last close | bar T appended `[T, o, h, l, ltp, vol]`, info.source `kite_close`, provisional |
| U2 | EOD already has day T | unchanged, info.used false, why `eod_in` (exchange prices win) |
| U3 | Kite prev close differs from EOD last close by > 0.05 % (split/bonus or missing session) | unchanged, why `does_not_join` |
| U4 | quote's exchange_ts is not on day T (did not trade today) | unchanged, why `not_traded_today` |
| U5 | weekday between EOD last day and T, holidays unknown | unchanged, why `gap_unchecked`; with that weekday a holiday → appended |
| U6 | high below ltp (snapshot lag) | high raised to ltp, low lowered to ltp; open missing → unchanged, why `bad_candle` |
| U7 | session open + fresh snapshot | source `kite_live`, day = today |
| U8 | session open + stale feed | no quotes, why `feed_not_live` (T-1 EOD stays, nothing stale shown as today) |
| U9 | closed, no close doc saved for the day | no quotes, why `no_saved_close` |
| U10 | weekend / before 15:30 | day = the last weekday close (config.last_close) |

## Route (TestClient, fakes)
| id | route | expected |
|---|---|---|
| R1 | /api/desk/live-chart/{sym} daily fallback after close | last bar = Kite close day, `last.source` `kite_close`, `timeframe.today` set, conditions evaluated on it |
| R2 | same, EOD in | no `timeframe.today`, last bar = EOD day |
| R3, R4 | (dropped) /api/research/chart-live | NOT changed: the frontend already appends and labels the Kite close there (`pick()` + `withLiveBar`); a backend bar would lose the "Kite" label |

## Staging (real data, in-process in nivesh-staging-app-backend, read only)
| id | case | expected |
|---|---|---|
| S1 | ADANIPORTS live chart, 29 Oct after close, before the 19:00 bhavcopy | last bar 2026-10-29 close 1872.0 from the Kite close; 28 Oct bar unchanged |
| S3 | data test: the appended bar equals the `kite_live_close` doc for 2026-10-29 field by field | equal |
| S4 | after the 19:00 bhavcopy lands (if it lands in-session) | EOD bar wins, no provisional bar |

## UI (Playwright, mocked API + staging screenshot)
| id | case | expected |
|---|---|---|
| P1 | Live chart daily fallback with `timeframe.today` kite_close | LAST shows the Kite price and day with "Kite close"; the note says end of day through T-1 and the Kite close for T, provisional |
| P2 | without `timeframe.today` | the old end-of-day note, no Kite label |
| P3 (KC-3) | Portfolio position chip after the close | the move at Kite's close, data-kind close, "Close · <day> · Kite, provisional" |

F&O (option chains, futures by month, strategy ideas) is PR 2: the saved Kite close does not hold stock options or next/far
futures yet, so the feed has to save them first; its cases are written with that PR.
