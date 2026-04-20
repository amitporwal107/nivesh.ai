#!/bin/bash
# Self-healing PostgreSQL wrapper — ensures user/install/initdb exist before exec.
# Used by supervisor so that post-fork container restarts are automatic.
set -e

log() { echo "[$(date +%H:%M:%S)] run_postgres: $*"; }

# 1. Ensure system user exists
if ! id postgres &>/dev/null; then
    log "Creating postgres user"
    useradd -r -s /bin/false postgres 2>/dev/null || true
fi

# 2. Ensure PostgreSQL is installed
if ! command -v /usr/lib/postgresql/15/bin/postgres &>/dev/null; then
    log "Installing PostgreSQL 15"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y postgresql-15 -qq >/dev/null 2>&1 || true
fi

# 3. Ensure data dir is initialized
PG_DATA_DIR="/var/lib/postgresql/15/main"
if [ ! -f "$PG_DATA_DIR/PG_VERSION" ]; then
    log "Initializing PostgreSQL data dir"
    mkdir -p "$PG_DATA_DIR"
    chown -R postgres:postgres /var/lib/postgresql 2>/dev/null || true
    su - postgres -s /bin/bash -c "/usr/lib/postgresql/15/bin/initdb -D $PG_DATA_DIR" 2>&1 | head -20 || true
fi

# 4. Ensure config files exist
if [ ! -f /etc/postgresql/15/main/postgresql.conf ]; then
    log "Copying PostgreSQL config files"
    mkdir -p /etc/postgresql/15/main
    cp "$PG_DATA_DIR/postgresql.conf" /etc/postgresql/15/main/ 2>/dev/null || true
    cp "$PG_DATA_DIR/pg_hba.conf" /etc/postgresql/15/main/ 2>/dev/null || true
fi

# 5. Ensure auth is local-trust + password for postgres user
PG_HBA="/etc/postgresql/15/main/pg_hba.conf"
if [ -f "$PG_HBA" ] && ! grep -q "^host.*all.*all.*127\.0\.0\.1/32.*md5" "$PG_HBA"; then
    log "Configuring pg_hba auth"
    echo "host all all 127.0.0.1/32 md5" >> "$PG_HBA"
    echo "local all all trust" >> "$PG_HBA"
fi

# 6. Runtime dir + ownership
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql /var/lib/postgresql -R 2>/dev/null || true

# 7. exec postgres as the postgres user (replaces supervisor's child PID)
log "Starting postgres (exec)"
exec sudo -u postgres /usr/lib/postgresql/15/bin/postgres \
    -D "$PG_DATA_DIR" \
    -c config_file=/etc/postgresql/15/main/postgresql.conf
