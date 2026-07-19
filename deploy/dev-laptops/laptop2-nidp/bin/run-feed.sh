#!/usr/bin/env bash
# run-feed.sh — container-native port of backend/nidp/deploy/vm/run_service.sh.
#
#   run-feed.sh <service> [args...]
#
# Keeps the VM wrapper's contract so behaviour matches nidp-stack-vm:
#   1. cd to /app/backend so `python -m nidp.services.<x>` resolves
#   2. flock so the same service never runs concurrently
#   3. bounded retry with exponential backoff (NIDP_MAX_ATTEMPTS / NIDP_RETRY_BACKOFF_S)
#   4. rc=2 (argparse/usage) treated as non-retryable
#   5. exits non-zero on failure so the scheduler surfaces it
#
# Differences from the VM version, deliberately:
#   - system python3, not $NIDP_HOME/venv/bin/python (container has no venv)
#   - env comes from the container environment (compose env_file), not
#     sourced from /opt/nidp/nidp.env
#   - output is tee'd to BOTH the log file and stdout, so `docker logs` and
#     promtail/Loki can see runs. The VM only wrote to a file.

set -uo pipefail

NIDP_HOME="${NIDP_HOME:-/opt/nidp}"
SERVICE="${1:-}"; shift || true

if [[ -z "$SERVICE" ]]; then
    echo "usage: $0 <service> [args...]" >&2
    exit 2
fi

LOG_DIR="$NIDP_HOME/logs/$SERVICE"
LOG_FILE="$LOG_DIR/$SERVICE.log"
LOCK_FILE="$NIDP_HOME/run/$SERVICE.lock"
mkdir -p "$LOG_DIR" "$NIDP_HOME/run"

cd /app/backend || { echo "FATAL: /app/backend not mounted" >&2; exit 1; }

# log <msg> — to stdout (docker logs) and the per-service file.
log() { echo "$*" | tee -a "$LOG_FILE"; }

exec 9> "$LOCK_FILE"
if ! flock -n 9; then
    log "[$(date -Iseconds)] $SERVICE skipped: previous run still active"
    exit 0
fi

MAX_ATTEMPTS="${NIDP_MAX_ATTEMPTS:-3}"
BACKOFF_S="${NIDP_RETRY_BACKOFF_S:-30}"

if [[ -n "${NIDP_RUN_CMD:-}" ]]; then
    read -r -a CMD <<< "$NIDP_RUN_CMD"
else
    CMD=(python3 -m "nidp.services.$SERVICE")
fi

attempt=1
RC=0
while : ; do
    START=$(date -Iseconds)
    log "[$START] starting $SERVICE (attempt $attempt/$MAX_ATTEMPTS) $*"
    "${CMD[@]}" "$@" 2>&1 | tee -a "$LOG_FILE"
    RC=${PIPESTATUS[0]}
    END=$(date -Iseconds)

    if [[ $RC -eq 0 ]]; then
        log "[$END] $SERVICE OK (attempt $attempt)"
        break
    fi
    if [[ $RC -eq 2 ]]; then
        log "[$END] $SERVICE FAILED rc=2 (usage — not retrying)"
        break
    fi
    if [[ $attempt -ge $MAX_ATTEMPTS ]]; then
        log "[$END] $SERVICE FAILED rc=$RC (gave up after $attempt attempt(s))"
        break
    fi
    delay=$(( BACKOFF_S * (2 ** (attempt - 1)) ))
    log "[$END] $SERVICE failed rc=$RC — retry $((attempt + 1))/$MAX_ATTEMPTS in ${delay}s"
    sleep "$delay"
    attempt=$(( attempt + 1 ))
done

exit $RC
