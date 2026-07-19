#!/usr/bin/env bash
# dump-app-vm.sh — take a Postgres dump from nivesh-app-vm for laptop 1.
#
# RUN THIS ON nivesh-app-vm (it needs the local docker socket; the app's
# Postgres binds 127.0.0.1 only and is NOT reachable over the VPC).
#
#   ./dump-app-vm.sh              # staging DB (default)
#   ./dump-app-vm.sh prod         # production DB — read the warning below
#
# Companion to the NIDP dump already taken on nidp-stack-vm:
#   /opt/nidp/dumps/nidp_staging_20260719.dump  (2.0 GB)
#
# ⚠️  PRODUCTION: `prod` dumps real customer data (portfolios, PAN-linked CAS
#     records, emails). Restoring that onto a laptop puts production PII on a
#     developer machine. Prefer `staging` unless you have a specific reason.
#
# ⚠️  DISK: this VM has filled up before (Docker build cache ate 79 GB and
#     took the app down). The script refuses to run below a free-space floor.

set -euo pipefail

ENVIRONMENT="${1:-staging}"
DUMP_DIR="${DUMP_DIR:-/opt/nivesh/dumps}"
MIN_FREE_GB="${MIN_FREE_GB:-10}"
STAMP="$(date +%Y%m%d)"

case "$ENVIRONMENT" in
    staging) CONTAINER=nivesh-staging-postgres ;;
    prod)    CONTAINER=nivesh-postgres ;;
    *) echo "usage: $0 [staging|prod]" >&2; exit 2 ;;
esac

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "FATAL: container '$CONTAINER' is not running. Running Postgres containers:" >&2
    docker ps --format '{{.Names}}' | grep -i postgres >&2 || echo "  (none)" >&2
    exit 1
fi

# Credentials come from the container's own env — no secrets in this script
# and none in the process list.
PGUSER_=$(docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' \
          | grep '^POSTGRES_USER=' | cut -d= -f2)
PGDB_=$(docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' \
        | grep '^POSTGRES_DB=' | cut -d= -f2)

if [[ -z "$PGUSER_" || -z "$PGDB_" ]]; then
    echo "FATAL: could not read POSTGRES_USER/POSTGRES_DB from $CONTAINER" >&2
    exit 1
fi

echo "==> Source: $CONTAINER  db=$PGDB_  user=$PGUSER_"

echo "==> Database size"
docker exec "$CONTAINER" psql -U "$PGUSER_" -d "$PGDB_" -tAc \
    "SELECT pg_size_pretty(pg_database_size('$PGDB_'));"

mkdir -p "$DUMP_DIR"
FREE_GB=$(df -BG --output=avail "$DUMP_DIR" | tail -1 | tr -dc '0-9')
echo "==> Free space at $DUMP_DIR: ${FREE_GB}G (floor: ${MIN_FREE_GB}G)"
if (( FREE_GB < MIN_FREE_GB )); then
    cat >&2 <<EOF
FATAL: only ${FREE_GB}G free — refusing to dump.
This VM has filled its disk before and taken the app down with it.
Reclaim first:  docker builder prune -af   (then re-run)
EOF
    exit 1
fi

OUT="$DUMP_DIR/${PGDB_}_${ENVIRONMENT}_${STAMP}.dump"
echo "==> Dumping to $OUT"
echo "    (--no-owner/--no-privileges: laptop roles differ from the VM's)"

# Plain Postgres here — no TimescaleDB on the app VM, so unlike the NIDP
# restore this one needs no pre_restore/post_restore dance.
docker exec "$CONTAINER" pg_dump -U "$PGUSER_" -d "$PGDB_" \
    -Fc --no-owner --no-privileges > "$OUT"

echo "==> Verifying the archive is readable"
docker cp "$OUT" "$CONTAINER:/tmp/_verify.dump"
ENTRIES=$(docker exec "$CONTAINER" pg_restore --list /tmp/_verify.dump | grep -c ';' || true)
docker exec "$CONTAINER" rm -f /tmp/_verify.dump
echo "    TOC entries: $ENTRIES"
if (( ENTRIES < 10 )); then
    echo "FATAL: archive looks empty or corrupt — do not use it." >&2
    exit 1
fi

sha256sum "$OUT" | tee "$OUT.sha256"
ls -lh "$OUT"

cat <<EOF

─────────────────────────────────────────────────────────────
Done. Pull it to laptop 1:

  gcloud compute scp nivesh-app-vm:$OUT ./dumps/ \\
      --tunnel-through-iap --zone asia-south1-a
  sha256sum -c dumps/$(basename "$OUT").sha256

Restore into the laptop 1 stack:

  docker compose -f docker-compose.app.yml up -d postgres
  docker compose -f docker-compose.app.yml exec -T postgres \\
      pg_restore -U nivesh -d portfolio_ingestion --no-owner --no-privileges \\
      --jobs 2 /dumps/$(basename "$OUT")

NOTE: this covers Postgres only. The app also stores data in MongoDB
(users, sessions, portfolios). For a fully working laptop you likely need
a mongodump too — ask before assuming Postgres alone is enough.
─────────────────────────────────────────────────────────────
EOF
