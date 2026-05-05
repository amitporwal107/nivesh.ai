#!/usr/bin/env bash
# fix_and_deploy.sh — one-shot end-to-end deploy + verify.
#
# Applies all pending writer patches (idempotent — safe if already
# patched), rebuilds container images, redeploys Cloud Run Jobs, runs
# all 11 ingesters in parallel, waits for completion, and reports
# row counts per table.
#
# Usage:
#   ./fix_and_deploy.sh [--project=PROJECT] [--region=asia-south1] [--skip-rebuild]
#
# Designed to be re-runnable. If anything fails mid-way, fix the
# underlying issue and re-run — earlier successful steps are skipped.

set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"
VM="${NIDP_VM_NAME:-nidp-stack-vm}"
SKIP_REBUILD=

for arg in "$@"; do
    case "$arg" in
        --project=*)     PROJECT="${arg#*=}" ;;
        --region=*)      REGION="${arg#*=}"; ZONE="${REGION}-a" ;;
        --skip-rebuild)  SKIP_REBUILD=1 ;;
        -h|--help)       sed -n '2,15p' "$0"; exit 0 ;;
    esac
done

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"; CYAN="\033[1;36m"; RESET="\033[0m"
log() { echo -e "${CYAN}[fix-deploy]${RESET} $*"; }
ok()  { echo -e "${GREEN}[fix-deploy] ✅${RESET} $*"; }
warn(){ echo -e "${YEL}[fix-deploy] ⚠${RESET} $*"; }
err() { echo -e "${RED}[fix-deploy] ❌${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_ROOT="$(cd "$NIDP_ROOT/.." && pwd)"

echo
log "config: project=$PROJECT region=$REGION zone=$ZONE vm=$VM"

# ── 1. Apply writer date-coerce patches (idempotent) ────────────────
log "step 1: ensuring writer date-coerce patches are applied..."

HELPER="$NIDP_ROOT/shared/_date_coerce.py"
if [[ ! -f "$HELPER" ]]; then
    cat > "$HELPER" << 'PY'
"""Date-string coercion for asyncpg executemany binders."""
from __future__ import annotations
from datetime import date as _date_t, datetime as _datetime_t
from typing import Any, Optional


def to_date(value: Any) -> Optional[_date_t]:
    if value is None:
        return None
    if isinstance(value, _date_t) and not isinstance(value, _datetime_t):
        return value
    if isinstance(value, _datetime_t):
        return value.date()
    return _date_t.fromisoformat(str(value))
PY
    ok "  created shared/_date_coerce.py"
else
    log "  shared/_date_coerce.py already exists"
fi

python_patch() {
    local file="$1"
    [[ -f "$file" ]] || { warn "  skipped (missing): $file"; return 0; }
    python3 - "$file" << 'PYPATCH'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text()
orig = s

# Add import if missing
if 'from nidp.shared._date_coerce import to_date' not in s:
    s = s.replace(
        'from nidp.shared.storage.pg import get_pool',
        'from nidp.shared._date_coerce import to_date\nfrom nidp.shared.storage.pg import get_pool',
        1,
    )

# Common single-date wrap patterns
for old, new in (
    ('r["as_of_date"]',     'to_date(r["as_of_date"])'),
    ('r["holiday_date"]',   'to_date(r["holiday_date"])'),
):
    if 'to_date(' + old + ')' not in s and old in s:
        # Only replace inside args = [(...)] tuples — i.e. not inside `to_date(...)` already
        s = re.sub(r'(?<!to_date\()' + re.escape(old), 'to_date(' + old + ')', s, count=1)

# corporate_actions has 5 date fields
if 'corporate_actions' in str(p):
    s = s.replace(
        'r.get("record_date"), r["ex_date"]',
        'to_date(r.get("record_date")), to_date(r["ex_date"])',
    )
    s = s.replace(
        'r.get("bc_start_date"), r.get("bc_end_date"), r.get("announcement_date")',
        'to_date(r.get("bc_start_date")), to_date(r.get("bc_end_date")), to_date(r.get("announcement_date"))',
    )

if s != orig:
    p.write_text(s)
    print(f"  patched {p.name}")
else:
    print(f"  unchanged {p.name}")
PYPATCH
}

for f in \
    "$NIDP_ROOT/services/nse_calendar/writer.py" \
    "$NIDP_ROOT/services/delivery/writer.py" \
    "$NIDP_ROOT/services/bhavcopy/writer.py" \
    "$NIDP_ROOT/services/index_close/writer.py" \
    "$NIDP_ROOT/services/fii_dii/writer.py" \
    "$NIDP_ROOT/services/rbi_yields/writer.py" \
    "$NIDP_ROOT/services/corporate_actions/writer.py"
do
    python_patch "$f"
done
ok "step 1 done"

# ── 2. Rebuild + push images, redeploy Cloud Run Jobs ───────────────
if [[ -z "$SKIP_REBUILD" ]]; then
    log "step 2: rebuild + push + redeploy Cloud Run Jobs..."
    if ! command -v docker >/dev/null; then
        err "Docker not found. Install Docker Desktop and retry, or pass --skip-rebuild if images are already current."
        exit 1
    fi
    if ! docker info &>/dev/null; then
        err "Docker daemon not running. Start Docker Desktop and retry."
        exit 1
    fi
    bash "$SCRIPT_DIR/deploy.sh" --project="$PROJECT" --confirm || {
        err "deploy.sh failed; aborting"; exit 1; }
    ok "step 2 done"
else
    log "step 2: --skip-rebuild → skipping image rebuild"
fi

# ── 3. Storage backend env: ensure all jobs use 'local' OR 'gcs' ────
log "step 3: ensuring NIDP_STORAGE_BACKEND is set on all jobs..."
# Default: try gcs first (proper backend); if old image without GCSBackend, fallback to local.
DESIRED_BACKEND="${NIDP_STORAGE_BACKEND:-gcs}"
JOBS=(
    nidp-bhavcopy nidp-block-deals nidp-bulk-deals nidp-corporate-actions
    nidp-delivery nidp-fii-dii nidp-index-close nidp-index-constituents
    nidp-nse-calendar nidp-rbi-yields nidp-snapshot-builder
)
for j in "${JOBS[@]}"; do
    gcloud run jobs update "$j" \
        --update-env-vars "NIDP_STORAGE_BACKEND=$DESIRED_BACKEND" \
        --region="$REGION" --project="$PROJECT" --quiet >/dev/null 2>&1 \
        && echo "  ✓ $j → $DESIRED_BACKEND" \
        || warn "  failed to update $j"
done
ok "step 3 done"

# ── 4. Run all 10 ingesters in parallel; snapshot_builder LAST ──────
log "step 4: triggering 10 data ingesters in parallel..."
EXEC_NAMES=()
for j in nidp-nse-calendar nidp-bulk-deals nidp-block-deals \
         nidp-corporate-actions nidp-rbi-yields nidp-bhavcopy \
         nidp-delivery nidp-index-close nidp-fii-dii \
         nidp-index-constituents
do
    out=$(gcloud run jobs execute "$j" --region="$REGION" \
        --project="$PROJECT" --async 2>&1)
    if [[ "$out" =~ \[(nidp-[a-z0-9-]+)\] ]]; then
        EXEC_NAMES+=("${BASH_REMATCH[1]}")
        echo "  ✓ fired $j (execution: ${BASH_REMATCH[1]})"
    else
        warn "  failed to fire $j: $out"
    fi
done
ok "step 4: ${#EXEC_NAMES[@]} executions started"

# ── 5. Wait for executions to complete (max 8 min) ──────────────────
log "step 5: waiting for ingesters to finish (up to 8 min)..."
for i in $(seq 1 48); do
    PENDING=0
    for ex in "${EXEC_NAMES[@]}"; do
        status=$(gcloud run jobs executions describe "$ex" \
            --region="$REGION" --project="$PROJECT" \
            --format='value(status.conditions[0].type)' 2>/dev/null || echo "Unknown")
        if [[ "$status" != "Completed" ]]; then
            PENDING=$((PENDING+1))
        fi
    done
    if [[ $PENDING -eq 0 ]]; then
        ok "  all executions completed in ~$((i*10))s"
        break
    fi
    [[ $i -eq 48 ]] && warn "  timeout — $PENDING still running"
    echo -n "."
    sleep 10
done

# ── 6. Run snapshot_builder ─────────────────────────────────────────
log "step 6: building snapshot..."
gcloud run jobs execute nidp-snapshot-builder \
    --region="$REGION" --project="$PROJECT" --wait 2>&1 | tail -3 || \
    warn "  snapshot_builder failed — likely missing data; check job_log"

# ── 7. Verify by row counts ─────────────────────────────────────────
log "step 7: row counts per NIDP table..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off -c "
SELECT '\''prices_eod'\'' AS tbl, count(*) AS rows FROM nidp.prices_eod
UNION ALL SELECT '\''delivery_data'\'',     count(*) FROM nidp.delivery_data
UNION ALL SELECT '\''index_eod'\'',         count(*) FROM nidp.index_eod
UNION ALL SELECT '\''index_constituents'\'',count(*) FROM nidp.index_constituents
UNION ALL SELECT '\''fii_dii_flows'\'',     count(*) FROM nidp.fii_dii_flows
UNION ALL SELECT '\''corporate_actions'\'', count(*) FROM nidp.corporate_actions
UNION ALL SELECT '\''bulk_deals'\'',        count(*) FROM nidp.bulk_deals
UNION ALL SELECT '\''block_deals'\'',       count(*) FROM nidp.block_deals
UNION ALL SELECT '\''rbi_yields'\'',        count(*) FROM nidp.rbi_yields
UNION ALL SELECT '\''nse_holidays'\'',      count(*) FROM nidp.nse_holidays
UNION ALL SELECT '\''market_daily_snapshot'\'',count(*) FROM nidp.market_daily_snapshot
UNION ALL SELECT '\''stock_daily_snapshot'\'', count(*) FROM nidp.stock_daily_snapshot
ORDER BY tbl;
"' || warn "  PG query failed"

# ── 8. job_log summary ──────────────────────────────────────────────
log "step 8: latest job_log status..."
gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off -c "
SELECT ingester, target_date, status, rows_inserted, error_class, finished_at
  FROM nidp.job_log
 WHERE started_at > NOW() - INTERVAL '\''30 minutes'\''
 ORDER BY started_at DESC LIMIT 25;
"' || warn "  PG query failed"

# ── 9. Final verdict ────────────────────────────────────────────────
echo
log "step 9: final verification — running ./verify_deployment.sh ..."
if [[ -x "$SCRIPT_DIR/verify_deployment.sh" ]]; then
    bash "$SCRIPT_DIR/verify_deployment.sh" --project="$PROJECT" --region="$REGION"
else
    warn "verify_deployment.sh not found"
fi

echo
ok "fix_and_deploy.sh complete. Review row counts + job_log above."
echo "  - any FAILED rows in step 8 → run: ./fetch_logs.sh <job-name> 30m"
echo "  - paste that output to the agent for per-source patching"
