# NIDP DaaS API

Public read-only HTTPS API over the NIDP Indian-market data warehouse.
Runs as a Cloud Run Service (`nidp-daas-api`) on GCP.

---

## Table of contents

1. [Architecture](#architecture)
2. [Authentication](#authentication)
3. [Plans & rate limits](#plans--rate-limits)
4. [Response envelope](#response-envelope)
5. [Pagination](#pagination)
6. [Error format](#error-format)
7. [Endpoints](#endpoints)
   - [Health](#health)
   - [Admin — key management](#admin--key-management)
   - [Me](#me)
   - [Catalog](#catalog)
   - [Prices](#prices)
   - [Corporate actions](#corporate-actions)
   - [Indices](#indices)
   - [Reference](#reference)
   - [Financials & shareholding](#financials--shareholding)
   - [F&O](#fo)
   - [Flows](#flows)
   - [Announcements](#announcements)
   - [Macro](#macro)
   - [Snapshots](#snapshots)
   - [Features](#features)
8. [Response headers](#response-headers)
9. [Code layout](#code-layout)
10. [Local development](#local-development)

---

## Architecture

```
Internet callers (X-API-Key)
        │
        ▼
Cloud Run Service: nidp-daas-api    ← asia-south1, --allow-unauthenticated
  Port 8081 (reads $PORT)           ← min=1 instance, max=20, 512Mi, 1 vCPU
  FastAPI + uvicorn
  │  auth.py       — token lookup + rate-limit enforcement
  │  ratelimit.py  — in-process token bucket (rpm) + DB daily quota
  │  middleware.py — X-Request-Id, rate-limit headers, usage logging
  │
  ▼  (Serverless VPC connector: nidp-vpc, 10.8.0.0/28)
GCE VM: nidp-stack-vm               ← Postgres:5433 / TimescaleDB on private IP
```

**Key design decisions:**
- Tokens are hashed (SHA-256) at rest — a DB leak cannot grant API access
- 30-second in-process lookup cache keeps DB load O(1) per caller, not per request
- Two-layer rate limiting: per-minute token bucket in RAM + per-day quota in DB
- Cloud Run min-instances=1 eliminates cold starts for callers

---

## Authentication

Every `/v1/*` endpoint requires an API key. Pass it in either header:

```
X-API-Key: nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Authorization: Bearer nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Admin endpoints (`/admin/*`) use a separate server-side internal token:

```
Authorization: Bearer <NIDP_DAAS_INTERNAL_TOKEN>
```

**Issue a key** (ops only — see [Admin endpoints](#admin--key-management)):
```bash
curl -X POST $SVC_URL/admin/keys \
  -H "Authorization: Bearer $NIDP_DAAS_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"AcmeCorp","owner_email":"ops@acme.com","plan":"free"}'
```

The cleartext token is returned **once** in the response. It is never stored — only its SHA-256 hash lives in the database. A lost key must be revoked and re-issued.

---

## Plans & rate limits

| Plan     | rpm   | Daily quota | Intended for              |
|----------|-------|-------------|---------------------------|
| free     | 60    | 1,000       | Dev / trial               |
| standard | 300   | 50,000      | Production SaaS           |
| pro      | 1,500 | 500,000     | Bulk / analytics          |
| internal | 6,000 | unlimited   | Service-to-service        |

`rpm` is enforced by a per-process sliding-window token bucket (fails open on process restart).
Daily quota is enforced by an atomic `UPSERT` on `nidp.daas_daily_usage` (hard limit, resets at midnight UTC).

---

## Response envelope

All `/v1/*` list endpoints return:

```json
{
  "data": [...],
  "count": 100,
  "pagination": {
    "limit": 100,
    "offset": 0,
    "total": null,
    "next_offset": 100
  },
  "as_of": "2026-05-08T07:00:00Z"
}
```

Single-row endpoints return `{"data": {...}, "as_of": "..."}`.

`next_offset` is `null` when there are no more rows.

---

## Pagination

All list endpoints accept:

| Param  | Default | Max       | Description       |
|--------|---------|-----------|-------------------|
| limit  | 100     | 5,000     | Rows per page     |
| offset | 0       | 1,000,000 | Skip N rows       |

```bash
curl "$SVC_URL/v1/prices/eod/RELIANCE?limit=100&offset=100" \
  -H "X-API-Key: nvd_..."
```

---

## Error format

```json
{
  "error": {
    "status": 429,
    "message": "rate limit exceeded",
    "request_id": "req_01HXYZ..."
  }
}
```

| Status | Meaning                                 |
|--------|-----------------------------------------|
| 400    | Bad request / validation error          |
| 401    | Missing or invalid API key              |
| 403    | Key revoked, expired, or plan violation |
| 404    | Symbol or resource not found            |
| 429    | Rate limit or daily quota exceeded      |
| 500    | Internal error                          |

On 429, the response includes `Retry-After: <seconds>`.

---

## Endpoints

Base URL: `https://<SVC_URL>`

### Health

#### `GET /health`
No auth required.

```bash
curl $SVC_URL/health
# {"status":"ok","service":"nidp-daas-api","ts":"2026-05-08T07:00:00Z"}
```

---

### Admin — key management

All admin endpoints require `Authorization: Bearer <NIDP_DAAS_INTERNAL_TOKEN>`.
The internal token is stored in Secret Manager as `NIDP_DAAS_INTERNAL_TOKEN`.

```bash
# Read it from Secret Manager
export NIDP_DAAS_INTERNAL_TOKEN=$(gcloud secrets versions access latest \
    --secret=NIDP_DAAS_INTERNAL_TOKEN --project=$GCP_PROJECT)
```

#### `POST /admin/keys` — Issue a new key

```bash
curl -X POST $SVC_URL/admin/keys \
  -H "Authorization: Bearer $NIDP_DAAS_INTERNAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AcmeCorp prod",
    "owner_email": "ops@acme.com",
    "plan": "standard",
    "expires_in_days": 365,
    "notes": "Q2 2026 pilot"
  }'
```

Request body:

| Field           | Required | Description                                              |
|-----------------|----------|----------------------------------------------------------|
| name            | ✓        | Human label, e.g. `"AcmeCorp prod"`                     |
| owner_email     | ✓        | Contact email for revocation                             |
| plan            |          | `free` \| `standard` \| `pro` \| `internal` (default: `free`) |
| rate_limit_rpm  |          | Override per-minute cap                                  |
| daily_quota     |          | Override daily quota (0 = unlimited)                     |
| expires_in_days |          | Auto-expire after N days; omit = never                   |
| notes           |          | Free-text memo                                           |

Response (201):
```json
{
  "token": "nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "key_id": "uuid",
  "key_prefix": "nvd_xxxxxxxx",
  "name": "AcmeCorp prod",
  "owner_email": "ops@acme.com",
  "plan": "standard",
  "rate_limit_rpm": 300,
  "daily_quota": 50000,
  "created_at": "2026-05-08T07:00:00+00:00",
  "expires_at": "2027-05-08T07:00:00+00:00"
}
```

> **Save the token immediately.** It is shown once and never stored.

---

#### `GET /admin/keys` — List all keys

```bash
curl $SVC_URL/admin/keys \
  -H "Authorization: Bearer $NIDP_DAAS_INTERNAL_TOKEN"
```

---

#### `DELETE /admin/keys/{key_id}` — Revoke a key

```bash
curl -X DELETE "$SVC_URL/admin/keys/<key_id>" \
  -H "Authorization: Bearer $NIDP_DAAS_INTERNAL_TOKEN"
# {"revoked": true, "key_id": "uuid"}
```

Revoked keys are rejected within 30 seconds (in-process cache TTL).

---

### Me

#### `GET /v1/me` — Key identity + plan

```bash
curl $SVC_URL/v1/me -H "X-API-Key: nvd_..."
```

#### `GET /v1/me/usage` — Daily request counts

```bash
curl "$SVC_URL/v1/me/usage?days=7" -H "X-API-Key: nvd_..."
```

---

### Catalog

#### `GET /v1/catalog` — All datasets + live row counts

```bash
curl $SVC_URL/v1/catalog -H "X-API-Key: nvd_..."
```

Returns 20 datasets, each with `id`, `name`, `description`, `table`, `row_count`, `endpoints[]`.

---

### Prices

#### `GET /v1/prices/eod/{symbol}` — Daily OHLCV (raw bhavcopy)

```bash
curl "$SVC_URL/v1/prices/eod/RELIANCE?start=2026-01-01&end=2026-05-01" \
  -H "X-API-Key: nvd_..."
```

| Param  | Description                          |
|--------|--------------------------------------|
| start  | Inclusive YYYY-MM-DD                 |
| end    | Inclusive YYYY-MM-DD                 |
| series | `EQ` \| `BE` \| `BZ` (default: all) |

Fields: `as_of_date`, `symbol`, `series`, `isin`, `prev_close`, `open_price`, `high_price`, `low_price`, `close_price`, `last_price`, `avg_price`, `volume`, `turnover`, `trades`, `deliv_qty`, `deliv_pct`

---

#### `GET /v1/prices/adjusted/{symbol}` — Split/bonus/dividend-adjusted OHLCV

Use this for return calculations across corporate actions.

Fields: `adj_open/high/low/close/volume` (price-return), `tret_close` (total-return including dividends), `cumulative_adj_factor`

---

#### `GET /v1/prices/latest/{symbol}` — Most recent bar

```bash
curl $SVC_URL/v1/prices/latest/TCS -H "X-API-Key: nvd_..."
```

---

#### `GET /v1/prices/eod` — All symbols on one date

```bash
curl "$SVC_URL/v1/prices/eod?on=2026-05-07&series=EQ&limit=500" \
  -H "X-API-Key: nvd_..."
```

---

#### `GET /v1/prices/index/{index_name}` — Index OHLC + valuation

```bash
curl "$SVC_URL/v1/prices/index/Nifty%2050?start=2026-01-01" \
  -H "X-API-Key: nvd_..."
```

Fields: `open_price`, `high_price`, `low_price`, `close_price`, `pe_ratio`, `pb_ratio`, `div_yield`, `volume`

---

#### `GET /v1/prices/delivery/{symbol}` — Delivery volume

Fields: `traded_qty`, `deliverable_qty`, `deliverable_pct`

---

### Corporate actions

#### `GET /v1/corporate-actions` — Full calendar

```bash
curl "$SVC_URL/v1/corporate-actions?symbol=INFY&type=dividend" \
  -H "X-API-Key: nvd_..."
```

| Param  | Description                                        |
|--------|----------------------------------------------------|
| symbol | Filter to one ticker                               |
| type   | `dividend` \| `split` \| `bonus` \| `rights`      |
| start  | Ex-date from (YYYY-MM-DD)                          |
| end    | Ex-date to                                         |

#### `GET /v1/corporate-actions/{symbol}` — One symbol's history

---

### Indices

#### `GET /v1/indices` — Distinct indices tracked

#### `GET /v1/indices/{index_name}/constituents` — Effective-dated membership

```bash
curl "$SVC_URL/v1/indices/Nifty%2050/constituents" -H "X-API-Key: nvd_..."
```

---

### Reference

#### `GET /v1/symbols` — Symbol master (symbol, company, sector, ISIN)

#### `GET /v1/symbols/search?q=<text>` — Substring search

```bash
curl "$SVC_URL/v1/symbols/search?q=hdfc" -H "X-API-Key: nvd_..."
```

#### `GET /v1/symbols/{symbol}` — One symbol's master row

#### `GET /v1/sectors` — Distinct sectors with member counts

#### `GET /v1/holidays?year=2026` — NSE trading holidays

---

### Financials & shareholding

#### `GET /v1/financials/{symbol}` — Quarterly financials

```bash
curl "$SVC_URL/v1/financials/RELIANCE?limit=8" -H "X-API-Key: nvd_..."
```

Fields: `period_end`, `revenue`, `ebitda`, `pat`, `eps`, `total_assets`, `total_debt`, `roe`, `roce`

#### `GET /v1/shareholding/{symbol}` — Promoter / FII / DII / retail split

---

### F&O

#### `GET /v1/fno/{symbol}` — Futures + options bhavcopy

```bash
curl "$SVC_URL/v1/fno/NIFTY?expiry=2026-05-29&instrument=CE" \
  -H "X-API-Key: nvd_..."
```

| Param      | Description                    |
|------------|--------------------------------|
| expiry     | Filter to one expiry YYYY-MM-DD|
| instrument | `FUT` \| `CE` \| `PE`         |

#### `GET /v1/fno/{symbol}/chain` — Latest options chain (CE+PE per strike)

#### `GET /v1/fno/{symbol}/expiries` — Available expiry dates with contract counts

---

### Flows

#### `GET /v1/flows/fii-dii` — Net FII / DII flows by category × segment

```bash
curl "$SVC_URL/v1/flows/fii-dii?start=2026-01-01" -H "X-API-Key: nvd_..."
```

Fields: `as_of_date`, `category` (FII/DII), `segment` (equity/debt), `buy_value`, `sell_value`, `net_value`

#### `GET /v1/flows/bulk-deals` — Bulk deals (>0.5% of listed shares, single client)

#### `GET /v1/flows/block-deals` — Block deals (negotiated, >₹10 Cr or >5L shares)

---

### Announcements

#### `GET /v1/announcements` — Corporate filings (filterable)

```bash
curl "$SVC_URL/v1/announcements?symbol=TCS&type=BoardMeeting&limit=10" \
  -H "X-API-Key: nvd_..."
```

| Param  | Description                  |
|--------|------------------------------|
| symbol | Filter to one ticker         |
| type   | Announcement category        |
| start  | Filed date from (YYYY-MM-DD) |
| end    | Filed date to                |

#### `GET /v1/announcements/{announcement_id}` — Full record including body text

---

### Macro

#### `GET /v1/macro/rbi-yields` — Indian G-Sec / T-bill / repo yields

```bash
curl "$SVC_URL/v1/macro/rbi-yields?start=2026-01-01" -H "X-API-Key: nvd_..."
```

#### `GET /v1/macro/fred` — Global macro series from FRED

```bash
curl "$SVC_URL/v1/macro/fred?series_id=DGS10&start=2025-01-01" \
  -H "X-API-Key: nvd_..."
```

Common series: `DGS10` (US 10Y yield), `DTWEXBGS` (DXY dollar index), `VIXCLS` (VIX), `DCOILWTICO` (WTI crude)

#### `GET /v1/macro/fred/series` — List of FRED series tracked

---

### Snapshots

Pre-computed daily summaries built by the snapshot engine.

#### `GET /v1/snapshots/market` — Market-wide daily snapshot

Fields: index levels, advance/decline breadth, FII/DII net flows, bulk/block deal totals

```bash
curl "$SVC_URL/v1/snapshots/market?on=2026-05-07" -H "X-API-Key: nvd_..."
```

#### `GET /v1/snapshots/market/recent` — Trailing N days

```bash
curl "$SVC_URL/v1/snapshots/market/recent?days=30" -H "X-API-Key: nvd_..."
```

#### `GET /v1/snapshots/stock/{symbol}` — Per-stock daily snapshot

OHLCV + index membership flags + bulk/block deal presence.

---

### Features

Engineered features from the Nivesh S4/S5 strategy pipeline.

#### `GET /v1/features/stocks/{symbol}` — Daily feature rows

```bash
curl "$SVC_URL/v1/features/stocks/RELIANCE?start=2026-01-01&limit=30" \
  -H "X-API-Key: nvd_..."
```

#### `GET /v1/features/stocks/{symbol}/latest` — Most-recent feature snapshot

---

## Response headers

Every authenticated response includes:

| Header                  | Description                              |
|-------------------------|------------------------------------------|
| `X-Request-Id`          | Unique `req_<ulid>` for tracing          |
| `X-RateLimit-Limit`     | Your rpm cap                             |
| `X-RateLimit-Remaining` | Requests left in current minute window   |
| `X-RateLimit-Reset`     | Seconds until window resets              |
| `X-Daily-Limit`         | Your daily quota (`unlimited` if none)   |
| `X-Daily-Remaining`     | Requests left today                      |
| `Retry-After`           | Seconds to wait (present on 429 only)    |

---

## Code layout

```
daas_api/
├── app.py           — FastAPI app, middleware, error handlers, router registration
├── auth.py          — X-API-Key resolution, 30s in-process cache, rate-limit check
├── keys.py          — Token minting (nvd_<32>), SHA-256 hashing, DB CRUD
├── ratelimit.py     — Token bucket (rpm, in-process) + daily quota UPSERT (DB)
├── middleware.py    — X-Request-Id injection, rate-limit headers, usage logging
├── responses.py     — Envelope builder, pagination params, type serialisation
├── __main__.py      — uvicorn entry point (port 8081)
├── Dockerfile       — python:3.11-slim image
└── routers/
    ├── admin.py             POST/GET/DELETE /admin/keys
    ├── health.py            GET /health
    ├── me.py                GET /v1/me, /v1/me/usage
    ├── catalog.py           GET /v1/catalog
    ├── prices.py            GET /v1/prices/eod, /adjusted, /latest, /index, /delivery
    ├── corporate_actions.py GET /v1/corporate-actions
    ├── indices.py           GET /v1/indices
    ├── reference.py         GET /v1/symbols, /sectors, /holidays
    ├── financials.py        GET /v1/financials, /shareholding
    ├── fno.py               GET /v1/fno
    ├── flows.py             GET /v1/flows/fii-dii, /bulk-deals, /block-deals
    ├── announcements.py     GET /v1/announcements
    ├── macro.py             GET /v1/macro/rbi-yields, /fred
    ├── snapshots.py         GET /v1/snapshots/market, /stock
    └── features.py          GET /v1/features/stocks
```

**DB tables used:**

| Table                       | Router              |
|-----------------------------|---------------------|
| `nidp.prices_eod`           | prices              |
| `nidp.prices_eod_adjusted`  | prices              |
| `nidp.index_eod`            | prices, indices     |
| `nidp.delivery_data`        | prices              |
| `nidp.corporate_actions`    | corporate_actions   |
| `nidp.index_constituents`   | indices             |
| `nidp.symbol_master`        | reference           |
| `nidp.trading_holidays`     | reference           |
| `nidp.quarterly_financials` | financials          |
| `nidp.shareholding`         | financials          |
| `nidp.fno_bhavcopy`         | fno                 |
| `nidp.fii_dii_flows`        | flows               |
| `nidp.bulk_deals`           | flows               |
| `nidp.block_deals`          | flows               |
| `nidp.announcements`        | announcements       |
| `nidp.rbi_yields`           | macro               |
| `nidp.fred_macro`           | macro               |
| `nidp.market_snapshot`      | snapshots           |
| `nidp.stock_features`       | features            |
| `nidp.daas_api_keys`        | auth, admin         |
| `nidp.daas_daily_usage`     | ratelimit           |
| `nidp.daas_usage_log`       | middleware          |

---

## Local development

```bash
# Start Postgres (from backend/nidp/deploy/)
docker compose -f docker-compose.dev.yml up -d postgres

# Run the service (from backend/)
NIDP_POSTGRES_URL="postgresql://postgres:postgres@localhost:5433/nidp" \
    python -m nidp.services.daas_api
# → http://localhost:8081/docs

# Run tests
pytest backend/nidp/tests/services/test_daas_api.py -v
```

Issue a key locally:
```bash
NIDP_POSTGRES_URL="postgresql://postgres:postgres@localhost:5433/nidp" \
    python -m nidp.cli daas-keygen \
    --name "local-test" --owner you@yourco.com --plan free
```
