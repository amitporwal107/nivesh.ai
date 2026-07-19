#!/usr/bin/env bash
# restore.sh — restore the staging NIDP dump into the laptop TimescaleDB.
#
#   ./restore.sh dumps/nidp_staging_20260719.dump
#
# WHY THIS IS NOT JUST `pg_restore`
# ---------------------------------
# The source DB has 17 hypertables and ~586 chunk tables under
# _timescaledb_internal. A plain pg_restore replays those chunk DDL
# statements while the TimescaleDB extension is live, so the extension tries
# to re-manage objects that are already being created -> duplicate-chunk and
# constraint errors, and circular-FK failures on the `hypertable` catalog
# (pg_dump warns about these at dump time).
#
# The supported path is to put the extension in restore mode first:
#     SELECT timescaledb_pre_restore();   -- extension stops interfering
#     pg_restore ...
#     SELECT timescaledb_post_restore();  -- rebuild catalogs + re-enable
#
# VERSION SKEW: the dump came from TimescaleDB 2.26.4 / PG 16.13. The compose
# file pins timescale/timescaledb:2.26.4-pg16 for exactly this reason. This
# script refuses to run against a mismatched extension rather than producing
# a subtly broken warehouse.

set -euo pipefail

DUMP="${1:-}"
COMPOSE_FILE="$(dirname "$0")/docker-compose.nidp.yml"
SERVICE="postgres"
EXPECTED_TSDB="${EXPECTED_TSDB:-2.26.4}"

if [[ -z "$DUMP" ]]; then
    echo "usage: $0 <path-to-dump>" >&2
    exit 2
fi
if [[ ! -f "$DUMP" ]]; then
    echo "FATAL: dump not found: $DUMP" >&2
    exit 1
fi

# Load .env for the DB credentials.
ENV_FILE="$(dirname "$0")/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi
PGUSER_="${NIDP_PG_USER:-nidp}"
PGDB_="${NIDP_PG_DB:-nidp}"

dc() { docker compose -f "$COMPOSE_FILE" "$@"; }
psql_() { dc exec -T "$SERVICE" psql -v ON_ERROR_STOP=1 -U "$PGUSER_" -d "$PGDB_" "$@"; }

echo "==> Checking Postgres is up"
dc exec -T "$SERVICE" pg_isready -U "$PGUSER_" -d "$PGDB_"

echo "==> Verifying TimescaleDB version matches the dump's source"
psql_ -tAc "CREATE EXTENSION IF NOT EXISTS timescaledb;" >/dev/null
ACTUAL_TSDB=$(psql_ -tAc "SELECT extversion FROM pg_extension WHERE extname='timescaledb';" | tr -d '[:space:]')
if [[ "$ACTUAL_TSDB" != "$EXPECTED_TSDB" ]]; then
    cat >&2 <<EOF
FATAL: TimescaleDB version mismatch.
  dump was taken from : $EXPECTED_TSDB
  this container has  : $ACTUAL_TSDB
Restoring across versions can corrupt hypertable catalogs. Either pin the
image back to timescale/timescaledb:${EXPECTED_TSDB}-pg16, or take a fresh
dump from a source running $ACTUAL_TSDB and re-run with
EXPECTED_TSDB=$ACTUAL_TSDB.
EOF
    exit 1
fi
echo "    timescaledb $ACTUAL_TSDB  OK"

# pgvector is needed by document_chunks.embedding.
psql_ -tAc "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
# postgres_fdw exists on staging; harmless if unused locally.
psql_ -tAc "CREATE EXTENSION IF NOT EXISTS postgres_fdw;" >/dev/null

# The dump path must be visible INSIDE the container. compose mounts ./dumps
# at /dumps, so translate.
DUMP_BASENAME="$(basename "$DUMP")"
IN_CONTAINER="/dumps/$DUMP_BASENAME"
if ! dc exec -T "$SERVICE" test -f "$IN_CONTAINER"; then
    echo "FATAL: $DUMP_BASENAME is not visible at $IN_CONTAINER inside the" >&2
    echo "       container. Put the dump in ./dumps/ (it is bind-mounted)." >&2
    exit 1
fi

echo "==> timescaledb_pre_restore()"
psql_ -tAc "SELECT timescaledb_pre_restore();" >/dev/null

# post_restore must run even if pg_restore fails, otherwise the database is
# left with the extension disabled and every query misbehaves.
cleanup() {
    echo "==> timescaledb_post_restore()"
    psql_ -tAc "SELECT timescaledb_post_restore();" >/dev/null || \
        echo "WARNING: post_restore failed — DB may be in restore mode!" >&2
}
trap cleanup EXIT

echo "==> pg_restore (this takes a while for a 19GB source)"
# --no-owner/--no-privileges: dump was taken the same way; laptop roles differ.
# --jobs: parallel restore. Keep modest — laptop disk is the bottleneck.
# We do NOT use ON_ERROR_STOP here: TimescaleDB restores legitimately emit
# some benign errors, so we capture the log and assert on real data after.
set +e
dc exec -T "$SERVICE" pg_restore \
    -U "$PGUSER_" -d "$PGDB_" \
    --no-owner --no-privileges \
    --jobs "${RESTORE_JOBS:-2}" \
    --verbose \
    "$IN_CONTAINER" 2> >(tee /tmp/pg_restore.log >&2)
RC=$?
set -e
echo "    pg_restore exit code: $RC (non-zero is common; verifying data below)"

cleanup
trap - EXIT

echo ""
echo "==> Post-restore verification (this is the real pass/fail)"
echo "--- hypertables ---"
psql_ -c "SELECT hypertable_schema||'.'||hypertable_name AS hypertable, num_chunks
          FROM timescaledb_information.hypertables ORDER BY 1;"

echo "--- row counts on the tables the app actually reads ---"
psql_ -c "SELECT 'prices_eod'      AS t, count(*) FROM nidp.prices_eod
UNION ALL SELECT 'mf_nav_daily',        count(*) FROM nidp.mf_nav_daily
UNION ALL SELECT 'corporate_announcements', count(*) FROM nidp.corporate_announcements
UNION ALL SELECT 'v3_stock_scores_daily',  count(*) FROM nidp.v3_stock_scores_daily
UNION ALL SELECT 'v3_mf_scores_daily',     count(*) FROM nidp.v3_mf_scores_daily;"

echo "--- object counts by schema ---"
psql_ -c "SELECT table_schema, table_type, count(*)
          FROM information_schema.tables
          WHERE table_schema NOT IN ('pg_catalog','information_schema')
          GROUP BY 1,2 ORDER BY 1,2;"

echo ""
echo "Compare the above against the source. Expected from staging on 2026-07-19:"
echo "  17 hypertables · nidp schema: 72 BASE TABLE + 38 VIEW"
echo "If hypertables came back as 0, the restore silently degraded them to"
echo "plain tables — do NOT use that database; re-check the version pin."
