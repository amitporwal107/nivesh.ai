#!/usr/bin/env bash
# Historical backfill driver for the NSE/BSE announcement ingester.
#
# The ingester's own docstring specifies this shape: "For backfill, loop over
# dates with --date YYYY-MM-DD." Nothing here bypasses it — every day goes
# through the same fetch → DQ gate → writer → archive → validation path as the
# live feed, and the writer's ON CONFLICT DO UPDATE makes re-runs no-ops.
#
# Resumable: days already present in corporate_announcements are skipped, so
# the script can be killed and restarted without losing or duplicating work.
#
#   ./backfill.sh 2024-06-01 2026-01-18 [nse|bse]
set -uo pipefail
FROM="${1:?usage: backfill.sh FROM_DATE TO_DATE [source]}"
TO="${2:?usage: backfill.sh FROM_DATE TO_DATE [source]}"
SRC="${3:-nse}"
DELAY="${BACKFILL_DELAY:-2}"          # politeness gap between exchange requests
PY=/opt/nidp-staging/venv/bin/python
SRCU=$(echo "$SRC" | tr '[:lower:]' '[:upper:]')_ANN

set -a; . /opt/nidp-staging/nidp.env; set +a
export PYTHONPATH="$(cd "$(dirname "$0")/../../.." && pwd)"

# One query for every date already ingested — avoids a DB round trip per day.
mapfile -t DONE < <(docker exec -i nidp-postgres-staging psql -U nidp_staging \
  -d nidp_staging -tAc "SELECT DISTINCT filed_at::date FROM nidp.corporate_announcements
                        WHERE source='$SRCU' AND filed_at::date BETWEEN '$FROM' AND '$TO';")
declare -A SEEN; for d in "${DONE[@]}"; do SEEN["$d"]=1; done
echo "[backfill] $SRC $FROM..$TO · ${#DONE[@]} days already present"

ok=0; skip=0; fail=0; d="$FROM"
while [[ "$d" < "$TO" || "$d" == "$TO" ]]; do
  if [[ -n "${SEEN[$d]:-}" ]]; then
    skip=$((skip+1))
  else
    if timeout 180 "$PY" -m nidp.services.corporate_announcements \
         --source "$SRC" --date "$d" >/dev/null 2>&1; then
      ok=$((ok+1))
    else
      fail=$((fail+1)); echo "[backfill] FAILED $d"
    fi
    sleep "$DELAY"
  fi
  [[ $(( (ok+skip+fail) % 25 )) -eq 0 ]] && \
    echo "[backfill] $d · ok=$ok skip=$skip fail=$fail"
  d=$(date -I -d "$d + 1 day")
done
echo "[backfill] DONE $SRC $FROM..$TO · ok=$ok skip=$skip fail=$fail"
