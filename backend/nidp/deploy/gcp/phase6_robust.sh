#!/usr/bin/env bash
# phase6_robust.sh — apply NIDP migrations directly on the VM via
# docker exec, bypassing the SSH-tunnel approach that doesn't work
# on Windows (PuTTY/plink doesn't grok OpenSSH's -N -f background-
# tunnel syntax, and pkill isn't available either).
#
# Approach:
#   1. scp the migrations directory to the VM
#   2. docker cp into the postgres container
#   3. psql -f each .sql file in name-order
#   4. verify nidp.* tables exist
#
# No local Python / asyncpg required.

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
ZONE="${GCP_ZONE:-asia-south1-a}"
VM="${NIDP_VM_NAME:-nidp-stack-vm}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MIGRATIONS_DIR="$NIDP_ROOT/migrations"

log() { echo -e "\033[1;36m[phase6]\033[0m $*"; }

[[ -d "$MIGRATIONS_DIR" ]] || {
    echo "ERROR: $MIGRATIONS_DIR not found." >&2; exit 1; }

log "migrations source: $MIGRATIONS_DIR ($(ls $MIGRATIONS_DIR/*.sql 2>/dev/null | wc -l) files)"

# 1. push migrations to the VM
log "pushing migrations to VM..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command='sudo mkdir -p /tmp/nidp_migrations && sudo chmod 777 /tmp/nidp_migrations'

gcloud compute scp --recurse \
    "$MIGRATIONS_DIR/." \
    "${VM}:/tmp/nidp_migrations/" \
    --zone="$ZONE" --project="$PROJECT" --quiet

# 2. copy into postgres container + apply each .sql in order
log "applying migrations via docker exec..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet --command='
    set -e
    if ! sudo docker ps --format "{{.Names}}" | grep -q "^nidp-postgres$"; then
        echo "ERROR: nidp-postgres container not running." >&2
        sudo docker ps
        exit 1
    fi

    # Wait for PG to be accepting connections (retry up to 60s)
    for i in $(seq 1 30); do
        sudo docker exec nidp-postgres pg_isready -U postgres -d nidp &>/dev/null && break
        echo "waiting for postgres... ($i)"
        sleep 2
    done

    # Ensure target DB exists (compose may default to a different name)
    sudo docker exec nidp-postgres psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='\''nidp'\''" \
        | grep -q 1 || sudo docker exec nidp-postgres psql -U postgres -c "CREATE DATABASE nidp"

    # Copy migrations into the container.
    # Trailing /. on the source forces "copy CONTENTS of src into dst"
    # rather than "copy src as a subdir of dst". Without it, when
    # /tmp/migrations already exists from a prior run, docker cp
    # silently puts new files at /tmp/migrations/nidp_migrations/
    # — and the loop below looks for them at /tmp/migrations/<name>,
    # so newer .sql files like 008, 022 fail with "No such file".
    sudo docker exec nidp-postgres rm -rf /tmp/migrations
    sudo docker exec nidp-postgres mkdir -p /tmp/migrations
    sudo docker cp /tmp/nidp_migrations/. nidp-postgres:/tmp/migrations/

    # Apply in name order
    APPLIED=0
    FAILED=0
    for f in $(ls /tmp/nidp_migrations/*.sql 2>/dev/null | sort); do
        name=$(basename "$f")
        echo "  applying $name ..."
        if sudo docker exec nidp-postgres psql -U postgres -d nidp -v ON_ERROR_STOP=1 -f /tmp/migrations/"$name" >/dev/null 2>&1; then
            APPLIED=$((APPLIED+1))
            echo "    ok"
        else
            FAILED=$((FAILED+1))
            echo "    FAILED — re-run with verbose output:" >&2
            sudo docker exec nidp-postgres psql -U postgres -d nidp -f /tmp/migrations/"$name" 2>&1 | tail -10 >&2
        fi
    done

    echo
    echo "applied: $APPLIED, failed: $FAILED"
    [[ $FAILED -eq 0 ]] || exit 1

    # Verify schema landed
    echo
    echo "--- nidp schema sanity ---"
    sudo docker exec nidp-postgres psql -U postgres -d nidp -c \
        "SELECT count(*) AS nidp_tables FROM information_schema.tables WHERE table_schema = '\''nidp'\'';"
    sudo docker exec nidp-postgres psql -U postgres -d nidp -c \
        "SELECT filename FROM nidp.schema_migrations ORDER BY filename;"
'

log "✅ migrations applied. Next: ./gcp_full_setup.sh --project=$PROJECT --phase=7 --confirm"
