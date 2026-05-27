#!/usr/bin/env bash
# run_service.sh — single-entrypoint wrapper invoked by cron.
#
#   /opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/run_service.sh <service> [args...]
#
# Responsibilities:
#   1. Load /opt/nidp/nidp.env into the environment
#   2. cd into the repo's backend/ so `python -m nidp.services.<x>` works
#   3. Use the venv's Python
#   4. Tee stdout/stderr to /opt/nidp/logs/<service>/<service>.log
#   5. Wrap an `flock` so the same service can never run concurrently
#      (cron racing a long-running invocation, manual ops re-run, etc.)
#   6. Exit non-zero on failure so cron's MAILTO and our health_check
#      can notice
#
# Service name MUST match a directory under backend/nidp/services/

set -uo pipefail

NIDP_HOME=/opt/nidp
SERVICE="${1:-}"; shift || true

if [[ -z "$SERVICE" ]]; then
    echo "usage: $0 <service> [args...]" >&2
    exit 2
fi

LOG_DIR="$NIDP_HOME/logs/$SERVICE"
LOG_FILE="$LOG_DIR/$SERVICE.log"
LOCK_FILE="$NIDP_HOME/run/$SERVICE.lock"
mkdir -p "$LOG_DIR" "$NIDP_HOME/run"

# shellcheck disable=SC1091
set -a
source "$NIDP_HOME/nidp.env"
set +a

cd "$NIDP_HOME/dev-repo/nivesh.ai/backend"

# flock -n: bail immediately if another invocation holds the lock.
# fd 9 keeps the lock alive for the duration of the python process.
exec 9> "$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -Iseconds)] $SERVICE skipped: previous run still active" \
        >> "$LOG_FILE"
    exit 0
fi

START=$(date -Iseconds)
echo "[$START] starting $SERVICE $*" >> "$LOG_FILE"

"$NIDP_HOME/venv/bin/python" -m "nidp.services.$SERVICE" "$@" \
    >> "$LOG_FILE" 2>&1
RC=$?

END=$(date -Iseconds)
if [[ $RC -eq 0 ]]; then
    echo "[$END] $SERVICE OK" >> "$LOG_FILE"
else
    echo "[$END] $SERVICE FAILED rc=$RC" >> "$LOG_FILE"
fi

exit $RC
