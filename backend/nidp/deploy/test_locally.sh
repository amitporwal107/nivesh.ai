#!/usr/bin/env bash
# test_locally.sh — fully local end-to-end test of any NIDP ingester.
#
# Brings up Postgres + Redpanda + Schema Registry in Docker, applies
# migrations, runs the ingester directly via `python -m
# nidp.services.<svc>`, and verifies rows + feed snapshot + parsed
# archive landed. No GCP, no Cloud Run, no S3.
#
# Pass --bus=local to skip Kafka/SR (faster; only validates DB path).
# Default --bus=kafka exercises the full pipeline including Avro
# serialization + producer flush.
#
# Usage:
#   ./test_locally.sh                          # default: nse_calendar, kafka bus
#   ./test_locally.sh bulk_deals               # any service
#   ./test_locally.sh bhavcopy 2026-05-04      # date-required services
#   ./test_locally.sh nse_calendar --bus=local # PG-only path (no Kafka)
#   ./test_locally.sh --reset                  # tear down volumes, fresh start
#
# Prereqs:
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
ARG3="${3:-}"
BUS="kafka"
for arg in "$@"; do
    case "$arg" in
        --bus=local) BUS="local" ;;
        --bus=kafka) BUS="kafka" ;;
    esac
done
[[ "$SERVICE" == "--reset" ]] && {
    log "tearing down local test containers..."
    cd "$SCRIPT_DIR" && docker compose -f docker-compose.dev.yml down -v
    ok "reset complete. Re-run without --reset to start fresh."
    exit 0
}

PG_CONTAINER="nidp-postgres"
PG_PORT="5433"     # host port from docker-compose.dev.yml mapping 5433:5432
PG_URL="postgres://postgres:postgres@localhost:${PG_PORT}/nidp"
KAFKA_BROKERS="localhost:9092"
SR_URL="http://localhost:8081"

# ── 1. Start Postgres (+ Redpanda + Schema Registry if --bus=kafka) ─
log "step 1: starting infra containers (bus=${BUS})..."
cd "$SCRIPT_DIR"
SERVICES_TO_START=(postgres)
[[ "$BUS" == "kafka" ]] && SERVICES_TO_START+=(redpanda schema-registry)
docker compose -f docker-compose.dev.yml up -d "${SERVICES_TO_START[@]}"

log "  waiting for postgres..."
for i in $(seq 1 30); do
    if docker exec "${PG_CONTAINER}" pg_isready -U postgres &>/dev/null; then
        ok "postgres ready (~${i}s)"; break
    fi
    sleep 1
    [[ $i -eq 30 ]] && { err "postgres didn't come up"; exit 1; }
done

if [[ "$BUS" == "kafka" ]]; then
    log "  waiting for redpanda + schema-registry..."
    for i in $(seq 1 60); do
        if docker exec nidp-redpanda rpk cluster info &>/dev/null; then
            ok "redpanda ready (~${i}s)"; break
        fi
        sleep 1
        [[ $i -eq 60 ]] && { err "redpanda didn't come up"; exit 1; }
    done
    for i in $(seq 1 60); do
        if curl -sS -o /dev/null -w '%{http_code}' "$SR_URL/subjects" 2>/dev/null | grep -q '^200$'; then
            ok "schema-registry ready (~${i}s)"; break
        fi
        sleep 1
        [[ $i -eq 60 ]] && {
            err "schema-registry didn't come up — check 'docker logs nidp-schema-registry'"
            exit 1
        }
    done
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
export NIDP_STORAGE_BACKEND=local       # raw + parsed archives go to /tmp
export NIDP_EVENT_BUS="$BUS"            # kafka | local
export NIDP_S3_BUCKET=nidp-local-test
export NIDP_KAFKA_BROKERS="$KAFKA_BROKERS"
export NIDP_SCHEMA_REGISTRY_URL="$SR_URL"
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
log "step 6: checking results in nidp.job_log + feed_snapshot + per-table counts..."
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT ingester, target_date, status, rows_fetched, rows_inserted, rows_skipped,
       duration_ms, error_class, finished_at
  FROM nidp.job_log
 WHERE started_at > NOW() - INTERVAL '5 minutes'
 ORDER BY started_at DESC LIMIT 5;
"
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT ingester, snapshot_date, row_count, captured_at
  FROM nidp.feed_snapshot
 WHERE captured_at > NOW() - INTERVAL '5 minutes'
 ORDER BY captured_at DESC LIMIT 5;
"
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT ingester, snapshot_date, row_count, format, file_bytes, file_path
  FROM nidp.parsed_archive_files
 WHERE created_at > NOW() - INTERVAL '5 minutes'
 ORDER BY created_at DESC LIMIT 5;
"
docker exec "${PG_CONTAINER}" psql -U postgres -d nidp -c "
SELECT ingester, last_run_status, last_run_duration_ms, success_count, failure_count,
       last_run_at::timestamp(0) AS last_run, next_run_at::timestamp(0) AS next_run
  FROM nidp.v_feed_status
 WHERE ingester = '${SERVICE}';
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

if [[ "$BUS" == "kafka" ]]; then
    log "step 6b: checking Redpanda received the event..."
    TOPIC=$(grep -r "KAFKA_TOPIC" "$NIDP_ROOT/services/${SERVICE}/" 2>/dev/null \
        | grep -oE 'nidp\.[a-z_]+\.v[0-9]+' | head -1)
    if [[ -n "$TOPIC" ]]; then
        echo "  topic: $TOPIC"
        docker exec nidp-redpanda rpk topic consume "$TOPIC" \
            --num=1 --offset=end:-1 --format='%v\n' 2>/dev/null | head -2 \
            && ok "  ↑ event present on Kafka"
    fi
fi

if [[ $RC -eq 0 ]]; then
    ok "ingester '${SERVICE}' exited cleanly"
else
    err "ingester '${SERVICE}' exited code $RC — see traceback above"
fi
exit $RC
