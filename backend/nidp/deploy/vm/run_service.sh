#!/usr/bin/env bash
# run_service.sh — single-entrypoint wrapper invoked by cron.
#
#   /opt/nidp/repo/backend/nidp/deploy/vm/run_service.sh <service> [args...]
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
if [[ -f "$NIDP_HOME/nidp.env" ]]; then
    set -a
    source "$NIDP_HOME/nidp.env"
    set +a
fi

cd "$NIDP_HOME/repo/backend"

# flock -n: bail immediately if another invocation holds the lock.
# fd 9 keeps the lock alive for the duration of the python process.
exec 9> "$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -Iseconds)] $SERVICE skipped: previous run still active" \
        >> "$LOG_FILE"
    exit 0
fi

# ── Bounded retry with exponential backoff ───────────────────────────
# A one-shot cron model leaves a failed feed broken until its next slot
# (24h). Retry transient failures a few times within the same slot so a
# blip (NSE timeout, DB restarting mid-disk-incident) self-recovers.
# Safe because every ingester is idempotent (already_succeeded + upsert).
#   NIDP_MAX_ATTEMPTS    total attempts (default 3; set 1 for legacy one-shot)
#   NIDP_RETRY_BACKOFF_S base backoff seconds (default 30; delay = base*2^(n-1))
# Exit code 2 (argparse/usage) is treated as non-retryable — it won't
# fix itself. All retries run under the same flock (serialized).
MAX_ATTEMPTS="${NIDP_MAX_ATTEMPTS:-3}"
BACKOFF_S="${NIDP_RETRY_BACKOFF_S:-30}"

# The command to run. Overridable via NIDP_RUN_CMD (used by the retry
# test harness); defaults to the service module under the venv Python.
if [[ -n "${NIDP_RUN_CMD:-}" ]]; then
    read -r -a CMD <<< "$NIDP_RUN_CMD"
else
    CMD=("$NIDP_HOME/venv/bin/python" -m "nidp.services.$SERVICE")
fi

attempt=1
RC=0
while : ; do
    START=$(date -Iseconds)
    echo "[$START] starting $SERVICE (attempt $attempt/$MAX_ATTEMPTS) $*" >> "$LOG_FILE"
    "${CMD[@]}" "$@" >> "$LOG_FILE" 2>&1
    RC=$?
    END=$(date -Iseconds)

    if [[ $RC -eq 0 ]]; then
        echo "[$END] $SERVICE OK (attempt $attempt)" >> "$LOG_FILE"
        break
    fi
    if [[ $RC -eq 2 ]]; then
        echo "[$END] $SERVICE FAILED rc=2 (usage — not retrying)" >> "$LOG_FILE"
        break
    fi
    if [[ $attempt -ge $MAX_ATTEMPTS ]]; then
        echo "[$END] $SERVICE FAILED rc=$RC (gave up after $attempt attempt(s))" >> "$LOG_FILE"
        break
    fi
    delay=$(( BACKOFF_S * (2 ** (attempt - 1)) ))
    echo "[$END] $SERVICE failed rc=$RC — retry $((attempt + 1))/$MAX_ATTEMPTS in ${delay}s" >> "$LOG_FILE"
    sleep "$delay"
    attempt=$(( attempt + 1 ))
done

exit $RC
