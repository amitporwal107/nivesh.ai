#!/usr/bin/env bash
# Work back through a window of filings in rounds, so a long catch-up never holds the lock the
# scheduled run needs. Each round is one ordinary pipeline run; it stops after three rounds in a
# row with nothing new to do.
#
#   ./backfill.sh 30            # last 30 days (the data API's maximum window)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAYS="${1:-30}"; ROUNDS="${2:-60}"; idle=0
for round in $(seq 1 "$ROUNDS"); do
  echo "[backfill] round $round of $ROUNDS · $(date -Is)"
  out="$(DAYS="$DAYS" MAX_FILINGS="${MAX_FILINGS:-300}" MAX_FILTER="${MAX_FILTER:-300}" MAX_ANALYSES="${MAX_ANALYSES:-60}" \
         flock /tmp/event-ai.lock "$HERE/pipeline.sh" 2>&1 | grep -vE 'FontBBox|GSM client')"
  echo "$out"
  if echo "$out" | grep -q '"collected": 0' && echo "$out" | grep -q '"filtered": 0' && echo "$out" | grep -q '"analysed": 0'; then
    idle=$((idle + 1)); [ "$idle" -ge 3 ] && { echo "[backfill] nothing left · done"; break; }
  else
    idle=0
  fi
  sleep 20
done
