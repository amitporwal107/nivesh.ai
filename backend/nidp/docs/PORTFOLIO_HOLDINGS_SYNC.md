# Portfolio Holdings Sync — Technical Reference

_Added: 2026-05-12 | Service: `portfolio_holdings_sync`_

---

## Overview

`portfolio_holdings_sync` is the bridge that moves client portfolio holdings from the **Nivesh application database (Postgres)** into the **NIDP intelligence database** so the analytics pipeline has live, per-client data to work with.

Without this service, NIDP's `portfolio.user_holdings_snapshot` table is empty and `portfolio_intelligence_sync` has nothing to process — no per-client risk scoring, no sector concentration, no quality tier, no AI-driven insights.

---

## Data Flow

```
User uploads CAS PDF
        │
        ▼
Nivesh App (cas_snapshot_engine.py)
        │
        ├─ MongoDB: db.portfolio_snapshots    ← existing app store
        │
        └─ Nivesh Postgres (immediate, same request)
               client_user_map               ← email bridge [migration 020]
               portfolio_snapshot_master      ← snapshot header
               portfolio_snapshot_holdings    ← per-holding rows
               │
               └─ fire-and-forget trigger →  NIDP Query API
                      POST /feeds/portfolio_holdings_sync/execute
                              │
                              ▼
              NIDP VM: portfolio_holdings_sync (this service)
                 reads Nivesh Postgres → upserts NIDP Postgres
                              │
                              ▼
              portfolio.user_holdings_snapshot   [migration 042]
              portfolio.client_master            [migration 046]
              portfolio.sync_audit_log           [migration 046]
                              │
                              ▼  (chained by scheduler / --run-intel flag)
              portfolio_intelligence_sync
                 security mapping → user_intelligence_snapshot
```

---

## Source Schema (Nivesh Postgres)

| Table | Key columns | Written by |
|-------|-------------|------------|
| `portfolio_snapshot_master` | `id`, `client_id`, `snapshot_date`, `total_value`, `updated_at` | `cas_snapshot_engine._persist_pg_snapshot()` |
| `portfolio_snapshot_holdings` | `snapshot_id`, `instrument_id`, `units`, `current_value`, `weight_pct` | same |
| `instrument_master` | `instrument_id`, `symbol`, `isin`, `instrument_type`, `instrument_name` | `pg_writer.py` |
| `client_user_map` | `client_id`, `email`, `display_name` | `cas_snapshot_engine._persist_pg_snapshot()` [new, migration 020] |

`client_user_map` is the critical bridge: Nivesh internally identifies users by a random `user_id` (e.g. `user_abc123`), but NIDP uses `email` as the canonical `external_user_id`. This table is populated on every CAS upload.

---

## Destination Schema (NIDP Postgres)

| Table | Purpose | Migration |
|-------|---------|-----------|
| `portfolio.user_holdings_snapshot` | One row per holding per (client, date) | 042 |
| `portfolio.holding_security_map` | Resolved `security_id` from `ref.security_master` | 042 |
| `portfolio.user_intelligence_snapshot` | Computed analytics (beta, RSI, sector weights…) | 042 |
| `portfolio.client_master` | Registry of synced clients (email PK, last_sync_at) | 046 |
| `portfolio.sync_audit_log` | Append-only per-run audit log with SHA-256 hash | 046 |

---

## Asset Class Normalisation

| Nivesh `instrument_type` | NIDP `asset_class` |
|--------------------------|--------------------|
| `EQUITY` | `EQUITY` |
| `MUTUAL_FUND` | `MF` |
| `SGB` | `GOLD` |
| `ETF` | `ETF` |
| `DEBT` | `DEBT` |
| `CASH` | `CASH` |
| anything else | `OTHER` |

For mutual funds, `instrument_master.symbol` = AMFI scheme code (as documented in `pg_client.py`). The sync sets:
- `symbol` → `instrument_master.symbol` if EQUITY, else NULL
- `amfi_scheme_code` → `instrument_master.symbol` if MUTUAL_FUND, else NULL
- `isin` → `instrument_master.isin` for all types

`avg_buy_price` is not stored in Nivesh Postgres (it lives in MongoDB `db.holdings`). It is written as NULL in `user_holdings_snapshot`; the intelligence pipeline does not require it.

---

## Incremental / No-op Detection

The service computes a 16-char SHA-256 hex digest over the sorted holdings payload for each (client, snapshot_date). Before upserting:

1. Query `portfolio.sync_audit_log` for the last SUCCESS row for this (client, date).
2. If the hash matches → mark SKIPPED; skip the upsert entirely.
3. If different (or no prior success) → upsert and write SUCCESS.

This means re-triggers on an unchanged portfolio cost one SELECT and one INSERT — no holding rows are touched.

---

## Triggers

### 1. On CAS upload (real-time, fire-and-forget)

`cas_snapshot_engine.create_cas_snapshot()` calls:

```python
asyncio.ensure_future(
    nidp_query_client.execute_feed("portfolio_holdings_sync", target_date=snapshot_date)
)
```

This fires without awaiting — the CAS upload response is not delayed. If NIDP is unavailable, the CAS still succeeds; the daily scheduler picks it up.

Requires `NIDP_QUERY_API_URL` and `NIDP_QUERY_API_TOKEN` to be configured.

### 2. Scheduled (daily safety net)

Registered in `seed_source_registry.py` as:

