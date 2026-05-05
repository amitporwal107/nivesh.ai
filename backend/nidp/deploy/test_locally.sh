#!/usr/bin/env bash
# test_locally.sh — fully local end-to-end test of any NIDP ingester.
#
# Brings up Postgres in Docker, applies migrations, runs the ingester
# directly via `python -m nidp.services.<svc>`, and verifies rows
# landed. No GCP, no Cloud Run, no Kafka, no S3 — pure code-against-PG.
#
# Why: separates "is the code correct" from "is the deploy plumbing
# correct". 90% of failures so far were deploy issues (stale image,
# wrong port, missing env). Local test proves code in 30 seconds,
# then deploy confidence increases.
#
# Usage:
#   ./test_locally.sh                    # default: nse_calendar
#   ./test_locally.sh bulk_deals         # any service
#   ./test_locally.sh bhavcopy 2026-05-04   # date-required services
#   ./test_locally.sh --reset             # tear down + bring up clean
#
# Prereqs on your machine:
#   - Docker Desktop running
#   - Python 3.11+

set -euo pipefail

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"; CYAN="\033[1;36m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[local-test]${RESET} $*"; }
ok()   { echo -e "${GREEN}[local-test] ✅${RESET} $*"; }
err()  { echo -e "${RED}[local-test] ❌${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_ROOT="$(cd "$NIDP_ROOT/.." && pwd)"

SERVICE="${1:-nse_calendar}"
ARG2="${2:-}"
[[ "$SERVICE" == "--reset" ]] && {
    log "tearing down local test containers..."
    cd "$SCRIPT_DIR" && docker compose -f docker-compose.dev.yml down -v
    ok "reset complete. Re-run without --reset to start fresh."
    exit 0
}

PG_CONTAINER="nidp-postgres"
PG_PORT="5433"     # host port from docker-compose.dev.yml mapping 5433:5432
PG_URL="postgres://postgres:postgres@localhost:${PG_PORT}/nidp"

# ── 1. Start Postgres only ──────────────────────────────────────────
log "step 1: starting Postgres container..."
cd "$SCRIPT_DIR"
if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
    docker compose -f docker-compose.dev.yml up -d postgres
    log "  waiting for postgres to be ready..."
    for i in $(seq 1 30); do
        if docker exec "${PG_CONTAINER}" pg_isready -U postgres &>/dev/null; then
            ok "postgres ready (~${i}s)"
            break
        fi
        sleep 1
        [[ $i -eq 30 ]] && { err "postgres didn't come up"; exit 1; }
    done
else
    ok "postgres already running"
fi
cd - >/dev/null

# ── 2. Ensure 'nidp' database exists ────────────────────────────────
log "step 2: ensuring nidp database exists..."
docker exec "${PG_CONTAINER}" psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='nidp'" \
    | grep -q 1 || \
    docker exec "${PG_CONTAINER}" psql -U postgres -c "CREATE DATABASE nidp"
ok "  nidp database present"

# ── 3. Apply migrations ─────────────────────────────────────────────
log "step 3: applying NIDP migrations..."
APPLIED=0
for f in $(ls "$NIDP_ROOT/migrations/"*.sql | sort); do
    name=$(basename "$f")
    docker cp "$f" "${PG_CONTAINER}:/tmp/${name}"
    if docker exec "${PG_CONTAINER}" psql -U postgres -d nidp \
            -v ON_ERROR_STOP=1 -f "/tmp/${name}" >/dev/null 2>&1; then
        APPLIED=$((APPLIED+1))
        echo "  ✓ ${name}"
    else
        err "  failed: ${name}"
        docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -f "/tmp/${name}" 2>&1 | tail -5
        exit 1
    fi
done
ok "  ${APPLIED} migrations applied"

# ── 4. Python venv + dependencies ───────────────────────────────────
log "step 4: ensuring Python venv with deps..."
VENV="$BACKEND_ROOT/.nidp-venv"
if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV" || python -m venv "$VENV"
    log "  installing requirements (~30s)..."
    "$VENV/bin/pip" install -q -r "$NIDP_ROOT/deploy/requirements.txt"
fi
ok "  venv ready: $VENV"

# ── 5. Set env + run the ingester ───────────────────────────────────
log "step 5: running ingester '${SERVICE}'..."
export NIDP_POSTGRES_URL="$PG_URL"
export NIDP_STORAGE_BACKEND=local       # writes raw bytes to /tmp
export NIDP_EVENT_BUS=local             # writes events to /tmp/nidp_events.jsonl
export NIDP_S3_BUCKET=nidp-local-test   # only used by storage backend label
export NIDP_KAFKA_BROKERS=unused
export NIDP_SCHEMA_REGISTRY_URL=unused
export NIDP_REDIS_URL=unused
export PYTHONPATH="$BACKEND_ROOT"

cd "$BACKEND_ROOT"
ARGS=()
case "$SERVICE" in
    bhavcopy|delivery|index_close|fii_dii)
        if [[ -z "$ARG2" ]]; then
            err "$SERVICE requires a date argument: ./test_locally.sh $SERVICE 2026-05-04"
            exit 1
        fi
        ARGS=(--date "$ARG2")
        ;;
    yfinance_backfill)
        ARGS=(--from 2024-01-01 --to 2024-03-31 --symbols RELIANCE,TCS)
        ;;
esac

set +e
"$VENV/bin/python" -m "nidp.services.${SERVICE}" "${ARGS[@]}"
RC=$?
set -e

# ── 6. Verify ───────────────────────────────────────────────────────
log "step 6: checking results in nidp.job_log + per-table row counts..."
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT ingester, target_date, status, rows_inserted, rows_skipped, error_class, finished_at
  FROM nidp.job_log
 WHERE started_at > NOW() - INTERVAL '5 minutes'
 ORDER BY started_at DESC LIMIT 5;
"
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT 'prices_eod'           AS tbl, count(*) FROM nidp.prices_eod
UNION ALL SELECT 'delivery_data',     count(*) FROM nidp.delivery_data
UNION ALL SELECT 'index_eod',         count(*) FROM nidp.index_eod
UNION ALL SELECT 'index_constituents',count(*) FROM nidp.index_constituents
UNION ALL SELECT 'fii_dii_flows',     count(*) FROM nidp.fii_dii_flows
UNION ALL SELECT 'corporate_actions', count(*) FROM nidp.corporate_actions
UNION ALL SELECT 'bulk_deals',        count(*) FROM nidp.bulk_deals
UNION ALL SELECT 'block_deals',       count(*) FROM nidp.block_deals
UNION ALL SELECT 'rbi_yields',        count(*) FROM nidp.rbi_yields
UNION ALL SELECT 'nse_holidays',      count(*) FROM nidp.nse_holidays
ORDER BY tbl;
"

if [[ $RC -eq 0 ]]; then
    ok "ingester '${SERVICE}' exited cleanly"
else
    err "ingester '${SERVICE}' exited code $RC — see traceback above"
fi
exit $RC
