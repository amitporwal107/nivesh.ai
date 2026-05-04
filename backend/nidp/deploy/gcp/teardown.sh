#!/usr/bin/env bash
# teardown.sh — destroy every resource recorded in gcp_resources.jsonl.
#
# Default: --dry-run. Pass --confirm to actually delete.
#
# Order matters (ignore-errors so a partial run is replayable):
#   1. Cloud Scheduler triggers
#   2. Cloud Run Jobs
#   3. GCE VM
#   4. Artifact Registry repository (deletes all images)
#   5. Secrets
#   6. GCS bucket
#   7. Service-account key(s) → service account itself

set -uo pipefail

CONFIRM="${1:-}"
DRY=true
[[ "$CONFIRM" == "--confirm" ]] && DRY=false

PROJECT="${GCP_PROJECT:?GCP_PROJECT must be set}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"
MANIFEST="$(cd "$(dirname "$0")" && pwd)/gcp_resources.jsonl"

log() { echo "[teardown] $*"; }
maybe() {
    if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@" || log "  (continued past failure)"; fi
}

if $DRY; then
    log "🚧 dry-run mode. Re-run with --confirm to actually delete."
fi
[[ -f "$MANIFEST" ]] || { log "no manifest found at $MANIFEST — nothing to do."; exit 0; }

log "project=$PROJECT region=$REGION manifest=$MANIFEST"

# Read manifest into typed buckets
SCHEDULES=()
RUN_JOBS=()
VMS=()
REPOS=()
SECRETS=()
BUCKETS=()
SAS=()

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    type=$(jq -r '.type' <<<"$line")
    name=$(jq -r '.name' <<<"$line")
    case "$type" in
        cloud_scheduler)   SCHEDULES+=("$name") ;;
        cloud_run_job)     RUN_JOBS+=("$name") ;;
        gce_vm)            VMS+=("$name") ;;
        artifact_registry) REPOS+=("$name") ;;
        secret)            SECRETS+=("$name") ;;
        gcs_bucket)        BUCKETS+=("$name") ;;
        service_account)   SAS+=("$name") ;;
    esac
done < "$MANIFEST"

# 1. Schedulers
for n in "${SCHEDULES[@]:-}"; do
    maybe "gcloud scheduler jobs delete $n --location=$REGION --project=$PROJECT --quiet"
done

# 2. Cloud Run Jobs
for n in "${RUN_JOBS[@]:-}"; do
    maybe "gcloud run jobs delete $n --region=$REGION --project=$PROJECT --quiet"
done

# 3. GCE VMs
for n in "${VMS[@]:-}"; do
    maybe "gcloud compute instances delete $n --zone=$ZONE --project=$PROJECT --quiet"
done

# 4. Artifact Registry repositories
for n in "${REPOS[@]:-}"; do
    maybe "gcloud artifacts repositories delete $n --location=$REGION --project=$PROJECT --quiet"
done

# 5. Secrets
for n in "${SECRETS[@]:-}"; do
    maybe "gcloud secrets delete $n --project=$PROJECT --quiet"
done

# 6. GCS buckets (force — empties first)
for n in "${BUCKETS[@]:-}"; do
    maybe "gsutil -m rm -r gs://$n"
done

# 7. Service accounts (delete keys first, then SA)
for sa in "${SAS[@]:-}"; do
    if ! $DRY; then
        keys=$(gcloud iam service-accounts keys list --iam-account="$sa" \
                --project="$PROJECT" --filter='keyType=USER_MANAGED' \
                --format='value(name)' 2>/dev/null || true)
        while IFS= read -r key; do
            [[ -z "$key" ]] && continue
            key_id="${key##*/}"
            log "deleting key $key_id"
            gcloud iam service-accounts keys delete "$key_id" --iam-account="$sa" \
                --project="$PROJECT" --quiet || true
        done <<< "$keys"
    fi
    maybe "gcloud iam service-accounts delete $sa --project=$PROJECT --quiet"
done

log "✅ teardown complete."
$DRY && log "(dry-run only — re-run with --confirm to apply)"
