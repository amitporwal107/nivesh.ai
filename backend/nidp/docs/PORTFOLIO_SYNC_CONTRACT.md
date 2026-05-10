# Portfolio Sync Contract (Step 1)

This defines the **local exporter payload contract** for pushing user holdings
into NIDP's portfolio bridge without changing existing NSDL-CAS storage.

## 1) Payload schema

Canonical JSON schema file:
- `backend/nidp/contracts/portfolio_holdings_snapshot_v1.schema.json`

Version: `v1`

## 2) Delivery pattern

- Transport: HTTPS POST from local app (or batch worker) to a sync adapter.
- Idempotency key:
  - `external_user_id + snapshot_date + (isin|symbol|amfi_scheme_code)`
- Frequency:
  - Initial backfill: historical snapshots as available.
  - Steady state: daily end-of-day (or on CAS refresh event).

## 3) DB mapping target

For each holding in payload, insert/upsert into:
- `portfolio.user_holdings_snapshot`

Mapped columns:
- `external_user_id` → `external_user_id`
- `snapshot_date`    → `snapshot_date`
- `source_system`    → `source_system`
- `asset_class`      → `asset_class`
- `symbol` / `isin` / `amfi_scheme_code` → same
- `instrument_name`  → `instrument_name`
- `quantity` / `avg_buy_price` / `market_value_inr` / `weight_pct` → same
- `metadata_json`    → `metadata_json`

## 4) Validation rules

Hard validation:
- `external_user_id` required.
- `snapshot_date` valid date.
- At least 1 holding.
- `market_value_inr >= 0`.
- `weight_pct` in `[0,100]` when present.

Soft validation:
- Prefer at least one identity field among `isin`, `symbol`, `amfi_scheme_code`.
- Unknown fields rejected (`additionalProperties=false`) to avoid contract drift.

## 5) Example payload

```json
{
  "external_user_id": "user_abc123",
  "snapshot_date": "2026-05-10",
  "source_system": "nsdl_cas",
  "holdings": [
    {
      "asset_class": "EQUITY",
      "symbol": "RELIANCE",
      "isin": "INE002A01018",
      "amfi_scheme_code": null,
      "instrument_name": "Reliance Industries Ltd",
      "quantity": 12,
      "avg_buy_price": 2410.5,
      "market_value_inr": 35520.0,
      "weight_pct": 14.32,
      "metadata_json": {"folio": "NA"}
    },
    {
      "asset_class": "MUTUAL_FUND",
      "symbol": null,
      "isin": "INF200K01XY4",
      "amfi_scheme_code": "120503",
      "instrument_name": "SBI Bluechip Fund Direct Growth",
      "quantity": 245.112,
      "avg_buy_price": 68.23,
      "market_value_inr": 18340.54,
      "weight_pct": 7.39,
      "metadata_json": {"folio": "FOLIO-1234"}
    }
  ]
}
```

## 6) Handoff to Step 2

After payload lands in `portfolio.user_holdings_snapshot`, execute:

```bash
python -m nidp.cli ingest portfolio_intelligence_sync
```

This resolves holdings to `ref.security_master` and computes
`portfolio.user_intelligence_snapshot`.
