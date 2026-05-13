# Portfolio Sync Contract

_Status: **Implemented** (2026-05-12) — see [PORTFOLIO_HOLDINGS_SYNC.md](PORTFOLIO_HOLDINGS_SYNC.md) for the full technical reference._

---

## What was planned here

This document originally described a push-based HTTP contract where the Nivesh app would POST a JSON payload to a sync adapter. That design was superseded by a **pull-based DB-to-DB sync** during implementation, which is cleaner, requires no new HTTP surface, and reuses the existing Nivesh Postgres tables (`portfolio_snapshot_master`, `portfolio_snapshot_holdings`, `instrument_master`).

---

## What was actually built

The sync is implemented as an NIDP service (`nidp.services.portfolio_holdings_sync`) that:

1. Opens two asyncpg pools: **Nivesh Postgres** (source) and **NIDP Postgres** (destination).
2. Reads `portfolio_snapshot_master JOIN client_user_map` to find clients with email mappings.
3. Fetches their holdings via `portfolio_snapshot_holdings JOIN instrument_master`.
4. Normalises instrument types to NIDP asset classes.
5. Upserts into `portfolio.user_holdings_snapshot` with SHA-256 hash deduplication.
6. Records every run in `portfolio.sync_audit_log`.

The email bridge (`client_user_map`) is populated automatically on every CAS upload by `cas_snapshot_engine._persist_pg_snapshot()`.

---

## Payload contract (for reference only)

The original JSON payload schema is preserved below. It is **not used** by the current implementation but documents the canonical field set that `portfolio.user_holdings_snapshot` expects.

### Canonical holding fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `external_user_id` | `TEXT` | Yes | Email address |
| `snapshot_date` | `DATE` | Yes | ISO format `YYYY-MM-DD` |
| `source_system` | `TEXT` | Yes | `nivesh_cas` for CAS-derived holdings |
| `asset_class` | `TEXT` | Yes | `EQUITY \| MF \| ETF \| GOLD \| DEBT \| CASH \| OTHER` |
| `symbol` | `TEXT` | Conditional | NSE symbol; required for equities |
| `isin` | `TEXT` | Conditional | ISIN; preferred identity for all types |
| `amfi_scheme_code` | `TEXT` | Conditional | AMFI code; required for mutual funds |
| `instrument_name` | `TEXT` | No | Human label |
| `quantity` | `NUMERIC` | Yes | Units held |
| `avg_buy_price` | `NUMERIC` | No | NULL when unavailable (not in Nivesh PG) |
| `market_value_inr` | `NUMERIC` | Yes | Current market value ≥ 0 |
| `weight_pct` | `NUMERIC` | No | 0–100; computed from total_value if absent |
| `metadata_json` | `JSONB` | No | Arbitrary extra fields |

At least one of `isin`, `symbol`, `amfi_scheme_code` must be non-null per holding for the security-resolution pass (`portfolio_intelligence_sync`) to match against `ref.security_master`.

---

## Idempotency key

`(external_user_id, snapshot_date, COALESCE(isin,''), COALESCE(symbol,''), COALESCE(amfi_scheme_code,''), source_system)`

This is the unique index on `portfolio.user_holdings_snapshot` (migration 042). Duplicate writes upsert — the later run wins on all numeric fields.

---

## After holdings land

`portfolio_intelligence_sync` must run next to resolve holdings to `ref.security_master` and compute `portfolio.user_intelligence_snapshot`. Run it as:

```bash
python -m nidp.services.portfolio_intelligence_sync
# or chain it:
python -m nidp.services.portfolio_holdings_sync --run-intel
```