```
Cron: 0 23 * * 1-5   (23:00 weekdays IST)
```

Runs before `portfolio_intelligence_sync` (23:30) so the analytics pass always has fresh holding data.

### 3. Manual

```bash
# Via admin panel: NIDP Jobs → portfolio_holdings_sync → Execute

# Via CLI on the NIDP VM:
python -m nidp.services.portfolio_holdings_sync

# With a specific date:
python -m nidp.services.portfolio_holdings_sync --date 2026-05-12

# Sync + immediately run intelligence pass:
python -m nidp.services.portfolio_holdings_sync --date 2026-05-12 --run-intel
```

---

## API Exposure

### Nivesh Admin Panel

`GET /api/admin/nidp/jobs` lists `portfolio_holdings_sync` alongside all other NIDP services with run history and an Execute button.

### NIDP Query API (VM-internal)

`POST /feeds/portfolio_holdings_sync/execute` — triggers an immediate run. Called by the admin panel Execute button and the fire-and-forget trigger.

`GET /feeds/portfolio_holdings_sync/runs` — run history from `nidp.job_log`.

### NIDP DaaS API (external, API-key required)

`GET /v1/intelligence/portfolio/sync/status` — per-client sync state:

```json
{
  "data": [
    {
      "external_user_id": "user@example.com",
      "display_name": "Ankit Porwal",
      "last_sync_at": "2026-05-12T23:01:42Z",
      "snapshot_date": "2026-05-12",
      "status": "SUCCESS",
      "holdings_upserted": 14,
      "synced_at": "2026-05-12T23:01:42Z",
      "error_detail": null
    }
  ]
}
```

Optional filter: `?external_user_id=user@example.com`

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NIVESH_POSTGRES_URL` | Yes | Nivesh app Postgres connection string (source) |
| `NIDP_POSTGRES_URL` | Yes | NIDP Postgres connection string (destination) |
| `NIDP_QUERY_API_URL` | For real-time trigger | Base URL of the NIDP Query API |
| `NIDP_QUERY_API_TOKEN` | For real-time trigger | Bearer token for the NIDP Query API |

`NIVESH_POSTGRES_URL` falls back to `POSTGRES_URL` then `postgresql://postgres:postgres@localhost:5432/nivesh` for local dev.

---

## Migrations Required

Run in order before deploying the service:

| Migration | Database | What it adds |
|-----------|----------|--------------|
| `backend/migrations/020_portfolio_pg_user_map.sql` | Nivesh Postgres | `client_user_map` table; `updated_at` on `portfolio_snapshot_master` |
| `backend/nidp/migrations/042_nidp_portfolio_bridge.sql` | NIDP Postgres | `portfolio.user_holdings_snapshot`, `holding_security_map`, `user_intelligence_snapshot` |
| `backend/nidp/migrations/046_nidp_portfolio_sync_log.sql` | NIDP Postgres | `portfolio.client_master`, `portfolio.sync_audit_log` |

---

## Observability

### Job log (NIDP Postgres)

```sql
SELECT ingester, target_date, status, duration_ms,
       rows_inserted, error_message
  FROM nidp.job_log
 WHERE ingester = 'portfolio_holdings_sync'
 ORDER BY started_at DESC LIMIT 10;
```

### Per-client sync audit

```sql
SELECT external_user_id, snapshot_date, status,
       holdings_upserted, portfolio_hash, synced_at, error_detail
  FROM portfolio.sync_audit_log
 ORDER BY synced_at DESC LIMIT 20;
```

### Client registry health

```sql
SELECT external_user_id, display_name,
       last_sync_at,
       EXTRACT(EPOCH FROM (NOW() - last_sync_at)) / 3600 AS hours_since_sync
  FROM portfolio.client_master
 ORDER BY last_sync_at ASC NULLS FIRST;
```

Clients with `hours_since_sync > 48` on a weekday indicate the sync trigger is not firing for them — check whether `client_user_map` has their email.

### Skipped clients (no email in Nivesh Postgres)

```sql
-- Find client_ids in portfolio_snapshot_master with no email mapping
SELECT DISTINCT psm.client_id
  FROM portfolio_snapshot_master psm
  LEFT JOIN client_user_map cum ON cum.client_id = psm.client_id
 WHERE cum.client_id IS NULL;
```

These clients' portfolios will not sync until they re-upload a CAS (which populates `client_user_map`). To backfill manually:

```sql
-- Run on Nivesh Postgres — inserts email for clients who are in MongoDB
-- but not yet in client_user_map. Requires access to both DBs.
INSERT INTO client_user_map (client_id, email, display_name)
SELECT user_id, email, name FROM <mongo_export_table>
ON CONFLICT (client_id) DO NOTHING;
```

---

## Relationship to `portfolio_intelligence_sync`

| Service | Reads from | Writes to | Job name |
|---------|-----------|-----------|---------|
| `portfolio_holdings_sync` | Nivesh Postgres | NIDP `portfolio.user_holdings_snapshot` | this doc |
| `portfolio_intelligence_sync` | NIDP `portfolio.user_holdings_snapshot` | NIDP `portfolio.holding_security_map` + `portfolio.user_intelligence_snapshot` | [existing service] |

`portfolio_holdings_sync` must run and succeed **before** `portfolio_intelligence_sync` for a given date. The scheduler enforces this by cron order (23:00 vs 23:30). `--run-intel` enforces it when triggering manually.
