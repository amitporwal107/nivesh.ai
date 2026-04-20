#!/bin/bash
# Self-healing Redis wrapper — ensures user/install exist before exec.
set -e

log() { echo "[$(date +%H:%M:%S)] run_redis: $*"; }

# 1. Ensure system user exists
if ! id redis &>/dev/null; then
    log "Creating redis user"
    useradd -r -s /bin/false redis 2>/dev/null || true
fi

# 2. Ensure Redis is installed
if ! command -v redis-server &>/dev/null; then
    log "Installing Redis"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y redis-server -qq >/dev/null 2>&1 || true
fi

# 3. Runtime dir
mkdir -p /var/run/redis
chown -R redis:redis /var/run/redis /var/lib/redis 2>/dev/null || true

# 4. exec redis-server as redis user
log "Starting redis (exec)"
exec sudo -u redis redis-server --port 6379 --daemonize no
