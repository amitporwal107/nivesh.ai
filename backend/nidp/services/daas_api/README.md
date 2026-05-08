# NIDP Data-as-a-Service API

Public read-only HTTPS surface over the NIDP warehouse. Distinct from
`nidp.services.query_api` (internal admin console; single shared bearer
token) — this service authenticates per-caller via API keys, enforces
per-key rate limits + daily quotas, and logs every request for usage
analytics.

## Surface

| Group        | Endpoint                                              | What it returns                                       |
|--------------|-------------------------------------------------------|-------------------------------------------------------|
| Meta         | `GET /health`                                         | Liveness + DB readiness (no auth)                     |
|              | `GET /v1/me`                                          | Identity + current rate-limit state                   |
|              | `GET /v1/me/usage?days=30`                            | Daily request counts                                  |
|              | `GET /v1/catalog`                                     | Datasets + coverage stats                             |
| Prices       | `GET /v1/prices/eod/{symbol}`                         | Daily OHLCV (raw bhavcopy)                            |
|              | `GET /v1/prices/eod?on=YYYY-MM-DD`                    | Whole-market OHLCV for one day                        |
|              | `GET /v1/prices/latest/{symbol}`                      | Most-recent EOD bar                                   |
|              | `GET /v1/prices/adjusted/{symbol}`                    | Split/bonus/dividend-adjusted OHLCV                   |
|              | `GET /v1/prices/index/{index_name}`                   | Daily OHLC for an index                               |
|              | `GET /v1/prices/delivery/{symbol}`                    | Daily delivery quantity / %                           |
| Indices      | `GET /v1/indices`                                     | Distinct indices we track                             |
|              | `GET /v1/indices/{name}/constituents?on=YYYY-MM-DD`   | Effective-dated constituent list                      |
| Reference    | `GET /v1/symbols`                                     | Symbol master                                         |
|              | `GET /v1/symbols/search?q=...`                        | Substring search                                      |
|              | `GET /v1/symbols/{symbol}`                            | Symbol detail                                         |
|              | `GET /v1/sectors`                                     | Sector list with member counts                        |
|              | `GET /v1/holidays?segment=CM`                         | NSE trading holidays                                  |
| Corp actions | `GET /v1/corporate-actions[?symbol=&action_type=]`    | Splits / bonuses / dividends / mergers                |
| Fundamentals | `GET /v1/financials/{symbol}`                         | Quarterly XBRL financials                             |
|              | `GET /v1/shareholding/{symbol}`                       | Quarterly shareholding pattern                        |
| F&O          | `GET /v1/fno/{symbol}`                                | Futures + options for an underlying                   |
|              | `GET /v1/fno/{symbol}/chain`                          | Latest options chain (CE+PE per strike)               |
|              | `GET /v1/fno/{symbol}/expiries`                       | Available expiries with contract counts               |
| Flows        | `GET /v1/flows/fii-dii`                               | FII/DII net flows                                     |
|              | `GET /v1/flows/bulk-deals`                            | Bulk deals                                            |
|              | `GET /v1/flows/block-deals`                           | Block deals                                           |
| Announcements| `GET /v1/announcements`                               | NSE+BSE filings (with classification)                 |
|              | `GET /v1/announcements/{id}`                          | Full announcement record                              |
| Macro        | `GET /v1/macro/rbi-yields`                            | Indian G-Sec / T-bill / repo                          |
|              | `GET /v1/macro/fred[?series_id=DGS10]`                | Global macro from FRED                                |
|              | `GET /v1/macro/fred/series`                           | Distinct FRED series                                  |
| Snapshots    | `GET /v1/snapshots/market`                            | Frozen daily market snapshot                          |
|              | `GET /v1/snapshots/market/recent?days=30`             | Trailing window of market snapshots                   |
|              | `GET /v1/snapshots/stock/{symbol}`                    | Per-stock daily snapshot                              |
| Features     | `GET /v1/features/stocks/{symbol}`                    | Engineered features (RSI/MACD/ATR/…)                  |
|              | `GET /v1/features/stocks/{symbol}/latest`             | Latest feature row                                    |

## Authentication

```
X-API-Key: nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# or
Authorization: Bearer nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Tokens are stored only as their SHA-256 hash in `nidp.daas_api_keys`. A
leak of that table cannot grant access on its own.

## Rate limits + quotas

Every response includes:

```
X-RateLimit-Limit:     <rpm>
X-RateLimit-Remaining: <int>
X-RateLimit-Reset:     <seconds-until-reset>
X-Daily-Limit:         <int|"unlimited">
X-Daily-Remaining:     <int|"unlimited">
X-Request-Id:          <uuid>
```

`429 Too Many Requests` includes `Retry-After`. Per-minute limits are
in-process (best-effort across instances); daily quotas are DB-backed.

| plan      | rpm  | daily_quota |
|-----------|------|-------------|
| free      |  60  |     1,000   |
| standard  | 300  |    50,000   |
| pro       | 1500 |   500,000   |
| internal  | 6000 |   unlimited |

## Issuing keys

```
python -m nidp.cli daas-keygen \
    --name "AcmeCorp prod" --owner ops@acme.com --plan standard
```

The cleartext token is printed once and never again. To revoke:

```
python -m nidp.cli daas-keys list
python -m nidp.cli daas-keys revoke --key-id <uuid>
```

## Running locally

```
python -m nidp.cli migrate                 # 033_nidp_daas_api.sql brings the tables
python -m nidp.services.daas_api           # listens on $PORT (default 8081)
```

Then `curl -H 'X-API-Key: <token>' http://localhost:8081/v1/me`.

## Deploying

The `Dockerfile` mirrors `query_api/`. Same env vars (`NIDP_POSTGRES_URL`,
`LOG_LEVEL`, `PORT`) plus:

* `NIDP_DAAS_LOG_REQUESTS=0` — disable per-request log inserts (still
  bumps the daily counter).
* `NIDP_DAAS_INTERNAL_TOKEN` — escape-hatch token for service-to-service
  calls; bypasses key lookup but still subject to rate limits.
* `NIDP_DAAS_CORS_ORIGINS=https://docs.example.com,…` — comma-separated
  origins (default `*`).
