# Functionality Verification Report — chart intraday reloads the day's Kite login

- Date: 2026-10-29, 18:37 IST (after the close; the platform Kite login of 09:41 IST is valid until 06:00 IST)
- Branch: fix/chart-kite-login-oi (from origin/dev bc0017cc)
- Environment: staging data, code run IN-PROCESS in `nivesh-staging-app-backend` from an overlay of the changed file (read
  only, nothing deployed, nothing written); backend unit tests in the staging image

## Summary
The Live chart said "Kite login needed for 15m candles: the platform Kite session expired" and fell back to daily candles
although the day's platform Kite login was valid. Cause: `GET /api/research/chart-intraday/{symbol}` (also read by
`/api/desk/live-chart`) used the token the uvicorn worker started with; only the feed's leader and the F&O routes
(`routes/fno.py _refresh_platform_token`) reload the stored login. On the daily fallback the futures OI strip (which DID get
Kite 15m OI windows, because its route reloads the login) was squeezed into the last two daily slots and its F&O labels piled
up under the last candle. Fix: the chart intraday route reloads the stored login first, the same call the F&O routes make.

## Test Cases
| ID | Case | Result |
|---|---|---|
| T1 | the route reloads the stored login before reading Kite | PASS (pytest) |
| T2 | a failed reload never raises (the worker keeps what it held) | PASS (pytest) |
| T3 | existing intraday route + live-chart + day-quote + feed tests unchanged | PASS (pytest, 122 passed) |
| S1 | staging: ADANIPORTS and RELIANCE live chart answer Kite 15m candles, not the daily fallback | PASS |

## API / Endpoint Tests (staging)
Before (deployed code, same container, 17:37 IST): `ADANIPORTS: interval=1d ... reason token_expired` (daily fallback).
After (overlay of routes/research_chart_intraday.py, `live_chart(symbol, interval="15m", sessions=2)`), run at 18:37 IST:
```
ADANIPORTS: interval=15m source=Kite intraday reason=None bars=48 days=['2026-10-28', '2026-10-29']
   first=['2026-10-28T09:15:00+05:30', 1747.0, 1748.0, 1727.6, 1735.4] last=['2026-10-29T15:00:00+05:30', 1863.7, 1872.0, 1861.0, 1863.1, 565222.0] last.price=1863.1 evaluated_at_bar=2026-10-29T15:00:00+05:30
RELIANCE: interval=15m source=Kite intraday reason=None bars=48 days=['2026-10-28', '2026-10-29']
   first=['2026-10-28T09:15:00+05:30', 1194.5, 1195.4, 1187.0, 1189.0] last=['2026-10-29T15:00:00+05:30', 1169.4, 1171.4, 1164.4, 1165.0, 4256913.0] last.price=1165.0 evaluated_at_bar=2026-10-29T15:00:00+05:30
```
Futures OI route for the same symbol at 18:2x IST: `mode: intraday | interval: 15m | kite_reason: None`, current / next / far
month 14 windows each over 28–29 Oct, so with 15m candles the strip's 4-bar windows line up with the candles again.

Backend tests: `pytest tests/test_kite_intraday.py tests/test_desk_live_chart.py tests/test_kite_day_quote.py
tests/test_kite_live_feed.py` → `122 passed, 2 warnings in 7.30s`.

## Data Correctness (staging)
- Kite's raw 15minute candles for ADANIPORTS on 29 Oct: 24 candles, the last stamped 15:00 (close 1863.1, high 1872.0);
  none dropped by the service's candle check. So after the close the last 15m candle can trail Kite's final quote
  (1872.0 at 15:30:57) by one candle; it is labelled with its own time ("15:00 IST"), not as the close. Not changed here.

## Inputs required from user
- Merge (a merge to dev deploys staging; the backend restarts). The broader fix for every Kite reader in every worker is the
  unpushed branch fix/kite-token-all-workers; this PR only covers the chart route.

## Verdict: PASS
