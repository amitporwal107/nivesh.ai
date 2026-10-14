# Markets home: movers, FII/DII and news through the NIDP API

Date: 2026-10-12 · Area: `backend/routes/markets.py` (`_top_movers`, `_fii_dii`, `_news`) · Commit `79c48e87` · Env: staging (CloudPe)

## Problem

`GET /api/markets/home` and `GET /api/markets/daily-brief` logged, on every request:
```
markets.home top_movers failed: relation "analytics.mv_top_momentum" does not exist
markets.home fii_dii failed: relation "nidp.fii_dii_flows" does not exist
markets.home news failed: relation "nidp.corporate_announcements" does not exist
```
The three helpers ran SQL for NIDP tables on the app's own Postgres pool. The app and
NIDP are separate servers; the app is meant to read NIDP data through the NIDP API.

## Change

The helpers call the existing DaaS client (`get_market_pulse_movers`, `_fii_dii`,
`_articles`). Output shapes are unchanged. No SQL remains in the three helpers.

## Test cases

| # | Case | Expected |
|---|---|---|
| U1 | FII/DII takes the newest day and rounds to 2 dp | pass |
| U2–U5 | FII/DII returns None for missing/empty/null data | pass |
| U6 | News keeps high/medium impact, drops regulatory/other, high first, title = "company — subject" | pass |
| U7 | News respects `limit` | pass |
| U8 | Movers merges large/mid/small, re-ranks, tolerates a missing segment | pass |
| U9 | Nothing is called when DaaS is unconfigured | pass |
| U10 | The helpers contain no pool/SQL and no NIDP relation names | pass |
| L1 | Live: `_fii_dii()` returns the latest day from the staging NIDP API | real data |
| L2 | Live: `_news()` / `_top_movers()` return without error | no exception |

## Results

Unit tests (DaaS client stubbed; `python -m pytest tests/test_markets_home_daas.py`, staging backend image):
```
..........                                                               [100%]
10 passed, 1 warning in 3.20s
```

Staging API — the three helpers executed inside the running staging backend after the CI
deploy (`Deploy backend → CloudPe app VM [staging]`: success), against the real NIDP API
at `https://staging-data.niveshcopilot.com/daas`:
```
fii_dii  → {"as_of": "2026-10-09", "fii_net_cr": -3568.9, "dii_net_cr": 4743.26}
news     → 0 items []
movers   → {"as_of": null, "gainers": 0, "losers": 0}
```
```
GET https://staging.niveshcopilot.com/api/healthz → HTTP 200 {"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
```

Data test: the FII/DII figures are the row the NIDP `fii_dii` feed ingested today
(`nidp.fii_dii_flows`: 2 rows, as of 2026-10-09).

## Why news and movers are empty (data, not code)

- News keeps only announcements classified high/medium impact. The NIDP
  `announcement_classifier` feed is held (OpenAI key has no credits), so none of the 966
  announcements in the last 3 days carries an impact yet.
- Movers come from `analytics.stock_card`, which the derived engines fill once the price
  backfill (running) completes. Until then `/api/markets/home` falls back to its live
  Nifty-50 movers, as before.

## Not verified

- `GET /api/markets/home` over HTTP with a signed-in session (the route requires auth).
- The other direct-SQL paths in the app (SQL fallbacks behind `_daas_first`, sector index
  series, international funds, strategy SQL provider, admin paths) are unchanged.

## Verdict: PASS
