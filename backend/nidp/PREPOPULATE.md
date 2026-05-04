# NIDP Prepopulate Runbook

How to prepopulate the NIDP warehouse with historical Nifty 500 data.

> **Important:** NSE bhavcopy / delivery / FII-DII / corporate-actions
> are **whole-market** files. There is no "Nifty 500 only" fetch at
> the source. We backfill the whole market and filter to Nifty 500 at
> query time via [migrations/006_nidp_views.sql](migrations/006_nidp_views.sql).

## 0. Prerequisites

This must run on a host that has:
- Outbound HTTPS to `archives.nseindia.com`, `nsearchives.nseindia.com`,
  `www.nseindia.com`, `www.rbi.org.in`. **The Anthropic sandbox does
  not** — Akamai bot-mgmt 503s the request. Run from a normal cloud
  VM or workstation.
- Docker (or your own Postgres+TimescaleDB+Kafka+Redis).
- Python 3.11+.

If running from this repo:
```bash
cd /app/backend
pip install -r nidp/deploy/requirements.txt pytest
```

## 1. Bring up dev infra

```bash
cd backend/nidp/deploy
docker compose -f docker-compose.dev.yml up -d
docker compose ps                      # all services should be healthy
```

This starts Postgres+TimescaleDB (5433), Redpanda Kafka (9092), Schema
Registry (8081), Redis (6380), MinIO (9000/9001), Prometheus (9090),
Grafana (3000).

## 2. Configure environment

```bash
cp backend/nidp/deploy/.env.example backend/nidp/deploy/.env
# Edit .env if you want non-default ports/buckets
set -a && source backend/nidp/deploy/.env && set +a
```

Key envs:
- `NIDP_POSTGRES_URL=postgresql://postgres:postgres@localhost:5433/nidp`
- `NIDP_EVENT_BUS=local` (use `kafka` once you've validated)
- `NIDP_STORAGE_BACKEND=local` (use `s3` for prod with `NIDP_S3_BUCKET`)

## 3. Apply migrations

```bash
cd backend
python -m nidp.cli migrate
python -m nidp.cli health    # verify TimescaleDB is loaded + tables present
```

Expected:
```
  Postgres reachable:        True
  TimescaleDB extension:     2.x.y
  Tables in nidp schema:     ~20
```

## 4. Smoke-test one source before backfilling

The smallest, safest loop validation — should complete in seconds:

```bash
python -m nidp.cli ingest nse_calendar     # ~30 rows, weekly cadence
python -m nidp.cli ingest bulk_deals       # rolling NSE file, ~hundreds of rows
```

Inspect:
```bash
psql "$NIDP_POSTGRES_URL" -c "SELECT ingester, status, rows_inserted, started_at \
                              FROM nidp.job_log ORDER BY started_at DESC LIMIT 10;"
psql "$NIDP_POSTGRES_URL" -c "SELECT count(*) FROM nidp.nse_holidays;"
psql "$NIDP_POSTGRES_URL" -c "SELECT count(*) FROM nidp.bulk_deals;"
```

If those rows landed, the loop is healthy and you can proceed.

## 5. Bootstrap the Nifty 500 universe

`index_constituents` populates `index_constituents` for Nifty 50 / 100 /
200 / 500 / Bank / IT in one shot.

```bash
python -m nidp.cli ingest index_constituents
psql "$NIDP_POSTGRES_URL" -c "SELECT count(*) FROM nidp.v_nifty500_members;"
```

You should see ~500.

## 6. Backfill — choose your scope

### Option A — Last 1 year (recommended first run)

```bash
python -m nidp.cli backfill --from 2025-05-04 --to 2026-05-04
```

Expected runtime: **30–60 minutes** depending on NSE responsiveness.
Order:
1. Reference + rolling sources (calendar, constituents, bulk, block, CA, RBI)
2. Per-day loop: bhavcopy → delivery → index_close → fii_dii × ~250 days

The orchestrator polite-gaps each call to avoid NSE 503s.

### Option B — Last 5 years (full warehouse)

```bash
python -m nidp.cli backfill --from 2021-05-04 --to 2026-05-04
```

Expected runtime: **3–5 hours**. Plan for it. Backfill is resumable
(`--skip-existing` is on by default), so a network blip just means
you re-run the same command and it picks up from where it left off.

### Option C — Specific service only

```bash
python -m nidp.cli backfill --from 2024-01-01 --to 2026-05-04 \
    --services bhavcopy,delivery
```

## 7. Verify coverage

```bash
psql "$NIDP_POSTGRES_URL" -c "SELECT * FROM nidp.v_warehouse_coverage;"
```

Returns one row with row counts and date ranges per domain. Spot-check:

```bash
# Nifty 500 latest closes — should show ~500 symbols
psql "$NIDP_POSTGRES_URL" -c "SELECT count(*) FROM nidp.v_nifty500_latest_close;"

# Daily prices for RELIANCE
psql "$NIDP_POSTGRES_URL" -c "SELECT as_of_date, close_price \
    FROM nidp.v_nifty500_prices_eod \
    WHERE symbol='RELIANCE' \
    ORDER BY as_of_date DESC LIMIT 10;"

# Net FII flows last 30 days
psql "$NIDP_POSTGRES_URL" -c "SELECT as_of_date, sum(net_value_cr) FILTER (WHERE category='FII') AS fii_net, \
                                                  sum(net_value_cr) FILTER (WHERE category='DII') AS dii_net \
    FROM nidp.fii_dii_flows \
    WHERE as_of_date >= CURRENT_DATE - 30 \
    GROUP BY 1 ORDER BY 1 DESC;"
```

## 8. Triage failures

Every failed run is in `nidp.job_log`:

```bash
psql "$NIDP_POSTGRES_URL" -c "SELECT ingester, target_date, status, error_message, \
                                     left(source_url, 80) AS url \
    FROM nidp.job_log WHERE status='FAILED' \
    ORDER BY started_at DESC LIMIT 20;"
```

Common patterns and remedies:
- **HTTP 503 on archives.nseindia.com** — Akamai blocked the IP. Wait
  20 min and re-run the same backfill command (resume picks it up).
- **HTTP 404 for a specific date** — that day was a closed market and
  nse_holidays didn't have it yet. Run `nse_calendar` first, then
  resume; the holiday filter will skip it.
- **fii_dii NotImplementedError: unrecognised body** — NSE shipped a
  new XLS layout. Capture the raw file from
  `nidp.raw_archive_files.file_path` and add a fixture under
  `tests/fixtures/fii_dii/` before patching the parser.

## 9. Re-run after parser/logic changes (replay)

The `raw_archive_files` table indexes every byte of every fetch. To
replay without re-hitting NSE:

```bash
# (Reload-from-archive is a future tool; for now, re-running the
# backfill with --skip-existing=false on the affected date refetches
# from upstream. Replay-from-archive lands when we wire it via Kafka
# in Phase 2.)
```

## 10. Move to Kafka + Airflow (Phase 2 prep)

Once Phase 1 is stable, flip these env knobs and re-run:

```bash
export NIDP_EVENT_BUS=kafka
export NIDP_KAFKA_BROKERS=localhost:9092
export NIDP_SCHEMA_REGISTRY_URL=http://localhost:8081
python -m nidp.cli ingest bulk_deals       # validates Kafka path end-to-end
```

The Airflow DAGs in `nidp/dags/` are import-safe; mount them into your
Airflow scheduler's `dags/` folder when ready.
