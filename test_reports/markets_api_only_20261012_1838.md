# Market Pulse, Filings and Sector Analysis: API-only

Date: 2026-10-12 · Commit `d9adf9c8` · Env: staging (CloudPe)
Areas: `backend/routes/markets.py`, `backend/routes/filings.py`, `backend/services/sector_analysis.py`,
`backend/nidp/services/daas_api/routers/indices.py`

## Change

The app reads NIDP data through the NIDP (DaaS) API only. These paths preferred DaaS
but kept a direct-SQL fallback against `nidp.*` / `analytics.*` on the app's own pool.
The fallback and its SQL are removed (about 840 lines). Sector Analysis reads benchmark
index levels from `GET /v1/indices/{name}/eod`, which now also returns `pe_ratio`.

## Test cases

| # | Case | Expected |
|---|---|---|
| U1–U10 | Home helpers (earlier report) | pass |
| U11 | `_daas_first` returns DaaS data without any pool | pass |
| U12–U14 | `_daas_first` returns `empty` when DaaS returns None / raises / is unconfigured | pass |
| U15 | No SQL against NIDP schemas and no `pg_client` in markets, filings, sector_analysis | pass |
| U16 | Sector index levels use the DaaS index series, latest row, de-duplicated | pass |
| U17 | Existing filings test (`test_event_ai_insight.py`) with the new signature | pass |
| L1–L8 | Live: each converted read returns from the staging NIDP API without exception | no exception |
| L9 | Live: sector index levels include close, % change and P/E via the API | real values |
| L10 | Backend healthy after deploy; no "relation does not exist" in its log | 0 lines |

## Results

Unit tests (`python -m pytest tests/test_markets_home_daas.py tests/test_event_ai_insight.py`, staging backend image):
```
25 passed, 1 warning in 3.20s
```

CI: `Deploy backend → CloudPe app VM [staging]` success; `Deploy → CloudPe NIDP VM [staging]` success.

Staging API — executed inside the running staging backend against the real NIDP API
(`https://staging-data.niveshcopilot.com/daas`):
```
movers (mid)                 → {"as_of": null, "cap": "mid", "gainers": "[0 rows]", "losers": "[0 rows]"}
fii-dii series               → {"as_of": "2026-10-09", "daily": "[1 rows]", "monthly": "[1 rows]"}
corporate actions            → {"from": "2026-09-12", "to": "2026-11-11", "types": "[7 rows]", "actions": "[4 rows]", ...}
articles                     → {"articles": "[5 rows]", "total": 1029, ...}
earnings                     → {"index": "NIFTY 50", "period_end": null, ..., "sectors": "[0 rows]", "available_indices": "[7 rows]", ...}
institutional positioning    → {"period_end": "2026-09-30", "universe": "Nifty 500", "sectors": "[0 rows]"}
filings company search       → {"data": "[5 rows]", "count": 5, "query": "RELI"}
documents by symbol          → {"symbol": "RELIANCE", "data": "[1 rows]", "count": 1, ...}
sector index levels          → {"Nifty 50": {"pct_change": 1.3, "pe_ratio": 19.27, "close": 22520.45}, "Nifty Bank": {...}, "Nifty IT": {...}}
sector build_all_metrics     → 0 sector docs
home helpers                 → {"as_of": "2026-10-09", "fii_net_cr": -3568.9, "dii_net_cr": 4743.26}
```
```
nivesh-staging-app-backend: Up (healthy)
Traceback or missing-relation lines: 0
GET https://staging.niveshcopilot.com/api/healthz → HTTP 200
GET https://staging-data.niveshcopilot.com/daas/v1/indices/Nifty%2050/eod (no key) → HTTP 401  (auth enforced)
```

## Empty results that are data, not code

Movers, earnings, institutional-positioning sectors and the sector grid return no rows
because the NIDP derived tables (`analytics.stock_card`, `nidp.stock_features_daily`,
quarterly financials) are not populated yet: the price backfill is still running and the
derived engines run after it.

## Not verified

- The HTTP routes with a signed-in session (they require auth); the reads behind them were
  exercised directly.
- Other direct-SQL paths remain: international funds, strategy SQL provider, V3 primitive
  fallbacks, legacy market-events routes, `/api/feeds`, admin and monitoring paths.

## Verdict: PASS
