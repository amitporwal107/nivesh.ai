#!/usr/bin/env bash
# cleanup_triggers.sh — find and force-delete all nidp-* Cloud Build
# triggers across every plausible location, so a fresh setup run
# can't hit the "trigger exists somewhere else, patch fails" path.
#
# Usage:
#   ./cleanup_triggers.sh                # delete
#   ./cleanup_triggers.sh --dry-run      # only list

set -uo pipefail
PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
DRY=""
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# 2nd-gen triggers can live in any region the API supports + global.
LOCATIONS=(
    global
    asia-south1 asia-south2 asia-southeast1
    us-central1 us-east1 us-west1
    europe-west1 europe-west2 europe-west3
)

CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[cleanup]${RESET} $*"; }
ok()   { echo -e "${GREEN}[cleanup] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[cleanup] ⚠${RESET}  $*"; }

log "scanning project=$PROJECT for nidp-* triggers ${DRY:+(dry-run)}"
echo

FOUND=0
for loc in "${LOCATIONS[@]}"; do
    triggers=$(gcloud builds triggers list \
        --region="$loc" --project="$PROJECT" \
        --format='value(name)' 2>/dev/null \
        | grep -E '^nidp-' || true)
    [[ -z "$triggers" ]] && continue

    while IFS= read -r t; do
        [[ -z "$t" ]] && continue
        FOUND=$((FOUND+1))
        if [[ -n "$DRY" ]]; then
            warn "would delete: $t  (location=$loc)"
        else
            log "deleting $t  (location=$loc)"
            gcloud builds triggers delete "$t" \
                --region="$loc" --project="$PROJECT" --quiet >/dev/null 2>&1 \
                && ok "  deleted" \
                || warn "  delete failed (might already be gone)"
        fi
    done <<< "$triggers"
done

echo
if [[ $FOUND -eq 0 ]]; then
    ok "no nidp-* triggers found anywhere — clean slate"
else
    log "scanned ${#LOCATIONS[@]} locations, processed $FOUND trigger(s)"
fi
